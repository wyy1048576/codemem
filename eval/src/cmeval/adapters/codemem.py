"""The codemem adapter: the only file in cmeval that imports codemem.

Install codemem into the eval environment with: uv sync --extra codemem

Three facts about codemem shape this adapter:
- CodememService.update() catches every exception and only stores it in last_error. The adapter
  checks last_error after each update and raises, so a failed index never looks like success.
- Each codemem Store loads its vectors into memory once. Two services on one index folder would
  not see each other's updates. So systems with the same index_key share one service.
- codemem.search.search takes the config for each call. So systems that share a service can
  still use their own search-time settings (signals, RRF and BM25 weights).
"""

from __future__ import annotations

import dataclasses
import subprocess
import time
from pathlib import Path
from typing import Any

from codemem import __version__ as CODEMEM_VERSION
from codemem.config import config_from_dict
from codemem.embedder import resolve_device
from codemem.render import format_results
from codemem.search import SearchResponse, search
from codemem.service import CodememService

from ..retriever import Hit, IndexReport, RetrieverError, stable_hash

# Settings that change the index. Everything else in codemem's Config is used at search time.
INDEX_TIME_FIELDS = (
    "embedding_dim", "max_seq_length", "batch_size", "bm25_stem", "bm25_stopwords",
    "max_defs_per_name", "max_usage_items", "include_commits", "max_file_size", "ignore",
)  # fmt: skip


def _codemem_git() -> dict[str, Any]:
    """The codemem commit the run used, and whether its source had uncommitted changes."""
    import codemem

    src = Path(codemem.__file__).resolve().parent
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=src, capture_output=True, text=True)
    if sha.returncode != 0:
        return {"sha": None, "dirty": None}
    return {"sha": sha.stdout.strip(), "dirty": bool(dirty.stdout.strip())}


# One service for each index folder, shared by every system with the same index_key.
# resolved index_dir -> {"service": ..., "key": ..., "users": int}
_SHARED: dict[Path, dict[str, Any]] = {}


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


class CodememRetriever:
    granularity = "line"

    def __init__(self, name: str = "codemem", signals: list[str] | None = None, config: dict[str, Any] | None = None):
        self.name = name
        self.signals = list(signals) if signals is not None else None  # None: every available signal
        # config_from_dict only: no ~/.codemem/config.toml, no .codemem.toml, no env vars.
        self.config = config_from_dict(config or {})
        self._config_raw = config or {}
        self._index_dir: Path | None = None
        self._key = self.index_key()

    # ---- identity

    def _index_settings(self) -> dict[str, Any]:
        cfg = self.config
        return {
            "codemem": CODEMEM_VERSION,
            "vectors": {name: {"model": cfg.model_id(name)} for name in cfg.enabled_vec_types()},
            "device": resolve_device(cfg.device),  # GPU and CPU round slightly differently
            **{f: getattr(cfg, f) for f in INDEX_TIME_FIELDS},
        }

    def index_key(self) -> str:
        return stable_hash(self._index_settings())

    def describe(self) -> dict[str, Any]:
        return {
            "adapter": "codemem",
            "codemem_version": CODEMEM_VERSION,
            "codemem_git": _codemem_git(),
            "device": resolve_device(self.config.device),
            "signals": self.signals,
            "index_key": self._key,
            "config": dataclasses.asdict(self.config),
        }

    # ---- index

    def _service(self, repo: Path, index_dir: Path) -> CodememService:
        index_dir = Path(index_dir).resolve()
        entry = _SHARED.get(index_dir)
        if entry is None:
            service = CodememService(Path(repo), index_dir=index_dir, config=self.config)
            entry = _SHARED[index_dir] = {"service": service, "key": self._key, "users": 0}
        elif entry["key"] != self._key:
            raise RetrieverError(f"{self.name}: {index_dir} already holds an index with other index-time settings")
        if self._index_dir != index_dir:
            if self._index_dir is not None:
                self._release()
            entry["users"] += 1
            self._index_dir = index_dir
        if entry["service"].repo_root != Path(repo).resolve():
            raise RetrieverError(f"{self.name}: {index_dir} indexes {entry['service'].repo_root}, not {repo}")
        return entry["service"]

    def _index(self, repo: Path, index_dir: Path, full: bool) -> IndexReport:
        service = self._service(repo, index_dir)
        start = time.perf_counter()
        stats = service.update(full=full)
        seconds = time.perf_counter() - start
        if service.last_error or stats is None:
            raise RetrieverError(f"{self.name}: codemem indexing failed: {service.last_error or 'update did not run'}")
        return IndexReport(
            seconds=seconds,
            bytes_on_disk=_dir_size(self._index_dir),
            items=service.store.counts()["chunks"],
            items_reembedded=sum(stats.embedded.values()),
            extra=stats.to_dict(),
        )

    def build(self, repo: Path, index_dir: Path) -> IndexReport:
        return self._index(repo, index_dir, full=True)

    def update(self, repo: Path, index_dir: Path) -> IndexReport:
        return self._index(repo, index_dir, full=False)

    # ---- search

    def search(self, query: str, k: int) -> list[Hit]:
        if self._index_dir is None:
            raise RetrieverError(f"{self.name}: search before build")
        service = _SHARED[self._index_dir]["service"]
        resp = search(service.store, query, self.config, k=k, signals=self.signals, debug=True)
        hits = []
        for rank, card in enumerate(resp.results, start=1):
            # The card exactly as the MCP tool shows it to an agent (no debug ranks).
            text = format_results(SearchResponse(resp.query, resp.signals, [card]))
            text = f"{rank}." + text[2:] if text.startswith("1.") else text
            hits.append(Hit(
                path=card.path, start_line=card.start_line, end_line=card.end_line, symbol=card.qualname,
                score=card.score, text=text,
                extra={"ranks": card.ranks or {}, "kind": card.kind, "chunk_id": card.chunk_id},
            ))
        if hits:
            hits[0].extra["signals"] = resp.signals
        return hits

    # ---- cleanup

    def _release(self) -> None:
        entry = _SHARED.get(self._index_dir)
        if entry is None:
            return
        entry["users"] -= 1
        if entry["users"] <= 0:
            entry["service"].close()
            del _SHARED[self._index_dir]

    def close(self) -> None:
        if self._index_dir is not None:
            self._release()
            self._index_dir = None
