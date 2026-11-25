"""Embedder interface: the local sentence-transformers (jina) embedder, any OpenAI-compatible
embeddings API, an embedder class named in config (`vectors.<type>.embedder = "module:Class"`),
and FakeEmbedder.

Callers only see `embed_documents` / `embed_queries`; task prompts/prefixes are
handled here. All outputs are float32, L2-normalized, shape (n, dim), at the model's full
dimension: Matryoshka truncation (`embedding_dim`) is applied by the store when it builds the
search index, so changing it never re-embeds.

`Embedder.key` names the embedding space of document vectors (model and its weights version,
prompt, max length, dtype, device): vectors with equal keys are interchangeable, so the store and
the vector cache reuse them by (key, text hash).

`embed_texts` and `prefixes` are what `codemem serve-embeddings` needs to put an embedder behind an
HTTP endpoint (embedserver.py): the endpoint embeds each text as given, and its clients put the
query or document prefix in front themselves.

The local model's packages (PyTorch, sentence-transformers) are imported only when a local model
is used. A codemem that embeds through an API or a served model therefore runs in an environment
built without them, and one that is asked for the local model there names what is missing and the
two ways out.

A local model is loaded at its first use and can leave memory while idle (`Embedder.unload`,
docs/architecture.md §3.5); the next call loads it again. `Embedder.trim` gives back only what
its calls needed besides it.
"""

from __future__ import annotations

import dataclasses
import functools
import gc
import hashlib
import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from importlib.util import find_spec
from typing import Any
from urllib.parse import urlparse

import numpy as np

from .config import AssistConfig, Config, EmbeddingConfig, VectorConfig, model_version
from .plugins import load_object
from .tokenize import tokenize

log = logging.getLogger(__name__)

QUERY_PROMPT = "nl2code_query"
DOCUMENT_PROMPT = "nl2code_document"
# Fallback if a model card doesn't ship named prompts (expected for jina-code-embeddings).
FALLBACK_PROMPTS = {
    QUERY_PROMPT: "Find the most relevant code snippet given the following query:\n",
    DOCUMENT_PROMPT: "Candidate code snippet:\n",
}
_AS_GIVEN = ""  # no prompt: the text exactly as given
_QUERY_CACHE_SIZE = 512
# A model's working memory is given back once it has made no call for this long. Calls closer
# together are one burst, so nothing is given back between two calls of a batch.
TRIM_AFTER_IDLE = 5.0
# The local model's packages, by the name pip installs them under, with the name to print.
_LOCAL_PACKAGES = {"torch": "PyTorch", "sentence-transformers": "sentence-transformers"}


class LocalModelUnavailable(RuntimeError):
    """The packages the local embedding model runs on are not installed."""


def require_local_model() -> None:
    """Raise, naming what to install and what to set instead, when the local model's packages are
    missing (an environment built without them, for a client of an API or of a served model)."""
    missing = [package for package in _LOCAL_PACKAGES if find_spec(package.replace("-", "_")) is None]
    if missing:
        names = " and ".join(_LOCAL_PACKAGES[package] for package in missing)
        raise LocalModelUnavailable(
            f"The local embedding model cannot run because {names} {'is' if len(missing) == 1 else 'are'} not "
            f"installed: run `pip install {' '.join(missing)}`, or set `[embedding] provider = \"openai\"` to embed "
            "through an API or a `codemem serve-embeddings` server."
        )


def l2_normalize(vecs: np.ndarray) -> np.ndarray:
    """Every row at length 1. A row that already is, to the precision of a float32, comes back as it
    is: a vector a server has normalized is the same numbers after its client normalizes it again."""
    vecs = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.where((norms == 0) | (np.abs(norms - 1.0) < 1e-6), 1.0, norms)


