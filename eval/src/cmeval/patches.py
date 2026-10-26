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
    ".pyx": "cython", ".pxd": "cython",  # pandas, ray: code fixes that codemem cannot read yet
    ".go": "go",
    ".c": "c", ".h": "c",
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".c++": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".h++": "cpp", ".inl": "cpp", ".ipp": "cpp", ".tpp": "cpp", ".cu": "cpp", ".cuh": "cpp",  # as codemem
    # GPU kernels and web UI code (llama.cpp): code fixes that the labeler cannot read
    ".cl": "opencl", ".comp": "glsl", ".glsl": "glsl", ".wgsl": "wgsl", ".metal": "metal", ".svelte": "svelte",
    ".java": "java",
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript", ".tsx": "tsx",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".rs": "rust",
    ".rb": "ruby", ".php": "php", ".kt": "kotlin", ".scala": "scala", ".cs": "csharp", ".swift": "swift",
}  # fmt: skip

# Directories that hold tests anywhere in a path.
TEST_DIRS = {"tests", "testdata", "__tests__", "spec", "specs"}
# Directories that hold tests only at the repo top or under src/. Elsewhere they are often library
# code that a fix can change: django/test/, sympy/testing/, numpy/testing/.
TOP_TEST_DIRS = {"test", "testing"}
# In TypeScript code they hold tests at any depth (vscode: src/vs/**/test/, extensions/*/test/).
ANY_DEPTH_TEST_DIRS = {"typescript": TOP_TEST_DIRS, "tsx": TOP_TEST_DIRS}
# Product code in a folder named test: playwright's MCP test tools.
CODE_DIRS_NAMED_TEST = ("packages/playwright/src/mcp/test/",)

# File-name patterns that mark a test file, for each language.
TEST_NAME_PATTERNS = {
    "python": [r"^test_.*\.pyi?$", r"^.*_test\.py$", r"^conftest\.py$"],
    "go": [r"^.*_test\.go$"],
    "c": [r"^test_.*\.[ch]$", r"^.*_test\.[ch]$"],
    "cpp": [r"^test_.*", r"^.*_test\.\w+$", r"^.*_unittest\.\w+$"],
    "java": [r"^.*Tests?\.java$", r"^.*IT\.java$"],
    "typescript": [r"^.*\.(test|spec)\.[mc]?ts$"],
    "tsx": [r"^.*\.(test|spec)\.tsx$"],
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
    # Base lines as stated in the diff. labels.py uses align_file_diff, which also handles
    # diffs whose line numbers are off from the base file.
    changed: list[int] = field(default_factory=list)  # base lines removed or modified
    insert_after: list[int] = field(default_factory=list)  # pure insertions between base line L and L+1
    added: int = 0
    removed: int = 0
    diff: str = field(default="", repr=False)  # this file's part of the diff, unchanged

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
    dirs = [part.lower() for part in p.parts[:-1]]
    if any(d in TEST_DIRS for d in dirs):
        return "test", language
    if any(d in TOP_TEST_DIRS and (i == 0 or dirs[i - 1] == "src") for i, d in enumerate(dirs)):
        return "test", language
    if any(d in ANY_DEPTH_TEST_DIRS.get(language, ()) for d in dirs) and not path.startswith(CODE_DIRS_NAMED_TEST):
        return "test", language
    if any(rx.match(p.name) for rx in _TEST_NAME_RE.get(language, [])):
        return "test", language
    return "code", language


def _strip_prefix(name: str, prefix: str) -> str | None:
    if name == "/dev/null":
        return None
    return name[len(prefix):] if name.startswith(prefix) else name


def _touched_lines(patched_file, offsets: list[int] | None = None) -> tuple[list[int], list[int]]:
    """Base-side changed lines and pure-insertion points for one file.

    offsets (one per hunk) move each hunk from the line numbers stated in the diff to where it
    really applies in the base file.
    """
    changed: set[int] = set()
    insert_after: set[int] = set()
    for i, hunk in enumerate(patched_file):
        shift = offsets[i] if offsets else 0
        # Last base line seen. A hunk with no base lines (-U0 insertion, new file) inserts after source_start.
        last_base = (hunk.source_start if hunk.source_length == 0 else hunk.source_start - 1) + shift
        prev_type = None
        for line in hunk:
            if line.is_removed:
                changed.add(line.source_line_no + shift)
                last_base = line.source_line_no + shift
            elif line.is_context:
                last_base = line.source_line_no + shift
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
        diff=str(pf),
    )


