"""A second source of document vectors beside the local model (`[embedding.assist]`).

In a build the local model is the slow part. `AssistedEmbedder` wraps the local embedder so that
an OpenAI-compatible endpoint that serves the same model (a `codemem serve-embeddings` server on a
machine with a GPU, or a hosted API) embeds part of each large call's texts while the local model
embeds the rest. The vectors are stored under the local embedder's key, as if it had made them
all, so the endpoint has to give the same vectors. Four rules keep that true and keep a build
going (docs/architecture.md §3.5):

- **Proof first.** Before the endpoint gets any text, a fixed set of probe texts is embedded both
  ways and compared (`SAME_VECTORS`), the endpoint's vectors scaled to length 1. An endpoint that
  differs is not used, and `status` says why. `AssistedEmbedder.check` runs that alone.
- **A text the local model would cut stays local.** The local model reads `max_seq_length` tokens
  of a text; a hosted model usually reads many more and would give another vector for a longer
  one. So each call's texts are counted with the local model's own tokenizer (`Embedder.cut`), and
  the endpoint is handed only those the local model reads whole.
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
import re
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
PROBES_VERSION = 2  # part of the name of a remembered probe: another recipe below makes new files
FIRST_PAUSE_S, LONGEST_PAUSE_S = 1.0, 60.0  # after a failure the endpoint rests; each further failure doubles the rest
# When the local model has nothing else left, it takes a request's texts back and embeds them
# itself: at once if it would be done before the request is expected back, else once the request
# is overdue by the time the local model needs for them. The first result counts, so a request
# that hangs costs a call about twice that time, not its timeout. Until the local model's speed is
# known, a request is overdue at twice its expected time, and at LEAST_PATIENCE_S at the earliest.
LEAST_PATIENCE_S = 0.5
FIRST_CHECK_WAIT_S = 2.0  # how long a build's first large call waits for the endpoint's answer to the probe

UNCHECKED, CHECKING, SHARING, RESTING, REFUSED = "unchecked", "checking", "sharing", "resting", "refused"
_FULL = "a text as long as the local model reads"
_LONG = "a long text"  # the last probe of a local model that reads further than the probe's long text
_FILL = 64  # one-letter words tried at most to fill the last probe to the limit: a word of its text is far fewer tokens
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


_SUBJECTS = ("session", "invoice", "upload", "tenant", "webhook", "ledger", "thumbnail", "refund",
             "cursor", "shard", "digest", "quota", "locale", "replica", "voucher", "sensor")
_ACTIONS = ("open", "settle", "resize", "archive", "retry", "audit", "render", "revoke",
            "advance", "split", "verify", "raise", "format", "promote", "redeem", "sample")


def _line(i: int) -> str:
    """Line `i` of the probe's long text: seven words, and of the first 256 lines no two do the
    same thing to the same thing, so a text that is cut earlier is another text to a model."""
    subject, action = _SUBJECTS[i % 16], _ACTIONS[(i // 16 + i) % 16]
    return f"{subject}_{i} = {action}_{subject}({_SUBJECTS[(i + 5) % 16]}_{i}, limit={i % 24})  # {action} {i}"


def probe_texts(inner: Embedder, max_seq_length: int | None) -> list[tuple[str, str]]:
    """The probe: (what it is, the text), each one a text the local model reads whole
    (`Embedder.cut`). The last is filled to the local model's limit: the longest start of a long
    text that the model does not cut, then one-letter words for as long as it still does not. An
    endpoint that cuts a text earlier gives another vector for that one. The long text has more
    than four words a line, so `max_seq_length // 4` lines are more tokens than the limit under
    any tokenizer."""
    short = [probe for probe, cut in zip(_PROBES, inner.cut([text for _, text in _PROBES])) if not cut]
    lines = "\n".join(_line(i) for i in range(max(64, (max_seq_length or 0) // 4)))
    words = re.findall(r"\S+\s*", lines)
    if not inner.cut([lines])[0]:
        return [*short, (_LONG, lines)]
    low, high = 0, len(words) - 1  # the most words the local model reads whole, found by halving
    while low < high:
        middle = (low + high + 1) // 2
        if inner.cut(["".join(words[:middle])])[0]:
            high = middle - 1
        else:
            low = middle
    text = "".join(words[:low]).rstrip()
    for _ in range(_FILL):
        if inner.cut([longer := f"{text} x".lstrip()])[0]:
            break
        text = longer
    return [*short, (_FULL, text)] if text else short


def _lengths(raw: np.ndarray) -> tuple[np.ndarray, bool]:
    """Each vector's length, and whether every one can be scaled to length 1: none is all zeros,
    and none holds a number that is not finite."""
    with np.errstate(invalid="ignore", over="ignore"):
        norms = np.linalg.norm(raw, axis=1)
    return norms, bool(np.isfinite(norms).all() and (norms > 0).all())


def difference(
    local: np.ndarray, raw: np.ndarray, probes: Sequence[tuple[str, str]], host: str, model: str
) -> dict[str, Any]:
    """Compare an endpoint's probe vectors with the local model's, after scaling the endpoint's to
    length 1: a provider need not normalize. `reason` says why the endpoint cannot share the work
    and is None when it can; `agreement` is the smallest cosine; `probes` has each probe's numbers,
    the endpoint's lengths as it sent them."""
    rows = [{"probe": label, "characters": len(text), "cosine": None,
             "local_length": round(float(np.linalg.norm(vec)), 6), "endpoint_length": None}
            for (label, text), vec in zip(probes, local)]
    if raw.shape[1] != local.shape[1]:
        return {"agreement": None, "probes": rows, "reason": (
            f"{host} returns vectors of {raw.shape[1]} numbers for {model} and the local model's have "
            f"{local.shape[1]}: another model, or vectors that a setting cuts short")}
    norms, scalable = _lengths(raw)
    for row, norm in zip(rows, norms):
        row["endpoint_length"] = round(float(norm), 6) if np.isfinite(norm) else None
    if not scalable:
        return {"agreement": None, "probes": rows, "reason": (
            f"{host} returns a vector for {model} that cannot be scaled to length 1: it is all zeros, or holds a "
            "number that is not finite")}
    cosines = np.sum(local * (raw / norms[:, None]), axis=1)
    for row, cosine in zip(rows, cosines):
        row["cosine"] = round(float(cosine), 6)
    agreement = float(cosines.min())
    differing = [label for (label, _), cosine in zip(probes, cosines) if cosine < SAME_VECTORS]
    if not differing:
        reason = None
    elif differing[0] in (_FULL, _LONG):  # the last probe alone
        reason = (f"{host} gives the local model's vectors for short texts and another one for {differing[0]} "
                  f"(cosine {agreement:.5f}, {SAME_VECTORS} needed): it probably cuts a text earlier than the local "
                  "model does")
    else:
        reason = (f"{host} gives other vectors than the local model for the same texts (cosine {agreement:.5f} at "
                  f"worst, {SAME_VECTORS} needed): another model, another prompt before the text, or another precision")
    return {"agreement": agreement, "probes": rows, "reason": reason}


