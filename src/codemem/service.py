"""Long-lived owner of one repo's index: background updates, progress, watcher, queries.

The MCP server and `codemem watch` both use this. It holds no front-end
assumptions, so a future daemon can reuse it unchanged.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from .config import Config, default_index_dir, find_repo_root, load_config
from .embedder import make_embedder
from .indexer import IndexStats, Indexer, git_head
from .search import SearchResponse, make_card, search
from .store import Store
from .watcher import RepoWatcher

log = logging.getLogger(__name__)

# Rough share of total work per phase, for a single progress percentage.
_PHASE_SPAN = {"chunk": (0.0, 0.15), "embed": (0.15, 1.0), "done": (1.0, 1.0)}


class CodememService:
    def __init__(
        self,
        repo_root: Path | str | None = None,
        *,
        index_dir: Path | str | None = None,
        config: Config | None = None,
        embedder_factory=make_embedder,
    ):
        self.repo_root = find_repo_root(repo_root)
        self.index_dir = Path(index_dir) if index_dir else default_index_dir(self.repo_root)
        self.config = config or load_config(self.repo_root)
        self.embedder_factory = embedder_factory
        self.store = Store(self.index_dir, bm25_stem=self.config.bm25_stem, bm25_stopwords=self.config.bm25_stopwords)
        self.state = "ready" if self.has_index() else "empty"
        self.progress = 0.0
        self.last_error: str | None = None
        self.last_stats: IndexStats | None = None
        self._update_lock = threading.Lock()
        self._pending = threading.Event()
        self._worker: threading.Thread | None = None
        self._watcher: RepoWatcher | None = None

    # ---- indexing
    def has_index(self) -> bool:
        return self.store.get_meta("indexed_at") is not None

    def _on_progress(self, phase: str, done: int, total: int) -> None:
        lo, hi = _PHASE_SPAN.get(phase, (0.0, 0.0))
        self.progress = 100 * (lo + (hi - lo) * (done / total if total else 1.0))

    def update(self, *, full: bool = False) -> IndexStats | None:
        """Run an update now (blocking). Concurrent requests coalesce into one re-run."""
        if not self._update_lock.acquire(blocking=False):
            self._pending.set()
            return None
        try:
            while True:
                self._pending.clear()
                self.state = "indexing" if not self.has_index() or full else "updating"
                self.progress = 0.0
                try:
                    indexer = Indexer(
                        self.repo_root, self.store, self.config,
                        embedder_factory=self.embedder_factory, progress=self._on_progress,
                    )
                    self.last_stats = indexer.update(full=full)
                    self.last_error = None
                    self.state = "ready"
                except Exception as e:
                    log.exception("index update failed")
                    self.last_error = f"{type(e).__name__}: {e}"
                    self.state = "error" if not self.has_index() else "ready"
                full = False
                if not self._pending.is_set():
                    return self.last_stats
        finally:
            self._update_lock.release()

    def start_background_update(self, *, full: bool = False, prewarm: bool = True) -> threading.Thread:
        def run() -> None:
            try:
                self.update(full=full)
            finally:
                self.store.close_thread_conn()
            if prewarm:
                self.prewarm()

        self._worker = threading.Thread(target=run, name="codemem-index", daemon=True)
        self._worker.start()
        return self._worker

    def request_update(self) -> None:
        """Called by the watcher (debounced). Never blocks the caller."""
        if self._update_lock.locked():
            self._pending.set()
            return

        def run() -> None:
            try:
                self.update()
            finally:
                self.store.close_thread_conn()

        threading.Thread(target=run, name="codemem-update", daemon=True).start()

    def prewarm(self) -> None:
        """Load embedding models so the first query doesn't pay for it."""
        for model in {self.config.vectors[v].model for v in self.config.enabled_vec_types()}:
            try:
                self.embedder_factory(model, self.config).embed_queries(["warmup"])
            except Exception:
                log.exception("could not load embedding model %s", model)

    def start_watcher(self) -> RepoWatcher:
        self._watcher = RepoWatcher(
            self.repo_root, self.request_update, debounce_ms=self.config.debounce_ms, skip=[self.index_dir]
        )
        self._watcher.start()
        return self._watcher

    def close(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()
        self.store.close()

    # ---- queries
    def search(self, query: str, **kwargs: Any) -> SearchResponse:
        return search(self.store, query, self.config, embedder_factory=self.embedder_factory, **kwargs)

    def resolve_ref(self, ref: str | int):
        ref_s = str(ref).strip()
        if ref_s.isdigit():
            return self.store.get_chunk(int(ref_s))
        if "::" in ref_s:
            return self.store.get_chunk_by_key(ref_s.replace("\\", "/"))
        path, sep, line = ref_s.rpartition(":")
        if sep and line.split("-")[0].isdigit():
            return self.store.find_chunk_at(path.replace("\\", "/").removeprefix("./"), int(line.split("-")[0]))
        return None

    def get_chunk(self, ref: str | int) -> dict[str, Any] | None:
        chunk = self.resolve_ref(ref)
        if chunk is None:
            return None

        def brief(c) -> dict[str, Any]:
            return {"chunk_id": c.chunk_id, "qualname": c.qualname, "location": c.location}

        return {
            **make_card(chunk, 0.0, self.config).to_dict(),
            "code": chunk.code,
            "docstring": chunk.docstring,
            "callers": [brief(c) for c in self.store.callers_of(chunk.chunk_id)],
            "callees": [brief(c) for c in self.store.callees_of(chunk.chunk_id)],
        }

    def status(self, *, check_staleness: bool = True) -> dict[str, Any]:
        store = self.store
        info: dict[str, Any] = {
            "state": self.state,
            "progress": round(self.progress, 1) if self.state in ("indexing", "updating") else None,
            "repo": str(self.repo_root),
            "index_dir": str(self.index_dir),
            **store.counts(),
            "models": {
                v: {"model": store.get_meta(f"vec.{v}.model"), "dim": store.get_meta(f"vec.{v}.dim")}
                for v in self.config.enabled_vec_types()
            },
            "indexed_commit": store.get_meta("indexed_commit"),
            "indexed_at": store.get_meta("indexed_at"),
            "last_update": store.get_meta("last_update"),
            "error": self.last_error,
        }
        if check_staleness and self.state not in ("indexing", "updating"):
            scan = Indexer(self.repo_root, store, self.config).scan()
            head = git_head(self.repo_root)
            info["stale"] = {
                "changed_files": len(scan.changed),
                "deleted_files": len(scan.deleted),
                "head": head,
                "head_moved": bool(head and head != info["indexed_commit"]),
            }
        if info["indexed_at"]:
            info["age_seconds"] = round(time.time() - info["indexed_at"], 1)
        return info
