"""File events -> batches of changed paths for incremental updates.

The watcher only notices; the service decides when to index (docs/architecture.md §4):
- paths are collected until saves stop for `debounce_ms`, or at most `max_wait_ms` after the
  first one, then handed over in one batch;
- a change to `.gitignore`, the repo config or the git branch asks for a full reconcile instead;
- `barrier()` lets a search wait until every event before it has arrived: it writes a marker file
  into the git folder and waits for that file's own event (events arrive in order).
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import ALWAYS_SKIP_DIRS, REPO_CONFIG_NAME
from .languages import EXTENSIONS

log = logging.getLogger(__name__)

OnChange = Callable[[set[str], bool], None]  # (repo-relative paths, reconcile everything)
_BARRIER = "codemem-barrier-"


def git_dir(root: Path) -> Path | None:
    """The repo's git folder: `.git/`, or where a worktree's or submodule's `.git` file points."""
    dot = root / ".git"
    if dot.is_dir():
        return dot
    if dot.is_file():
        try:
            line = dot.read_text("utf-8").strip()
        except OSError:
            return None
        if line.startswith("gitdir:"):
            target = Path(line.split(":", 1)[1].strip())
            target = target if target.is_absolute() else (root / target)
            return target.resolve() if target.is_dir() else None
    return None


class Debouncer:
    """Collects paths and hands them over once no new one arrived for `delay` seconds, or at most
    `max_wait` seconds after the first, so a long burst of saves can't postpone indexing forever."""

    def __init__(self, delay: float, fn: OnChange, max_wait: float | None = None):
        self.delay = delay
        self.max_wait = max_wait if max_wait is not None else max(delay, 2.0)
        self.fn = fn
        self._paths: set[str] = set()
        self._reconcile = False
        self._timer: threading.Timer | None = None
        self._first: float | None = None
        self._lock = threading.Lock()

    def trigger(self, paths: set[str] | None = None, reconcile: bool = False) -> None:
        with self._lock:
            self._paths |= paths or set()
            self._reconcile |= reconcile
            now = time.monotonic()
            if self._first is None:
                self._first = now
            if self._timer is not None:
                self._timer.cancel()
            wait = max(0.0, min(self.delay, self._first + self.max_wait - now))
            self._timer = threading.Timer(wait, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> tuple[set[str], bool]:
        """Take what is collected now, without waiting for the quiet period. A hand-over in
        progress finishes first, so every path is either returned here or already delivered."""
        with self._lock:
            return self._take()

    def _take(self) -> tuple[set[str], bool]:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        paths, reconcile = self._paths, self._reconcile
        self._paths, self._reconcile, self._first = set(), False, None
        return paths, reconcile

    def _fire(self) -> None:
        with self._lock:  # delivered before the lock is released (see flush)
            paths, reconcile = self._take()
            if paths or reconcile:
                self.fn(paths, reconcile)

    def cancel(self) -> None:
        self.flush()


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: RepoWatcher):
        self.w = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type in ("opened", "closed_no_write"):
            return
        if event.is_directory and event.event_type == "modified":
            return  # a folder's entry list changed: the files themselves report their own events
        for raw in (event.src_path, getattr(event, "dest_path", "")):
            if raw:
                self.w.seen(os.fsdecode(raw), event.is_directory)


class RepoWatcher:
    def __init__(
        self, root: Path, on_change: OnChange, *, debounce_ms: int = 500, max_wait_ms: int = 2000,
        skip: Sequence[Path] = (),
    ):
        self.root = Path(root).resolve()
        self.debouncer = Debouncer(debounce_ms / 1000, on_change, max_wait_ms / 1000)
        self.skip = [os.path.normcase(str(Path(p).resolve())) for p in skip]
        self.git = git_dir(self.root)
        self.observer = Observer()
        self.observer.schedule(_Handler(self), str(self.root), recursive=True)
        if self.git is not None and not self._inside_root(self.git):
            self.observer.schedule(_Handler(self), str(self.git), recursive=False)  # a worktree's git folder
        self._barriers: dict[str, threading.Event] = {}
        self._barrier_lock = threading.Lock()

    def _inside_root(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
            return True
        except ValueError:
            return False

    def _git_relative(self, path: Path) -> Path | None:
        """`path` relative to the git folder, or None when it is outside it."""
        if self.git is None:
            return None
        try:
            return path.relative_to(self.git)
        except ValueError:
            try:
                return path.resolve().relative_to(self.git)
            except (ValueError, OSError):
                return None

    # ---- events
    def seen(self, raw: str, is_dir: bool) -> None:
        path = Path(raw)
        if path.name.lstrip(".").startswith(_BARRIER):
            with self._barrier_lock:
                event = self._barriers.get(path.name)
            if event is not None:
                event.set()
            return
        in_git = self._git_relative(path)
        if in_git is not None:
            if in_git.as_posix() in ("HEAD", "packed-refs") or in_git.parts[:1] == ("refs",):
                self.debouncer.trigger(reconcile=True)  # branch switch, pull, reset
            return
        norm = os.path.normcase(os.path.abspath(raw))
        if any(norm == s or norm.startswith(s + os.sep) for s in self.skip):
            return
        try:
            rel = Path(raw).resolve().relative_to(self.root) if Path(raw).exists() else Path(raw).relative_to(self.root)
        except ValueError:
            return
        parts = rel.parts
        if not parts or any(p in ALWAYS_SKIP_DIRS for p in parts[:-1]) or parts[0] in ALWAYS_SKIP_DIRS:
            return
        name = parts[-1]
        if name in (".gitignore", REPO_CONFIG_NAME):
            self.debouncer.trigger(reconcile=True)
            return
        if is_dir or os.path.splitext(name)[1].lower() in EXTENSIONS or not Path(raw).exists():
            # A folder (moved or deleted), a source file, or something gone (it may have been one).
            self.debouncer.trigger({rel.as_posix()})

    # ---- for searches
    def pending(self) -> tuple[set[str], bool]:
        """Collected paths not handed over yet (taken now, so a search can apply them first)."""
        return self.debouncer.flush()

    def barrier(self, timeout: float = 0.25) -> bool:
        """Wait until every file event that happened before this call has arrived: write a marker
        file and wait for its own event. The marker goes into the git folder, where `git status`
        never shows it; a repo without git gets a hidden file in its root, removed at once.
        True if the marker came back in time."""
        folder, prefix = (self.git, "") if self.git is not None else (self.root, ".")
        name = f"{prefix}{_BARRIER}{os.getpid()}-{uuid.uuid4().hex[:8]}"
        event = threading.Event()
        with self._barrier_lock:
            self._barriers[name] = event
        marker = folder / name
        try:
            marker.write_bytes(b"")
            return event.wait(timeout)
        except OSError:
            return True
        finally:
            with self._barrier_lock:
                self._barriers.pop(name, None)
            try:
                marker.unlink()
            except OSError:
                pass

    # ---- lifecycle
    def start(self) -> None:
        self.observer.daemon = True
        self.observer.start()
        log.info("watching %s", self.root)

    def alive(self) -> bool:
        return self.observer.is_alive()

    def stop(self) -> None:
        self.debouncer.cancel()
        self.observer.stop()
        self.observer.join(timeout=5)


def git_busy(root: Path) -> bool:
    """A git command is changing the working tree right now (checkout, merge, rebase)."""
    gd = git_dir(root)
    return gd is not None and (gd / "index.lock").exists()