class _Uses:
    """Who is using a model: the embedding calls in progress, and when the last one ended. It
    decides when a model's memory may be given back, never under a running call and only after
    the idle time asked for: the model itself (`Embedder.unload`), or only what its calls needed
    besides it (`Embedder.trim`). Tests replace `clock`, so they need not wait."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._calls = 0
        self._last = clock()
        self._trimmed = True  # no call has run since the last trim: nothing to give back

    def __enter__(self) -> None:
        with self._lock:
            self._calls += 1

    def __exit__(self, *exc: object) -> None:
        with self._lock:
            self._calls -= 1
            self._last = self.clock()
            self._trimmed = False

    def touch(self) -> None:
        with self._lock:
            self._last = self.clock()

    def drop_if_idle(self, seconds: float, drop: Callable[[], bool]) -> bool:
        """Run `drop`, which lets go of the model and says whether it held one, unless a call is
        running or the last use is less than `seconds` old. A call that starts meanwhile waits."""
        with self._lock:
            if self._calls or self.clock() - self._last < seconds:
                return False
            dropped = bool(drop())
            self._trimmed = self._trimmed or dropped  # what the model's calls needed goes with it
            return dropped

    def trim_if_idle(self, seconds: float, trim: Callable[[], bool]) -> bool:
        """Run `trim`, which gives back what calls needed besides the model, once after a burst of
        calls: not while one is running, not before the last use is `seconds` old, and not again
        until another call has ended. A call that starts meanwhile waits."""
        with self._lock:
            if self._calls or self._trimmed or self.clock() - self._last < seconds:
                return False
            self._trimmed = True
            return bool(trim())


def _counted(embed: Callable[..., np.ndarray]) -> Callable[..., np.ndarray]:
    """Make an embedding method a use of the model (`self._uses`): no unload while it runs."""

    @functools.wraps(embed)
    def call(self, *args, **kwargs):
        with self._uses:
            return embed(self, *args, **kwargs)

    return call


def _empty_cache(device: str) -> bool:
    """Empty the device's allocator cache; False for a device without one. On a GPU (cuda, mps,
    xpu) PyTorch keeps freed blocks for reuse, and they stay with the process until this."""
    import torch

    backend = getattr(torch, device, None)
    if not hasattr(backend, "empty_cache"):
        return False
    backend.empty_cache()
    return True


def _release_memory(device: str) -> None:
    """Hand a dropped model's memory back to the system: collect what reference cycles kept of
    it, then empty the device's allocator cache."""
    gc.collect()
    _empty_cache(device)


class Embedder(ABC):
    model_name: str

    @property
    @abstractmethod
    def dim(self) -> int: ...

    @property
    def key(self) -> str:
        """Identity of the document-vector space; equal keys give interchangeable vectors. Every
        built-in embedder defines it. A plugin class need not: PluginEmbedder names its vectors."""
        raise NotImplementedError(f"{type(self).__name__} does not name its vectors")

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> np.ndarray: ...

    @abstractmethod
    def embed_queries(self, texts: Sequence[str]) -> np.ndarray: ...

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        """Each text exactly as given, with nothing put before it. `codemem serve-embeddings` serves
        this; an embedder that does not define it cannot be served."""
        raise NotImplementedError(f"{type(self).__name__} cannot embed a text exactly as given")

    @property
    def prefixes(self) -> tuple[str, str]:
        """What this embedder puts before each query and before each document:
        `embed_texts([prefix + text])` gives what `embed_queries([text])` and `embed_documents([text])`
        give. A served model's clients carry the two as `query_prefix` and `document_prefix`."""
        raise NotImplementedError(f"{type(self).__name__} does not say what it puts before a query or a document")

    @property
    def ready(self) -> bool:
        """Can embed now, without loading a model first."""
        return True

    def touch(self) -> None:
        """Count as used now. A caller that will embed only if the model is in memory calls this
        before it checks `ready`: a model it then finds stays for its idle time, so `unload`
        cannot fall between the check and the call."""

    def unload(self, idle_seconds: float = 0.0) -> bool:
        """Free the model's memory, unless a call is using it or its last use is less than
        `idle_seconds` old. The next call loads it again. True when it was freed. An embedder
        that holds no model has nothing to free."""
        return False

    def trim(self, idle_seconds: float = 0.0) -> bool:
        """Give back what the model's calls needed besides the model itself (on a GPU, the
        allocator's cache), once after a burst of calls: not under a running call, not before
        the last use is `idle_seconds` old, and not again until another call has ended. The
        model stays in memory. True when something was given back."""
        return False


