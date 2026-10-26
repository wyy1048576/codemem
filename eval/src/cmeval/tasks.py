"""Task schema (the answer key), validation, load and save, and dev/test split assignment.

A task is one issue (the query), one repo snapshot (base_commit), and the gold answer: the
files, classes, and functions that the real fix changed. Task files are JSON lines, one task
for each line, in eval/tasks/<set>.jsonl.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import MISSING, asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SOURCES = ("swebench_verified", "fresh", "locbench")
SPLITS = ("dev", "test")
MERGE_TYPES = ("squash", "merge", "rebase")
DEFAULT_SPLIT_SEED = "cmeval-split-1"
DEV_PERCENT = 20

# Known tags and their types. A known tag can also be None (not computed yet).
# Other tags are allowed, so an experiment can add its own tags without a schema change.
KNOWN_TAGS: dict[str, type] = {
    "identifier_in_query": bool,
    "n_gold_files": int,
    "n_gold_classes": int,
    "n_gold_functions": int,
    "module_level_change": bool,
    "has_test_patch": bool,
    "body_edited_after_fix": bool,
    "query_tokens": int,
    "partial_labels": bool,  # a gold code file could not be labeled below file level
    "hunks_moved": int,  # diff hunks that apply at a different line than the diff states
}

_ID_RE = re.compile(r"^(?P<owner>[A-Za-z0-9-]+)__(?P<name>[A-Za-z0-9_.-]+)-(?P<number>\d+)$")
_REPO_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9_.-]+$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class TaskError(ValueError):
    """A task or a task file is not valid. `problems` lists every problem found."""

    def __init__(self, problems: list[str] | str):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("\n".join(self.problems))


@dataclass
class Span:
    path: str  # repo-relative, forward slashes
    start: int  # 1-based, inclusive
    end: int
    symbol: str | None = None  # dotted name, for example SessionManager.revoke_session


@dataclass
class Issue:
    number: int | None = None
    url: str | None = None
    created_at: str | None = None  # ISO 8601


@dataclass
class Fix:
    pr_number: int | None = None
    url: str | None = None
    merged_at: str | None = None  # ISO 8601
    merge_type: str | None = None  # squash | merge | rebase; None for imported tasks


@dataclass
class Gold:
    files: list[str] = field(default_factory=list)
    classes: list[Span] = field(default_factory=list)
    functions: list[Span] = field(default_factory=list)
    lines: list[Span] = field(default_factory=list)  # changed lines, base side


@dataclass
class Unretrievable:
    """Code the patch adds. It does not exist at base_commit, so no system can find it."""

    files: list[str] = field(default_factory=list)
    classes: list[Span] = field(default_factory=list)
    functions: list[Span] = field(default_factory=list)


@dataclass(kw_only=True)
class Task:
    schema: int = SCHEMA_VERSION
    id: str  # <owner>__<repo>-<pr_number>, like SWE-bench instance_id
    source: str
    split: str
    repo: str  # owner/name
    base_commit: str
    language: str
    query: str  # issue title and body as of before the fix; never comments
    hints: str | None = None  # comments from before the fix PR; not used in the main eval
    issue: Issue = field(default_factory=Issue)
    fix: Fix = field(default_factory=Fix)
    patch: str  # unified diff, code files only
    test_patch: str | None = None
    gold: Gold
    unretrievable: Unretrievable = field(default_factory=Unretrievable)
    tags: dict[str, Any] = field(default_factory=dict)
    labeler: str | None = None  # version of the labeling rules

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> Task:
        task = _build(cls, data, "task")
        task.issue = _build(Issue, task.issue, "issue")
        task.fix = _build(Fix, task.fix, "fix")
        task.gold = _build_with_spans(Gold, task.gold, "gold")
        task.unretrievable = _build_with_spans(Unretrievable, task.unretrievable, "unretrievable")
        return task


def _build(cls, data: Any, where: str):
    """Build a dataclass from a dict. Unknown or missing fields are errors, so typos fail loudly."""
    if isinstance(data, cls):
        return data
    if not isinstance(data, dict):
        raise TaskError(f"{where}: must be a JSON object")
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise TaskError(f"{where}: unknown fields: {', '.join(unknown)}")
    required = [f.name for f in fields(cls) if f.default is MISSING and f.default_factory is MISSING]
    missing = [name for name in required if name not in data]
    if missing:
        raise TaskError(f"{where}: missing fields: {', '.join(missing)}")
    return cls(**data)


def _build_with_spans(cls, data: Any, where: str):
    obj = _build(cls, data, where)
    for f in fields(cls):
        if f.name == "files":
            continue
        items = getattr(obj, f.name)
        if not isinstance(items, list):
            raise TaskError(f"{where}.{f.name}: must be a list")
        setattr(obj, f.name, [_build(Span, s, f"{where}.{f.name}[{i}]") for i, s in enumerate(items)])
    return obj


# ---- validation


def validate(task: Task) -> list[str]:
    """Return every problem with the task. An empty list means the task is valid."""
    problems: list[str] = []
    add = problems.append

    if task.schema != SCHEMA_VERSION:
        add(f"schema is {task.schema!r}, expected {SCHEMA_VERSION}")
    match = _ID_RE.match(task.id) if isinstance(task.id, str) else None
    if not match:
        add(f"id {task.id!r} is not <owner>__<repo>-<number>")
    if task.source not in SOURCES:
        add(f"source {task.source!r} is not one of {', '.join(SOURCES)}")
    if task.split not in SPLITS:
        add(f"split {task.split!r} is not one of {', '.join(SPLITS)}")
    if not (isinstance(task.repo, str) and _REPO_RE.match(task.repo)):
        add(f"repo {task.repo!r} is not owner/name")
    elif match and f"{match['owner']}/{match['name']}" != task.repo:
        add(f"id {task.id!r} does not match repo {task.repo!r}")
    if not (isinstance(task.base_commit, str) and _SHA_RE.match(task.base_commit)):
        add(f"base_commit {task.base_commit!r} is not a 40-character lowercase hex sha")
    if not (isinstance(task.language, str) and task.language and task.language == task.language.lower()):
        add(f"language {task.language!r} must be a non-empty lowercase name")
    if not (isinstance(task.query, str) and task.query.strip()):
        add("query is empty")
    if not (isinstance(task.patch, str) and task.patch.strip()):
        add("patch is empty")
    for name in ("hints", "test_patch", "labeler"):
        if getattr(task, name) is not None and not isinstance(getattr(task, name), str):
            add(f"{name} must be a string or null")

    _check_optional_int(task.issue.number, "issue.number", add)
    _check_date(task.issue.created_at, "issue.created_at", add)
    _check_optional_int(task.fix.pr_number, "fix.pr_number", add)
    _check_date(task.fix.merged_at, "fix.merged_at", add)
    if task.fix.merge_type is not None and task.fix.merge_type not in MERGE_TYPES:
        add(f"fix.merge_type {task.fix.merge_type!r} is not one of {', '.join(MERGE_TYPES)}")
    if match and isinstance(task.fix.pr_number, int) and task.fix.pr_number != int(match["number"]):
        add(f"id {task.id!r} does not match fix.pr_number {task.fix.pr_number}")

    gold_files = _check_files(task.gold.files, "gold.files", add)
    if not gold_files:
        add("gold.files is empty")
    for level in ("classes", "functions", "lines"):
        for i, span in enumerate(getattr(task.gold, level)):
            where = f"gold.{level}[{i}]"
            _check_span(span, where, add)
            if isinstance(span.path, str) and span.path not in gold_files:
                add(f"{where}: path {span.path!r} is not in gold.files")
    _check_files(task.unretrievable.files, "unretrievable.files", add)
    for level in ("classes", "functions"):
        for i, span in enumerate(getattr(task.unretrievable, level)):
            _check_span(span, f"unretrievable.{level}[{i}]", add)

    if not isinstance(task.tags, dict):
        add("tags must be an object")
    else:
        for name, expected in KNOWN_TAGS.items():
            value = task.tags.get(name)
            if value is not None and not _is_type(value, expected):
                add(f"tags.{name} must be {expected.__name__} or null, got {value!r}")
    return problems


def _is_type(value: Any, expected: type) -> bool:
    # bool is a subclass of int in Python; a count must not be True or False.
    if expected is int and isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _check_optional_int(value: Any, where: str, add) -> None:
    if value is not None and not _is_type(value, int):
        add(f"{where} must be an integer or null")


def _check_date(value: Any, where: str, add) -> None:
    if value is None:
        return
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError):
        add(f"{where} {value!r} is not an ISO 8601 date")


def _valid_path(path: Any) -> bool:
    return (
        isinstance(path, str)
        and bool(path)
        and "\\" not in path
        and not path.startswith(("/", "./"))
        and ".." not in path.split("/")
    )


def _check_files(files: Any, where: str, add) -> set[str]:
    if not isinstance(files, list):
        add(f"{where} must be a list")
        return set()
    seen: set[str] = set()
    for path in files:
        if not _valid_path(path):
            add(f"{where}: {path!r} is not a repo-relative path with forward slashes")
        elif path in seen:
            add(f"{where}: {path!r} is listed twice")
        else:
            seen.add(path)
    return seen


def _check_span(span: Span, where: str, add) -> None:
    if not _valid_path(span.path):
        add(f"{where}: path {span.path!r} is not a repo-relative path with forward slashes")
    if not (_is_type(span.start, int) and _is_type(span.end, int)):
        add(f"{where}: start and end must be integers")
    elif not 1 <= span.start <= span.end:
        add(f"{where}: needs 1 <= start <= end, got {span.start}..{span.end}")
    if span.symbol is not None and not (isinstance(span.symbol, str) and span.symbol):
        add(f"{where}: symbol must be a non-empty string or null")


# ---- load and save


def dumps(task: Task) -> str:
    return json.dumps(task.to_dict(), ensure_ascii=False)


def load_tasks(path: Path | str) -> list[Task]:
    """Read a task file. Raises TaskError with every problem in the file, by line number."""
    path = Path(path)
    tasks: list[Task] = []
    problems: list[str] = []
    first_line: dict[str, int] = {}
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            where = f"{path.name}:{lineno}"
            try:
                task = Task.from_dict(json.loads(line))
            except json.JSONDecodeError as exc:
                problems.append(f"{where}: invalid JSON ({exc.msg})")
                continue
            except TaskError as exc:
                problems.extend(f"{where}: {p}" for p in exc.problems)
                continue
            problems.extend(f"{where} ({task.id}): {p}" for p in validate(task))
            if not isinstance(task.id, str):
                pass  # validate already reported it; a non-string id cannot be checked for duplicates
            elif task.id in first_line:
                problems.append(f"{where}: duplicate id {task.id!r} (first on line {first_line[task.id]})")
            else:
                first_line[task.id] = lineno
            tasks.append(task)
    if problems:
        raise TaskError(problems)
    return tasks


def save_tasks(path: Path | str, tasks: Iterable[Task]) -> None:
    """Validate, then write all tasks. A temp file and a rename mean a crash never leaves a half file."""
    path = Path(path)
    tasks = list(tasks)
    problems: list[str] = []
    seen: set[str] = set()
    for i, task in enumerate(tasks):
        problems.extend(f"task {i} ({task.id}): {p}" for p in validate(task))
        if isinstance(task.id, str):
            if task.id in seen:
                problems.append(f"task {i}: duplicate id {task.id!r}")
            seen.add(task.id)
    if problems:
        raise TaskError(problems)

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        # newline="\n": the same bytes on Windows, macOS, and Linux.
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            for task in tasks:
                f.write(dumps(task) + "\n")
        os.chmod(tmp, 0o644)  # mkstemp makes the file private; a task file is shared data
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---- queries


_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def clean_query(text: str | None) -> str:
    """Remove hidden HTML comments (for example issue template instructions) and outer whitespace.

    Everything a person sees on the issue page stays, including code blocks and stack traces.
    """
    return _HTML_COMMENT_RE.sub("", text or "").strip()


# ---- splits


def assign_split(task_id: str, seed: str = DEFAULT_SPLIT_SEED, dev_percent: int = DEV_PERCENT) -> str:
    """Dev or test for a fresh task, from a hash of its ID.

    The same ID always gets the same split, and adding tasks never moves old ones.
    """
    digest = hashlib.sha256(f"{seed}:{task_id}".encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    return "dev" if bucket < dev_percent else "test"


def select(tasks: Iterable[Task], split: str | None) -> list[Task]:
    """Tasks in one split. None means all tasks."""
    if split is not None and split not in SPLITS:
        raise ValueError(f"split must be one of {', '.join(SPLITS)} or None, got {split!r}")
    return [t for t in tasks if split is None or t.split == split]


# ---- task filters (KEY=VALUE), shared by `cmeval report --where` and `cmeval subset --where`


class WhereError(ValueError):
    """A task filter is not KEY=VALUE, or names a key that no task has."""


def parse_where(conditions: list[str] | None) -> list[tuple[str, object]]:
    """["gold_all_python=true", "repo=pandas-dev/pandas"] -> [(key, value)]. true/false and whole
    numbers are typed; any other value is text and compared without case."""
    out = []
    for condition in conditions or []:
        key, sep, raw = condition.partition("=")
        key, raw = key.strip(), raw.strip()
        if not sep or not key or not raw:
            raise WhereError(f"filter {condition!r} must be KEY=VALUE, for example gold_all_python=true")
        value: object = raw
        if raw.lower() in ("true", "false"):
            value = raw.lower() == "true"
        elif re.fullmatch(r"-?[0-9]+", raw):  # plain whole numbers only; anything else stays text
            value = int(raw)
        out.append((key, value))
    return out


def task_value(task: Task, key: str):
    """A filter key's value for a task: `repo`, `language`, or a tag (None if the task lacks it)."""
    if key in ("repo", "language"):
        return getattr(task, key)
    return task.tags.get(key)


def task_matches(task: Task, conditions: list[tuple[str, object]]) -> bool:
    """True if the task matches every condition."""
    for key, wanted in conditions:
        value = task_value(task, key)
        if isinstance(wanted, bool) or isinstance(value, bool):
            if value is not wanted:
                return False
        elif isinstance(wanted, int):
            if value != wanted:
                return False
        elif str(value).lower() != str(wanted).lower():
            return False
    return True


def check_where_keys(tasks: Iterable[Task], conditions: list[tuple[str, object]], what: str = "task") -> None:
    """A key that none of the tasks has is a mistyped filter, not an empty result."""
    known = {"repo", "language"} | {k for task in tasks for k in task.tags}
    unknown = sorted({key for key, _ in conditions} - known)
    if unknown:
        raise WhereError(f"no {what} has {unknown}; known keys: {', '.join(sorted(known))}")
