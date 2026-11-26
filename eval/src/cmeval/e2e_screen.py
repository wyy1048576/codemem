"""The screen for unfair hidden tests (batch B13).

A valid task can still be unfair: a correct, general fix made from the issue alone does not pass all of
its hidden tests. A reader (a model session that the orchestrator starts) answers that question for each
task, under the rules in tasks/screen-rules-v1.md. Each task gets two independent reads. This module calls
no model. It has four parts:

  pack    one packet for each valid task: the issue, the real fix, the test change, the two test lists
          and a few facts. Also an index of the packets, and batch files that split them between readers
  add     check a reader's output against the packets, then append it to a screen file as one read
  merge   the status of each task from its reads
  table   kept and removed tasks per repo and difficulty, with a warning when a repo or a level runs short

A screen file (tasks/screen/<name>.jsonl) has one JSON row for each task and read. Rows are only appended.
The fields of a row:

  id, repo, difficulty   the task. difficulty is generate.difficulty of the real fix
  read                   1, 2, ...: the read number. The reads of one task come from different readers
  reader                 a label of the reader session (model and session)
  fair                   true or false
  kinds                  [] when fair. Else one or more names of KINDS
  deciding_assertions    the test assertions that decide the verdict
  reason                 why the reader decided so
  confidence             high, medium or low
  rules                  the version of the reader's rules
  content_hash           content_hash() of the issue, the real fix and the test change that the reader read.
                         A row whose hash is not the task's hash of today is stale and is not used
  date                   the day of the read, YYYY-MM-DD
  note                   optional text

The status of a task, from its rows that are not stale:
  fair, unfair   all reads (at least two) agree. With three or more reads that do not agree, a strict
                 majority decides
  disagree       two reads that do not agree, or no majority. The task needs another read
  one read       only one read
  not screened   no read
Only "fair" counts in the completion score.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .files import sha256_file, write_json, write_text_atomic
from .tasks import Task

RULES_VERSION = "screen-rules-v1"
RULES_FILE = Path(__file__).resolve().parents[2] / "tasks" / f"{RULES_VERSION}.md"

# The kinds of unfairness seen so far (F9 5.3), and "other".
KINDS = {
    "exact-value": "the tests assert an exact internal value, limit, format or message that the issue does not give",
    "new-name": "the tests call or pass a new name (function, parameter, option, setting value, marker) that "
                "the issue does not give",
    "other-behaviour": "the tests expect another behaviour or another error class than the issue asks for",
    "issue-case-works": "the issue's own case already works before the fix; the tests check something else",
    "extra-cases": "the tests cover cases or code paths that the issue does not mention or imply",
    "fix-only-tests": "the real fix changes only test files; there is nothing to fix from the issue",
    "other": "another reason; the reason field says which",
}
CONFIDENCE = ("high", "medium", "low")
LEVELS = ("easy", "medium", "hard")
STATUSES = ("fair", "unfair", "disagree", "one read", "not screened")

# The run matrix takes 20 tasks per repo (plan 3.3). The split over the levels follows the plan's mix of
# 10 easy, 15 medium and 10 hard (8.3) and the admission mix 3:4:3, rounded so that the sum is 20.
NEED_REPO = 20
NEED_LEVEL = {"easy": 6, "medium": 8, "hard": 6}

LIST_SHOWN = 200  # test ids shown in a packet for each list
GROUPS_SHOWN = 50  # groups of test ids (the part before "::") shown in a packet for each list

ROW_FIELDS = {"id": str, "repo": str, "difficulty": str, "read": int, "reader": str, "fair": bool, "kinds": list,
              "deciding_assertions": str, "reason": str, "confidence": str, "rules": str, "content_hash": str,
              "date": str}
OPTIONAL_FIELDS = {"note": str}
# The fields a reader writes for each packet.
OUTPUT_FIELDS = {"id": str, "content_hash": str, "fair": bool, "kinds": list, "deciding_assertions": str,
                 "reason": str, "confidence": str}

INDEX_NAME = "index.json"
STALE_RECORD = "the validation record is from another version of the recipe or the task"


class ScreenError(ValueError):
    pass


def content_hash(task: Task) -> str:
    """A short hash of what a reader reads: the issue text, the real fix and the test change."""
    data = {"issue": task.query, "fix": task.patch, "tests": task.test_patch or ""}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ---- rows and screen files

def _type_problems(row: dict, fields: dict, optional: dict | None = None) -> list[str]:
    problems = []
    for name, kind in fields.items():
        if name not in row:
            problems.append(f"'{name}' is missing")
        elif kind is int and (isinstance(row[name], bool) or not isinstance(row[name], int)):
            problems.append(f"'{name}' must be an integer")
        elif not isinstance(row[name], kind):
            problems.append(f"'{name}' must be {kind.__name__}")
    optional = optional or {}
    for name in sorted(set(row) - set(fields) - set(optional)):
        problems.append(f"unknown field '{name}'")
    for name, kind in optional.items():
        if name in row and not isinstance(row[name], kind):
            problems.append(f"'{name}' must be {kind.__name__}")
    return problems


def verdict_problems(row: dict) -> list[str]:
    """Problems of the verdict fields: fair, kinds, reason, confidence."""
    problems = []
    if not isinstance(row.get("fair"), bool) or not isinstance(row.get("kinds"), list):
        return problems
    kinds = row["kinds"]
    unknown = [k for k in kinds if k not in KINDS]
    if unknown:
        problems.append(f"unknown kinds {unknown}; use {sorted(KINDS)}")
    if len(set(map(str, kinds))) != len(kinds):
        problems.append("a kind is given twice")
    if row["fair"] and kinds:
        problems.append("a fair verdict has no kinds")
    if not row["fair"] and not kinds:
        problems.append("an unfair verdict needs at least one kind")
    if isinstance(row.get("reason"), str) and not row["reason"].strip():
        problems.append("'reason' is empty")
    if isinstance(row.get("confidence"), str) and row["confidence"] not in CONFIDENCE:
        problems.append(f"'confidence' must be one of {list(CONFIDENCE)}")
    return problems


def row_problems(row) -> list[str]:
    """Problems of one row of a screen file. An empty list means the row is good."""
    if not isinstance(row, dict):
        return ["a row must be a JSON object"]
    problems = _type_problems(row, ROW_FIELDS, OPTIONAL_FIELDS) + verdict_problems(row)
    if isinstance(row.get("read"), int) and not isinstance(row.get("read"), bool) and row["read"] < 1:
        problems.append("'read' must be 1 or more")
    if isinstance(row.get("difficulty"), str) and row["difficulty"] not in LEVELS:
        problems.append(f"'difficulty' must be one of {list(LEVELS)}")
    for name in ("id", "repo", "reader", "rules"):
        if isinstance(row.get(name), str) and not row[name].strip():
            problems.append(f"'{name}' is empty")
    if isinstance(row.get("content_hash"), str) and not re.fullmatch(r"[0-9a-f]{16}", row["content_hash"]):
        problems.append("'content_hash' must be 16 hex digits")
    if isinstance(row.get("date"), str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date"]):
        problems.append("'date' must be YYYY-MM-DD")
    return problems


def _rows_conflicts(rows: list[dict], where: list[str]) -> list[str]:
    """Rows that cannot be in one screen: the same task and read twice, or one reader for two reads of a task."""
    problems = []
    seen: dict[tuple[str, int], str] = {}
    readers: dict[tuple[str, str], str] = {}
    for row, place in zip(rows, where):
        key = (row["id"], row["read"])
        if key in seen:
            problems.append(f"{place}: read {row['read']} of {row['id']} is already at {seen[key]}")
        seen.setdefault(key, place)
        who = (row["id"], row["reader"])
        if who in readers and readers[who] != place:
            problems.append(f"{place}: reader '{row['reader']}' already read {row['id']} at {readers[who]}; "
                            "the reads of a task must be independent")
        readers.setdefault(who, place)
    return problems


def load_screen(path: Path) -> list[dict]:
    """The rows of a screen file. A file with any bad row, or with two rows of one task and read, is refused."""
    path = Path(path)
    if not path.exists():
        raise ScreenError(f"{path}: no such screen file")
    rows, where, problems = [], [], []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"line {n}: not JSON ({exc.msg})")
            continue
        bad = row_problems(row)
        if bad:
            problems.append(f"line {n}: " + "; ".join(bad))
            continue
        rows.append(row)
        where.append(f"{path.name} line {n}")
    problems += _rows_conflicts(rows, where)
    if problems:
        raise ScreenError(f"{path}: {len(problems)} problems:\n  " + "\n  ".join(problems[:20]))
    return rows


def load_screens(paths: list[Path]) -> list[dict]:
    """The rows of several screen files, checked together."""
    rows, where = [], []
    for path in paths:
        for n, row in enumerate(load_screen(path), start=1):
            rows.append(row)
            where.append(f"{Path(path).name} row {n}")
    problems = _rows_conflicts(rows, where)
    if problems:
        raise ScreenError("the screen files do not fit together:\n  " + "\n  ".join(problems[:20]))
    return rows


# ---- merge

@dataclass
class TaskScreen:
    id: str
    repo: str
    difficulty: str
    status: str
    reads: list[dict] = field(default_factory=list)
    stale: int = 0  # rows left out, because the task changed after the read


def task_status(reads: list[dict]) -> str:
    """fair, unfair, disagree, one read or not screened (see the module text)."""
    if not reads:
        return "not screened"
    if len(reads) == 1:
        return "one read"
    votes = Counter(bool(r["fair"]) for r in reads)
    if len(votes) == 1:
        return "fair" if reads[0]["fair"] else "unfair"
    if len(reads) >= 3 and votes[True] != votes[False]:
        return "fair" if votes[True] > votes[False] else "unfair"
    return "disagree"


def merge(rows: list[dict], hashes: dict[str, str] | None = None,
          tasks: dict[str, tuple[str, str]] | None = None) -> dict[str, TaskScreen]:
    """The status of each task. `hashes` (task id -> content_hash of today) makes rows with another hash stale.
    Without it, a task whose rows have more than one hash has only stale rows. `tasks` (task id -> (repo,
    difficulty)) adds the tasks that have no row, as not screened."""
    by_id: dict[str, list[dict]] = {}
    for row in rows:
        by_id.setdefault(row["id"], []).append(row)
    result: dict[str, TaskScreen] = {}
    for task_id, task_rows in by_id.items():
        if hashes is not None:
            if task_id not in hashes:
                continue  # not a task of today's set
            good = [r for r in task_rows if r["content_hash"] == hashes[task_id]]
        else:
            good = task_rows if len({r["content_hash"] for r in task_rows}) == 1 else []
        first = task_rows[0]
        repo, level = (tasks or {}).get(task_id, (first["repo"], first["difficulty"]))
        good.sort(key=lambda r: r["read"])
        result[task_id] = TaskScreen(task_id, repo, level, task_status(good), good, len(task_rows) - len(good))
    for task_id, (repo, level) in (tasks or {}).items():
        result.setdefault(task_id, TaskScreen(task_id, repo, level, "not screened"))
    return result


@dataclass
class CompletionSet:
    """The tasks that count in the completion score, from screen files."""
    files: list[str]
    status: dict[str, TaskScreen]

    @property
    def fair(self) -> set[str]:
        return {i for i, s in self.status.items() if s.status == "fair"}

    def status_of(self, task_id: str) -> str:
        screen = self.status.get(task_id)
        return screen.status if screen else "not screened"


def completion_set(paths: list[Path], tasks: list[Task] | None = None) -> CompletionSet:
    """Load and merge screen files for the score. With `tasks`, rows are checked against each task's hash."""
    rows = load_screens(paths)
    hashes = {t.id: content_hash(t) for t in tasks} if tasks is not None else None
    return CompletionSet([Path(p).name for p in paths], merge(rows, hashes))