def release_idle(embedder: Embedder, idle_minutes: float) -> None:
    """What a quiet moment does for a model. Whoever owns the model calls this about once a
    second while it has no work for it (the service's writer, the embedding server's queue): the
    model is freed after `idle_minutes` without a call (0 keeps it), and otherwise what its calls
    needed besides it is given back, once after each burst. The embedder refuses both under a
    running call. An error is logged, not raised, and counts as a use, so the next try is an idle
    time away."""
    try:
        if idle_minutes > 0 and embedder.unload(idle_minutes * 60):
            log.info("unloaded %s after %g idle minutes", embedder.model_name, idle_minutes)
        else:
            embedder.trim(TRIM_AFTER_IDLE)
    except Exception:
        log.exception("could not give back the memory of %s", embedder.model_name)
        embedder.touch()


class FakeEmbedder(Embedder):
    """Deterministic hashed bag-of-tokens vectors. No downloads, ~instant.

    Texts sharing tokens get similar vectors, which is enough to exercise the
    pipeline and the usage signal in tests. It is not semantic.

    It also stands in for a model in memory: it starts loaded, `unload` drops it, the next call
    loads it again (`load`), and `trim` counts in `trims`, so tests cover the idle unload and the
    trim without the real model.
    """

    def __init__(self, dim: int = 64, clock: Callable[[], float] = time.monotonic):
        self.model_name = f"fake:{dim}"
        self._dim = dim
        self.calls: list[int] = []  # batch sizes, so tests can count embeddings
        self.loads = 0  # loads after an unload
        self.trims = 0  # times its calls' working memory was given back
        self._loaded = True
        self._lock = threading.Lock()
        self._uses = _Uses(clock)

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def key(self) -> str:
        return f"{self.model_name}|doc"

    @property
    def ready(self) -> bool:
        return self._loaded

    def touch(self) -> None:
        self._uses.touch()

    def load(self) -> None:
        """What loading the model would be. Tests override it to make a load slow."""
        self.loads += 1

    def unload(self, idle_seconds: float = 0.0) -> bool:
        return self._uses.drop_if_idle(idle_seconds, self._drop)

    def _drop(self) -> bool:
        had, self._loaded = self._loaded, False
        return had

    def trim(self, idle_seconds: float = 0.0) -> bool:
        return self._uses.trim_if_idle(idle_seconds, self._trim)

    def _trim(self) -> bool:
        self.trims += self._loaded
        return self._loaded

    @_counted
    def _embed(self, texts: Sequence[str]) -> np.ndarray:
        with self._lock:  # one load, however many calls wait for it
            if not self._loaded:
                self.load()
                self._loaded = True
        self.calls.append(len(texts))
        out = np.zeros((len(texts), self._dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for tok in tokenize(text):
                h = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "little") % self._dim
                out[row, idx] += 1.0 if h[4] & 1 else -1.0
        return l2_normalize(out)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed(texts)

    @property
    def prefixes(self) -> tuple[str, str]:
        return ("", "")


def resolve_device(preference: str) -> str:
    """The device a local model runs on. An environment without PyTorch has nothing to run on a GPU: cpu."""
    if preference == "cpu" or find_spec("torch") is None:
        return "cpu"
    import torch

    if preference in ("auto", "cuda") and torch.cuda.is_available():
        return "cuda"
    if preference in ("auto", "mps") and torch.backends.mps.is_available():
        # Apple Silicon GPU. torch reports it as unavailable on Windows and Linux.
        return "mps"
    if preference == "mps":
        log.warning("device=mps requested but torch.backends.mps is unavailable; using cpu")
        return "cpu"
    if preference == "xpu":
        # Intel Arc via PyTorch's XPU backend: experimental, fall back quietly.
        if getattr(torch, "xpu", None) is not None and torch.xpu.is_available():
            return "xpu"
        log.warning("device=xpu requested but torch.xpu is unavailable; using cpu")
        return "cpu"
    if preference == "cuda":
        log.warning("device=cuda requested but CUDA is unavailable; using cpu")
    return "cpu"


def resolve_dtype(preference: str, device: str) -> str:
    """auto = float16 on GPUs (cuda, mps), float32 elsewhere."""
    if preference != "auto":
        return preference
    return "float16" if device in ("cuda", "mps") else "float32"


class SentenceTransformerEmbedder(Embedder):
    """jina-code-embeddings (or any sentence-transformers model), loaded lazily."""

    def __init__(
        self,
        model_name: str,
        device: str = "auto",
        batch_size: int = 16,
        max_seq_length: int | None = 1024,
        dtype: str = "auto",
        version: str | None = None,
    ):
        self.model_name = model_name
        self.version = version  # of the weights (config.model_version); None for a hub name
        self.device_preference = device
        self.dtype_preference = dtype
        self.batch_size = batch_size
        self.max_seq_length = max_seq_length
        self._model = None
        self._prompts: dict[str, dict[str, str]] = {_AS_GIVEN: {"prompt": ""}}  # how each kind of text is encoded
        self._prefixes = ("", "")  # the query and document prompts as text, known once the model is loaded
        self._lock = threading.Lock()
        self._device: str | None = None
        self._queries: OrderedDict[str, np.ndarray] = OrderedDict()
        self._uses = _Uses()

    @property
    def ready(self) -> bool:
        return self._model is not None

    def touch(self) -> None:
        self._uses.touch()

    def unload(self, idle_seconds: float = 0.0) -> bool:
        if not self._lock.acquire(blocking=False):  # held by a load or a float32 pass: in use
            return False
        try:
            if not self._uses.drop_if_idle(idle_seconds, self._drop):
                return False
            # Still under the lock: a call that needs the model again loads it once this is done.
            _release_memory(self.device)
            return True
        finally:
            self._lock.release()

    def _drop(self) -> bool:
        had, self._model = self._model is not None, None
        return had

    def trim(self, idle_seconds: float = 0.0) -> bool:
        return self._uses.trim_if_idle(idle_seconds, lambda: self._model is not None and _empty_cache(self.device))

    @property
    def device(self) -> str:
        if self._device is None:
            if self.device_preference != "cpu":
                # Without PyTorch the answer would be "cpu", and the key would name another set of
                # vectors: an index built on a GPU would drop its vectors before the model failed.
                require_local_model()
            self._device = resolve_device(self.device_preference)
        return self._device

    @property
    def dtype(self) -> str:
        return resolve_dtype(self.dtype_preference, self.device)

    @property
    def key(self) -> str:
        """The model, the longest text, and the precision and device the model runs in: the
        weights are converted to that precision when they are loaded."""
        model = f"{self.model_name}#{self.version}" if self.version else self.model_name  # unchanged for hub names
        return f"{model}|doc|L{self.max_seq_length}|{self.dtype}|{self.device}"

    @property
    def model(self):
        with self._lock:
            if self._model is None:
                require_local_model()
                import torch
                from sentence_transformers import SentenceTransformer

                log.info("loading %s on %s (%s)", self.model_name, self.device, self.dtype)
                # The weights are converted to the precision the key names, whatever the file
                # stores: the default model's file is bfloat16, and is loaded as stored. For the
                # Apple GPU that happens on the CPU, before the move: converted on that GPU, the
                # blocks of the file's format stay in its allocator for as long as the model
                # lives (1.1 GB on an M1). Other GPUs convert on the device (not measured).
                first = "cpu" if self.device == "mps" else self.device
                model = SentenceTransformer(self.model_name, device=first)
                model = model.to(getattr(torch, self.dtype)).to(self.device)
                if self.max_seq_length:
                    model.max_seq_length = min(model.max_seq_length or 10**9, self.max_seq_length)
                available = getattr(model, "prompts", {}) or {}
                for name in (QUERY_PROMPT, DOCUMENT_PROMPT):
                    if name in available:
                        self._prompts[name] = {"prompt_name": name}
                    else:
                        log.warning("%s has no %r prompt; using built-in prefix", self.model_name, name)
                        self._prompts[name] = {"prompt": FALLBACK_PROMPTS[name]}
                self._prefixes = (
                    available.get(QUERY_PROMPT, FALLBACK_PROMPTS[QUERY_PROMPT]),
                    available.get(DOCUMENT_PROMPT, FALLBACK_PROMPTS[DOCUMENT_PROMPT]),
                )
                self._model = model
            return self._model

    @property
    def dim(self) -> int:
        model = self.model
        getter = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
        return int(getter())

    @_counted
    def _encode(self, texts: Sequence[str], prompt: str) -> np.ndarray:
        model = self.model
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        kwargs = dict(
            batch_size=self.batch_size, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False,
            **self._prompts[prompt],
        )
        vecs = np.asarray(model.encode(list(texts), **kwargs), dtype=np.float32)
        bad = ~np.isfinite(vecs).all(axis=1)
        if bad.any():
            # float16 can overflow on unusual inputs; redo those rows in float32.
            import torch

            log.warning("%d embeddings overflowed in %s; recomputing them in float32", int(bad.sum()), self.dtype)
            with self._lock:
                model.to(torch.float32)
                try:
                    redo = model.encode([t for t, b in zip(texts, bad) if b], **kwargs)
                finally:
                    model.to(getattr(torch, self.dtype))
            vecs[bad] = np.asarray(redo, dtype=np.float32)
        return l2_normalize(vecs)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts, DOCUMENT_PROMPT)

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts, _AS_GIVEN)

    @property
    def prefixes(self) -> tuple[str, str]:
        _ = self.model  # loads it: the prompts come with the model
        return self._prefixes

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        """Queries are cached (the eval asks the same query of several systems that share a model)."""
        missing = [t for t in dict.fromkeys(texts) if t not in self._queries]
        if missing:
            for text, vec in zip(missing, self._encode(missing, QUERY_PROMPT)):
                self._queries[text] = vec
                if len(self._queries) > _QUERY_CACHE_SIZE:
                    self._queries.popitem(last=False)
        return np.stack([self._queries[t] for t in texts]) if texts else np.zeros((0, self.dim), dtype=np.float32)


