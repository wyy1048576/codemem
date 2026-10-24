"""Embedder interface, the sentence-transformers (jina) embedder and FakeEmbedder.

Callers only see `embed_documents` / `embed_queries`; task prompts/prefixes are
handled here. All outputs are float32, L2-normalized, shape (n, dim), at the model's full
dimension: Matryoshka truncation (`embedding_dim`) is applied by the store when it builds the
search index, so changing it never re-embeds.

`Embedder.key` names the embedding space of document vectors (model, prompt, max length, dtype,
device): vectors with equal keys are interchangeable, so the store and the vector cache reuse
them by (key, text hash).
"""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Sequence

import numpy as np

from .config import Config
from .tokenize import tokenize

log = logging.getLogger(__name__)

QUERY_PROMPT = "nl2code_query"
DOCUMENT_PROMPT = "nl2code_document"
# Fallback if a model card doesn't ship named prompts (expected for jina-code-embeddings).
FALLBACK_PROMPTS = {
    QUERY_PROMPT: "Find the most relevant code snippet given the following query:\n",
    DOCUMENT_PROMPT: "Candidate code snippet:\n",
}
_QUERY_CACHE_SIZE = 512


def l2_normalize(vecs: np.ndarray) -> np.ndarray:
    vecs = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.where(norms == 0, 1.0, norms)


class Embedder(ABC):
    model_name: str

    @property
    @abstractmethod
    def dim(self) -> int: ...

    @property
    @abstractmethod
    def key(self) -> str:
        """Identity of the document-vector space; equal keys give interchangeable vectors."""

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> np.ndarray: ...

    @abstractmethod
    def embed_queries(self, texts: Sequence[str]) -> np.ndarray: ...


class FakeEmbedder(Embedder):
    """Deterministic hashed bag-of-tokens vectors. No downloads, ~instant.

    Texts sharing tokens get similar vectors, which is enough to exercise the
    pipeline and the usage signal in tests. It is not semantic.
    """

    def __init__(self, dim: int = 64):
        self.model_name = f"fake:{dim}"
        self._dim = dim
        self.calls: list[int] = []  # batch sizes, so tests can count embeddings

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def key(self) -> str:
        return f"{self.model_name}|doc"

    def _embed(self, texts: Sequence[str]) -> np.ndarray:
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


def resolve_device(preference: str) -> str:
    import torch

    if preference == "cpu":
        return "cpu"
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
    ):
        self.model_name = model_name
        self.device_preference = device
        self.dtype_preference = dtype
        self.batch_size = batch_size
        self.max_seq_length = max_seq_length
        self._model = None
        self._prompts: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()
        self._device: str | None = None
        self._queries: OrderedDict[str, np.ndarray] = OrderedDict()

    @property
    def device(self) -> str:
        if self._device is None:
            self._device = resolve_device(self.device_preference)
        return self._device

    @property
    def dtype(self) -> str:
        return resolve_dtype(self.dtype_preference, self.device)

    @property
    def key(self) -> str:
        return f"{self.model_name}|doc|L{self.max_seq_length}|{self.dtype}|{self.device}"

    @property
    def model(self):
        with self._lock:
            if self._model is None:
                import torch
                from sentence_transformers import SentenceTransformer

                log.info("loading %s on %s (%s)", self.model_name, self.device, self.dtype)
                model = SentenceTransformer(self.model_name, device=self.device)
                if self.dtype != "float32":
                    model = model.to(getattr(torch, self.dtype))
                if self.max_seq_length:
                    model.max_seq_length = min(model.max_seq_length or 10**9, self.max_seq_length)
                available = getattr(model, "prompts", {}) or {}
                for name in (QUERY_PROMPT, DOCUMENT_PROMPT):
                    if name in available:
                        self._prompts[name] = {"prompt_name": name}
                    else:
                        log.warning("%s has no %r prompt; using built-in prefix", self.model_name, name)
                        self._prompts[name] = {"prompt": FALLBACK_PROMPTS[name]}
                self._model = model
            return self._model

    @property
    def dim(self) -> int:
        model = self.model
        getter = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
        return int(getter())

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

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        """Queries are cached (the eval asks the same query of several systems that share a model)."""
        missing = [t for t in dict.fromkeys(texts) if t not in self._queries]
        if missing:
            for text, vec in zip(missing, self._encode(missing, QUERY_PROMPT)):
                self._queries[text] = vec
                if len(self._queries) > _QUERY_CACHE_SIZE:
                    self._queries.popitem(last=False)
        return np.stack([self._queries[t] for t in texts]) if texts else np.zeros((0, self.dim), dtype=np.float32)


_CACHE: dict[tuple, Embedder] = {}
_CACHE_LOCK = threading.Lock()


def make_embedder(model_name: str, config: Config) -> Embedder:
    """Build (or reuse) the embedder for a model name. `fake` / `fake:<dim>` -> FakeEmbedder."""
    key = (model_name, config.device, config.dtype, config.batch_size, config.max_seq_length)
    with _CACHE_LOCK:
        if key not in _CACHE:
            if model_name == "fake" or model_name.startswith("fake:"):
                dim = int(model_name.split(":", 1)[1]) if ":" in model_name else 64
                _CACHE[key] = FakeEmbedder(dim)
            else:
                _CACHE[key] = SentenceTransformerEmbedder(
                    model_name,
                    device=config.device,
                    batch_size=config.batch_size,
                    max_seq_length=config.max_seq_length,
                    dtype=config.dtype,
                )
        return _CACHE[key]