# ---- packets

def _group(test_id: str) -> str:
    return test_id.split("::", 1)[0]


def short_list(tests: list[str], limit: int = LIST_SHOWN, groups: int = GROUPS_SHOWN) -> dict:
    """A test list for a reader: the count, the first `limit` ids, and, for a long list, the count of ids in each
    group (the part before "::": the test file or the test class)."""
    tests = sorted(tests)
    result: dict = {"total": len(tests), "shown": tests[:limit]}
    if len(tests) > limit:
        counts = Counter(_group(t) for t in tests).most_common()
        result["groups"] = dict(counts[:groups])
        result["groups_total"] = len(counts)
    return result


def packet_facts(task: Task, record: dict, tests: dict) -> dict:
    """The facts of one packet, for packet.json and the index."""
    from .generate import changed_files, changed_lines, difficulty
    from .patches import classify_path

    fix_files = changed_files(task.patch)
    return {
        "id": task.id,
        "repo": task.repo,
        "difficulty": difficulty(task.patch),
        "content_hash": content_hash(task),
        "rules": RULES_VERSION,
        "fix_files": fix_files,
        "fix_changed_lines": changed_lines(task.patch),
        "test_files": changed_files(task.test_patch or ""),
        # F9 5.3: such a task cannot be solved from the issue.
        "fix_changes_only_tests": not any(classify_path(f)[0] == "code" for f in fix_files),
        # Not test files by the path rules, but test helpers by name. A hint for the reader.
        "fix_files_named_test": [f for f in fix_files if "test" in f.lower()],
        "fail_to_pass": short_list(tests.get("fail_to_pass", [])),
        # How the fail-to-pass tests did before the fix. Many "missing before" tests often mean a test file
        # that did not load before the fix (F9 5.3, pandas 67471).
        "fail_to_pass_before": {kind: record.get(f"fail_to_pass_{kind}_before")
                                for kind in ("failed", "skipped", "missing")},
        "pass_to_pass": short_list(tests.get("pass_to_pass", [])),
    }


