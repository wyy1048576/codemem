"""The plug: the interface every retrieval system implements, and the types it returns.

The runner talks only to this interface. grep, grep-fn, codemem, and any later system are
adapters. Hits are graded by location (path and line range), never by a system's own IDs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

GRANULARITIES = ("file", "line")


class RetrieverError(ValueError):
    """A system returned something that breaks the contract (for example a hit without lines)."""


@dataclass
class Hit:
    path: str  # repo-relative, forward slashes
    start_line: int | None = None  # 1-based, inclusive; None for a file-level hit
    end_line: int | None = None
    symbol: str | None = None  # qualified name, if the system knows it
    score: float = 0.0
    text: str = ""  # exactly what an agent would see for this hit; token metrics count it
    extra: dict[str, Any] = field(default_factory=dict)  # system-specific debug data

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Hit:
        return cls(**data)


@dataclass
class IndexReport:
    seconds: float
    bytes_on_disk: int = 0
    items: int = 0  # chunks, files, or whatever the system indexes
    items_reembedded: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class Retriever(Protocol):
    name: str
    granularity: str  # "file": hits are paths only; "line": hits have line ranges

    def describe(self) -> dict[str, Any]:
        """Everything needed to repeat a run: versions, models, device, settings."""

    def index_key(self) -> str:
        """Hash of the settings that change the index. Systems with the same key share one index."""

    def build(self, repo: Path, index_dir: Path) -> IndexReport:
        """Build a full index of the repo at its current commit."""

    def update(self, repo: Path, index_dir: Path) -> IndexReport:
        """Bring the index up to date after the repo moved. Must give the same results as build."""

    def search(self, query: str, k: int) -> list[Hit]:
        """Best hits first, at most k, on the last built or updated index."""

    def close(self) -> None:
        """Free resources (models, open files)."""


def stable_hash(value: Any) -> str:
    """A short hash of JSON-like data, the same for equal data. Use it for index_key."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def check_hits(hits: list[Hit], granularity: str, k: int, system: str = "system") -> list[Hit]:
    """Check a system's hits against the contract. Returns the hits; raises RetrieverError.

    A "line" system must give line ranges on every hit; a "file" system must not. A missing
    line range would otherwise turn quietly into a file-level hit (Decision 4).
    """
    if granularity not in GRANULARITIES:
        raise RetrieverError(f"{system}: granularity {granularity!r} is not one of {', '.join(GRANULARITIES)}")
    if len(hits) > k:
        raise RetrieverError(f"{system}: returned {len(hits)} hits, more than k={k}")
    for i, hit in enumerate(hits):
        where = f"{system}: hit {i}"
        if not isinstance(hit, Hit):
            raise RetrieverError(f"{where} is a {type(hit).__name__}, not a Hit")
        path = hit.path
        if not (isinstance(path, str) and path and "\\" not in path and not path.startswith(("/", "./"))):
            raise RetrieverError(f"{where}: path {path!r} is not a repo-relative path with forward slashes")
        has_lines = hit.start_line is not None or hit.end_line is not None
        if granularity == "file" and has_lines:
            raise RetrieverError(f"{where}: a file-level system returned line numbers")
        if granularity == "line":
            if not (isinstance(hit.start_line, int) and isinstance(hit.end_line, int)):
                raise RetrieverError(f"{where} ({path}): a line-level system returned a hit without line numbers")
            if not 1 <= hit.start_line <= hit.end_line:
                raise RetrieverError(f"{where} ({path}): needs 1 <= start <= end, got {hit.start_line}..{hit.end_line}")
        if not isinstance(hit.text, str):
            raise RetrieverError(f"{where}: text must be a string")
    return hits
