"""Hybrid retrieval: BM25 (FTS5) + one vector search per enabled vector set, merged with RRF.

`search()` is a pure library function returning structured results; MCP and the
CLI only format them. A chunk with several vectors of one type (windows of a long function)
is scored by its best one, and the card says which lines that window covers.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from .config import Config, VectorConfig
from .embedder import Embedder, make_embedder
from .schema import Chunk
from .store import ChunkFilter, Store, VectorHit
from .tokenize import fts_or, tokenize

BM25 = "bm25"
# The augmented query (search(): intent, symptom, anchors, locations).
MAX_ANCHORS = 20
MAX_LOCATIONS = 10
MAX_PINS = 10  # chunks of named locations put first
PINS_PER_LOCATION = 3
_FILE_LIKE = re.compile(r"/|\.[A-Za-z0-9+]{1,6}$")


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
    language: str = "python"
    subkind: str = ""
    name: str = ""
    is_test: bool = False
    best_lines: tuple[int, int] | None = None  # the best-matching window of a long chunk

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
    freshness: Any = None  # set by CodememService.search: what the index could not include yet
    # set by CodememService.search: keywords only, the model or the search index was still loading
    models_loading: bool = False
    # set with it: why no vector could be used, when that is a failure and not a load in progress
    # (a model that did not load, an embedding endpoint that does not answer)
    models_error: str | None = None

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
    # Ties broken by id, so rrf() alone is repeatable. search() then orders ties by location,
    # because ids depend on the history of the index.
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def _pick_top(
    fused: list[tuple[int, float]], k: int, get_chunks: Callable[[list[int]], dict[int, Chunk]]
) -> list[tuple[Chunk, float]]:
    """The k best results, with exact ties ordered by location (path, start line, key).

    Chunk ids depend on the history of the index: the order of builds and updates, and the
    file order of the OS. So ids must not decide the order of tied results, or which of them
    get into the top k. The same code then gives the same order on any index.
    """
    # Over-fetch a little: a reader may see ids whose rows were just deleted by a writer.
    cut = min(k + 10, len(fused))
    while 0 < cut < len(fused) and fused[cut][1] == fused[cut - 1][1]:
        cut += 1  # keep the whole group of results that tie with the last one
    chunks = get_chunks([doc for doc, _ in fused[:cut]])
    found = [(chunks[doc], score) for doc, score in fused[:cut] if doc in chunks]
    found.sort(key=lambda cs: (-cs[1], cs[0].path, cs[0].start_line, cs[0].key))
    return found[:k]


def _focus(lines: list[str], query_tokens: set[str], size: int) -> int:
    """Start of the `size`-line stretch around the line sharing the most query tokens."""
    best_i, best = 0, 0
    for i, line in enumerate(lines):
        score = len(query_tokens.intersection(tokenize(line)))
        if score > best:
            best_i, best = i, score
    return max(0, min(best_i - size // 3, len(lines) - size))


def _preview(
    chunk: Chunk, max_lines: int, max_chars: int, best_lines: tuple[int, int] | None = None,
    query_tokens: set[str] | None = None,
) -> str:
    text_source = chunk.skeleton if chunk.kind == "class" and chunk.skeleton else chunk.code
    lines = text_source.splitlines()
    if best_lines is not None:  # show the window that matched, not the top of a long function
        lines = lines[best_lines[0] - chunk.start_line : best_lines[1] - chunk.start_line + 1]
        if query_tokens and len(lines) > max_lines:  # and, inside it, the lines that match the query
            start = _focus(lines, query_tokens, max_lines)
            lines = lines[start:]
    text = "\n".join(lines[:max_lines])
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + " ..."
    elif len(lines) > max_lines:
        text += f"\n... ({len(lines) - max_lines} more lines)"
    return text


def make_card(
    chunk: Chunk, score: float, config: Config, ranks: dict[str, int] | None = None,
    best_lines: tuple[int, int] | None = None, query_tokens: set[str] | None = None,
) -> ResultCard:
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
        preview=_preview(chunk, config.preview_lines, config.preview_chars, best_lines, query_tokens),
        score=score,
        ranks=ranks,
        language=chunk.language,
        subkind=chunk.subkind,
        name=chunk.name,
        is_test=chunk.is_test,
        best_lines=best_lines,
    )


def available_signals(store: Store, config: Config) -> list[str]:
    stored = set(store.vec_types())
    return [BM25] + [v for v in config.enabled_vec_types() if v in stored]


def _reweigh(
    store: Store, fused: list[tuple[int, float]], test_weight: float, kind_weights: dict[str, float]
) -> list[tuple[int, float]]:
    """Multiply fused scores by the test weight (test chunks) and the weight of each chunk's kind,
    so kinds an agent rarely wants (tests, classes, blocks) can be pushed down without dropping them."""
    ids = [doc for doc, _ in fused]
    factor: dict[int, float] = {}
    for start in range(0, len(ids), 500):
        batch = ids[start : start + 500]
        marks = ",".join("?" * len(batch))
        for chunk_id, kind, is_test in store.conn.execute(
            f"SELECT chunk_id, kind, is_test FROM chunks WHERE chunk_id IN ({marks})", batch
        ):
            f = kind_weights.get(kind, 1.0) * (test_weight if is_test else 1.0)
            if f != 1.0:
                factor[chunk_id] = f
    if not factor:
        return fused
    weighed = [(doc, score * factor.get(doc, 1.0)) for doc, score in fused]
    return sorted(weighed, key=lambda kv: (-kv[1], kv[0]))


TEST_FILTERS = ("include", "exclude", "only")


def bm25_match(store: Store, query: str, config: Config) -> str | None:
    """The query's words for BM25 (docs/architecture.md §6). Stopwords are dropped (a query of stopwords
    only keeps them). A long query, over `bm25_query_terms` words, also drops the words the index
    lacks and the words more than `bm25_common_share` of chunks contain: their long posting lists
    made a 250-word query take 0.6 s on vLLM, and they weigh almost nothing. Rare words are not
    preferred: in an issue text they are often noise (versions, URLs, the reporter's own names),
    and keeping only the 32 rarest cost keyword search a third of its file MRR on the dev tasks.
    `bm25_query_terms = 0` keeps every word. The index is unchanged."""
    limit = config.bm25_query_terms
    if limit <= 0:
        return fts_or(tokenize(query, stem=config.bm25_stem, stopwords=config.bm25_stopwords))
    words = list(dict.fromkeys(tokenize(query, stem=config.bm25_stem, stopwords=True)))
    if not words:
        words = list(dict.fromkeys(tokenize(query, stem=config.bm25_stem, stopwords=False)))
    if len(words) > limit and config.bm25_common_share > 0:
        docs = store.term_doc_counts(words)
        most = config.bm25_common_share * max(store.chunk_total(), 1)
        words = [w for w in words if 0 < docs.get(w, 0) <= most] or words
    return fts_or(words)


def search(
    store: Store,
    query: str,
    config: Config,
    *,
    k: int = 10,
    signals: Sequence[str] | None = None,
    path_prefix: str | None = None,
    debug: bool = False,
    embedder_factory: Callable[[VectorConfig, Config], Embedder] = make_embedder,
    kinds: Sequence[str] | None = None,
    languages: Sequence[str] | None = None,
    test_weight: float | None = None,
    kind_weights: dict[str, float] | None = None,
    tests: str = "include",
    intent: str = "",
    symptom: str = "",
    anchors: Sequence[str] = (),
    locations: Sequence[str] = (),
) -> SearchResponse:
    """`tests`: "include" (default), "exclude" or "only" test code.

    The rest is an augmented query, written by the calling agent's model (search_code's fields;
    the loop of track B wrote it with a model call of its own, eval/experiments/b1-loop):
    - `intent` and `symptom`: what the code to change does, and the wrong behaviour. Together one
      more ranking by meaning for each vector signal (`intent_<signal>`).
    - `anchors`: exact strings from the task that may be in the code. One more keyword ranking.
    - `locations`: files or functions the task itself names. Their chunks come first (at most
      MAX_PINS, PINS_PER_LOCATION each), then the merged ranking.
    With none of them, the search is exactly the plain one."""
    if tests not in TEST_FILTERS:
        raise ValueError(f"tests must be one of {'|'.join(TEST_FILTERS)}, got {tests!r}")
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

    kinds = kinds if kinds is not None else config.kinds
    test_weight = config.test_weight if test_weight is None else test_weight
    flt = ChunkFilter(
        path_prefix=path_prefix or None,
        kinds=tuple(kinds) if kinds is not None else None,
        languages=tuple(languages) if languages else None,
        exclude_tests=test_weight <= 0 or tests == "exclude",
        only_tests=tests == "only",
    )
    allowed = store.filter_ids(flt) if flt.active else None
    dense = "\n".join(part for part in (intent.strip(), symptom.strip()) if part)
    anchors = [a.strip() for a in anchors if a and a.strip()][:MAX_ANCHORS]
    locations = [loc for loc in locations if loc and loc.strip()][:MAX_LOCATIONS]
    n = max(config.candidates, k)
    ranked: dict[str, list[int]] = {}
    best_part: dict[tuple[str, int], VectorHit] = {}

    if BM25 in signals:
        t = time.perf_counter()
        match = bm25_match(store, query, config)
        ranked[BM25] = store.bm25_search(match, n, config.bm25_weights5(), flt=flt) if match else []
        timings[BM25] = time.perf_counter() - t
        if anchors and (match := bm25_match(store, " ".join(anchors), config)):
            ranked["anchors_bm25"] = store.bm25_search(match, n, config.bm25_weights5(), flt=flt)

    vec_signals = [s for s in signals if s != BM25]
    if vec_signals and (allowed is None or allowed):
        # Embed the query once per distinct model (and plugin and weights), not once per vector set.
        # The intent and symptom are embedded in the same call as the query.
        texts = [query, dense] if dense else [query]
        query_vecs: dict[tuple, np.ndarray] = {}
        for vec_type in vec_signals:
            spec = config.vectors[vec_type]
            model = (spec.model, spec.embedder, spec.version)
            if model not in query_vecs:
                t = time.perf_counter()
                query_vecs[model] = embedder_factory(spec, config).embed_queries(texts)
                label = f"{spec.model}+{spec.embedder}" if spec.embedder else spec.model
                timings[f"embed_query:{label}"] = time.perf_counter() - t
            t = time.perf_counter()
            hits = store.vector_search(vec_type, query_vecs[model][0], n, allowed)
            ranked[vec_type] = [h.chunk_id for h in hits]
            for h in hits:
                best_part[(vec_type, h.chunk_id)] = h
            if dense:
                ranked[f"intent_{vec_type}"] = [h.chunk_id for h in store.vector_search(vec_type, query_vecs[model][1], n, allowed)]
            timings[vec_type] = time.perf_counter() - t
    elif vec_signals:
        for vec_type in vec_signals:
            ranked[vec_type] = []

    t = time.perf_counter()
    weights = config.rrf_weights
    if extra := [name for name in ranked if name.startswith(("intent_", "anchors_"))]:
        # An augmented list weighs as its signal does: intent_code as code, anchors_bm25 as bm25.
        base = {name: name.split("_", 1)[1] if name.startswith("intent_") else BM25 for name in extra}
        weights = {**config.rrf_weights, **{name: config.rrf_weights.get(base[name], 1.0) for name in extra}}
    fused = rrf(ranked, k=config.rrf_k, weights=weights)
    kind_weights = config.kind_weights if kind_weights is None else kind_weights
    if (0 < test_weight != 1) or any(w != 1.0 for w in kind_weights.values()):
        fused = _reweigh(store, fused, test_weight if test_weight > 0 else 1.0, kind_weights)
    rank_of = {s: {doc: r for r, doc in enumerate(ids, start=1)} for s, ids in ranked.items()}
    query_tokens = set(tokenize(query, stopwords=True))
    if anchors:
        query_tokens |= set(tokenize(" ".join(anchors), stopwords=True))
    top = _pick_top(fused, k, store.get_chunks)
    if locations and (pins := _pins(store, locations, dict(fused), allowed)):
        pinned = store.get_chunks(pins)
        scores = dict(fused)
        first = [(pinned[c], 1.0 + scores.get(c, 0.0)) for c in pins if c in pinned][:k]
        chosen = {chunk.chunk_id for chunk, _ in first}
        rest = _pick_top([item for item in fused if item[0] not in chosen], k - len(first), store.get_chunks)
        top = first + rest
    results: list[ResultCard] = []
    for chunk, score in top:
        doc = chunk.chunk_id
        ranks = {s: rank_of[s][doc] for s in ranked if doc in rank_of[s]} if debug else None
        hit = best_part.get(("code", doc))
        best_lines = None
        if hit is not None and hit.n_parts > 1 and chunk.kind != "class":
            best_lines = (chunk.start_line + hit.start_off, chunk.start_line + hit.end_off)
        results.append(make_card(chunk, score, config, ranks, best_lines, query_tokens))
    timings["fuse"] = time.perf_counter() - t
    timings["total"] = time.perf_counter() - t_total
    return SearchResponse(query=query, signals=list(signals), results=results, timings=timings)


def _pins(store: Store, locations: Sequence[str], scores: dict[int, float], allowed: set[int] | None) -> list[int]:
    """The chunks of the locations a task names, in the order named (at most MAX_PINS)."""
    ids: list[int] = []
    for location in locations:
        ids += _location_ids(store, location, scores, allowed)
    return list(dict.fromkeys(ids))[:MAX_PINS]


def _location_ids(store: Store, location: str, scores: dict[int, float], allowed: set[int] | None) -> list[int]:
    """One named location: a key (`path::qualname`), `path:line`, a file (its best-ranked chunks, else its
    first ones), or a symbol (`name`, `Class.name`, `name()`): the chunks of that name in the ranking, or all
    of them when there are at most PINS_PER_LOCATION. A location that fits nothing, or too much, pins nothing."""
    text = location.strip().strip("`'\"").replace("\\", "/").removeprefix("./").strip("/")
    if not text:
        return []

    def keep(chunks) -> list:
        return [c for c in chunks if c is not None and (allowed is None or c.chunk_id in allowed)]

    if "::" in text:
        return [c.chunk_id for c in keep([store.get_chunk_by_key(text)])]
    path, sep, line = text.rpartition(":")
    if sep and path and line.split("-")[0].isdigit():
        return [c.chunk_id for c in keep([store.find_chunk_at(path, int(line.split("-")[0]))])]
    if _FILE_LIKE.search(text) and (paths := store.paths_ending_with(text, limit=4)):
        if len(paths) > 3:
            return []
        ids: list[int] = []
        for p in paths:
            chunks = keep(store.chunks_for_path(p))
            ranked = sorted((c for c in chunks if c.chunk_id in scores), key=lambda c: -scores[c.chunk_id])
            ids += [c.chunk_id for c in (ranked or chunks)[:PINS_PER_LOCATION]]
        return ids
    parts = [part for part in re.split(r"::|->|\.", re.sub(r"\(.*$", "", text).strip()) if part]
    if not parts:
        return []
    named = keep(store.chunks_named(parts[-1]))
    if len(parts) > 1:
        named = [c for c in named if c.qualname.endswith(f"{parts[-2]}.{parts[-1]}")] or named
    in_ranking = sorted((c for c in named if c.chunk_id in scores), key=lambda c: -scores[c.chunk_id])
    chosen = in_ranking or (named if len(named) <= PINS_PER_LOCATION else [])
    return [c.chunk_id for c in chosen[:PINS_PER_LOCATION]]