class OpenAIEmbedder(Embedder):
    """Any OpenAI-compatible `/embeddings` endpoint: Nebius, OpenAI, Together, a self-hosted vLLM
    or TEI server, Ollama. Texts go in requests of `batch_size`, up to `max_concurrency` at once.
    Rate limits (429), server errors (5xx) and dropped connections are retried with backoff;
    other errors fail at once, with the provider's message. The key is read from the environment
    variable `api_key_env` at each request and never stored."""

    RETRIES = 6
    BACKOFF_S = 1.0  # first wait between retries; doubles, up to 30 s

    def __init__(self, cfg: EmbeddingConfig, *, section: str = "[embedding]", request: dict[str, Any] | None = None):
        self.cfg = cfg
        self.model_name = cfg.model
        self.section = section  # the config section these settings come from, for messages
        self.request = dict(request or {})  # more fields for the request body, a provider's own
        self._dim: int | None = None
        self._client: Any = None
        self._lock = threading.Lock()
        self._queries: OrderedDict[str, np.ndarray] = OrderedDict()

    @property
    def host(self) -> str:
        return urlparse(self.cfg.base_url).netloc or self.cfg.base_url

    @property
    def key(self) -> str:
        prefix = self.cfg.document_prefix
        doc = hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:8] if prefix else "0"
        # A `space` names the vectors whatever address serves them: the host is then no part of the key.
        served_by = self.cfg.space or self.host
        return f"api:{served_by}|{self.model_name}|dims={self.cfg.dimensions or 'full'}|doc={doc}"

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._dim = int(self._request(["dimension check"]).shape[1])
        return self._dim

    def _http(self) -> Any:
        with self._lock:
            if self._client is None:
                import httpx

                self._client = httpx.Client(timeout=self.cfg.timeout_s)
            return self._client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key_env:
            key = os.environ.get(self.cfg.api_key_env)
            if not key:
                raise RuntimeError(
                    f"{self.section} api_key_env is {self.cfg.api_key_env!r}, but that environment variable is not set"
                )
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def attempt(self, texts: list[str]) -> np.ndarray:
        """One request, sent once: the reply's vectors as they came, one row per text. Raises
        TryLater for what a later request may not hit (a rate limit, a server error, a timeout, a
        refused or dropped connection) and RuntimeError, with the provider's message, for the rest."""
        import httpx

        url = self.cfg.base_url.rstrip("/") + "/embeddings"
        body: dict[str, Any] = {**self.request, "model": self.model_name, "input": texts}
        if self.cfg.dimensions:
            body["dimensions"] = self.cfg.dimensions
        try:
            r = self._http().post(url, json=body, headers=self._headers())
        except httpx.TransportError as e:
            raise TryLater(f"embedding request to {self.host} failed: {e}") from e
        if r.status_code == 429 or r.status_code >= 500:
            failed = f"embedding request to {self.host} failed: HTTP {r.status_code} {r.text[:300]}"
            raise TryLater(failed, _retry_after(r), rate_limited=r.status_code == 429)
        if r.status_code >= 400:
            raise RuntimeError(f"embedding request to {self.host} failed: HTTP {r.status_code} {r.text[:300]}")
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        if len(data) != len(texts):
            raise RuntimeError(f"{self.host} returned {len(data)} embeddings for {len(texts)} texts")
        rows = [d["embedding"] for d in data]
        if len({len(row) for row in rows}) != 1:
            raise RuntimeError(f"{self.host} returned vectors of different lengths")
        return np.asarray(rows, dtype=np.float32)

    def _request(self, texts: list[str]) -> np.ndarray:
        delay = self.BACKOFF_S
        for attempt in range(self.RETRIES):
            try:
                return self._shape(self.attempt(texts))
            except TryLater as e:
                if attempt == self.RETRIES - 1:
                    raise RuntimeError(str(e)) from e
                time.sleep(e.wait or delay)
                delay = min(delay * 2, 30.0)
        raise AssertionError("unreachable")

    def _shape(self, vecs: np.ndarray) -> np.ndarray:
        """A reply's vectors at the configured length, normalized. `dimensions` goes to the provider,
        but one that ignores it answers with full vectors: the first numbers of those are the short
        vector, so they are cut here, and what the key names is what gets stored."""
        want = self.cfg.dimensions
        if want and vecs.shape[1] < want:
            raise RuntimeError(
                f"{self.host} returned vectors of {vecs.shape[1]} numbers for {self.model_name}, fewer than "
                f"[embedding] dimensions = {want}"
            )
        return l2_normalize(vecs[:, :want] if want else vecs)

    def _embed(self, texts: Sequence[str], prefix: str) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        inputs = [prefix + t for t in texts]
        size = max(1, self.cfg.batch_size)
        batches = [inputs[i : i + size] for i in range(0, len(inputs), size)]
        if len(batches) == 1:
            return self._request(batches[0])
        with ThreadPoolExecutor(max_workers=max(1, self.cfg.max_concurrency)) as pool:
            return np.vstack(list(pool.map(self._request, batches)))

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed(texts, self.cfg.document_prefix)

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        """Queries are cached: a repeated query costs no request."""
        missing = [t for t in dict.fromkeys(texts) if t not in self._queries]
        if missing:
            for text, vec in zip(missing, self._embed(missing, self.cfg.query_prefix)):
                self._queries[text] = vec
                if len(self._queries) > _QUERY_CACHE_SIZE:
                    self._queries.popitem(last=False)
        return np.stack([self._queries[t] for t in texts]) if texts else np.zeros((0, self.dim), dtype=np.float32)


