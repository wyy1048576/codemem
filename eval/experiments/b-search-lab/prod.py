"""The product's own code on an index copy: its Store, its search(), with question vectors made earlier."""
from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import lab_common as L

import codemem  # noqa: F401  (before FAISS: it sets OpenMP up on macOS)
from codemem.config import Config
from codemem.embedder import Embedder
from codemem.search import bm25_match, search
from codemem.store import Store

KEY = "jinaai/jina-code-embeddings-0.5b|doc|L1024|float16|mps"


class Precomputed(Embedder):
    """Query vectors made earlier, by text: a search then needs no model."""

    def __init__(self, vectors: dict[str, np.ndarray]):
        self.model_name, self._vectors = "precomputed", vectors

    @property
    def dim(self) -> int:
        return L.DIM

    @property
    def key(self) -> str:
        return KEY

    def embed_documents(self, texts):
        raise RuntimeError("the lab embeds no documents")

    def embed_queries(self, texts):
        return np.stack([self._vectors[t] for t in texts])


def open_store(repo: str, config: Config | None = None) -> tuple[Store, Config]:
    config = config or Config()  # the shipped defaults: this machine has no config file
    store = Store(L.REPOS[repo]["index"], bm25_stem=config.bm25_stem, bm25_stopwords=config.bm25_stopwords,
                  vector_backend=config.vector_backend, vector_options=config.vector_options(),
                  vector_memory_mb=config.vector_memory_mb)
    return store, config


__all__ = ["Precomputed", "open_store", "search", "bm25_match", "Config", "Store"]
