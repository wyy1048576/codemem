"""Hybrid retrieval: BM25 (FTS5) + one vector search per enabled vector set, merged with RRF.

`search()` is a pure library function returning structured results; MCP and the
CLI only format them.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field

import numpy as np

from .config import Config
from .embedder import Embedder, make_embedder
from .schema import Chunk
from .store import Store
from .tokenize import fts_match_query

BM25 = "bm25"


@dataclass
class ResultCard:
    chunk_id: int
    key: str
    path: str
    start_line: int
    end_line: int
    qualname: str
    kind: str
    signature: str
    doc: str  # first docstring line
    preview: str
    score: float
    ranks: dict[str, int] | None = None  # per-signal 1-based ranks (debug)

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["location"] = self.location
        if self.ranks is None:
            d.pop("ranks")
        return d


@dataclass
class SearchResponse:
    query: str
    signals: list[str]
    results: list[ResultCard]
    timings: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "signals": self.signals,
            "timings": self.timings,
            "results": [r.to_dict() for r in self.results],
        }


def rrf(
    ranked: dict[str, Sequence[int]], k: int = 60, weights: dict[str, float] | None = None
) -> list[tuple[int, float]]:
    """Reciprocal rank fusion: score(d) = sum_s w_s / (k + rank_s(d)), ranks 1-based."""
    weights = weights or {}
    scores: dict[int, float] = {}
    for signal, ids in ranked.items():
        w = weights.get(signal, 1.0)
        for rank, doc in enumerate(ids, start=1):
            scores[doc] = scores.get(doc, 0.0) + w / (k + rank)
    # Ties broken by id for repeatable eval numbers.
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def _preview(chunk: Chunk, max_lines: int, max_chars: int) -> str:
    lines = chunk.code.splitlines()
    text = "\n".join(lines[:max_lines])
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + " ..."
    elif len(lines) > max_lines:
        text += f"\n... ({len(lines) - max_lines} more lines)"
    return text


def make_card(chunk: Chunk, score: float, config: Config, ranks: dict[str, int] | None = None) -> ResultCard:
    return ResultCard(
        chunk_id=chunk.chunk_id or 0,
        key=chunk.key,
        path=chunk.path,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        qualname=chunk.qualname,
        kind=chunk.kind,
        signature=chunk.signature,
        doc=chunk.docstring.strip().splitlines()[0] if chunk.docstring.strip() else "",
        preview=_preview(chunk, config.preview_lines, config.preview_chars),
        score=score,
        ranks=ranks,
    )


def available_signals(store: Store, config: Config) -> list[str]:
    stored = set(store.vec_types())
    return [BM25] + [v for v in config.enabled_vec_types() if v in stored]


def search(
    store: Store,
    query: str,
    config: Config,
    *,
    k: int = 10,
    signals: Sequence[str] | None = None,
    path_prefix: str | None = None,
    debug: bool = False,
    embedder_factory: Callable[[str, Config], Embedder] = make_embedder,
) -> SearchResponse:
    timings: dict[str, float] = {}
    t_total = time.perf_counter()
    stored_vec_types = set(store.vec_types())
    if signals is None:
        signals = available_signals(store, config)
    else:
        unknown = [s for s in signals if s != BM25 and s not in config.vectors]
        if unknown:
            raise ValueError(f"unknown signals {unknown}; choose from {[BM25, *config.vectors]}")
        signals = [s for s in signals if s == BM25 or s in stored_vec_types]

    allowed = store.ids_with_prefix(path_prefix) if path_prefix else None
    n = max(config.candidates, k)
    ranked: dict[str, list[int]] = {}

    if BM25 in signals:
        t = time.perf_counter()
        match = fts_match_query(query, stem=config.bm25_stem, stopwords=config.bm25_stopwords)
        ranked[BM25] = store.bm25_search(match, n, config.bm25_weights, path_prefix) if match else []
        timings[BM25] = time.perf_counter() - t

    vec_signals = [s for s in signals if s != BM25]
    if vec_signals and (allowed is None or allowed):
        # Embed the query once per distinct model, not once per vector set.
        query_vecs: dict[str, np.ndarray] = {}
        for vec_type in vec_signals:
            model = config.vectors[vec_type].model
            if model not in query_vecs:
                t = time.perf_counter()
                query_vecs[model] = embedder_factory(model, config).embed_queries([query])[0]
                timings[f"embed_query:{model}"] = time.perf_counter() - t
            t = time.perf_counter()
            hits = store.vector_search(vec_type, query_vecs[model], n, allowed)
            ranked[vec_type] = [i for i, _ in hits]
            timings[vec_type] = time.perf_counter() - t

    t = time.perf_counter()
    fused = rrf(ranked, k=config.rrf_k, weights=config.rrf_weights)
    rank_of = {s: {doc: r for r, doc in enumerate(ids, start=1)} for s, ids in ranked.items()}
    # Over-fetch a little: a reader may see ids whose rows were just deleted by a writer.
    top = fused[: k + 10]
    chunks = store.get_chunks([doc for doc, _ in top])
    results: list[ResultCard] = []
    for doc, score in top:
        chunk = chunks.get(doc)
        if chunk is None:
            continue
        ranks = {s: rank_of[s][doc] for s in ranked if doc in rank_of[s]} if debug else None
        results.append(make_card(chunk, score, config, ranks))
        if len(results) == k:
            break
    timings["fuse"] = time.perf_counter() - t
    timings["total"] = time.perf_counter() - t_total
    return SearchResponse(query=query, signals=list(signals), results=results, timings=timings)