class TryLater(Exception):
    """A request failed in a way a later one may not: a rate limit (429), a server error (5xx), a
    timeout, a refused or dropped connection. `wait` is the server's Retry-After, when it sent
    one; `rate_limited` says the server answered, and only asked for fewer requests."""

    def __init__(self, message: str, wait: float | None = None, rate_limited: bool = False):
        super().__init__(message)
        self.wait, self.rate_limited = wait, rate_limited


def _retry_after(response: Any) -> float | None:
    """The server's Retry-After, in seconds (capped at a minute), when it sends one."""
    try:
        return min(float(response.headers.get("retry-after", "")), 60.0)
    except ValueError:
        return None


class PluginEmbedder(Embedder):
    """An embedder class named in config (`vectors.<type>.embedder = "module:Class"`), built
    as Class(model, config). It subclasses Embedder and gives `dim`, `embed_documents` and
    `embed_queries`; codemem names its vectors by model, weights version, class and the settings
    passed to it, so a new class or new weights re-embed. Its vectors are normalized here. A
    class that can free its model defines `unload()`, and one that can give back its calls' working
    memory defines `trim()`; each is called only while no call of the class is running and none has
    for the idle time, so the class needs no clock or lock for them."""

    def __init__(self, spec: str, model_name: str, config: Config, version: str | None):
        inner = load_object(spec)(model_name, config)
        if not isinstance(inner, Embedder):
            raise TypeError(f"{spec} must subclass codemem.embedder.Embedder")
        self.inner, self.spec, self.model_name, self.version = inner, spec, model_name, version
        self._settings = f"L{config.max_seq_length}|{config.dtype}|{config.device}"
        self._uses = _Uses()

    @property
    def dim(self) -> int:
        return self.inner.dim

    @property
    def key(self) -> str:
        model = f"{self.model_name}#{self.version}" if self.version else self.model_name
        return f"{model}|plugin={self.spec}|{self._settings}"

    @property
    def ready(self) -> bool:
        return self.inner.ready

    def touch(self) -> None:
        self._uses.touch()

    def unload(self, idle_seconds: float = 0.0) -> bool:
        return self._uses.drop_if_idle(idle_seconds, self.inner.unload)

    def trim(self, idle_seconds: float = 0.0) -> bool:
        return self._uses.trim_if_idle(idle_seconds, self.inner.trim)

    @_counted
    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return l2_normalize(self.inner.embed_documents(texts))

    @_counted
    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        return l2_normalize(self.inner.embed_queries(texts))

    @_counted
    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        return l2_normalize(self.inner.embed_texts(texts))

    @property
    def prefixes(self) -> tuple[str, str]:
        return self.inner.prefixes


