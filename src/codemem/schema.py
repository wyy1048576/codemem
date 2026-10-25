"""Chunk dataclass and ID helpers.

A chunk is the unit codemem retrieves: a function or method, a class, or a block of top-level
code. `docs/data-model.md` describes every field and the rules for keys, lines and hashes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

KINDS = ("function", "method", "class", "block")
CALLABLE_KINDS = ("function", "method", "class")  # kinds a call can resolve to
BLOCK_QUALNAME = "<block>"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def make_key(path: str, qualname: str) -> str:
    return f"{path}::{qualname}"


@dataclass
class Chunk:
    key: str  # stable: path::qualname, with #2, #3 ... on duplicates; blocks: path::<block>@<hash8>
    path: str  # repo-relative, forward slashes
    qualname: str  # e.g. SessionManager.expire_old; scopes joined by "."
    name: str  # blocks: a short label such as "imports" or "MAX_AGE"
    kind: str  # function | method | class | block
    start_line: int  # 1-based, inclusive; decorators/annotations/export/template included
    end_line: int
    signature: str
    docstring: str  # Python docstring, or the doc comment right above the definition
    code: str  # the exact source lines start_line..end_line
    content_hash: str  # text_hash(code)
    class_name: str | None = None  # innermost enclosing class (or receiver / impl type)
    calls: list[str] = field(default_factory=list)  # callee names (unresolved), first-occurrence order
    chunk_id: int | None = None  # assigned by the store
    language: str = "python"
    subkind: str = ""  # struct, interface, enum, trait, macro, constructor, arrow, imports, ...
    parent_key: str | None = None  # key of the enclosing chunk (class or function), if any
    is_test: bool = False
    skeleton: str = ""  # classes only: header + member signatures (embedded instead of the full code)
    call_lines: list[int] = field(default_factory=list)  # line of the first call of each name in `calls`
    lead_comment: str = ""  # Python: the comment lines directly above (other languages keep them in docstring)

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"
