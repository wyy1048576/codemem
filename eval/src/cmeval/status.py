"""Status files for long jobs, read by the dashboard.

Each long job (run, score, collect, repo-stats) writes one small JSON file in
CMEVAL_HOME/status/. A thread writes the file again every 2 seconds, also while the job waits
in one long call (an index build), so the time in "updated" shows that the process is alive.

The status file is only a view. A failed write is ignored, so the dashboard can never stop or
change a job. The job's own files (meta.json, results) stay the record.

File <job>-<UTC start, to the millisecond>-<pid>.json:
    job, name, argv, pid, started, updated, ended, state ("running", "done", "failed"), error,
    stage, done, total, unit, rate (units per minute), eta_seconds, parts {name: {done, total}},
    retries (None if the job has no retry count), result {key: value}, log (the last progress lines)
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .files import now, write_text_atomic
from .paths import status_dir

WRITE_INTERVAL = 2.0  # seconds between writes
KEEP_FINISHED = 20  # finished status files kept; older ones are deleted when a job starts
LOG_LINES = 10
RATE_WINDOW = 300.0  # the speed is measured over the last 5 minutes of this session
STALE_SECONDS = 60  # a running job with no write for this long is over (killed, or the machine slept)
TMP_MAX_AGE = 3600  # seconds; a temp file this old is left from a write that was stopped


def pid_alive(pid: int) -> bool:
    """True if a process with this id exists on this machine.

    On Windows, os.kill(pid, 0) would end the process, so there the answer is always True and
    the dashboard uses only the age of the last update.
    """
    if pid <= 0:
        return False  # no pid in the file; os.kill(0, 0) would ask about our own process group
    if os.name == "nt":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists, but belongs to another user
    except OSError:
        return False
    return True


class NullStatus:
    """A status that writes nothing. The default in the job functions, and in tests."""

    def stage(self, text: str) -> None:
        pass

    def total(self, n: int, unit: str | None = None) -> None:
        pass

    def part(self, name: str, total: int, done: int = 0) -> None:
        pass

    def already_done(self, n: int) -> None:
        pass

    def set_done(self, n: int) -> None:
        pass

    def advance(self, n: int = 1, part: str | None = None) -> None:
        pass

    def log(self, message: str) -> None:
        pass

    def retries(self, read: Callable[[], int]) -> None:
        pass

    def result(self, **values: Any) -> None:
        pass

    def fail(self, error: str) -> None:
        pass


class JobStatus(NullStatus):
    """The status of one job, written to its own file. Use it as a context manager:

        with JobStatus("run", run_id) as status:
            status.total(399, "tasks")
            ...
            status.advance(part="pandas-dev/pandas")

    On exit the state is "done", or "failed" with the error (also for Ctrl-C, or after fail()).
    """

    def __init__(self, job: str, name: str, *, folder: Path | None = None, interval: float = WRITE_INTERVAL,
                 keep: int = KEEP_FINISHED, clock: Callable[[], float] = time.monotonic):
        self.folder = folder or status_dir()
        self.interval = interval
        self.keep = keep
        self.clock = clock
        started = datetime.now(timezone.utc)
        self.path = self.folder / f"{job}-{started:%Y%m%dT%H%M%S}.{started.microsecond // 1000:03d}Z-{os.getpid()}.json"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._read_retries: Callable[[], int] | None = None
        self._samples: deque[tuple[float, int]] = deque()  # (clock, units done in this session)
        self._session_done = 0
        self._base: tuple[float, int] = (clock(), 0)  # start of the speed window: (clock, units done)
        self._log: deque[str] = deque(maxlen=LOG_LINES)
        self.data: dict[str, Any] = {
            "job": job, "name": name, "argv": sys.argv[1:], "pid": os.getpid(),
            "started": started.isoformat(timespec="milliseconds"), "updated": None, "ended": None,
            "state": "running", "error": None, "stage": "", "done": 0, "total": None, "unit": None,
            "rate": None, "eta_seconds": None, "parts": {}, "retries": None, "result": {}, "log": [],
        }

    # ---- context manager

    def __enter__(self) -> JobStatus:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            prune(self.folder, self.keep)
        except OSError:
            pass
        self.write()
        self._thread = threading.Thread(target=self._loop, name="cmeval-status", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        with self._lock:
            if exc_type is not None:
                self.data["state"] = "failed"
                self.data["error"] = f"{exc_type.__name__}: {exc}" if str(exc) else exc_type.__name__
            elif self.data["state"] == "running":
                self.data["state"] = "done"
            self.data["ended"] = now()
        self.write()
        return False  # never hide the error

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self.write()

    # ---- updates from the job

    def stage(self, text: str) -> None:
        with self._lock:
            self.data["stage"] = text

    def total(self, n: int, unit: str | None = None) -> None:
        with self._lock:
            if self._session_done == 0:
                self._base = (self.clock(), 0)  # the speed starts with the counted work, not with the setup
            self.data["total"] = n
            if unit is not None:
                self.data["unit"] = unit

    def part(self, name: str, total: int, done: int = 0) -> None:
        with self._lock:
            self.data["parts"][name] = {"done": done, "total": total}

    def already_done(self, n: int) -> None:
        """Units done before this session (a resumed run). They count as done, not in the speed."""
        with self._lock:
            self.data["done"] += n

    def set_done(self, n: int) -> None:
        """Set the done count, for a step that has no count of its own (estimated tokens). Not in the speed."""
        with self._lock:
            self.data["done"] = n

    def advance(self, n: int = 1, part: str | None = None) -> None:
        with self._lock:
            self.data["done"] += n
            if part is not None and part in self.data["parts"]:
                self.data["parts"][part]["done"] += n
            self._session_done += n
            self._samples.append((self.clock(), self._session_done))

    def log(self, message: str) -> None:
        with self._lock:
            self._log.append(message)

    def retries(self, read: Callable[[], int]) -> None:
        """A function that returns the retry count so far, for example lambda: gh.retries."""
        self._read_retries = read

    def result(self, **values: Any) -> None:
        """Final numbers for the list of finished jobs, for example searched=1197."""
        with self._lock:
            self.data["result"].update(values)

    def fail(self, error: str) -> None:
        """Mark the job failed when the caller handles the error itself (the CLI prints it and returns 1)."""
        with self._lock:
            self.data["state"] = "failed"
            self.data["error"] = error

    # ---- writing

    def _speed(self) -> tuple[float | None, float | None]:
        """Units per minute and seconds left, over the last RATE_WINDOW seconds of this session (or less, early on)."""
        t = self.clock()
        while self._samples and t - self._samples[0][0] > RATE_WINDOW:
            self._base = self._samples.popleft()  # the window starts at the newest sample that left it
        base_t, base_done = self._base
        seconds = t - base_t
        if seconds <= 0 or self._session_done <= base_done:
            return None, None
        per_second = (self._session_done - base_done) / seconds
        total = self.data["total"]
        eta = max(0.0, (total - self.data["done"]) / per_second) if total is not None else None
        return per_second * 60, eta

    def write(self) -> None:
        """Write the file now. Errors are ignored: the status must never stop the job."""
        try:
            retries = self._read_retries() if self._read_retries else None
            with self._lock:
                if retries is not None:
                    self.data["retries"] = retries
                rate, eta = self._speed() if self.data["state"] == "running" else (self.data["rate"], None)
                self.data.update(updated=now(), rate=None if rate is None else round(rate, 2),
                                 eta_seconds=None if eta is None else round(eta), log=list(self._log))
                text = json.dumps(self.data, indent=2, ensure_ascii=False, default=str) + "\n"
            write_text_atomic(self.path, text)
        except Exception:  # noqa: BLE001 - a view only; the job goes on
            pass


def read_all(folder: Path | None = None) -> list[dict]:
    """Every status file that can be read, newest start first. A file in the middle of a write is skipped."""
    folder = folder or status_dir()
    jobs = []
    for path in folder.glob("*.json") if folder.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data["file"] = path.name
            jobs.append(data)
    jobs.sort(key=lambda d: str(d.get("started") or ""), reverse=True)
    return jobs


def is_over(job: dict, now: datetime | None = None) -> bool:
    """True if the job will not change again: it ended, its process is gone, or it has not written
    for STALE_SECONDS (killed, or the machine slept). The dashboard and prune use this one rule."""
    if job.get("state") != "running":
        return True
    if not pid_alive(int(job.get("pid") or 0)):
        return True
    try:
        updated = datetime.fromisoformat(job["updated"])
    except (KeyError, TypeError, ValueError):
        return True
    return ((now or datetime.now(timezone.utc)) - updated).total_seconds() > STALE_SECONDS


def prune(folder: Path, keep: int = KEEP_FINISHED) -> None:
    """Delete finished status files beyond the newest `keep`, and old temp files from stopped writes.
    Running jobs are never deleted."""
    over = [job for job in read_all(folder) if is_over(job)]
    for job in over[keep:]:
        (folder / job["file"]).unlink(missing_ok=True)
    for tmp in folder.glob("*.json.tmp"):
        try:
            if time.time() - tmp.stat().st_mtime > TMP_MAX_AGE:
                tmp.unlink()
        except OSError:
            pass
