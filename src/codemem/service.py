"""Long-lived owner of one repo's index: updates, freshness, the watcher, queries.

The MCP server and `codemem watch` call `start()`. The CLI and the eval call `update()` and
`search()` directly; `codemem search` first asks `behind()` and, when the index is behind its
checkout, calls `follow_checkout()`. Creating a service with an `index_dir` has no side effects
beyond opening the index, because the eval adapter re-pins `repo_root` after construction.
Without one, the checkout's default index folder is prepared first (worktrees.py): a new index
starts from a copy of another checkout's, and the indexes of removed worktrees are deleted.

Freshness (docs/architecture.md §4):
- the watcher hands over batches of changed paths; a writer thread applies them (stage A), then
  embeds what they queued (stage B, in small batches, so new edits get applied in between);
- `search()` hands every save seen so far to the writer thread and waits until it has applied
  them (stage A), then embeds what is queued: first the chunks its own keyword ranking puts on
  top, then the newest edits, all within `catchup_budget_ms`. The writer gives it the model
  meanwhile. `get_chunk()` waits for stage A only;
- a reconcile (a scan of the whole repo) runs at startup, every few minutes, on `refresh()`, and
  when the ignore rules, the config or the git branch change;
- the search indexes' files are written once the index has been quiet for a while, and on close.

The embedding model (docs/architecture.md §3.5) loads in a background thread, at start-up and
again after the writer has freed it for being idle (`model_idle_minutes`). The writer and a search
with a budget wait for that thread instead of loading the model themselves. In its quiet steps the
writer also gives back what the model's calls needed besides the model (`embedder.release_idle`).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import assist
from .config import Config, VectorConfig, default_index_dir, find_repo_root, load_config
from .embedder import Embedder, make_embedder, release_idle
from .indexer import IndexStats, Indexer, git_head
from .search import BM25, SearchResponse, make_card, search
from .store import Store
from .watcher import RepoWatcher, git_busy
from .worktrees import prepare_index

log = logging.getLogger(__name__)

_LONG_CLASS_LINES = 80
# Rough share of total work per phase, for a single progress percentage.
_PHASE_SPAN = {"chunk": (0.0, 0.15), "embed": (0.15, 1.0), "done": (1.0, 1.0)}
CATCHUP_MAX_CHUNKS = 1000  # beyond this many queued chunks a search embeds only its own keyword results
SAVE_AFTER_IDLE = 30.0  # write the search indexes' files once nothing changed for this long
RECONCILE_EVERY = 300.0  # a full scan, in case a file event was missed
POLL_EVERY = 10.0  # the scan interval when file events don't work
RETRY_FIRST = 1.0  # a step of the writer that failed is tried again after this long ...
RETRY_MAX = 60.0  # ... then after twice as long each time, up to this
# A search that may not wait for a loading model still waits this long for one that was freed for
# being idle: after an idle time a search costs the reload (2 to 6 s on an M1), not its results.
IDLE_RELOAD_WAIT = 20.0
CACHE_UPKEEP_EVERY = 6 * 3600.0  # in a quiet moment the writer keeps the vector cache: what this index uses, the age limit, the cap
CACHE_UPKEEP_SECONDS = 1.0  # ... deleting for this long at a time, so that a save never waits long behind it
BURST_PATHS = 2000  # more changed paths than this at once: scan everything instead
_BATCH = 64  # queued chunks per embedding batch outside a build (new edits wait for one at most)
_FILTERS = ("path_prefix", "kinds", "languages", "tests", "test_weight", "kind_weights")  # of a search
# Characters per model call outside a build: about 0.6 s on an M1, so a search waits at most that
# long for the background writer's current call. A build uses bigger calls, for speed.
_CALL_CHARS = 3000


def _by_meaning(signals: Sequence[str] | None) -> bool:
    """Whether a search by `signals` ranks by vectors too (None: every signal the index has)."""
    return signals is None or any(s != BM25 for s in signals)


def _model_of(embedder_key: str | None) -> str | None:
    """The model in an embedder key: `jina…|doc|L1024|…` or `api:<host or space>|<model>|dims=…`."""
    if not embedder_key:
        return None
    parts = embedder_key.split("|")
    return parts[1] if embedder_key.startswith("api:") and len(parts) > 1 else parts[0]


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


class _Retry:
    """When a failed step is tried again: after `RETRY_FIRST`, then after twice as long each time,
    up to `RETRY_MAX`, and from the start once it has worked. A step that cannot work (a local
    model whose packages are not installed) is then not tried every second for ever. An error is
    logged with its traceback the first time, and with one line each time it comes back."""

    clock = staticmethod(time.monotonic)  # tests replace it, so they need not wait

    def __init__(self) -> None:
        self.error: str | None = None  # what failed, as `last_error` shows it; None while the step works
        self.at = 0.0  # when the next try is due
        self._wait = 0.0
        self._seen: set[str] = set()

    @property
    def due(self) -> bool:
        return self.clock() >= self.at

    def failed(self, what: str, error: Exception) -> float:
        """Note a failure of `what`, and log it. Returns the seconds until the next try."""
        self.error = f"{type(error).__name__}: {error}"
        self._wait = min(max(RETRY_FIRST, 2 * self._wait), RETRY_MAX)
        self.at = self.clock() + self._wait
        if self.error in self._seen:
            log.warning("%s failed again; next try in %.0f s: %s", what, self._wait, self.error)
        else:
            if len(self._seen) >= 8:  # errors whose text keeps changing: don't keep them all
                self._seen.clear()
            self._seen.add(self.error)
            log.error("%s failed; next try in %.0f s", what, self._wait, exc_info=error)
        return self._wait

    def worked(self) -> None:
        self.error, self.at, self._wait = None, 0.0, 0.0
        self._seen.clear()


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
        self._own_config = config is None  # loaded from the repo's files: reload it when they change
        self.config = config or load_config(self.repo_root)
        self.copied_from: Path | None = None  # the index folder this checkout's new index was copied from
        if index_dir:
            self.index_dir = Path(index_dir)
        else:
            self.index_dir = default_index_dir(self.repo_root)
            self.copied_from = prepare_index(self.repo_root, self.index_dir, self.config)
        self._make_embedder = embedder_factory
        self._embedders: dict[tuple, Embedder] = {}  # every embedder handed out so far, by model
        self.store = Store(
            self.index_dir, bm25_stem=self.config.bm25_stem, bm25_stopwords=self.config.bm25_stopwords,
            vector_backend=self.config.vector_backend, vector_options=self.config.vector_options(),
            vector_memory_mb=self.config.vector_memory_mb,
        )
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
        self._prewarm: threading.Thread | None = None
        # The three things the writer tries again after a failure: stage A, stage B, a model's load.
        self._update_retry, self._embed_retry, self._load_retry = _Retry(), _Retry(), _Retry()
        self._polling = False
        self._last_write = 0.0  # monotonic time of the last index change
        self._last_reconcile = 0.0
        self._last_cache_upkeep = time.monotonic()  # an update at start has just done it

    def embedder_factory(self, spec: VectorConfig | str, config: Config) -> Embedder:
        """The embedder of a vector type (or of a bare model name, as `make_embedder` takes). Each
        one handed out is remembered, so `status` and the idle unload reach the models in use
        without building any."""
        embedder = self._make_embedder(spec, config)
        named = VectorConfig(model=spec) if isinstance(spec, str) else spec
        self._embedders[(named.model, named.embedder, named.version)] = embedder
        return embedder

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
        search indexes' files written. Waits for any update in progress. An error is kept in `last_error`
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
        for retry in (self._update_retry, self._embed_retry, self._load_retry):
            retry.worked()
        self._last_write = self._last_reconcile = time.monotonic()
        return stats

    # ---- before a search of a command that answers once (`codemem search`)
    def behind(self, signals: Sequence[str] | None = None) -> dict[str, Any] | None:
        """What stands between the index and an answer for the checkout as it is now, for a search
        by `signals` (None: all of them); None when nothing does. A full check that changes
        nothing, the one `status` makes, finds the files to re-chunk and to drop (after a `git
        switch` or a pull, or edits made while nothing watched), and whether git's HEAD moved. A
        search that ranks by meaning also needs the vectors of the chunks still queued."""
        scan = self.indexer.scan()
        pending = self.store.dirty_count() if _by_meaning(signals) else 0
        if scan.is_clean and not pending:
            return None
        head = git_head(self.repo_root)
        return {
            "changed_files": len(scan.changed) + len(scan.skipped),
            "deleted_files": len(scan.deleted),
            "head_moved": bool(head and head != self.store.get_meta("indexed_commit")),
            "pending_chunks": pending,
        }

    def follow_checkout(self, query: str, **options: Any) -> Freshness:
        """Bring the index to the checkout now, in the calling thread, before `search(query,
        **options)`: what `codemem search` does when `behind()` says the index is behind. Such a
        command has no writer that would do it, and it waits, as it waits for the model.

        Stage A first, a full check however long it takes: from then on names, lines and keywords
        are the checkout's. Then stage B: every queued chunk, or, with more than
        `CATCHUP_MAX_CHUNKS` queued (a large switch, a build another process has not finished),
        only the chunks this search's own keywords rank on top, as a search of a running server
        does. A search by keywords alone needs no vector and embeds nothing. Returns what the
        search still lacks.

        It follows the files and does nothing else: an index built with other settings or by
        another embedder, which an update would rebuild or embed again, is left as it is
        (`indexer.SettingsChanged`). That and every other error is raised, not kept: the caller
        says what it means for its answer."""
        stats = IndexStats()
        with self._apply_lock:
            self.indexer.structure(stats, only_files=True)
        self._last_write = self._last_reconcile = time.monotonic()
        pending = self.store.dirty_count()
        if not pending or not _by_meaning(options.get("signals")):
            return Freshness()
        big = pending > CATCHUP_MAX_CHUNKS
        self.indexer.embed_pending(stats, only=self._keyword_results(query, options) if big else None)
        return Freshness(self.store.dirty_count(), indexing=big)

    # ---- indexing in the background (MCP server, `codemem watch`)
    def start(self, *, watch: bool = True, prewarm: bool = True) -> None:
        """Keep the index fresh in the background: a catch-up now, then the watcher's batches,
        a reconcile every few minutes, and lazy saves of the search indexes' files."""
        self.request_reconcile()
        self._ensure_worker()
        if watch:
            self.start_watcher()
        if prewarm:
            with self._cond:
                self._prewarm = threading.Thread(target=self.prewarm, name="codemem-prewarm", daemon=True)
                self._prewarm.start()

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
        """Another name for `request_reconcile`."""
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
        self.last_error = self._load_retry.error or self._embed_retry.error  # what still fails, if anything
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
        failed, pause = False, 0.0
        with self._apply_lock:
            paths, reconcile, upto = self._take_changes()
            if paths or reconcile:
                self._applying = len(paths) or 1
                first = not self.has_index()
                self.state = "indexing" if first else "updating"
                try:
                    self._apply_changes(paths, reconcile)
                    self.state = "ready" if self.has_index() else self.state
                    self._update_retry.worked()
                except Exception as e:
                    pause = self._update_retry.failed("the index update", e)
                    self.last_error = self._update_retry.error
                    self.state = "error" if not self.has_index() else "ready"
                    self._requeue(paths, reconcile)
                    failed = True
                finally:
                    self._applying = 0
            self._settle(upto, applied=not failed)  # searches waiting for these edits go on
        if paths or reconcile:
            if failed:
                self._pause(pause, upto)
            return True
        if self.store.dirty_count() and self._embed_some():
            return True
        now = time.monotonic()
        if self.store.vectors_unsaved() and now - self._last_write > SAVE_AFTER_IDLE:
            self.store.save_vectors()
            return True
        for embedder in list(self._embedders.values()):  # no model call is due here: a quiet moment for the models
            release_idle(embedder, self.config.model_idle_minutes)
        if now - self._last_cache_upkeep > CACHE_UPKEEP_EVERY:
            # A session that runs for days makes no update of its own kind (Indexer.update), which
            # is where the cache is kept otherwise. Cut short, it goes on at the next quiet moment.
            try:
                done = self.indexer.cache_upkeep(CACHE_UPKEEP_SECONDS)
            except Exception:
                log.exception("could not keep the vector cache")
                done = True
            if done:
                self._last_cache_upkeep = now
            return True
        if self._watcher is not None and not self._watcher.alive() and not self._polling:
            log.warning("the file watcher stopped; scanning the repo every %.0f s instead", POLL_EVERY)
            self._polling = True
        interval = POLL_EVERY if self._polling or self._watcher is None else RECONCILE_EVERY
        if self._worker is threading.current_thread() and now - self._last_reconcile > interval:
            self.request_reconcile()
            return True
        return False

    def _pause(self, seconds: float, since: int) -> None:
        """Wait before a failed update is tried again: `seconds`, or until the service closes, or
        until something newer than hand-over `since` arrives (a save, a search), which is tried at
        once."""
        with self._cond:
            self._cond.wait_for(lambda: self._stop.is_set() or self._received > since, timeout=seconds)

    def _embed_some(self) -> bool:
        """Stage B for a slice of the queue. False when it has to wait for a later try, because
        the model could not be loaded or the last slice failed: the writer then goes on with its
        quiet work, and saves are still applied."""
        if self.indexer.searches_waiting:
            self._stop.wait(0.05)  # a search is embedding what it needs: leave it the model
            return True
        if not self._embed_retry.due:
            return False
        stats = IndexStats()
        try:
            if not self._models_ready(0.0):
                if self._prewarm is None or not self._prewarm.is_alive():
                    return False  # the load failed, and its next try is not due
                # The model is loading in its own thread (start-up, or the first use after an
                # idle unload): saves are still applied meanwhile.
                self._stop.wait(0.05)
                return True
            # Stops at its next model call when a search wants the model or new saves arrive.
            self.indexer.embed_pending(
                stats, deadline=time.monotonic() + 5.0, batch_chunks=_BATCH, group=self.config.batch_size,
                group_chars=_CALL_CHARS, stop=self._should_yield,
            )
            self._recovered(self._embed_retry)
        except Exception as e:
            self._embed_retry.failed("embedding", e)
            self.last_error = self._embed_retry.error
        self._last_write = time.monotonic()
        if sum(stats.embedded.values()):
            self.last_stats = stats
        if not self.store.dirty_count():
            self.state = "ready"
        return True

    def _recovered(self, retry: _Retry) -> None:
        """A step has worked. If it had failed before, `last_error` goes back to what still fails,
        if anything."""
        if retry.error is not None:
            retry.worked()
            self.last_error = self._update_retry.error or self._load_retry.error or self._embed_retry.error

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
            asked = (new.vector_backend, new.vector_options(), new.vector_memory_mb)
            if asked != (self.store.vector_backend, self.store.vector_options, self.store.vector_memory_mb):
                try:
                    self.store.use_vector_backend(*asked)
                except Exception:
                    log.exception("could not load vector_backend %r; keeping the current config", new.vector_backend)
                    return
            self.config = new
            self.store.tok_opts = {"stem": new.bm25_stem, "stopwords": new.bm25_stopwords}
            if self._indexer is not None:
                self._indexer.config = new
                self._indexer.reset_rules()

    def refresh(self, timeout: float = 60.0) -> dict[str, Any]:
        """Reconcile now (after `git checkout` or `git pull`, or when in doubt), embed within
        `timeout`, and write the search indexes' files. Returns what changed."""
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

    def catch_up(
        self, budget: float | None = None, *, embed: bool = True, wait_for_models: bool = True,
        first: Callable[[], list[int]] | None = None,
    ) -> Freshness:
        """Bring the index up to every save made before this call, for at most `budget` seconds
        (default `catchup_budget_ms`). The writer thread applies them (stage A) while this waits;
        then this embeds what is queued (stage B): the chunks `first()` names, in its order and
        however long the queue is, then the newest edits. With `embed=False` it stops after stage
        A (`get_chunk` needs no vectors). With `wait_for_models=False` it embeds, the chunks of
        `first()` too, only if the model is in memory by then. What doesn't fit is reported, not
        waited for."""
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
            big = pending > CATCHUP_MAX_CHUNKS  # a big change: report the rest, don't wait for it
            if big and first is None:
                return Freshness(pending, indexing=True, unconfirmed=not confirmed)
            if not wait_for_models and not self._models_ready(deadline, after_idle=True):
                # Embedding now would wait out the load, for the chunks of `first()` as for the rest.
                return Freshness(pending, indexing=big, unconfirmed=not confirmed)
            if first is not None:
                self._embed_first(first(), stats, deadline)
                big = self.store.dirty_count() > CATCHUP_MAX_CHUNKS
            while not big and time.monotonic() < deadline:
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
        return Freshness(self.store.dirty_count(), indexing=big, unconfirmed=not confirmed)

    def _embed_first(self, chunk_ids: list[int], stats: IndexStats, deadline: float) -> None:
        """Stage B for the queued chunks among `chunk_ids`, one at a time and in that order, until
        `deadline`: when the time runs out, the best-ranked ones are done."""
        queued = self.store.dirty_seqs(chunk_ids)
        todo = [i for i in chunk_ids if i in queued]
        while todo and time.monotonic() < deadline:
            try:
                done = self.indexer.embed_pending(
                    stats, only=todo[:1], deadline=deadline, batch_chunks=1, group=self.config.batch_size,
                    group_chars=_CALL_CHARS,
                )
            except Exception:
                log.exception("could not embed a search's keyword results before it")
                return
            if not done:
                return
            chunk_id = todo.pop(0)
            if self.store.dirty_seqs([chunk_id]):
                todo.append(chunk_id)  # it is in the writer thread's batch, which it is handing back
                time.sleep(0.02)

    def _keyword_results(self, query: str, options: dict[str, Any]) -> list[int]:
        """The chunks a search's keyword ranking puts on top, best first: as many as one ranking
        gives to the merge, under the search's own filters."""
        filters = {k: v for k, v in options.items() if k in _FILTERS}
        n = max(self.config.candidates, options.get("k") or 0)
        resp = search(self.store, query, self.config, k=n, signals=[BM25], embedder_factory=self.embedder_factory, **filters)
        return [r.chunk_id for r in resp.results]

    def prewarm(self) -> None:
        """Load the embedding models and the search indexes, so the first query doesn't wait. It
        runs in a thread at start-up, and again when a model that was freed while idle is needed.
        The two load side by side: a model takes seconds, and so does a search index that has to
        be rebuilt from the stored vectors."""
        indexes = threading.Thread(target=self._load_indexes, name="codemem-indexes", daemon=True)
        indexes.start()
        specs = {}
        for v in self.config.enabled_vec_types():
            spec = self.config.vectors[v]
            specs.setdefault((spec.model, spec.embedder, spec.version), spec)
        failed = False
        for spec in specs.values():
            try:
                # A document, not a query: query vectors are cached, and a cached one would not
                # bring a model back that was freed while idle.
                self.embedder_factory(spec, self.config).embed_documents(["warmup"])
            except Exception as e:
                failed = True
                self._load_retry.failed(f"loading the embedding model {spec.model}", e)
                self.last_error = self._load_retry.error
        if not failed:
            self._recovered(self._load_retry)
        indexes.join()

    def _load_indexes(self) -> None:
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
    def search(self, query: str, *, wait_for_models: bool = True, **kwargs: Any) -> SearchResponse:
        """Catch up on pending saves, then search. With `wait_for_models=False` (the MCP server), a
        search waits for what is still loading only within `catchup_budget_ms` too: the embedding
        model at start-up, and the search indexes (read from their files, or rebuilt from the stored
        vectors on the first start after the search index changed, which takes half a minute for
        200,000 vectors in the compact form, with FAISS on one thread). If they are not in memory
        by then, or will not be, the search uses keywords alone and says so. A model that was
        freed for being idle is waited for longer (`IDLE_RELOAD_WAIT`): the first search after an
        idle time then costs the reload, not the vectors' part of its results."""
        deadline = time.monotonic() + self.config.catchup_budget_ms / 1000
        freshness = Freshness()
        if self._worker is not None or self._watcher is not None:
            # A pending chunk has an old vector or none, so the merge ranks it by its keywords
            # alone. The ones this query's keywords rank on top are embedded before anything else,
            # under the catch-up's own rule for a model that is loading (`wait_for_models`).
            first = (lambda: self._keyword_results(query, kwargs)) if _by_meaning(kwargs.get("signals")) else None
            freshness = self.catch_up(wait_for_models=wait_for_models, first=first)
        loading = not wait_for_models and "signals" not in kwargs and not (
            self._models_ready(deadline, after_idle=True) and self._indexes_ready(deadline))
        if loading:
            kwargs["signals"] = ["bm25"]
        resp = search(self.store, query, self.config, embedder_factory=self.embedder_factory, **kwargs)
        resp.freshness, resp.models_loading = freshness, loading
        return resp

    def _models_ready(self, until: float, *, after_idle: bool = False) -> bool:
        """Whether the embedding models are in memory, waiting until `until` while they load.
        Starts loading them in the background if nothing is and a try is due (`_Retry`). It does
        not wait for a load that has failed: there is nothing to wait for until the next try.
        With `after_idle`, a model that was freed for being idle is waited for until
        `IDLE_RELOAD_WAIT` from now, however near `until` is."""
        embedders = [self.embedder_factory(self.config.vectors[v], self.config) for v in self.config.enabled_vec_types()]
        for e in embedders:
            e.touch()  # first, so that an idle unload cannot fall between this check and the embedding
        if all(e.ready for e in embedders):
            return True
        if after_idle and any(e.freed_idle for e in embedders):
            until = max(until, time.monotonic() + IDLE_RELOAD_WAIT)
        with self._cond:
            if (self._prewarm is None or not self._prewarm.is_alive()) and self._load_retry.due:
                self._prewarm = threading.Thread(target=self.prewarm, name="codemem-prewarm", daemon=True)
                self._prewarm.start()
            loader = self._prewarm
        while loader is not None and loader.is_alive() and time.monotonic() < until:
            if all(e.ready for e in embedders):
                return True
            time.sleep(0.05)
        return all(e.ready for e in embedders)

    def _models_loaded(self) -> bool | None:
        """Whether the model of every enabled vector type is in this process's memory. None when
        there is none to hold: embeddings from an API, or no vector type."""
        specs = [self.config.vectors[v] for v in self.config.enabled_vec_types()]
        if self.config.embedding.remote or not specs:
            return None
        embedders = [self._embedders.get((s.model, s.embedder, s.version)) for s in specs]
        return all(e is not None and e.ready for e in embedders)

    def _indexes_ready(self, until: float) -> bool:
        """Whether the search indexes are in memory, waiting until `until` while they load, but
        not for a rebuild that will not be done by then. Starts loading them in the background if
        nothing has yet."""
        if self.store.vectors_loaded():
            return True
        with self._cond:
            if self._prewarm is None or not self._prewarm.is_alive():
                self._prewarm = threading.Thread(target=self.prewarm, name="codemem-prewarm", daemon=True)
                self._prewarm.start()
        while (now := time.monotonic()) < until:
            if self.store.vectors_loaded():
                return True
            left = self.store.load_eta()
            if left is not None and now + left > until:
                return False
            time.sleep(0.05)
        return self.store.vectors_loaded()

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

    def check_assist(self) -> list[dict[str, Any]]:
        """Compare the assist endpoint's vectors with each local model's now, without a build
        (`AssistedEmbedder.check`): one report per model, none without an assist."""
        specs = [self.config.vectors[v] for v in self.config.enabled_vec_types()]
        embedders = {id(e): e for e in (self.embedder_factory(spec, self.config) for spec in specs)}
        return [e.check() for e in embedders.values() if isinstance(e, assist.AssistedEmbedder)]

    def status(self, *, check_staleness: bool = True) -> dict[str, Any]:
        store = self.store
        info: dict[str, Any] = {
            "state": self.state,
            "progress": round(self.progress, 1) if self.state in ("indexing", "updating") else None,
            "repo": str(self.repo_root),
            "index_dir": str(self.index_dir),
            **store.counts(),
            "embedding": (
                {"provider": self.config.embedding.provider, "model": self.config.embedding.model,
                 "host": urlparse(self.config.embedding.base_url).netloc or self.config.embedding.base_url,
                 "space": self.config.embedding.space or None}
                if self.config.embedding.remote else {"provider": "local"}
            ),
            # Where code texts also go, and whether that endpoint shares the work (None: no assist).
            "assist": None if self.config.embedding.remote else assist.describe(
                self.config.embedding.assist, list(self._embedders.values()),
                [store.get_meta(f"vec.{v}.embedder") for v in self.config.enabled_vec_types()],
            ),
            "models": {
                v: {
                    "model": _model_of(store.get_meta(f"vec.{v}.embedder")),
                    "embedder": store.get_meta(f"vec.{v}.embedder"),
                    "dim": store.vector_dim(v),
                }
                for v in self.config.enabled_vec_types()
            },
            "models_loaded": self._models_loaded(),
            "search_index": store.search_index_status(),
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
        cache = self.indexer.vector_cache()
        if cache is None:
            info["vector_cache"] = None  # off
        else:
            info["vector_cache"] = cache.stats() or {"path": str(cache.path), "entries": None}  # None: unreadable
            cache.close()
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
