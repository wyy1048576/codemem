"""Call-graph resolution: baseline name-matching heuristic.

Kept isolated so import/scope-aware resolution can replace it later without
touching the store or text builders.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath

_TEST_DIRS = {"tests", "test", "testing"}
_TEST_FILE = re.compile(r"^(test_.*|.*_test|conftest)\.py$")


def is_test_path(path: str) -> bool:
    """A Python-only heuristic, for Refs built without an `is_test` flag. Chunks carry their own
    language-aware `is_test` (see `LanguageSpec.is_test_path`)."""
    p = PurePosixPath(path)
    return bool(_TEST_FILE.match(p.name)) or any(part in _TEST_DIRS for part in p.parts[:-1])


def is_test_caller(path: str, name: str) -> bool:
    return is_test_path(path) or name.startswith("test_") or name == "test"


def resolve_edges(
    definitions: Iterable[Sequence],
    calls: Iterable[Sequence],
    max_defs_per_name: int,
) -> set[tuple[int, int]]:
    """Link each call to every chunk defining that name.

    definitions: (chunk_id, name) or (chunk_id, name, family) for functions/methods/classes.
    calls: (caller_id, callee_name) or (caller_id, callee_name, family).
    A family groups languages that can call each other (c with cpp, javascript with typescript);
    a call only links within its family. Names defined more than `max_defs_per_name` times are
    ignored (get/run/...); self-recursion is dropped.
    """
    by_name: dict[tuple[str, str], list[int]] = defaultdict(list)
    for chunk_id, name, *family in definitions:
        by_name[(family[0] if family else "", name)].append(chunk_id)
    edges: set[tuple[int, int]] = set()
    for caller_id, callee, *family in calls:
        targets = by_name.get((family[0] if family else "", callee))
        if not targets or len(targets) > max_defs_per_name:
            continue
        edges.update((caller_id, t) for t in targets if t != caller_id)
    return edges
