"""A second source of document vectors beside the local model (`[embedding.assist]`).

In a build the local model is the slow part. `AssistedEmbedder` wraps the local embedder so that
an OpenAI-compatible endpoint that serves the same model (a `codemem serve-embeddings` server on a
machine with a GPU, or a hosted API) embeds part of each large call's texts while the local model
embeds the rest. The vectors are stored under the local embedder's key, as if it had made them
all, so the endpoint has to give the same vectors. Three rules keep that true and keep a build
going (docs/architecture.md §3.5):

- **Proof first.** Before the endpoint gets any text, a fixed set of probe texts is embedded both
  ways and compared (`SAME_VECTORS`). An endpoint that differs is not used, and `status` says why.
- **The local model never waits for the endpoint.** One call's texts are a row both work through
  from opposite ends: the local model from the front, in its usual batches and in the caller's
  thread, the endpoint from the back, in several requests at once. The endpoint takes a text only
  if, by the speeds measured so far, it will have it before the local model gets there. A request
  that fails gives its texts back; one that is late has them taken back.
- **Small calls stay local.** A call of one local batch or less (an edit, a search's catch-up, a
  model warm-up) never reaches the endpoint, so what those callers rely on is unchanged.

Queries are always embedded locally.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .config import AssistConfig, EmbeddingConfig, codemem_home
from .embedder import Embedder, OpenAIEmbedder, TryLater, _counted, _Uses, l2_normalize

log = logging.getLogger(__name__)

# The smallest cosine between an endpoint's vector and the local model's for the same probe text
# at which the two may share an index. Between what is known to be harmless and what is known not
# to be: the same model on this machine's CPU in float32 and on its GPU in float16 agree to
# 0.999996, and no score moves by more than 0.0007; in bfloat16 against float16 it is 0.99978, and
# 2 of 20 top-10 lists change.
SAME_VECTORS = 0.99995
NORM_TOLERANCE = 0.01  # how far from 1 the length of an endpoint's vector may be
FIRST_PAUSE_S, LONGEST_PAUSE_S = 1.0, 60.0  # after a failure the endpoint rests; each further failure doubles the rest
# When the local model has nothing else left, it takes a request's texts back and embeds them
# itself: at once if it would be done before the request is expected back, else once the request
# is overdue by the time the local model needs for them. The first result counts, so a request
# that hangs costs a call about twice that time, not its timeout. Until the local model's speed is
# known, a request is overdue at twice its expected time, and at LEAST_PATIENCE_S at the earliest.
LEAST_PATIENCE_S = 0.5
FIRST_CHECK_WAIT_S = 2.0  # how long a build's first large call waits for the endpoint's answer to the probe

UNCHECKED, CHECKING, SHARING, RESTING, REFUSED = "unchecked", "checking", "sharing", "resting", "refused"
_LONG = "a text longer than the model reads"
_PROBES = (
    ("a function", '# auth/sessions.py\ndef revoke_session(session_id):\n    """End one session."""\n'
                   "    db.sessions.delete(session_id)"),
    ("a method in another language", "// auth/sessions.go\n// RevokeSession deletes one session from the store.\n"
                                     "func (m *SessionManager) RevokeSession(id string) error {\n"
                                     "\tif _, ok := m.sessions[id]; !ok {\n\t\treturn ErrNoSession\n\t}\n"
                                     "\tdelete(m.sessions, id)\n\treturn nil\n}"),
    ("a usage text", "revoke_session in auth/sessions.py\ncalled by logout in api/routes.py\n"
                     "called by disable_user in auth/users.py\n"
                     "tested by test_disabled_user_loses_sessions in tests/test_users.py"),
    ("a class outline", "# upload/pipeline.py\nclass UploadPipeline:\n    def add_stage(self, stage): ...\n"
                        "    def run(self, upload): ...\n    def transcribe_audio(self, upload): ..."),
    ("plain words", "Uploaded images are stored, but the text in them is never extracted, so a search cannot find it."),
    ("other alphabets", "# données/überprüfung.py\ndef prüfe_größe(datei):  # 检查文件大小\n"
                        "    return datei.größe <= MAX_GRÖSSE  # 最大サイズ"),
)


def probe_texts(max_seq_length: int | None) -> list[tuple[str, str]]:
    """The probe: (what it is, the text). The last one is longer than the local model reads, with
    other words at its end than at its start, so an endpoint that cuts texts at another length
    gives another vector for it. Each line has more than four words, so `max_seq_length // 4` of
    them are more tokens than that under any tokenizer."""
    lines = max(64, (max_seq_length or 1024) // 4)
    half = range(lines // 2)
    head = [f"session_{i} = sessions.open(user_{i}, expires=hours({i % 24}))  # login {i}" for i in half]
    tail = [f"total_{i} = add_tax(invoice_{i}, rate_{i % 7}) + shipping_{i}  # ledger line {i}" for i in half]
    return [*_PROBES, (_LONG, "\n".join(head + tail))]


def difference(
    local: np.ndarray, raw: np.ndarray, labels: Sequence[str], host: str, model: str, max_seq_length: int | None
) -> tuple[float | None, str | None]:
    """Compare an endpoint's probe vectors, as they came, with the local model's: (smallest cosine,
    why the endpoint cannot share the work). The reason is None when it can."""
    if raw.shape[1] != local.shape[1]:
        return None, (f"{host} returns vectors of {raw.shape[1]} numbers for {model} and the local model's have "
                      f"{local.shape[1]}, so it is another model")
    if not np.isfinite(raw).all():
        return None, f"{host} returns numbers that are not finite for {model}"
    norms = np.linalg.norm(raw, axis=1)
    worst = float(norms[np.argmax(np.abs(norms - 1.0))])
    if abs(worst - 1.0) > NORM_TOLERANCE:
        return None, (f"{host} returns vectors that are not normalized (length {worst:.3g}, the local model's have "
                      f"length 1), so it does not run {model} the way the local model does")
    cosines = np.sum(local * (raw / norms[:, None]), axis=1)
    agreement = float(cosines.min())
    if agreement >= SAME_VECTORS:
        return agreement, None
    if [label for label, c in zip(labels, cosines) if c < SAME_VECTORS] == [_LONG]:
        return agreement, (f"{host} gives another vector for a text longer than the local model reads (cosine "
                           f"{agreement:.5f}), so it cuts texts at another length than {max_seq_length} tokens")
    return agreement, (f"{host} gives other vectors than the local model for the same texts (cosine {agreement:.5f} "
                       f"at worst, {SAME_VECTORS} needed): another model, another prompt before the text, or "
                       "another precision")


class _Speed:
    """Seconds per character, as a moving average over calls (the indexer measures a model the
    same way). Averaging the time, not the rate, lets one slow call count at once and a fast one
    only gradually: an endpoint that slows down loses work quickly and wins it back slowly."""

    def __init__(self) -> None:
        self.per_char: float | None = None

    def add(self, chars: int, seconds: float) -> None:
        if chars > 0 and seconds > 0:
            self.per_char = seconds / chars if self.per_char is None else 0.7 * self.per_char + 0.3 * seconds / chars

    def seconds(self, chars: int) -> float | None:
        """Expected time for `chars` characters; None until something was measured."""
        return None if self.per_char is None else chars * self.per_char


class Endpoint:
    """The assist endpoint as this process knows it: whether its vectors were found equal to the
    local model's, how fast it answers, and when it may be asked again after a failure."""

    def __init__(self, cfg: AssistConfig, clock: Callable[[], float] = time.monotonic):
        self.cfg, self.clock = cfg, clock
        self.client = OpenAIEmbedder(
            EmbeddingConfig(provider="openai", model=cfg.model, base_url=cfg.base_url, api_key_env=cfg.api_key_env,
                            timeout_s=cfg.timeout_s),
            section="[embedding.assist]", request=cfg.request,
        )
        self.host = self.client.host
        # Of everything it has in the air together: the time from its first request out to its
        # last one back, per character. That holds for a server with one model, where requests
        # wait for each other, and for an API that answers them side by side.
        self.speed = _Speed()
        self.in_the_air = 0  # characters of the requests that are out
        self._out, self._busy_since, self._landed = 0, 0.0, 0
        self.state = UNCHECKED
        self.reason: str | None = None  # why it is not used, in one sentence
        self.agreement: float | None = None  # the smallest cosine of the last check
        self.dim: int | None = None
        self.prefix = ""  # put before each document text
        self._rest_until = 0.0
        self._next_rest = FIRST_PAUSE_S
        self._lock = threading.Lock()

    @property
    def usable(self) -> bool:
        with self._lock:
            return self.state == SHARING and self.clock() >= self._rest_until

    @property
    def check_due(self) -> bool:
        """Whether its vectors have to be compared (again) before it gets work: at first, and
        after a failure once its rest is over, since what answers then may be another server."""
        with self._lock:
            return self.state == UNCHECKED or (self.state == RESTING and self.clock() >= self._rest_until)

    def checking(self) -> None:
        with self._lock:
            self.state = CHECKING

    def accept(self, agreement: float, dim: int, prefix: str) -> None:
        with self._lock:
            self.state, self.reason, self.agreement, self.dim, self.prefix = SHARING, None, agreement, dim, prefix
        log.info("the assist endpoint %s gives the local model's vectors for %s (cosine %.6f at worst): it shares "
                 "the work of large embedding calls", self.host, self.cfg.model, agreement)

    def refuse(self, reason: str, agreement: float | None = None) -> None:
        """Not used again by this process: it answered, and not as the local model does."""
        with self._lock:
            already = self.state == REFUSED
            self.state, self.reason, self.agreement = REFUSED, reason, agreement
        if not already:
            log.warning("the assist endpoint is not used: %s", reason)

    def failed(self, error: Exception) -> None:
        """A request did not come back with vectors. What may pass (TryLater) rests the endpoint,
        longer each time; after a rate limit it gets work again as it is, after anything else its
        vectors are compared first. Any other error is the endpoint's answer: it is refused."""
        if not isinstance(error, TryLater):
            return self.refuse(str(error))
        with self._lock:
            now = self.clock()
            if self.state == REFUSED or now < self._rest_until:  # refused, or one more request of the same outage
                return
            rest = error.wait or self._next_rest
            self._next_rest = min(self._next_rest * 2, LONGEST_PAUSE_S)
            self._rest_until = now + rest
            if not error.rate_limited:
                self.state = RESTING
            self.reason = f"{error}; the local model embeds alone, and the endpoint is tried again in {rest:.0f} s"
        log.warning("the assist endpoint is not used for now: %s", self.reason)

    def late(self, chars: int, seconds: float) -> None:
        """`chars` characters were expected back within less than the `seconds` that have passed:
        the endpoint is at most this fast."""
        with self._lock:
            self.speed.add(chars, seconds)

    def left(self, chars: int) -> None:
        """A request of `chars` characters goes out."""
        with self._lock:
            if not self._out:
                self._busy_since, self._landed = time.perf_counter(), 0
            self._out += 1
            self.in_the_air += chars

    def back(self, chars: int, ok: bool) -> None:
        """A request is back, with vectors (`ok`) or not. Once none is out, what came back since
        the first one left is one measure of the endpoint's speed."""
        with self._lock:
            self._out -= 1
            self.in_the_air -= chars
            self._landed += chars if ok else 0
            if not self._out:
                self.speed.add(self._landed, time.perf_counter() - self._busy_since)
            if ok:
                self._next_rest = FIRST_PAUSE_S
                if self.state == SHARING and self.clock() >= self._rest_until:
                    self.reason = None

    def embed(self, texts: list[str]) -> np.ndarray:
        """Document vectors for these texts from the endpoint, normalized. A reply that is not what
        the check saw (another length, not normalized) raises: the endpoint is then refused."""
        raw = self.client.attempt([self.prefix + t for t in texts])
        if raw.shape[1] != self.dim or not np.isfinite(raw).all():
            raise RuntimeError(f"{self.host} returned vectors of {raw.shape[1]} numbers, or numbers that are not "
                               f"finite, after its check passed with {self.dim}")
        if np.abs(np.linalg.norm(raw, axis=1) - 1.0).max() > NORM_TOLERANCE:
            raise RuntimeError(f"{self.host} returned vectors that are not normalized after its check passed")
        return l2_normalize(raw)


