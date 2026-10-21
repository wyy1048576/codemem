"""watchdog -> debounced incremental re-index."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import ALWAYS_SKIP_DIRS

log = logging.getLogger(__name__)


class Debouncer:
    """Calls `fn` once, `delay` seconds after the last `trigger()`."""

    def __init__(self, delay: float, fn: Callable[[], None]):
        self.delay = delay
        self.fn = fn
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def trigger(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay, self.fn)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


class _Handler(FileSystemEventHandler):
    def __init__(self, root: Path, skip: list[Path], on_change: Callable[[], None]):
        self.root = root
        self.skip = [os.path.normcase(str(p)) for p in skip]
        self.on_change = on_change

    def _relevant(self, path: str) -> bool:
        if not path:
            return False
        norm = os.path.normcase(os.path.abspath(path))
        if any(norm == s or norm.startswith(s + os.sep) for s in self.skip):
            return False
        try:
            parts = Path(path).resolve().relative_to(self.root).parts
        except ValueError:
            return False
        if any(p in ALWAYS_SKIP_DIRS for p in parts[:-1]):
            return False
        name = parts[-1] if parts else ""
        return name.endswith(".py") or name == ".gitignore"

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type in ("opened", "closed_no_write"):
            return
        paths = [event.src_path, getattr(event, "dest_path", "")]
        # Directory moves/deletes can drop many .py files at once.
        if event.is_directory and event.event_type in ("moved", "deleted"):
            self.on_change()
            return
        if any(self._relevant(os.fsdecode(p)) for p in paths if p):
            self.on_change()


class RepoWatcher:
    def __init__(self, root: Path, on_change: Callable[[], None], *, debounce_ms: int = 400, skip: list[Path] = ()):
        self.root = Path(root).resolve()
        self.debouncer = Debouncer(debounce_ms / 1000, on_change)
        self.observer = Observer()
        self.observer.schedule(_Handler(self.root, list(skip), self.debouncer.trigger), str(self.root), recursive=True)

    def start(self) -> None:
        self.observer.daemon = True
        self.observer.start()
        log.info("watching %s", self.root)

    def stop(self) -> None:
        self.debouncer.cancel()
        self.observer.stop()
        self.observer.join(timeout=5)
