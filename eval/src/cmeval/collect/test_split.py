"""Split a pull request into the fix (code) and the test change, with the rules of each repo.

The grader of the end-to-end eval applies the agent's change without each file of the test
change, then applies the real test change (e2e.py). So each changed file must be on one side.

The rules, in order:
1. A path that matches one of the repo's `test_paths` globs (collect config) is a test file,
   whatever its extension. Snapshot files, markdown tests and golden files have no known
   language, so the path rules of patches.classify_path call them "other".
2. Else patches.classify_path decides: code, test, or other.
3. Rust code files are read at the base commit and after the fix. A changed line is test code
   when it is inside an item marked `#[cfg(test)]` or `#[test]` (Rust keeps unit tests in the
   source file). A file whose changed lines are all test code is a test file. A file with
   changes in both parts is "mixed": it cannot be on either side, so the task is dropped.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

from tree_sitter import Language, Node, Parser

from ..patches import FILE_CLASSES, FileChange, PatchMismatch, align_file_diff, parse_patch, split_lines


def path_matches(path: str, pattern: str) -> bool:
    """The glob rule of recipe `test_files` (generate.py): `*` also crosses "/", and `a/**/b`
    also matches `a/b`."""
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern.replace("/**/", "/"))


# Attributes that mark test-only code. Not `cfg(any(test, ...))`: that code is also built
# outside tests.
_TEST_ATTRIBUTE = re.compile(
    r"^#!?\[(cfg\((all\()?test[,)]|test\]|tokio::test\b|test_case\b|test_case::test_case\b|rstest\b)")
_ATTRIBUTES = ("attribute_item", "inner_attribute_item")
_SKIPPED = ("line_comment", "block_comment", "attribute_item")


@lru_cache(maxsize=1)
def _rust_parser() -> Parser:
    import tree_sitter_rust

    return Parser(Language(tree_sitter_rust.language()))


def _end_line(node: Node) -> int:
    row, col = node.end_point
    return row if col == 0 and row > node.start_point[0] else row + 1


def _is_test_attribute(node: Node) -> bool:
    return bool(_TEST_ATTRIBUTE.match(re.sub(r"\s+", "", node.text.decode("utf-8", "replace"))))


def rust_test_lines(source: str) -> set[int]:
    """The 1-based lines of a Rust file that are test code: each item with a test attribute,
    from its first attribute line to its last line. A file with `#![cfg(test)]` is all test code."""
    root = _rust_parser().parse(source.encode("utf-8")).root_node
    n_lines = len(split_lines(source))
    lines: set[int] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        children = node.children
        for i, child in enumerate(children):
            if child.type == "inner_attribute_item" and _is_test_attribute(child):
                if node is root:
                    return set(range(1, n_lines + 1))
                lines.update(range(node.start_point[0] + 1, _end_line(node) + 1))
            elif child.type == "attribute_item" and _is_test_attribute(child):
                item = next((c for c in children[i + 1:] if c.type not in _SKIPPED), None)
                end = _end_line(item) if item is not None else _end_line(child)
                lines.update(range(child.start_point[0] + 1, end + 1))
            elif child.named_child_count:
                stack.append(child)
    return lines


def rust_change_kind(change: FileChange, base_text: str | None) -> str:
    """code, test, or mixed, for one changed Rust file. Blank lines do not count. A diff that does
    not fit the base text is code: the `applies` step drops it later."""
    try:
        applied = align_file_diff(base_text, change.diff)
    except (PatchMismatch, ValueError):
        return "code"
    base_lines = split_lines(base_text or "")
    new_text = applied.new_text if change.status != "deleted" else ""
    new_lines = split_lines(new_text)
    base_test = rust_test_lines(base_text) if base_text else set()
    new_test = rust_test_lines(new_text) if new_text else set()
    kinds = set()
    for line in applied.changed:
        if 1 <= line <= len(base_lines) and base_lines[line - 1].strip():
            kinds.add(line in base_test)
    for line in applied.added_lines:
        if 1 <= line <= len(new_lines) and new_lines[line - 1].strip():
            kinds.add(line in new_test)
    if kinds == {True}:
        return "test"
    return "mixed" if kinds == {True, False} else "code"


@dataclass
class Split:
    parts: dict[str, str]  # the diff text for each file class, as patches.split_patch gives
    moved: list[str] = field(default_factory=list)  # Rust code files whose changes are all test code
    mixed: list[str] = field(default_factory=list)  # Rust files with changes in code and test code


def split_for_repo(patch: str, test_paths: list[str], read_base: Callable[[str], str | None]) -> Split:
    """The diff of a pull request cut into code, test and other parts with the rules above.
    read_base(path) gives a file's text at the base commit, or None."""
    split = Split({name: "" for name in FILE_CLASSES})
    for change in parse_patch(patch):
        file_class = change.file_class
        paths = [p for p in (change.old_path, change.new_path) if p]
        if file_class != "test" and any(path_matches(p, g) for p in paths for g in test_paths):
            if change.diff and "GIT binary patch" not in change.diff and "Binary files " not in change.diff:
                file_class = "test"
        elif file_class == "code" and change.language == "rust":
            kind = rust_change_kind(change, read_base(change.old_path) if change.old_path else None)
            if kind == "test":
                file_class = "test"
                split.moved.append(change.path)
            elif kind == "mixed":
                split.mixed.append(change.path)
        split.parts[file_class] += change.diff
    return split