def _valid_record(recipe, task: Task) -> tuple[dict | None, dict | None, str]:
    """(result record, tests, problem) of a task, checked the way the grader checks tests.json."""
    from .e2e import load_tests
    from .generate import GenerateError, task_dir, validation_fingerprint

    saved = task_dir(recipe, task) / "result.json"
    if not saved.exists():
        return None, None, "not validated"
    record = json.loads(saved.read_text(encoding="utf-8"))
    if record.get("fingerprint") != validation_fingerprint(recipe, task, record.get("repeats")):
        return record, None, STALE_RECORD
    if not record.get("valid"):
        return record, None, f"not valid: {record.get('reason', '')}"
    try:
        tests = load_tests(recipe, task)
    except GenerateError as exc:
        return record, None, str(exc)
    return record, tests, ""


def pool_counts(recipe, tasks: list[Task]) -> dict[str, dict[str, int]]:
    """For each level: the repo's tasks with tests in the task file, those with a current validation record,
    and the valid ones."""
    from .generate import difficulty, task_test_files

    pool = {level: {"candidates": 0, "validated": 0, "valid": 0} for level in LEVELS}
    for task in tasks:
        if task.repo != recipe.repo or not task.test_patch or not task_test_files(recipe, task):
            continue
        counts = pool[difficulty(task.patch)]
        counts["candidates"] += 1
        record, tests, problem = _valid_record(recipe, task)
        if record is not None and problem != STALE_RECORD:
            counts["validated"] += 1
        if tests is not None:
            counts["valid"] += 1
    return pool


