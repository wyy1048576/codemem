"""Long-lived owner of one repo's index: updates, freshness, the watcher, queries.

The MCP server and `codemem watch` call `start()`. The CLI and the eval call `update()` and
`search()` directly. Creating a service has no side effects beyond opening the index, because the
eval adapter re-pins `repo_root` after construction.

Freshness (docs/architecture.md §8):
- the watcher hands over batches of changed paths; a writer thread applies them (stage A), then
  embeds what they queued (stage B, in small batches, so new edits get applied in between);
- `search()` hands every save seen so far to the writer thread and waits until it has applied
  them (stage A), then embeds what is queued, newest edits first: all within `catchup_budget_ms`.
  The writer gives it the model meanwhile. `get_chunk()` waits for stage A only;
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
CATCHUP_MAX_CHUNKS = 1000  # beyond this many queued chunks the index is being built: don't wait
SAVE_AFTER_IDLE = 30.0  # write the FAISS files once nothing changed for this long
RECONCILE_EVERY = 300.0  # a full scan, in case a file event was missed
POLL_EVERY = 10.0  # the scan interval when file events don't work
BURST_PATHS = 2000  # more changed paths than this at once: scan everything instead
_BATCH = 64  # queued chunks per embedding batch outside a build (new edits wait for one at most)
# Characters per model call outside a build: about 0.6 s on an M1, so a search waits at most that
# long for the background writer's current call. A build uses bigger calls, for speed.
_CALL_CHARS = 3000


@dataclass
class Freshness:
    """What a search could not include yet."""

    pending_chunks: int = 0  # queued chunks whose vectors are not computed yet
    indexing: bool = False  # the index is being built: many chunks still to embed
    pending_files: int = 0  # saved files not applied yet (still being applied, or applying failed)
    unconfirmed: bool = False  # the watcher could not confirm in time that every earlier save was seen

    @property
    def complete(self) -> bool:
        return self.pending_chunks == 0 and self.pending_files == 0 and not self.unconfirmed


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
        # Only the writer thread (and refresh) take and apply edits, one at a time under _apply_lock;
        # `_applying` counts the files being applied. Each hand-over of edits is numbered
        # (`_received`); `_applied` is the newest one committed and `_settled` the newest one done
        # with, committed or put back after an error. A search waits for its number.
        self._apply_lock = threading.Lock()
        self._applying = 0
        self._received = self._settled = self._applied = 0
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
            self._received += 1
            self._cond.notify_all()

    def request_reconcile(self) -> None:
        self.notify(set(), reconcile=True)

    def request_update(self) -> None:
        """v2 name for a full catch-up."""
        self.request_reconcile()

    def _take_changes(self) -> tuple[set[str], bool, int]:
        """Pending edits, and the number of the newest hand-over among them. Call it holding
        `_apply_lock`, apply them, then `_settle` that number."""
        with self._cond:
            paths, reconcile, upto = self._dirty, self._reconcile, self._received
            self._dirty, self._reconcile = set(), False
            return paths, reconcile, upto

    def _settle(self, upto: int, applied: bool) -> None:
        """Every hand-over up to `upto` is done with: committed, or put back after an error."""
        with self._cond:
            self._settled = max(self._settled, upto)
            if applied:
                self._applied = max(self._applied, upto)
            self._cond.notify_all()

    def _hand_over(self) -> int:
        """Give the writer every save seen so far, now: the watcher's quiet period is for bursts of
        background saves, not for a waiting search. Returns the number of the hand-over that
        includes them; once `_applied` reaches it, they are committed."""
        if self._watcher is not None:
            paths, reconcile = self._watcher.pending()  # waits for a hand-over in progress
            if paths or reconcile:
                self.notify(paths, reconcile)
        with self._cond:
            return self._received

    def _should_yield(self) -> bool:
        """Background embedding gives way: to a search that is catching up, to new saves, or to close()."""
        return self._stop.is_set() or self.indexer.searches_waiting or bool(self._dirty or self._reconcile)

    def _requeue(self, paths: set[str], reconcile: bool) -> None:
        with self._cond:
            self._dirty |= paths
            self._reconcile |= reconcile

    def _wait_for_git(self, until: float) -> bool:
        """Wait while a git command (checkout, merge, rebase) is writing files: index the result,
        not the middle. False if it is still busy at `until`."""
        while git_busy(self.repo_root):
            if time.monotonic() >= until:
                return False
            time.sleep(0.1)
        return True

    def _apply_changes(self, paths: set[str], reconcile: bool) -> set[int] | None:
        """Stage A for pending edits. Returns what was queued (None = everything)."""
        self._wait_for_git(time.monotonic() + 10.0)
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
        failed = False
        with self._apply_lock:
            paths, reconcile, upto = self._take_changes()
            if paths or reconcile:
                self._applying = len(paths) or 1
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
                    failed = True
                finally:
                    self._applying = 0
            self._settle(upto, applied=not failed)  # searches waiting for these edits go on
        if paths or reconcile:
            if failed:
                self._stop.wait(1.0)
            return True
        if self.store.dirty_count():
            if self.indexer.searches_waiting:
                self._stop.wait(0.05)  # a search is embedding what it needs: leave it the model
                return True
            stats = IndexStats()
            try:
                # Stops at its next model call when a search wants the model or new saves arrive.
                self.indexer.embed_pending(
                    stats, deadline=time.monotonic() + 5.0, batch_chunks=_BATCH, group=self.config.batch_size,
                    group_chars=_CALL_CHARS, stop=self._should_yield,
                )
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
        self._hand_over()
        with self._apply_lock:
            _, _, upto = self._take_changes()  # a reconcile covers every pending path
            self._applying = 1
            ok = False
            try:
                self._reload_config()
                self.indexer.reset_rules()
                self.indexer.structure(stats)
                ok = True
            except Exception:
                self._requeue(set(), True)  # the writer thread tries the reconcile again
                raise
            finally:
                self._applying = 0
                self._settle(upto, applied=ok)
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

    def catch_up(self, budget: float | None = None, *, embed: bool = True) -> Freshness:
        """Bring the index up to every save made before this call, for at most `budget` seconds
        (default `catchup_budget_ms`). The writer thread applies them (stage A) while this waits;
        then this embeds what is queued (stage B), newest edits first. With `embed=False` it stops
        after stage A (`get_chunk` needs no vectors). What doesn't fit is reported, not waited for."""
        budget = self.config.catchup_budget_ms / 1000 if budget is None else budget
        deadline = time.monotonic() + budget
        if self.state in ("empty", "indexing"):
            return Freshness(self.store.dirty_count(), indexing=True)  # a first build: report, don't wait
        self._ensure_worker()
        stats = IndexStats()
        with self.indexer.searching():  # the writer's embedding stops at its next model call
            confirmed = True
            if self._watcher is not None and self._watcher.alive() and not self._polling:
                # Every earlier save has been reported once the marker's own event is back.
                confirmed = self._watcher.barrier(timeout=min(0.25, budget))
            else:
                self.notify(set(), reconcile=True)  # no file events: a full check finds every save
            target = self._hand_over()
            with self._cond:
                while self._settled < target and (left := deadline - time.monotonic()) > 0:
                    self._cond.wait(left)
                if self._applied < target:  # still being applied (a huge file, a checkout), or it failed
                    files = max(1, len(self._dirty) + self._applying)
                    return Freshness(self.store.dirty_count(), pending_files=files, unconfirmed=not confirmed)
            if not embed:
                return Freshness(unconfirmed=not confirmed)
            pending = self.store.dirty_count()
            if pending == 0:
                return Freshness(unconfirmed=not confirmed)
            if pending > CATCHUP_MAX_CHUNKS:  # a big change: report, don't wait
                return Freshness(pending, indexing=True, unconfirmed=not confirmed)
            while time.monotonic() < deadline:
                try:
                    done = self.indexer.embed_pending(
                        stats, deadline=deadline, batch_chunks=_BATCH, group=self.config.batch_size,
                        group_chars=_CALL_CHARS,
                    )
                except Exception:
                    log.exception("could not embed pending edits before a search")
                    break
                if not done or not self.store.dirty_count():
                    break
                time.sleep(0.02)  # what is left is in the writer thread's batch, which it is handing back
        if sum(stats.embedded.values()):
            self._last_write = time.monotonic()
        return Freshness(self.store.dirty_count(), unconfirmed=not confirmed)

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
        if self._worker is not None or self._watcher is not None:
            self.catch_up(embed=False)  # code, lines and links as of every earlier save
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
            "pending_files": len(self._dirty) + self._applying,
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
