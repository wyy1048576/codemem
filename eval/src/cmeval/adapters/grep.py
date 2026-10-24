"""The offline grep baseline (Decision 4): ripgrep over keywords from the issue, files ranked by match count.

This is the proposal's grep baseline. It returns files only (granularity "file"). grep_fn.py
adds the step an agent takes next: reading the function around each match.
"""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..retriever import Hit, IndexReport, RetrieverError, stable_hash
from .keywords import MAX_KEYWORDS, STOP_WORDS, extract_keywords

NO_INDEX_KEY = stable_hash({"index": "none"})  # grep needs no index; all grep systems share this key
MAX_COLUMNS = 300  # long lines (minified code) are cut in the hit text, as an agent's grep would show them


def find_rg(path: str | None = None) -> str:
    """The rg binary: a configured path or command name, else rg on PATH."""
    rg = shutil.which(path or "rg") or (path if path and Path(path).is_file() else None)
    if not rg:
        raise RetrieverError(f"ripgrep ({path or 'rg'}) not found; install it: brew install ripgrep")
    return rg


@lru_cache(maxsize=None)
def rg_version(rg: str) -> str:
    out = subprocess.run([rg, "--version"], capture_output=True, text=True)
    return out.stdout.splitlines()[0] if out.stdout else "unknown"


# Flags for every call: ignore the user's ripgrep config (repeatable results), fixed strings,
# ignore case, forward slashes on every OS, no warnings about unreadable files.
_BASE_FLAGS = ["--no-config", "--fixed-strings", "--ignore-case", "--path-separator", "/", "--no-messages", "--null"]


def _run_rg(rg: str, repo: Path, args: list[str]) -> str:
    # stdin=DEVNULL and an explicit path: with no path and a non-terminal stdin, rg searches stdin.
    proc = subprocess.run([rg, *_BASE_FLAGS, *args], cwd=repo, capture_output=True, stdin=subprocess.DEVNULL)
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode == 2 and not out:
        raise RetrieverError(f"rg failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return out  # exit code 1 means no match: empty output


def _patterns(keywords: list[str]) -> list[str]:
    args: list[str] = []
    for kw in keywords:
        args += ["-e", kw]
    return args


def _type_args(types: list[str] | None) -> list[str]:
    """rg file-type filters, for example ["py"] for Python files only."""
    return [arg for t in types or [] for arg in ("--type", t)]


def rg_count(rg: str, repo: Path, keywords: list[str], types: list[str] | None = None) -> dict[str, int]:
    """Matches of any keyword in each file of the repo (respects .gitignore; skips hidden and binary files)."""
    out = _run_rg(rg, repo, ["--count-matches", *_type_args(types), *_patterns(keywords), "--", "."])
    counts: dict[str, int] = {}
    for line in out.splitlines():
        path, _, count = line.partition("\0")
        if count.isdigit():
            counts[path.removeprefix("./")] = int(count)
    return counts


def rg_files(rg: str, repo: Path, keywords: list[str] | None = None, types: list[str] | None = None) -> set[str]:
    """Files that contain any of the keywords; with no keywords, every searchable file."""
    args = ["--files"] if keywords is None else ["--files-with-matches", *_patterns(keywords)]
    out = _run_rg(rg, repo, [*args, *_type_args(types), "--", "."])
    return {path.removeprefix("./") for path in out.split("\0") if path}  # --null: one path per NUL


def preview_line(content: str) -> str:
    """A long line cut as `rg --max-columns MAX_COLUMNS --max-columns-preview` shows it."""
    if len(content.encode("utf-8")) <= MAX_COLUMNS:
        return content
    return content[:MAX_COLUMNS] + " [... omitted end of long line]"


def rg_lines(rg: str, repo: Path, keywords: list[str], paths: list[str], max_count: int | None = None,
             max_columns: int | None = MAX_COLUMNS) -> dict[str, list[tuple[int, str]]]:
    """Matching lines (line number, content) in the given files; long lines cut unless max_columns is None."""
    if not paths:
        return {}
    args = ["--line-number", "--no-heading", "--with-filename"]
    if max_columns is not None:
        args += ["--max-columns", str(max_columns), "--max-columns-preview"]
    if max_count is not None:
        args += ["--max-count", str(max_count)]
    out = _run_rg(rg, repo, [*args, *_patterns(keywords), "--", *paths])
    lines: dict[str, list[tuple[int, str]]] = {}
    for line in out.splitlines():
        path, _, rest = line.partition("\0")
        number, _, content = rest.partition(":")
        if number.isdigit():
            lines.setdefault(path.removeprefix("./"), []).append((int(number), content))
    return lines


def rank_files(counts: dict[str, int]) -> list[tuple[str, int]]:
    """Files by match count, highest first; ties by path."""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def format_lines(path: str, lines: list[tuple[int, str]]) -> str:
    """Lines in `rg -n` form, as an agent would see them."""
    return "\n".join(f"{path}:{number}:{content}" for number, content in lines)


class GrepRetriever:
    granularity = "file"

    def __init__(self, name: str = "grep", max_keywords: int = MAX_KEYWORDS, max_lines: int = 10, rg: str | None = None):
        self.name = name
        self.max_keywords = max_keywords
        self.max_lines = max_lines
        self.rg = find_rg(rg)
        self.repo: Path | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "adapter": "grep",
            "rg": rg_version(self.rg),
            "max_keywords": self.max_keywords,
            "max_lines": self.max_lines,
            "stop_words": len(STOP_WORDS),
        }

    def index_key(self) -> str:
        return NO_INDEX_KEY

    def build(self, repo: Path, index_dir: Path) -> IndexReport:
        self.repo = Path(repo)
        return IndexReport(seconds=0.0)  # grep needs no index: its main advantage for freshness

    def update(self, repo: Path, index_dir: Path) -> IndexReport:
        return self.build(repo, index_dir)

    def _keywords(self, query: str) -> list[str]:
        if self.repo is None:
            raise RetrieverError(f"{self.name}: search before build")
        return extract_keywords(query, self.max_keywords)

    def search(self, query: str, k: int) -> list[Hit]:
        keywords = self._keywords(query)
        if not keywords:
            return []
        counts = rg_count(self.rg, self.repo, keywords)
        ranked = rank_files(counts)[:k]
        lines = rg_lines(self.rg, self.repo, keywords, [path for path, _ in ranked], max_count=self.max_lines)
        hits = [
            Hit(path, score=float(count), text=format_lines(path, lines.get(path, [])), extra={"matches": count})
            for path, count in ranked
        ]
        if hits:
            hits[0].extra["keywords"] = keywords  # once per search, for analysis
        return hits

    def close(self) -> None:
        self.repo = None