_CACHE: dict[tuple, Embedder] = {}
_CACHE_LOCK = threading.Lock()


def make_embedder(spec: VectorConfig | str, config: Config) -> Embedder:
    """Build (or reuse) the embedder for a vector type's settings (or a bare model name), in this
    order: `fake` / `fake:<dim>` -> FakeEmbedder, even with a plugin set, so CODEMEM_MODEL=fake
    always gives a test setup; a plugin (`embedder = "module:Class"`); with `[embedding] provider =
    "openai"`, the API's `[embedding] model` for every vector type; else sentence-transformers."""
    if isinstance(spec, str):
        spec = VectorConfig(model=spec)
    model_name = spec.model
    fake = model_name == "fake" or model_name.startswith("fake:")
    emb = config.embedding
    settings = (config.device, config.dtype, config.batch_size, config.max_seq_length)
    if fake:
        key: tuple = ("fake", model_name, *settings)
    elif spec.embedder:
        key = ("plugin", spec.embedder, model_name, model_version(spec), *settings)
    elif emb.remote:  # every setting but the assist's, which is the local model's alone
        key = ("api", *(getattr(emb, f) for f in emb.__dataclass_fields__ if f != "assist"))
    else:  # the version is in the key, so new weights saved over a model folder load fresh
        key = ("local", model_name, model_version(spec), *settings)
    if emb.assist.active and not emb.remote:
        return _assisted(key, spec, config)
    with _CACHE_LOCK:
        if key not in _CACHE:
            if fake:
                dim = int(model_name.split(":", 1)[1]) if ":" in model_name else 64
                _CACHE[key] = FakeEmbedder(dim)
            elif spec.embedder:
                _CACHE[key] = PluginEmbedder(spec.embedder, model_name, config, key[3])
            elif emb.remote:
                _CACHE[key] = OpenAIEmbedder(emb)
            else:
                _CACHE[key] = SentenceTransformerEmbedder(
                    model_name,
                    device=config.device,
                    batch_size=config.batch_size,
                    max_seq_length=config.max_seq_length,
                    dtype=config.dtype,
                    version=key[2],
                )
        return _CACHE[key]


def _assisted(key: tuple, spec: VectorConfig, config: Config) -> Embedder:
    """The embedder `make_embedder` gives for these settings without an assist, wrapped so that an
    endpoint shares its document work (assist.py). The wrapped one is the cached one: a process
    that uses a model with and without the assist loads it once."""
    from .assist import AssistedEmbedder

    assist = config.embedding.assist
    plain = dataclasses.replace(config, embedding=dataclasses.replace(config.embedding, assist=AssistConfig()))
    inner = make_embedder(spec, plain)
    wrapped = ("assist", key, json.dumps(dataclasses.asdict(assist), sort_keys=True, default=str))
    with _CACHE_LOCK:
        if wrapped not in _CACHE:
            _CACHE[wrapped] = AssistedEmbedder(
                inner, assist, batch_size=config.batch_size, max_seq_length=config.max_seq_length
            )
        return _CACHE[wrapped]
