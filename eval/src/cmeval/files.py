"""Small file helpers shared by the runner and the scorer."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_text_atomic(path: Path, text: str) -> None:
    """Write to a temp file, then rename: a stopped process never leaves a half-written file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def write_json(path: Path, data: dict) -> None:
    write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


def append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        f.flush()


def drop_unfinished_line(path: Path) -> bool:
    """Cut a last line that has no newline (a write stopped by a power loss). True if cut.

    append_jsonl writes each line and its newline in one write, so a line without a newline
    was never finished. The runner does that task again.
    """
    if not path.exists() or path.stat().st_size == 0:
        return False
    with path.open("r+b") as f:
        f.seek(-1, os.SEEK_END)
        if f.read(1) == b"\n":
            return False  # the normal case: only the last byte is read
        data = path.read_bytes()
        f.truncate(data.rfind(b"\n") + 1)
    return True


class FileLock:
    """An exclusive lock on a file, so two processes never work on one run at the same time.

    The OS releases the lock when the process ends, also after kill -9 or a crash, so a stopped
    run can always be resumed.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fh = None

    def acquire(self) -> bool:
        """True if this process now holds the lock; False if another process holds it."""
        fh = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None


def read_jsonl(path: Path) -> list[dict]:
    """Rows of a JSON-lines file ([] if missing). A bad line raises ValueError naming the file and line."""
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{number}: not valid JSON ({exc.msg})") from None
    return rows