@dataclass
class _Flight:
    """A request in the air: its texts, their cost, when it left and when it is expected back."""

    indices: list[int]
    cost: int
    load: int  # the characters the endpoint had in the air with it
    left: float
    expected: float  # seconds until it is back, by the endpoint's measured speed for that load
    landed: bool = False
    retaken: bool = False

    def retake_at(self, now: float, redo: float | None) -> float:
        """When the local model, free at `now` and needing `redo` seconds for these texts, takes
        them back."""
        due = self.left + self.expected
        if redo is None:
            return max(self.left + LEAST_PATIENCE_S, due + self.expected)
        return now if now + redo <= due else due + redo


class _Split:
    """One large call: its texts in a row, the local model working from the front and the endpoint
    from the back."""

    def __init__(self, owner: AssistedEmbedder, texts: list[str]):
        self.owner, self.texts = owner, texts
        self.cost = [len(t) + 1 for t in texts]  # in characters, as the indexer counts a call
        self.todo = deque(range(len(texts)))  # not taken by anyone yet
        self.todo_cost = sum(self.cost)
        self.rows: list[np.ndarray | None] = [None] * len(texts)
        self.missing = len(texts)
        self.flights: list[_Flight] = []
        self.crew = 0  # threads asking the endpoint
        self.closed = False
        self.cond = threading.Condition()

    def run(self) -> np.ndarray:
        owner = self.owner
        with self.cond:
            bite = self._bite()  # the local model's first batch is taken before any request starts
            self._man()
        try:
            while bite:
                loaded = owner.inner.ready
                t = time.perf_counter()
                vecs = owner.inner.embed_documents([self.texts[i] for i in bite])
                took = time.perf_counter() - t
                with self.cond:
                    if loaded:  # a call that loads the model first says nothing about its speed
                        owner.local_speed.add(sum(self.cost[i] for i in bite), took)
                    self._fill(bite, vecs, "local")
                    bite = self._next_bite()
        finally:
            with self.cond:
                self.closed = True  # nothing more is taken; a request still in the air is ignored
        return np.stack(self.rows)  # type: ignore[arg-type]

    def _bite(self) -> list[int]:
        """The local model's next batch: from the front, the longest texts first, as without an assist."""
        bite = [self.todo.popleft() for _ in range(min(self.owner.batch_size, len(self.todo)))]
        self.todo_cost -= sum(self.cost[i] for i in bite)
        return bite

    def _next_bite(self) -> list[int]:
        """What the local model embeds next: untaken texts; else the texts of a request that is
        late, which it then embeds itself; else nothing yet, until a request lands or is late.
        Empty when every vector is there."""
        owner = self.owner
        while self.missing:
            if self.todo:
                self._man()  # an endpoint that is back from a rest joins in again
                return self._bite()
            now = time.monotonic()
            out = [f for f in self.flights if not f.landed and not f.retaken]
            if not out:
                raise RuntimeError("texts of an embedding call were lost between the local model and the endpoint")
            when = {id(f): f.retake_at(now, owner.local_speed.seconds(f.cost)) for f in out}
            take = min(out, key=lambda f: when[id(f)])
            if now >= when[id(take)]:
                take.retaken = True
                if now > take.left + take.expected:
                    owner.endpoint.late(take.load, now - take.left)
                if bite := [i for i in take.indices if self.rows[i] is None]:
                    return bite
                continue
            self.cond.wait(timeout=when[id(take)] - now)
        return []

    def _fill(self, indices: list[int], vecs: np.ndarray, source: str) -> None:
        new = 0
        for i, vec in zip(indices, vecs):
            if self.rows[i] is None:  # the first result counts, when two embedded the same text
                self.rows[i] = vec
                new += 1
        self.missing -= new
        self.owner.count(source, new)

    def _man(self) -> None:
        """Start threads for the endpoint, as many as have requests to make."""
        owner = self.owner
        if self.closed or not owner.endpoint.usable or not self._worth(self.cost[self.todo[-1]] if self.todo else 0):
            return
        wanted = min(owner.cfg.max_concurrency, -(-len(self.todo) // owner.cfg.batch_size))
        for _ in range(wanted - self.crew):
            self.crew += 1
            threading.Thread(target=self._fly, name="codemem-assist", daemon=True).start()

    def _worth(self, mine: int) -> bool:
        """Whether a request of `mine` characters from the back is the endpoint's to make: it is
        expected back, after what the endpoint already has in the air, before the local model at
        its measured speed would have reached those texts. The last text is never the endpoint's."""
        owner = self.owner
        ahead = self.todo_cost - mine  # what the local model embeds before it gets there
        there = owner.local_speed.seconds(ahead)
        back = owner.endpoint.speed.seconds(owner.endpoint.in_the_air + mine)
        return ahead > 0 and not (there is not None and back is not None and back > there)

    def _claim(self) -> list[int]:
        """A request's texts: from the back, as many as are the endpoint's to take (`_worth`). An
        endpoint that is slow beside the local model so gets few texts or none."""
        owner = self.owner
        if self.closed or not owner.endpoint.usable:
            return []
        taken: list[int] = []
        cost = 0
        while self.todo and len(taken) < owner.cfg.batch_size and self._worth(cost + self.cost[self.todo[-1]]):
            cost += self.cost[self.todo[-1]]
            taken.append(self.todo.pop())
        self.todo_cost -= cost
        return taken[::-1]

    def _fly(self) -> None:
        """One thread's requests to the endpoint, until it has none to make or one fails."""
        owner, endpoint = self.owner, self.owner.endpoint
        try:
            while True:
                with self.cond:
                    indices = self._claim()
                    if not indices:
                        return
                    cost = sum(self.cost[i] for i in indices)
                    load = endpoint.in_the_air + cost
                    expected = endpoint.speed.seconds(load)
                    self.flights.append(flight := _Flight(
                        indices, cost, load, time.monotonic(), owner.cfg.timeout_s if expected is None else expected
                    ))
                    endpoint.left(cost)
                try:
                    vecs = endpoint.embed([self.texts[i] for i in indices])
                except Exception as e:
                    endpoint.back(cost, ok=False)
                    endpoint.failed(e)
                    with self.cond:
                        flight.landed = True
                        if not flight.retaken and not self.closed:  # back to the row, at the local model's far end
                            back = [i for i in indices if self.rows[i] is None]
                            self.todo.extend(back)
                            self.todo_cost += sum(self.cost[i] for i in back)
                        self.cond.notify_all()
                    return
                endpoint.back(cost, ok=True)
                with self.cond:
                    flight.landed = True
                    if not self.closed:
                        self._fill(indices, vecs, "endpoint")
                    self.cond.notify_all()
        finally:
            with self.cond:
                self.crew -= 1
                self.cond.notify_all()


class AssistedEmbedder(Embedder):
    """The local embedder, with an endpoint that embeds part of each large call's documents. Its
    key, its queries, its served texts and its idle behaviour are the local embedder's own."""

    def __init__(
        self, inner: Embedder, cfg: AssistConfig, *, batch_size: int = 16, max_seq_length: int | None = 1024,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.inner, self.cfg = inner, cfg
        self.model_name = inner.model_name
        self.batch_size = max(1, batch_size)  # the local model's: a call of up to this many texts is not shared
        self.max_seq_length = max_seq_length
        self.endpoint = Endpoint(cfg, clock)
        self.local_speed = _Speed()
        self.shared = {"local": 0, "endpoint": 0}  # document texts each has embedded in shared calls
        self._uses = _Uses(clock)  # a shared call is one use: no unload or trim between its local batches
        self._lock = threading.Lock()
        self._probe: np.ndarray | None = None  # the local model's vectors for the probe texts

    @property
    def dim(self) -> int:
        return self.inner.dim

    @property
    def key(self) -> str:
        return self.inner.key

    @property
    def ready(self) -> bool:
        return self.inner.ready

    @property
    def prefixes(self) -> tuple[str, str]:
        return self.inner.prefixes

    def touch(self) -> None:
        self._uses.touch()
        self.inner.touch()

    def unload(self, idle_seconds: float = 0.0) -> bool:
        return self._uses.drop_if_idle(idle_seconds, lambda: self.inner.unload(idle_seconds))

    def trim(self, idle_seconds: float = 0.0) -> bool:
        return self._uses.trim_if_idle(idle_seconds, lambda: self.inner.trim(idle_seconds))

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self.inner.embed_queries(texts)

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        return self.inner.embed_texts(texts)

    @_counted
    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        texts = list(texts)
        if len(texts) <= self.batch_size:
            return self.inner.embed_documents(texts)
        self._check_if_due()
        if self.endpoint.state == REFUSED:
            return self.inner.embed_documents(texts)
        return _Split(self, texts).run()  # an endpoint that is being checked or is resting joins in when it can

    def count(self, source: str, texts: int) -> None:
        with self._lock:
            self.shared[source] += texts

    # ---- the check
    def _check_if_due(self) -> None:
        """Compare the endpoint's vectors with the local model's when that is due. The local half
        runs here, in the caller's thread, which has the model; the request runs in its own
        thread, so an endpoint that does not answer holds no call up. A first check is waited for
        briefly, so that the call that starts it can share its work already."""
        endpoint = self.endpoint
        with self._lock:
            if not endpoint.check_due:
                return
            first = endpoint.state == UNCHECKED
            endpoint.checking()
        try:
            prefix = self.cfg.document_prefix if self.cfg.document_prefix is not None else self.inner.prefixes[1]
        except NotImplementedError as e:  # a plugin embedder that does not name its prefixes
            return endpoint.refuse(f"{e}, so the endpoint's texts cannot be given the same one")
        probes = probe_texts(self.max_seq_length)
        texts = [text for _, text in probes]
        local_done = threading.Event()
        answer = threading.Thread(
            target=self._compare, args=(probes, prefix, local_done), name="codemem-assist-check", daemon=True
        )
        answer.start()
        try:
            if self._probe is None:
                self._probe = self._remembered(texts, prefix)
            if self._probe is None:
                loaded = self.inner.ready
                t = time.perf_counter()
                self._probe = np.asarray(self.inner.embed_documents(texts), dtype=np.float32)
                if loaded:
                    self.local_speed.add(sum(len(text) + 1 for text in texts), time.perf_counter() - t)
                self._remember(texts, prefix, self._probe)
        finally:
            local_done.set()
        if first:
            answer.join(FIRST_CHECK_WAIT_S)

    def _compare(self, probes: list[tuple[str, str]], prefix: str, local_done: threading.Event) -> None:
        """The endpoint's half of a check, and its verdict."""
        endpoint = self.endpoint
        texts = [text for _, text in probes]
        try:
            t = time.perf_counter()
            raw = endpoint.client.attempt([prefix + text for text in texts])
            took = time.perf_counter() - t
            local_done.wait()
            if self._probe is None:  # the local model failed; its error went to the caller
                with endpoint._lock:
                    endpoint.state = UNCHECKED
                return
            agreement, reason = difference(
                self._probe, raw, [label for label, _ in probes], endpoint.host, self.cfg.model, self.max_seq_length
            )
            if reason is None:
                endpoint.speed.add(sum(len(prefix) + len(text) + 1 for text in texts), took)
                endpoint.accept(agreement or 0.0, raw.shape[1], prefix)
            else:
                endpoint.refuse(reason, agreement)
        except TryLater as e:
            endpoint.failed(e)
            with endpoint._lock:
                endpoint.state = RESTING  # also after a rate limit: it has not been compared yet
        except Exception as e:
            endpoint.refuse(str(e))
        self._remember_verdict()

    # ---- what is remembered between processes
    def _probe_file(self, texts: list[str], prefix: str) -> Path:
        """Where the local model's probe vectors are kept. They belong to the embedder key, which
        names the model, its weights, its longest text, its precision and its device, so they are
        computed once per machine and model, and a check then costs one request."""
        name = hashlib.sha256(json.dumps([self.inner.key, prefix, texts]).encode("utf-8")).hexdigest()[:16]
        return codemem_home() / "assist" / f"probe-{name}.npy"

    def _remembered(self, texts: list[str], prefix: str) -> np.ndarray | None:
        try:
            vecs = np.load(self._probe_file(texts, prefix), allow_pickle=False)
        except (OSError, ValueError):
            return None
        return vecs if vecs.ndim == 2 and len(vecs) == len(texts) else None

    def _remember(self, texts: list[str], prefix: str, vecs: np.ndarray) -> None:
        path = self._probe_file(texts, prefix)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.stem}.{os.getpid()}.tmp.npy")
            np.save(tmp, vecs, allow_pickle=False)
            os.replace(tmp, path)
        except OSError:  # it only saves the local model a few texts at the next start
            log.debug("could not write %s", path)

    def _remember_verdict(self) -> None:
        """Keep the last check's result for `codemem status`, which runs in a process of its own."""
        path = _verdicts_file()
        try:
            verdicts = _read_verdicts()
            verdict = {k: v for k, v in self.status().items() if k != "texts"}
            verdicts[_endpoint_id(self.cfg, self.inner.key)] = {**verdict, "checked_at": time.time()}
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(verdicts), "utf-8")
            os.replace(tmp, path)
        except OSError:
            log.debug("could not write %s", path)

    def status(self) -> dict[str, Any]:
        """The endpoint for `status`: where code is sent, whether it shares the work, and why not."""
        endpoint = self.endpoint
        with endpoint._lock:
            state, reason, agreement = endpoint.state, endpoint.reason, endpoint.agreement
            if state == SHARING and endpoint.clock() < endpoint._rest_until:
                state = RESTING  # a rate limit: it shares again without another check
        return {
            "host": endpoint.host, "model": self.cfg.model, "state": state, "reason": reason, "agreement": agreement,
            "texts": dict(self.shared),
        }


def _verdicts_file() -> Path:
    return codemem_home() / "assist" / "checks.json"


def _read_verdicts() -> dict[str, Any]:
    try:
        verdicts = json.loads(_verdicts_file().read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return verdicts if isinstance(verdicts, dict) else {}


def _endpoint_id(cfg: AssistConfig, local_key: str) -> str:
    """Names a pairing of a local model with an endpoint's settings, for the remembered verdicts."""
    what = [local_key, cfg.base_url, cfg.model, cfg.document_prefix, cfg.request]
    return hashlib.sha256(json.dumps(what, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def describe(
    cfg: AssistConfig, embedders: Iterable[Embedder], local_keys: Iterable[str | None]
) -> dict[str, Any] | None:
    """The assist endpoint for `status`: from an embedder of this process that has one, else what
    the last check of another process found for one of the index's embedder keys, else that it
    has not been checked. None without an assist."""
    if not cfg.active:
        return None
    for embedder in embedders:
        if isinstance(embedder, AssistedEmbedder) and embedder.endpoint.state != UNCHECKED:
            return embedder.status()
    verdicts = _read_verdicts()
    for key in local_keys:
        if key and (verdict := verdicts.get(_endpoint_id(cfg, key))):
            return verdict
    client = Endpoint(cfg)
    return {"host": client.host, "model": cfg.model, "state": UNCHECKED, "reason": None, "agreement": None}
