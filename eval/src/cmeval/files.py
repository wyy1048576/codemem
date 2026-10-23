"""Small file helpers shared by the runner and the scorer."""

from __future__ import annotations

import hashlib
import json
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
    if not path.exists():
        return False
    data = path.read_bytes()
    if not data or data.endswith(b"\n"):
        return False
    with path.open("r+b") as f:
        f.truncate(data.rfind(b"\n") + 1)
    return True


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
