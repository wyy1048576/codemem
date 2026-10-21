"""Chunk dataclass and ID helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

KINDS = ("function", "method", "file_header")
FILE_HEADER_QUALNAME = "<module>"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def make_key(path: str, qualname: str) -> str:
    return f"{path}::{qualname}"


@dataclass
class Chunk:
    key: str  # stable: path::qualname, with #2, #3 ... on duplicates
    path: str  # repo-relative, forward slashes
    qualname: str  # e.g. SessionManager.expire_old
    name: str
    kind: str  # function | method | file_header
    start_line: int  # 1-based, inclusive
    end_line: int
    signature: str
    docstring: str
    code: str
    content_hash: str
    class_name: str | None = None
    calls: list[str] = field(default_factory=list)  # callee names (unresolved)
    chunk_id: int | None = None  # assigned by the store

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"