def parse_patch(text: str) -> list[FileChange]:
    """One FileChange for each file in a unified diff (git format, a/ and b/ prefixes)."""
    return [_file_change(pf) for pf in PatchSet(text)]


def split_patch(text: str) -> dict[str, str]:
    """The diff text for each file class. Each file appears in exactly one part, with its text unchanged."""
    parts = {name: "" for name in FILE_CLASSES}
    for change in parse_patch(text):
        parts[change.file_class] += change.diff
    return parts


class PatchMismatch(ValueError):
    """A diff does not fit the base text: its context or removed lines differ from the base."""


def _strip_eol(line: str) -> str:
    return line.rstrip("\r\n")


def split_lines(text: str) -> list[str]:
    """Lines with their endings, split on "\\n" only, the way git, unidiff, and tree-sitter count.

    str.splitlines also splits on form feeds, vertical tabs, and other characters, which would
    shift line numbers in files that contain them.
    """
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:  # a last line without a final newline
        lines.append(parts[-1])
    return lines


@dataclass
class AppliedDiff:
    new_text: str  # the file after the fix
    changed: list[int]  # base lines, where the hunks really apply
    insert_after: list[int]
    offsets: list[int]  # for each hunk: real start minus the start stated in the diff
    added_lines: list[int] = field(default_factory=list)  # lines of the new file that the diff adds


def _find_hunk(base: list[str], want: list[str], stated: int, lowest: int) -> int | None:
    """Index where the hunk's base lines match exactly: the stated index if it matches, else the nearest one."""
    if not want:  # a hunk with no base lines (-U0 insertion) has nothing to match
        return stated if lowest <= stated <= len(base) else None
    highest = len(base) - len(want)
    for distance in range(0, max(stated - lowest, highest - stated, 0) + 1):
        for start in (stated - distance, stated + distance) if distance else (stated,):
            if lowest <= start <= highest and base[start : start + len(want)] == want:
                return start
    return None


def align_file_diff(base_text: str | None, diff_text: str) -> AppliedDiff:
    """Apply a one-file diff to its base text the way `git apply` does, and find the real lines.

    Each hunk applies where its context and removed lines equal the base lines exactly (no
    fuzz). The stated line numbers are tried first; if the base moved (some SWE-bench patches
    are off by a few lines), the nearest exact match is used. No exact match anywhere raises
    PatchMismatch, so a diff that does not belong to this base can never be labeled.
    None as base_text means the file is new.
    """
    files = list(PatchSet(diff_text))
    if len(files) != 1:
        raise ValueError(f"expected a diff for one file, got {len(files)}")
    pf = files[0]
    base = split_lines(base_text) if base_text else []
    base_stripped = [_strip_eol(line) for line in base]
    out: list[str] = []
    offsets: list[int] = []
    added_lines: list[int] = []
    pos = 0  # index of the next base line to copy
    for hunk in pf:
        want = [_strip_eol(line.value) for line in hunk if line.is_context or line.is_removed]
        stated = hunk.source_start if hunk.source_length == 0 else hunk.source_start - 1
        start = _find_hunk(base_stripped, want, stated, pos)
        if start is None:
            first = want[0] if want else ""
            raise PatchMismatch(
                f"{pf.path}: hunk at base line {hunk.source_start} matches nowhere in the base file "
                f"(first expected line {first!r})"
            )
        offsets.append(start - stated)
        out.extend(base[pos:start])
        pos = start
        for line in hunk:
            if line.is_context:
                out.append(base[pos])
                pos += 1
            elif line.is_removed:
                pos += 1
            elif line.is_added:
                out.append(line.value)
                added_lines.append(len(out))
    out.extend(base[pos:])
    changed, insert_after = _touched_lines(pf, offsets)
    return AppliedDiff("".join(out), changed, insert_after, offsets, added_lines)


def apply_file_diff(base_text: str | None, diff_text: str) -> str:
    """The file after the fix. See align_file_diff."""
    return align_file_diff(base_text, diff_text).new_text
