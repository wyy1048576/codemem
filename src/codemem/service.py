"""Long-lived owner of one repo's index: updates, freshness, the watcher, queries.

The MCP server and `codemem watch` call `start()`. The CLI and the eval call `update()` and
`search()` directly. Creating a service has no side effects beyond opening the index, because the
eval adapter re-pins `repo_root` after construction.

Freshness (docs/architecture.md §8):
- the watcher hands over batches of changed paths; a writer thread applies them (stage A), then
  embeds what they queued (stage B, in small batches, so new edits get applied in between);
- `search()` first applies every edit seen so far, and embeds what they queued within a budget;
- a reconcile (a scan of the whole repo) runs at startup, every few minutes, on `refresh()`, and
  when the ignore rules, the config or the git branch change;
- the FAISS files are written once the index has been quiet for a while, and on close.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config, default_index_dir, find_repo_root, load_config
from .embedder import make_embedder
from .indexer import IndexStats, Indexer, git_head
from .search import SearchResponse, make_card, search
from .store import Store
from .watcher import RepoWatcher, git_busy

log = logging.getLogger(__name__)

_LONG_CLASS_LINES = 80
# Rough share of total work per phase, for a single progress percentage.
_PHASE_SPAN = {"chunk": (0.0, 0.15), "embed": (0.15, 1.0), "done": (1.0, 1.0)}
CATCHUP_BUDGET = 2.0  # seconds a search may spend applying and embedding pending edits
CATCHUP_MAX_CHUNKS = 1000  # beyond this many queued chunks the index is being built: don't wait
SAVE_AFTER_IDLE = 30.0  # write the FAISS files once nothing changed for this long
RECONCILE_EVERY = 300.0  # a full scan, in case a file event was missed
POLL_EVERY = 10.0  # the scan interval when file events don't work
BURST_PATHS = 2000  # more changed paths than this at once: scan everything instead
_BACKGROUND_BATCH = 64  # queued chunks per background embedding batch (new edits wait at most one)


@dataclass
class Freshness:
    """What a search could not include yet."""

    pending_chunks: int = 0  # queued chunks whose vectors are not computed yet
    indexing: bool = False  # the index is being built: many chunks still to embed

    @property
    def complete(self) -> bool:
        return self.pending_chunks == 0


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
        self._own_config = config is None  # loaded from the repo's files: reload it when they change
        self.config = config or load_config(self.repo_root)
        self.embedder_factory = embedder_factory
        self.store = Store(self.index_dir, bm25_stem=self.config.bm25_stem, bm25_stopwords=self.config.bm25_stopwords)
        self.state = "ready" if self.has_index() else "empty"
        self.progress = 0.0
        self.last_error: str | None = None
        self.last_stats: IndexStats | None = None
        self._write_lock = threading.RLock()  # shared with the indexer: one writer thread at a time
        self._indexer: Indexer | None = None
        self._cond = threading.Condition()
        self._dirty: set[str] = set()
        self._reconcile = False
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._watcher: RepoWatcher | None = None
        self._polling = False
        self._last_write = 0.0  # monotonic time of the last index change
        self._last_reconcile = 0.0

    @property
    def indexer(self) -> Indexer:
        root = Path(self.repo_root).resolve()
        if self._indexer is None or self._indexer.root != root:
            self._indexer = Indexer(
                root, self.store, self.config, embedder_factory=self.embedder_factory,
                progress=self._on_progress, write_lock=self._write_lock,
            )
        return self._indexer

    # ---- indexing on request (CLI, eval)
    def has_index(self) -> bool:
        return self.store.get_meta("indexed_at") is not None

    def _on_progress(self, phase: str, done: int, total: int) -> None:
        lo, hi = _PHASE_SPAN.get(phase, (0.0, 0.0))
        self.progress = 100 * (lo + (hi - lo) * (done / total if total else 1.0))

    def update(self, *, full: bool = False) -> IndexStats | None:
        """Bring the index up to date now: a full reconcile, then every queued vector, then the
        FAISS files written. Waits for any update in progress. An error is kept in `last_error`
        (the eval adapter relies on that) and gives None."""
        self.state = "indexing" if not self.has_index() or full else "updating"
        self.progress = 0.0
        try:
            stats = self.indexer.update(full=full, save=True)
        except Exception as e:
            log.exception("index update failed")
            self.last_error = f"{type(e).__name__}: {e}"
            self.state = "error" if not self.has_index() else "ready"
            return None
        self.last_stats, self.last_error, self.state = stats, None, "ready"
        self._last_write = self._last_reconcile = time.monotonic()
        return stats

    # ---- indexing in the background (MCP server, `codemem watch`)
    def start(self, *, watch: bool = True, prewarm: bool = True) -> None:
        """Keep the index fresh in the background: a catch-up now, then the watcher's batches,
        a reconcile every few minutes, and lazy saves of the FAISS files."""
        self.request_reconcile()
        self._ensure_worker()
        if watch:
            self.start_watcher()
        if prewarm:
            threading.Thread(target=self.prewarm, name="codemem-prewarm", daemon=True).start()

    def start_background_update(self, *, full: bool = False, prewarm: bool = True) -> threading.Thread:
        """One update in a thread (the handshake of the MCP server is never blocked by it)."""

        def run() -> None:
            try:
                self.update(full=full)
            finally:
                self.store.close_thread_conn()
            if prewarm:
                self.prewarm()

        thread = threading.Thread(target=run, name="codemem-index", daemon=True)
        thread.start()
        return thread

    def notify(self, paths: set[str], reconcile: bool = False) -> None:
        """Changed paths from the watcher (or a request for a full reconcile)."""
        with self._cond:
            self._dirty |= paths
            self._reconcile |= reconcile or len(self._dirty) > BURST_PATHS
            self._cond.notify_all()

    def request_reconcile(self) -> None:
        self.notify(set(), reconcile=True)

    def request_update(self) -> None:
        """v2 name for a full catch-up."""
        self.request_reconcile()

    def _take_changes(self, *, flush_watcher: bool = False) -> tuple[set[str], bool]:
        """Pending edits. Only a search flushes the watcher's not-yet-handed-over paths: the writer
        thread waits for the quiet period, so a burst of saves becomes one update."""
        with self._cond:
            paths, reconcile = self._dirty, self._reconcile
            self._dirty, self._reconcile = set(), False
        if flush_watcher and self._watcher is not None:
            more, again = self._watcher.pending()
            paths, reconcile = paths | more, reconcile or again
        return paths, reconcile

    def _requeue(self, paths: set[str], reconcile: bool) -> None:
        with self._cond:
            self._dirty |= paths
            self._reconcile |= reconcile

    def _apply_changes(self, paths: set[str], reconcile: bool) -> set[int] | None:
        """Stage A for pending edits. Returns what was queued (None = everything)."""
        deadline = time.monotonic() + 10.0
        while git_busy(self.repo_root) and time.monotonic() < deadline:
            time.sleep(0.1)  # a checkout is writing files: index the result, not the middle
        stats = IndexStats()
        if reconcile:
            self._reload_config()
            self.indexer.reset_rules()
        queued = self.indexer.structure(stats, paths=None if reconcile else paths)
        if reconcile:
            self._last_reconcile = time.monotonic()
        self._last_write = time.monotonic()
        self.last_error = None
        if stats.files_changed or stats.files_deleted or stats.files_skipped:
            self.last_stats = stats
        return queued

    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._run, name="codemem-writer", daemon=True)
        self._worker.start()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if not self._step():
                    with self._cond:
                        if not (self._dirty or self._reconcile) and not self._stop.is_set():
                            self._cond.wait(timeout=1.0)
        finally:
            self.store.close_thread_conn()

    def _step(self) -> bool:
        """One unit of background work; False when there was nothing to do."""
        paths, reconcile = self._take_changes()
        if paths or reconcile:
            first = not self.has_index()
            self.state = "indexing" if first else "updating"
            try:
                self._apply_changes(paths, reconcile)
                self.state = "ready" if self.has_index() else self.state
            except Exception as e:
                log.exception("index update failed; will retry")
                self.last_error = f"{type(e).__name__}: {e}"
                self.state = "error" if not self.has_index() else "ready"
                self._requeue(paths, reconcile)
                self._stop.wait(1.0)
            return True
        if self.store.dirty_count():
            stats = IndexStats()
            try:
                self.indexer.embed_pending(stats, deadline=time.monotonic() + 5.0, batch_chunks=_BACKGROUND_BATCH)
            except Exception as e:
                log.exception("embedding failed; will retry")
                self.last_error = f"{type(e).__name__}: {e}"
                self._stop.wait(1.0)
            self._last_write = time.monotonic()
            if sum(stats.embedded.values()):
                self.last_stats = stats
            if not self.store.dirty_count():
                self.state = "ready"
            return True
        now = time.monotonic()
        if self.store.vectors_unsaved() and now - self._last_write > SAVE_AFTER_IDLE:
            self.store.save_vectors()
            return True
        if self._watcher is not None and not self._watcher.alive() and not self._polling:
            log.warning("the file watcher stopped; scanning the repo every %.0f s instead", POLL_EVERY)
            self._polling = True
        interval = POLL_EVERY if self._polling or self._watcher is None else RECONCILE_EVERY
        if self._worker is threading.current_thread() and now - self._last_reconcile > interval:
            self.request_reconcile()
            return True
        return False

    def _reload_config(self) -> None:
        """Pick up an edited `.codemem.toml` (only when the config came from the repo's files)."""
        if not self._own_config:
            return
        try:
            new = load_config(self.repo_root)
        except Exception:
            log.exception("could not read the config; keeping the current one")
            return
        if new != self.config:
            log.info("the config changed; the index follows it")
            self.config = new
            self.store.tok_opts = {"stem": new.bm25_stem, "stopwords": new.bm25_stopwords}
            if self._indexer is not None:
                self._indexer.config = new
                self._indexer.reset_rules()

    def refresh(self, timeout: float = 60.0) -> dict[str, Any]:
        """Reconcile now (after `git checkout` or `git pull`, or when in doubt), embed within
        `timeout`, and write the FAISS files. Returns what changed."""
        t = time.monotonic()
        stats = IndexStats()
        self._take_changes(flush_watcher=True)  # a reconcile covers every pending path
        self._reload_config()
        self.indexer.reset_rules()
        self.indexer.structure(stats)
        self._last_reconcile = time.monotonic()
        self.indexer.embed_pending(stats, deadline=t + timeout)
        self.store.save_vectors()
        self._last_write = time.monotonic()
        return {
            "files_changed": stats.files_changed, "files_deleted": stats.files_deleted,
            "files_skipped": stats.files_skipped, "chunks_added": stats.chunks_added,
            "chunks_updated": stats.chunks_updated, "chunks_deleted": stats.chunks_deleted,
            "texts_embedded": sum(stats.embedded.values()), "pending": self.store.dirty_count(),
            "seconds": round(time.monotonic() - t, 2),
        }

    def catch_up(self, budget: float = CATCHUP_BUDGET) -> Freshness:
        """Apply every edit seen so far, then embed what is queued, within `budget` seconds."""
        deadline = time.monotonic() + budget
        if self._watcher is not None:
            self._watcher.barrier(timeout=min(0.25, budget))  # every earlier save has been reported
        paths, reconcile = self._take_changes(flush_watcher=True)
        if paths or reconcile:
            try:
                self._apply_changes(paths, reconcile)
            except Exception as e:
                log.exception("could not apply pending edits before a search")
                self.last_error = f"{type(e).__name__}: {e}"
                self._requeue(paths, reconcile)
        pending = self.store.dirty_count()
        if pending == 0:
            return Freshness()
        if pending > CATCHUP_MAX_CHUNKS or self.state == "indexing":
            return Freshness(pending, indexing=True)  # the index is being built: report, don't wait
        stats = IndexStats()
        try:
            self.indexer.embed_pending(stats, deadline=deadline, batch_chunks=pending)
        except Exception:
            log.exception("could not embed pending edits before a search")
        while self.store.dirty_count() and time.monotonic() < deadline:
            time.sleep(0.02)  # the writer thread is finishing a batch it had already taken
        if sum(stats.embedded.values()):
            self._last_write = time.monotonic()
        return Freshness(self.store.dirty_count())

    def prewarm(self) -> None:
        """Load the embedding models and the search indexes, so the first query doesn't wait."""
        for model in {self.config.vectors[v].model for v in self.config.enabled_vec_types()}:
            try:
                self.embedder_factory(model, self.config).embed_queries(["warmup"])
            except Exception:
                log.exception("could not load embedding model %s", model)
        try:
            self.store.load_vectors()
        except Exception:
            log.exception("could not load the search indexes")
        finally:
            self.store.close_thread_conn()

    def start_watcher(self) -> RepoWatcher:
        self._ensure_worker()
        try:
            self._watcher = RepoWatcher(
                self.repo_root, self.notify, debounce_ms=self.config.debounce_ms,
                max_wait_ms=self.config.debounce_max_wait_ms, skip=[self.index_dir],
            )
            self._watcher.start()
        except Exception:
            log.exception("the file watcher could not start; scanning the repo every %.0f s instead", POLL_EVERY)
            self._polling = True
        return self._watcher  # type: ignore[return-value]

    def close(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._watcher is not None:
            self._watcher.stop()
        if self._worker is not None and self._worker is not threading.current_thread():
            self._worker.join(timeout=30)
        try:
            self.store.save_vectors()
        except Exception:
            log.exception("could not write the search indexes on close")
        self.store.close()

    # ---- queries
    def search(self, query: str, **kwargs: Any) -> SearchResponse:
        freshness = self.catch_up() if self._worker is not None or self._watcher is not None else Freshness()
        resp = search(self.store, query, self.config, embedder_factory=self.embedder_factory, **kwargs)
        resp.freshness = freshness
        return resp

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

        code = chunk.code
        members = self.store.children_of(chunk.key) if chunk.kind == "class" else []
        if chunk.kind == "class" and chunk.skeleton and code.count("\n") >= _LONG_CLASS_LINES:
            # A long class is read through its outline and members, not as thousands of lines.
            code = chunk.skeleton + f"\n... ({code.count(chr(10)) + 1} lines; use get_chunk on a member)"
        return {
            **make_card(chunk, 0.0, self.config).to_dict(),
            "code": code,
            "docstring": chunk.docstring,
            "members": [brief(c) for c in members],
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
                v: {
                    "model": (store.get_meta(f"vec.{v}.embedder") or "").split("|", 1)[0] or None,
                    "embedder": store.get_meta(f"vec.{v}.embedder"),
                    "dim": store.vector_dim(v),
                }
                for v in self.config.enabled_vec_types()
            },
            "indexed_commit": store.get_meta("indexed_commit"),
            "indexed_at": store.get_meta("indexed_at"),
            "last_update": store.get_meta("last_update"),
            "pending_chunks": store.dirty_count(),
            "pending_files": len(self._dirty),
            "watching": self._watcher is not None and self._watcher.alive() and not self._polling,
            "coverage": store.get_meta("coverage"),
            "skipped_files": store.skipped_files(),
            "error": self.last_error,
        }
        if check_staleness and self.state not in ("indexing", "updating"):
            scan = self.indexer.scan()
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
