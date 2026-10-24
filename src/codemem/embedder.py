"""Embedder interface, the sentence-transformers (jina) embedder and FakeEmbedder.

Callers only see `embed_documents` / `embed_queries`; task prompts/prefixes are
handled here. All outputs are float32, L2-normalized, shape (n, dim).

A custom embedder is named per vector type in config (`vectors.<type>.embedder =
"module:Class"`). It subclasses `Embedder` and is built as `Class(model, config)`.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Sequence

import numpy as np

from .config import Config, VectorConfig, model_version
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


def l2_normalize(vecs: np.ndarray) -> np.ndarray:
    vecs = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.where(norms == 0, 1.0, norms)


class Embedder(ABC):
    model_name: str

    @property
    @abstractmethod
    def dim(self) -> int: ...

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


class SentenceTransformerEmbedder(Embedder):
    """jina-code-embeddings (or any sentence-transformers model), loaded lazily."""

    def __init__(
        self,
        model_name: str,
        device: str = "auto",
        embedding_dim: int | None = None,
        batch_size: int = 16,
        max_seq_length: int | None = 1024,
    ):
        self.model_name = model_name
        self.device_preference = device
        self.embedding_dim = embedding_dim
        self.batch_size = batch_size
        self.max_seq_length = max_seq_length
        self._model = None
        self._prompts: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    @property
    def model(self):
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                device = resolve_device(self.device_preference)
                log.info("loading %s on %s", self.model_name, device)
                model = SentenceTransformer(
                    self.model_name, device=device, truncate_dim=self.embedding_dim
                )
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
        vecs = model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            **self._prompts[prompt],
        )
        # Re-normalize: truncate_dim is applied after normalization in some versions.
        return l2_normalize(vecs)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts, DOCUMENT_PROMPT)

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts, QUERY_PROMPT)


_CACHE: dict[tuple, Embedder] = {}
_CACHE_LOCK = threading.Lock()


def make_embedder(spec: VectorConfig | str, config: Config) -> Embedder:
    """Build (or reuse) the embedder for a vector type's spec (or a bare model name).

    `fake` / `fake:<dim>` -> FakeEmbedder, even with a custom embedder set, so
    CODEMEM_MODEL=fake always gives a test setup. Then `spec.embedder`, then sentence-transformers.
    """
    if isinstance(spec, str):
        spec = VectorConfig(model=spec)
    model_name = spec.model
    fake = model_name == "fake" or model_name.startswith("fake:")
    # The version is in the key so retrained weights in the same folder load fresh.
    version = None if fake else model_version(spec)
    key = (
        model_name, spec.embedder, version,
        config.device, config.embedding_dim, config.batch_size, config.max_seq_length,
    )
    with _CACHE_LOCK:
        if key not in _CACHE:
            if fake:
                dim = int(model_name.split(":", 1)[1]) if ":" in model_name else 64
                _CACHE[key] = FakeEmbedder(dim)
            elif spec.embedder:
                embedder = load_object(spec.embedder)(model_name, config)
                if not isinstance(embedder, Embedder):
                    raise TypeError(f"{spec.embedder} must subclass codemem.embedder.Embedder")
                _CACHE[key] = embedder
            else:
                _CACHE[key] = SentenceTransformerEmbedder(
                    model_name,
                    device=config.device,
                    embedding_dim=config.embedding_dim,
                    batch_size=config.batch_size,
                    max_seq_length=config.max_seq_length,
                )
        return _CACHE[key]