def write_packet(folder: Path, task: Task, facts: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    write_text_atomic(folder / "issue.txt", task.query)
    write_text_atomic(folder / "real-fix.patch", task.patch)
    write_text_atomic(folder / "test.patch", task.test_patch or "")
    write_json(folder / "packet.json", facts)


def batches(packets: list[dict], n: int) -> list[list[str]]:
    """Split packet ids into n batches, each with a mix of repos and levels."""
    order = sorted(packets, key=lambda p: (p["repo"], LEVELS.index(p["difficulty"]), p["id"]))
    out: list[list[str]] = [[] for _ in range(max(1, min(n, len(order))))]
    for i, packet in enumerate(order):
        out[i % len(out)].append(packet["id"])
    return out


def load_index(folder: Path) -> dict:
    path = Path(folder) / INDEX_NAME
    if not path.exists():
        raise ScreenError(f"{path}: no packet index; make the packets with cmeval e2e screen-pack")
    return json.loads(path.read_text(encoding="utf-8"))


def pack(recipe, tasks: list[Task], out: Path, *, task_file: str = "", ids: list[str] | None = None,
         n_batches: int = 1) -> dict:
    """Write a packet for each valid task of the recipe's repo, and update the index in `out`. Returns the
    index entry of this recipe: packets, skipped tasks, the pool counts, and the batch files. The index keeps the
    packets of the last call for each recipe."""
    from .generate import task_test_files

    out = Path(out)
    index = load_index(out) if (out / INDEX_NAME).exists() else {"rules": RULES_VERSION, "recipes": {}, "packets": []}
    if index.get("rules") != RULES_VERSION:
        raise ScreenError(f"{out}: the index is for rules {index.get('rules')}, not {RULES_VERSION}; use a new folder")
    repo_tasks = [t for t in tasks if t.repo == recipe.repo]
    if ids:
        wanted = set(ids)
        chosen = [t for t in repo_tasks if t.id in wanted]
    else:
        chosen = [t for t in repo_tasks if t.test_patch and task_test_files(recipe, t)]
    packets, skipped = [], []
    for task in chosen:
        record, tests, problem = _valid_record(recipe, task)
        if tests is None:
            skipped.append({"id": task.id, "reason": problem})
            continue
        facts = packet_facts(task, record, tests)
        write_packet(out / task.id, task, facts)
        packets.append({k: facts[k] for k in ("id", "repo", "difficulty", "content_hash", "fix_changes_only_tests")}
                       | {"recipe": recipe.name, "fail_to_pass": facts["fail_to_pass"]["total"],
                          "pass_to_pass": facts["pass_to_pass"]["total"]})
    batch_files = []
    for old in (out / "batches").glob(f"{recipe.name}-*.txt"):
        old.unlink()  # batch files of an earlier call
    if packets:
        (out / "batches").mkdir(parents=True, exist_ok=True)
        for k, batch in enumerate(batches(packets, n_batches), start=1):
            name = f"batches/{recipe.name}-{k}.txt"
            write_text_atomic(out / name, "".join(f"{i}\n" for i in batch))
            batch_files.append(name)
    # Tasks that were never validated are many; the index keeps only their count.
    not_validated = [s for s in skipped if s["reason"] == "not validated"]
    skipped = [s for s in skipped if s["reason"] != "not validated"]
    entry = {"repo": recipe.repo, "task_file": task_file, "packets": len(packets), "skipped": skipped,
             "not_validated": len(not_validated),
             "pool": pool_counts(recipe, repo_tasks), "batches": batch_files}
    index["rules_sha256"] = sha256_file(RULES_FILE) if RULES_FILE.exists() else None
    index["created"] = today()
    index["recipes"][recipe.name] = entry
    index["packets"] = sorted([p for p in index["packets"] if p.get("recipe") != recipe.name] + packets,
                              key=lambda p: p["id"])
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / INDEX_NAME, index)
    return entry