def _said(error: Exception, host: str) -> str:
    """Why a request to `host` gave no vectors, in words. The client's own errors (RuntimeError)
    are sentences already; anything else is a reply of another shape than an embeddings reply."""
    if isinstance(error, RuntimeError):
        return str(error)
    return f"{host} did not answer as an embeddings endpoint does ({type(error).__name__}: {error})"


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
        self.failure: str | None = None  # the last failure alone, without what a build does about it
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
        """A check found its vectors equal to the local model's."""
        with self._lock:
            if self.state != CHECKING:  # refused meanwhile, by a reply to an earlier request
                return
            self.state, self.reason, self.agreement, self.dim, self.prefix = SHARING, None, agreement, dim, prefix
        log.info("the assist endpoint %s gives the local model's vectors for %s (cosine %.6f at worst): it shares "
                 "the work of large embedding calls", self.host, self.cfg.model, agreement)

    def unchecked(self, state: str) -> None:
        """A check ended without a verdict: back to `state`, unless the endpoint was refused meanwhile."""
        with self._lock:
            if self.state == CHECKING:
                self.state = state

    def refuse(self, reason: str, agreement: float | None = None) -> None:
        """Not used again by this process: it answered, and not as the local model does."""
        reason = " ".join(reason.split())  # one line, whatever a provider's message holds
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
            return self.refuse(_said(error, self.host))
        with self._lock:
            now = self.clock()
            if self.state == REFUSED or now < self._rest_until:  # refused, or one more request of the same outage
                return
            rest = error.wait or self._next_rest
            self._next_rest = min(self._next_rest * 2, LONGEST_PAUSE_S)
            self._rest_until = now + rest
            if not error.rate_limited:
                self.state = RESTING
            self.failure = " ".join(str(error).split())
            self.reason = (
                f"{self.failure}; the local model embeds alone, and the endpoint is tried again in {rest:.0f} s"
            )
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
        """Document vectors for these texts from the endpoint, scaled to length 1. A reply that
        cannot be what the check saw (another number of numbers, a vector that cannot be scaled)
        raises: the endpoint is then refused."""
        raw = self.client.attempt([self.prefix + t for t in texts])
        if raw.shape[1] != self.dim:
            raise RuntimeError(f"{self.host} returned vectors of {raw.shape[1]} numbers after its check passed with "
                               f"{self.dim}")
        if not _lengths(raw)[1]:
            raise RuntimeError(f"{self.host} returned a vector that cannot be scaled to length 1 (all zeros, or a "
                               "number that is not finite) after its check passed")
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

    def __init__(self, owner: AssistedEmbedder, texts: list[str], cut: list[bool]):
        self.owner, self.texts, self.cut = owner, texts, cut
        self.cost = [len(t) + 1 for t in texts]  # in characters, as the indexer counts a call
        # Not taken by anyone yet. The texts the local model would cut are its own: they stand at
        # the front, where it starts, and the endpoint, coming from the back, stops before them.
        order = sorted(range(len(texts)), key=lambda i: not cut[i])
        self.todo = deque(order)
        self.todo_cost = sum(self.cost)
        self.rows: list[np.ndarray | None] = [None] * len(texts)
        self.missing = len(texts)
        self.made = {"local": 0, "endpoint": 0}  # vectors of this call by who made them
        self.flights: list[_Flight] = []
        self.crew = 0  # threads asking the endpoint
        self.closed = False
        self.cond = threading.Condition()

    def run(self) -> np.ndarray:
        owner, started = self.owner, time.perf_counter()
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
        log.debug(
            "an embedding call of %d texts took %.1f s: the local model embedded %d (%d are longer than it reads), "
            "%s embedded %d", len(self.texts), time.perf_counter() - started, self.made["local"], sum(self.cut),
            owner.endpoint.host, self.made["endpoint"],
        )
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
        self.made[source] += new
        self.owner.count(source, new)

    def _man(self) -> None:
        """Start threads for the endpoint, as many as have requests to make."""
        owner = self.owner
        if self.closed or not owner.endpoint.usable or not self.todo or not self._worth(self.cost[self.todo[-1]]):
            return
        wanted = min(owner.cfg.max_concurrency, -(-len(self.todo) // owner.cfg.batch_size))
        for _ in range(wanted - self.crew):
            self.crew += 1
            threading.Thread(target=self._fly, name="codemem-assist", daemon=True).start()

    def _worth(self, mine: int) -> bool:
        """Whether a request of `mine` characters from the back is the endpoint's to make: it is
        expected back, after what the endpoint already has in the air, before the local model at
        its measured speed would have reached those texts. The last text is never the endpoint's,
        and neither is one the local model would cut."""
        owner = self.owner
        if not self.todo or self.cut[self.todo[-1]]:
            return False
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
        # Document texts of shared calls: who embedded how many, and how many of the local model's
        # were its own because it reads only part of them.
        self.shared = {"local": 0, "endpoint": 0, "cut": 0}
        self._uses = _Uses(clock)  # a shared call is one use: no unload or trim between its local batches
        self._lock = threading.Lock()
        # The probe, the local model's vectors for it, and what the local model puts before a
        # document (None until it had to be asked: a config may name the endpoint's prefix itself).
        self._probe: tuple[list[tuple[str, str]], np.ndarray, str | None] | None = None
        self._probe_from = ""  # where they came from, for a check's report

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

    def cut(self, texts: Sequence[str]) -> list[bool]:
        return self.inner.cut(texts)

    @property
    def freed_idle(self) -> bool:
        return self.inner.freed_idle

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
        cut = None if self.endpoint.state == REFUSED else self._cut(texts)
        if cut is None or all(cut):
            return self.inner.embed_documents(texts)
        self.count("cut", sum(cut))
        return _Split(self, texts, cut).run()  # an endpoint that is being checked or is resting joins in when it can

    def count(self, source: str, texts: int) -> None:
        with self._lock:
            self.shared[source] += texts

    def _cut(self, texts: list[str]) -> list[bool] | None:
        """Which of a call's texts the local model would cut, counted once for the call; the
        endpoint never gets one of those. None when the local embedder cannot say: nothing can
        then be handed on safely, and the endpoint is refused."""
        try:
            return self.inner.cut(texts)
        except NotImplementedError as e:
            self.endpoint.refuse(f"{e}, so an endpoint cannot share its work")
            return None

    # ---- the check
    def _local_half(self) -> tuple[list[tuple[str, str]], np.ndarray, str] | None:
        """The probe, the local model's vectors for it, and what goes before each of the
        endpoint's texts: this process's, else what an earlier process left on disk, else made
        now, in the caller's thread, which loads the local model. None when the local embedder
        cannot take part: the endpoint is then refused."""
        named, changed = self.cfg.document_prefix, False
        try:
            if self._probe is None:
                self._probe, self._probe_from = self._remembered(), "remembered"
            if self._probe is None:
                loaded = self.inner.ready
                probes = probe_texts(self.inner, self.max_seq_length)
                if not probes:
                    raise NotImplementedError(f"{self.model_name} cuts every probe text")
                t = time.perf_counter()
                vecs = np.asarray(self.inner.embed_documents([text for _, text in probes]), dtype=np.float32)
                if loaded:  # a call that loads the model first says nothing about its speed
                    self.local_speed.add(sum(len(text) + 1 for _, text in probes), time.perf_counter() - t)
                self._probe, self._probe_from, changed = (probes, vecs, None), "embedded now", True
            probes, vecs, prefix = self._probe
            if prefix is None and named is None:  # the local model's own, asked for once
                prefix, changed = self.inner.prefixes[1], True
            if changed:
                self._probe = (probes, vecs, prefix)
                self._remember(probes, vecs, prefix)
        except NotImplementedError as e:  # an embedder that names no prefix, or cannot say what it cuts
            self.endpoint.refuse(f"{e}, so an endpoint cannot share its work")
            return None
        except BaseException:
            self.endpoint.unchecked(UNCHECKED)  # the local model failed: its error is the caller's
            raise
        return probes, vecs, prefix if named is None else named

    def _check_if_due(self) -> None:
        """Compare the endpoint's vectors with the local model's when that is due. The request
        runs in its own thread, so an endpoint that does not answer holds no call up. A first
        check is waited for briefly, so that the call that starts it can share its work already."""
        endpoint = self.endpoint
        with self._lock:
            if not endpoint.check_due:
                return
            first = endpoint.state == UNCHECKED
            endpoint.checking()
        if (half := self._local_half()) is None:
            return
        answer = threading.Thread(target=self._ask, args=half, name="codemem-assist-check", daemon=True)
        answer.start()
        if first:
            answer.join(FIRST_CHECK_WAIT_S)

    def check(self) -> dict[str, Any]:
        """Embed the probe both ways now and say what it shows, with each probe's numbers: a way
        to try an endpoint without a build (`codemem status --check-assist`). The local model is
        loaded unless its half is remembered. The verdict is kept for `codemem status`."""
        self.endpoint.checking()
        half = self._local_half()
        report = self._ask(*half) if half else {**self._verdict(), "needed": SAME_VECTORS, "probes": []}
        if report["state"] == RESTING:  # no build is running that would try again
            report["reason"] = self.endpoint.failure
        return {**report, "local_model": self.model_name, "local_vectors": self._probe_from if half else None}

    def _ask(self, probes: list[tuple[str, str]], local: np.ndarray, prefix: str) -> dict[str, Any]:
        """The endpoint's half of a check, and the verdict: it shares the work, it is refused with
        the reason, or it could not be reached and rests. Returns the verdict with each probe's
        numbers."""
        endpoint, numbers = self.endpoint, []
        try:
            t = time.perf_counter()
            raw = endpoint.client.attempt([prefix + text for _, text in probes])
            took = time.perf_counter() - t
            found = difference(local, raw, probes, endpoint.host, self.cfg.model)
            numbers = found["probes"]
            if found["reason"] is None:
                endpoint.speed.add(sum(len(prefix) + len(text) + 1 for _, text in probes), took)
                endpoint.accept(found["agreement"], raw.shape[1], prefix)
            else:
                endpoint.refuse(found["reason"], found["agreement"])
        except TryLater as e:
            endpoint.failed(e)
            endpoint.unchecked(RESTING)  # also after a rate limit: it has not been compared yet
        except Exception as e:
            endpoint.refuse(_said(e, endpoint.host))
        self._remember_verdict()
        return {**self._verdict(), "needed": SAME_VECTORS, "probes": numbers}

    # ---- what is remembered between processes
    def _probe_file(self) -> Path:
        """Where the local half of a check is kept. It belongs to the embedder key, which names
        the model, its weights, its longest text, its precision and its device, so it is made
        once per machine and model, and a check then costs one request and no model."""
        name = hashlib.sha256(json.dumps([PROBES_VERSION, self.inner.key]).encode("utf-8")).hexdigest()[:16]
        return codemem_home() / "assist" / f"probe-{name}.npz"

    def _remembered(self) -> tuple[list[tuple[str, str]], np.ndarray, str | None] | None:
        try:
            with np.load(self._probe_file(), allow_pickle=False) as kept:
                said, vecs = json.loads(kept["said"].item()), np.asarray(kept["vectors"], dtype=np.float32)
            probes, prefix = [(str(label), str(text)) for label, text in said["probes"]], said["prefix"]
        except Exception:  # no file, or not one of ours: the half is made again
            return None
        return (probes, vecs, prefix) if probes and vecs.ndim == 2 and len(vecs) == len(probes) else None

    def _remember(self, probes: list[tuple[str, str]], vecs: np.ndarray, prefix: str | None) -> None:
        path = self._probe_file()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            with open(tmp, "wb") as f:
                np.savez(f, said=np.array(json.dumps({"probes": probes, "prefix": prefix})), vectors=vecs)
            os.replace(tmp, path)
        except OSError:  # it only saves the local model a few texts at the next start
            log.debug("could not write %s", path)

    def _remember_verdict(self) -> None:
        """Keep the last check's result for `codemem status`, which runs in a process of its own."""
        path = _verdicts_file()
        try:
            verdicts = _read_verdicts()
            mine = verdicts.setdefault(_endpoint_id(self.cfg), {})
            mine[self.inner.key] = {**self._verdict(), "checked_at": time.time()}
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(verdicts), "utf-8")
            os.replace(tmp, path)
        except OSError:
            log.debug("could not write %s", path)

    def _verdict(self) -> dict[str, Any]:
        """Where code is sent, whether the endpoint shares the work, and why not."""
        endpoint = self.endpoint
        with endpoint._lock:
            state, reason, agreement = endpoint.state, endpoint.reason, endpoint.agreement
            if state == SHARING and endpoint.clock() < endpoint._rest_until:
                state = RESTING  # a rate limit: it shares again without another check
        return {
            "host": endpoint.host, "model": self.cfg.model, "state": state, "reason": reason, "agreement": agreement,
        }

    def status(self) -> dict[str, Any]:
        """The endpoint for `status`: its verdict, and who embedded how many texts of the shared calls."""
        with self._lock:
            return {**self._verdict(), "texts": dict(self.shared)}


def _verdicts_file() -> Path:
    return codemem_home() / "assist" / "checks.json"


def _read_verdicts() -> dict[str, dict[str, Any]]:
    """What the last checks found: by endpoint settings, then by the local embedder's key."""
    try:
        verdicts = json.loads(_verdicts_file().read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(verdicts, dict):
        return {}
    return {name: found for name, found in verdicts.items() if isinstance(found, dict)}


def _endpoint_id(cfg: AssistConfig) -> str:
    """Names an endpoint's settings, for the remembered verdicts."""
    what = [cfg.base_url, cfg.model, cfg.document_prefix, cfg.request]
    return hashlib.sha256(json.dumps(what, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def describe(
    cfg: AssistConfig, embedders: Iterable[Embedder], local_keys: Iterable[str | None]
) -> dict[str, Any] | None:
    """The assist endpoint for `status`: from an embedder of this process that has one, else what
    the last check of another process found for one of the index's embedder keys (for an index
    that has none yet: the last check of this endpoint), else that it has not been checked. None
    without an assist."""
    if not cfg.active:
        return None
    for embedder in embedders:
        if isinstance(embedder, AssistedEmbedder) and embedder.endpoint.state != UNCHECKED:
            return embedder.status()
    checked = _read_verdicts().get(_endpoint_id(cfg), {})
    keys = [key for key in local_keys if key]
    found = [checked[key] for key in keys if key in checked]
    if not keys:  # nothing is built yet: a provider was tried first (`codemem status --check-assist`)
        found = sorted(checked.values(), key=lambda verdict: verdict.get("checked_at", 0), reverse=True)
    if found:
        return found[0]
    client = Endpoint(cfg)
    return {"host": client.host, "model": cfg.model, "state": UNCHECKED, "reason": None, "agreement": None}
