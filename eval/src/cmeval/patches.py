"""Read a unified diff: which base-side lines each file change touches, and what kind of file it is.

Line numbers are on the base side (the code before the fix), because that is the code the
systems index and search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from unidiff import PatchSet

FILE_CLASSES = ("code", "test", "other")

LANGUAGE_BY_EXT = {
    ".py": "python", ".pyi": "python",
    ".go": "go",
    ".c": "c", ".h": "c",
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".java": "java",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".rs": "rust",
    ".rb": "ruby", ".php": "php", ".kt": "kotlin", ".scala": "scala", ".cs": "csharp", ".swift": "swift",
}  # fmt: skip

TEST_DIRS = {"test", "tests", "testing", "testdata", "__tests__", "spec", "specs"}

# File-name patterns that mark a test file, for each language.
TEST_NAME_PATTERNS = {
    "python": [r"^test_.*\.pyi?$", r"^.*_test\.py$", r"^conftest\.py$"],
    "go": [r"^.*_test\.go$"],
    "c": [r"^test_.*\.[ch]$", r"^.*_test\.[ch]$"],
    "cpp": [r"^test_.*", r"^.*_test\.\w+$", r"^.*_unittest\.\w+$"],
    "java": [r"^.*Tests?\.java$", r"^.*IT\.java$"],
    "typescript": [r"^.*\.(test|spec)\.tsx?$"],
    "javascript": [r"^.*\.(test|spec)\.[mc]?jsx?$"],
    "rust": [r"^.*_test\.rs$"],
    "ruby": [r"^.*_(test|spec)\.rb$"],
    "php": [r"^.*Test\.php$"],
    "kotlin": [r"^.*Tests?\.kt$"],
    "scala": [r"^.*(Test|Spec|Suite)\.scala$"],
    "csharp": [r"^.*Tests?\.cs$"],
    "swift": [r"^.*Tests?\.swift$"],
}
_TEST_NAME_RE = {lang: [re.compile(p) for p in pats] for lang, pats in TEST_NAME_PATTERNS.items()}


@dataclass
class FileChange:
    old_path: str | None  # None for an added file
    new_path: str | None  # None for a deleted file
    status: str  # modified | added | deleted | renamed
    file_class: str  # code | test | other
    language: str | None
    changed: list[int] = field(default_factory=list)  # base lines removed or modified
    insert_after: list[int] = field(default_factory=list)  # pure insertions between base line L and L+1
    added: int = 0
    removed: int = 0

    @property
    def path(self) -> str:
        """The base-side path, or the new path for an added file."""
        return self.old_path or self.new_path  # type: ignore[return-value]


def classify_path(path: str) -> tuple[str, str | None]:
    """(file class, language) for a repo-relative path. Class is code, test, or other."""
    p = PurePosixPath(path)
    language = LANGUAGE_BY_EXT.get(p.suffix.lower())
    if language is None:
        return "other", None
    if any(part.lower() in TEST_DIRS for part in p.parts[:-1]):
        return "test", language
    if any(rx.match(p.name) for rx in _TEST_NAME_RE.get(language, [])):
        return "test", language
    return "code", language


def _strip_prefix(name: str, prefix: str) -> str | None:
    if name == "/dev/null":
        return None
    return name[len(prefix):] if name.startswith(prefix) else name


def _touched_lines(patched_file) -> tuple[list[int], list[int]]:
    """Base-side changed lines and pure-insertion points for one file."""
    changed: set[int] = set()
    insert_after: set[int] = set()
    for hunk in patched_file:
        # Last base line seen. A hunk with no base lines (-U0 insertion, new file) inserts after source_start.
        last_base = hunk.source_start if hunk.source_length == 0 else hunk.source_start - 1
        prev_type = None
        for line in hunk:
            if line.is_removed:
                changed.add(line.source_line_no)
                last_base = line.source_line_no
            elif line.is_context:
                last_base = line.source_line_no
            elif line.is_added and prev_type not in ("-", "+"):
                # An added run that does not follow removed lines is a pure insertion.
                # Added lines after removed lines are part of that modification.
                insert_after.add(last_base)
            if line.line_type in ("-", "+", " "):  # skip "\ No newline at end of file"
                prev_type = line.line_type
    return sorted(changed), sorted(insert_after)


def _file_change(pf) -> FileChange:
    old = _strip_prefix(pf.source_file, "a/")
    new = _strip_prefix(pf.target_file, "b/")
    if pf.is_added_file:
        status, old = "added", None
    elif pf.is_removed_file:
        status, new = "deleted", None
    elif pf.is_rename:
        status = "renamed"
    else:
        status = "modified"
    file_class, language = classify_path(old or new)
    if pf.is_binary_file:
        file_class = "other"
    changed, insert_after = ([], []) if status == "added" else _touched_lines(pf)
    return FileChange(
        old_path=old,
        new_path=new,
        status=status,
        file_class=file_class,
        language=language,
        changed=changed,
        insert_after=insert_after,
        added=pf.added,
        removed=pf.removed,
    )


def parse_patch(text: str) -> list[FileChange]:
    """One FileChange for each file in a unified diff (git format, a/ and b/ prefixes)."""
    return [_file_change(pf) for pf in PatchSet(text)]


def split_patch(text: str) -> dict[str, str]:
    """The diff text for each file class. Each file appears in exactly one part, with its text unchanged."""
    parts = {name: "" for name in FILE_CLASSES}
    for pf in PatchSet(text):
        parts[_file_change(pf).file_class] += str(pf)
    return parts