# ---- add a read

def read_output(path: Path) -> list:
    """A reader's output: a JSON list of verdicts, or one JSON object per line."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    rows = []
    for n, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ScreenError(f"{path} line {n}: not JSON ({exc.msg})") from None
    return rows


def add_read(output: Path, packets_dir: Path, screen: Path, *, read: int, reader: str,
             batch: Path | None = None, date: str | None = None, note: str | None = None,
             rules: str | None = None) -> list[dict]:
    """Check a reader's output against the packets and append it to the screen file as read `read`.
    Nothing is written when there is any problem. `rules` replaces the rules version of the index, for reads
    made under other instructions. Returns the new rows."""
    index = load_index(packets_dir)
    known = {p["id"]: p for p in index.get("packets", [])}
    if batch is not None:
        expected = [line.strip() for line in Path(batch).read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        expected = sorted(known)
    raw = read_output(output)
    problems: list[str] = []
    rows: list[dict] = []
    for n, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            problems.append(f"verdict {n}: not a JSON object")
            continue
        bad = _type_problems(item, OUTPUT_FIELDS) + verdict_problems(item)
        task_id = item.get("id")
        packet = known.get(task_id) if isinstance(task_id, str) else None
        if isinstance(task_id, str) and packet is None:
            bad.append("no packet of this id")
        elif packet is not None and item.get("content_hash") != packet["content_hash"]:
            bad.append(f"content_hash {item.get('content_hash')} is not the packet's {packet['content_hash']}")
        if bad:
            problems.append(f"verdict {n} ({task_id}): " + "; ".join(bad))
            continue
        row = {"id": task_id, "repo": packet["repo"], "difficulty": packet["difficulty"], "read": read,
               "reader": reader, "fair": item["fair"], "kinds": item["kinds"],
               "deciding_assertions": item["deciding_assertions"], "reason": item["reason"],
               "confidence": item["confidence"], "rules": rules or index["rules"], "content_hash": packet["content_hash"],
               "date": date or today()}
        if note:
            row["note"] = note
        problems += [f"verdict {n} ({task_id}): {p}" for p in row_problems(row)]
        rows.append(row)
    ids = [r["id"] for r in rows]
    twice = sorted(i for i, c in Counter(ids).items() if c > 1)
    if twice:
        problems.append(f"verdicts given twice: {twice}")
    given = {item.get("id") for item in raw if isinstance(item, dict)}
    missing = sorted(set(expected) - given)
    extra = sorted(set(ids) - set(expected))
    if missing:
        problems.append(f"{len(missing)} packets of the batch have no verdict: {missing[:20]}")
    if extra:
        problems.append(f"verdicts for packets outside the batch: {extra[:20]}")
    old = load_screen(screen) if Path(screen).exists() else []
    problems += _rows_conflicts(old + rows, [f"{Path(screen).name} row {i}" for i in range(1, len(old) + 1)]
                                + [f"verdict of {r['id']}" for r in rows])
    if problems:
        raise ScreenError(f"{output}: {len(problems)} problems; nothing written:\n  " + "\n  ".join(problems[:20]))
    Path(screen).parent.mkdir(parents=True, exist_ok=True)
    with Path(screen).open("a", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows


# ---- table

def parse_need_level(text: str) -> dict[str, int]:
    """'easy=6,medium=8,hard=6' -> {"easy": 6, ...}. Levels that are not given keep their default."""
    need = dict(NEED_LEVEL)
    for part in filter(None, (p.strip() for p in text.split(","))):
        level, _, value = part.partition("=")
        if level.strip() not in LEVELS or not value.strip().isdigit():
            raise ScreenError(f"--need-level: '{part}' is not LEVEL=N with a level of {list(LEVELS)}")
        need[level.strip()] = int(value)
    return need


def _counts(screens: list[TaskScreen]) -> dict[str, int]:
    status = Counter(s.status for s in screens)
    return {"valid": len(screens), "kept": status["fair"], "removed": status["unfair"],
            "disagree": status["disagree"], "open": status["one read"] + status["not screened"]}


def table(status: dict[str, TaskScreen], *, pools: dict[str, dict] | None = None, need_repo: int = NEED_REPO,
          need_level: dict[str, int] | None = None) -> dict:
    """Counts per repo and level, warnings, the disagreements and the level shares. `pools` (repo -> the pool of
    pool_counts) adds the candidates that are not validated yet to the warnings."""
    need_level = need_level or NEED_LEVEL
    repos = sorted({s.repo for s in status.values()})
    rows, warnings = [], []
    for repo in repos:
        mine = [s for s in status.values() if s.repo == repo]
        pool = (pools or {}).get(repo)
        for level in (*LEVELS, "all"):
            part = mine if level == "all" else [s for s in mine if s.difficulty == level]
            if not part and level != "all":
                continue
            counts = _counts(part)
            rows.append({"repo": repo, "level": level, **counts})
            need = need_repo if level == "all" else need_level.get(level, 0)
            if counts["kept"] < need:
                left = None
                if pool:
                    levels = LEVELS if level == "all" else (level,)
                    left = sum(pool[lv]["candidates"] - pool[lv]["validated"] for lv in levels)
                warnings.append(_warning(repo, level, counts, need, left))
    total = _counts(list(status.values()))
    shares = {level: _counts([s for s in status.values() if s.difficulty == level]) for level in LEVELS}
    disagree = sorted(s.id for s in status.values() if s.status == "disagree")
    one_read = sorted(s.id for s in status.values() if s.status == "one read")
    stale = sorted(s.id for s in status.values() if s.stale)
    return {"rows": rows, "total": total, "warnings": warnings, "levels": shares, "disagree": disagree,
            "one_read": one_read, "stale": stale, "need_repo": need_repo, "need_level": need_level}


def _warning(repo: str, level: str, counts: dict, need: int, left: int | None) -> str:
    where = repo if level == "all" else f"{repo} {level}"
    decided = counts["kept"] + counts["removed"]
    text = f"{where}: {counts['kept']} kept, {need} needed"
    if counts["disagree"] or counts["open"]:
        text += f"; {counts['disagree'] + counts['open']} valid tasks not decided yet"
    if decided:
        rate = counts["kept"] / decided
        text += f"; keep rate {counts['kept']} of {decided}"
        if rate > 0:
            more = max(0, math.ceil((need - counts["kept"]) / rate) - counts["disagree"] - counts["open"])
            text += f", so about {more} more valid tasks are needed"
        else:
            text += ", so no estimate of the valid tasks needed"
    if left is not None:
        text += f"; {left} candidates with tests are not validated yet"
    return text


def _pct(part: int, whole: int) -> str:
    return f"{part} of {whole} ({round(100 * part / whole)}%)" if whole else "0 of 0"


def format_table(result: dict, files: list[str]) -> str:
    """The table as Markdown, for the work log."""
    lines = [f"Screen: {', '.join(files)}. Kept = both reads say fair; removed = both say unfair.", "",
             "| Repo | Difficulty | Valid | Kept | Removed | Disagree | Not done |",
             "|---|---|---|---|---|---|---|"]
    for row in result["rows"]:
        mark = "**" if row["level"] == "all" else ""
        lines.append(f"| {mark}{row['repo']}{mark} | {mark}{row['level']}{mark} | {row['valid']} | {row['kept']} | "
                     f"{row['removed']} | {row['disagree']} | {row['open']} |")
    t = result["total"]
    lines.append(f"| **all** | **all** | {t['valid']} | {t['kept']} | {t['removed']} | {t['disagree']} | {t['open']} |")
    lines.append("")
    shares = ", ".join(f"{level} {_pct(c['kept'], c['kept'] + c['removed'])}"
                       for level, c in result["levels"].items())
    lines.append(f"Kept share by difficulty, all repos (decided tasks only): {shares}.")
    need = ", ".join(f"{level} {n}" for level, n in result["need_level"].items())
    lines.append(f"Need: {result['need_repo']} kept tasks per repo; per level {need}.")
    if result["warnings"]:
        lines.append("")
        lines += [f"- **Warning:** {w}" for w in result["warnings"]]
    if result["disagree"]:
        lines.append("")
        lines.append(f"Disagree, needs a third read ({len(result['disagree'])}): " + ", ".join(result["disagree"]))
    if result["one_read"]:
        lines.append(f"One read only ({len(result['one_read'])}): " + ", ".join(result["one_read"]))
    if result["stale"]:
        lines.append("Reads left out because the task changed after the read: " + ", ".join(result["stale"]))
    return "\n".join(lines)


def screen_table(paths: list[Path], packet_dirs: list[Path] = (), *, need_repo: int = NEED_REPO,
                 need_level: dict[str, int] | None = None) -> dict:
    """Load, merge and count. With packet folders, the valid tasks and their hashes come from their indexes."""
    rows = load_screens(paths)
    hashes, tasks, pools = None, None, None
    if packet_dirs:
        hashes, tasks, pools = {}, {}, {}
        for folder in packet_dirs:
            index = load_index(folder)
            for packet in index.get("packets", []):
                hashes[packet["id"]] = packet["content_hash"]
                tasks[packet["id"]] = (packet["repo"], packet["difficulty"])
            for entry in index.get("recipes", {}).values():
                pools[entry["repo"]] = entry["pool"]
    status = merge(rows, hashes, tasks)
    return table(status, pools=pools, need_repo=need_repo, need_level=need_level)
