"""Import SWE-bench Verified as dev tasks, labeled with cmeval's own rules.

We keep SWE-bench's base commit and patch (SWE-bench validated them with test runs), and we
label the patch with our labeler, so every task source follows the same gold rules.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ..labels import LABELER_VERSION, LabelError, LabelResult, identifier_in_query, label_at_commit
from ..paths import datasets_dir
from ..patches import split_patch
from ..tasks import Fix, Issue, Task, clean_query, save_tasks, validate

DATASET = "SWE-bench/SWE-bench_Verified"
DEFAULT_REVISION = "78f471bf655a3137b2e8a75af1501690ec009ec3"  # 2026-08-16
DATA_FILE = "data/test-00000-of-00001.parquet"
COLUMNS = [
    "instance_id", "repo", "base_commit", "problem_statement", "hints_text",
    "patch", "test_patch", "created_at", "difficulty", "version",
]  # fmt: skip

_PR_NUMBER_RE = re.compile(r"-(\d+)$")


def download(revision: str = DEFAULT_REVISION) -> Path:
    """The dataset file at a pinned revision, downloaded once into CMEVAL_HOME/datasets."""
    path = datasets_dir() / f"swebench_verified@{revision[:12]}.parquet"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/datasets/{DATASET}/resolve/{revision}/{DATA_FILE}"
        tmp = path.with_name(path.name + ".partial")
        with urllib.request.urlopen(url, timeout=120) as resp, tmp.open("wb") as f:
            shutil.copyfileobj(resp, f)
        tmp.rename(path)
    return path


def load_rows(path: Path) -> list[dict]:
    import pyarrow.parquet as pq

    return pq.read_table(path, columns=COLUMNS).to_pylist()


def row_to_task(row: dict, label: LabelResult) -> Task:
    repo = row["repo"]
    number = int(_PR_NUMBER_RE.search(row["instance_id"]).group(1))
    query = clean_query(row["problem_statement"])
    tags = {
        **label.tags,
        "has_test_patch": bool(row.get("test_patch")),
        "identifier_in_query": identifier_in_query(query, label.gold),
        "query_tokens": None,
        "swebench_difficulty": row.get("difficulty"),
        "swebench_version": row.get("version"),
    }
    return Task(
        id=row["instance_id"],
        source="swebench_verified",
        split="dev",
        repo=repo,
        base_commit=row["base_commit"],
        language=label.language,
        query=query,
        hints=clean_query(row.get("hints_text")) or None,
        # SWE-bench gives one date: the creation time of the fix PR.
        issue=Issue(created_at=row.get("created_at")),
        fix=Fix(pr_number=number, url=f"https://github.com/{repo}/pull/{number}"),
        patch=split_patch(row["patch"])["code"],  # the schema keeps code files only
        test_patch=row.get("test_patch") or None,
        gold=label.gold,
        unretrievable=label.unretrievable,
        tags=tags,
        labeler=LABELER_VERSION,
    )


def balanced_order(rows: list[dict], seed: int | str) -> list[dict]:
    """Rows in a fixed order that takes about the same number from each repo.

    Each repo's rows are shuffled with a seed for that repo, then taken round-robin over the
    repos in sorted order. Small repos run out first; the rest come from bigger repos.
    """
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_repo[row["repo"]].append(row)
    queues = []
    for repo in sorted(by_repo):
        items = sorted(by_repo[repo], key=lambda r: r["instance_id"])  # independent of input order
        random.Random(f"{seed}:{repo}").shuffle(items)
        queues.append(items)
    ordered: list[dict] = []
    while any(queues):
        for queue in queues:
            if queue:
                ordered.append(queue.pop(0))
    return ordered


@dataclass
class ImportReport:
    tasks: list[Task]
    skipped: list[dict] = field(default_factory=list)  # {"id": ..., "reason": ...}
    stats: dict = field(default_factory=dict)
    written: bool = False  # False if fewer than n tasks were found: the old file is kept


def label_stats(tasks: list[Task]) -> dict:
    n = len(tasks) or 1

    def share(pred) -> float:
        return round(sum(1 for t in tasks if pred(t)) / n, 3)

    def mean(fn) -> float:
        return round(sum(fn(t) for t in tasks) / n, 2)

    return {
        "tasks": len(tasks),
        "tasks_per_repo": dict(sorted(Counter(t.repo for t in tasks).items())),
        "mean_gold_files": mean(lambda t: len(t.gold.files)),
        "mean_gold_classes": mean(lambda t: len(t.gold.classes)),
        "mean_gold_functions": mean(lambda t: len(t.gold.functions)),
        "share_no_gold_function": share(lambda t: not t.gold.functions),
        "share_module_level_change": share(lambda t: t.tags.get("module_level_change")),
        "share_partial_labels": share(lambda t: t.tags.get("partial_labels")),
        "share_identifier_in_query": share(lambda t: t.tags.get("identifier_in_query")),
        "share_with_unretrievable_functions": share(lambda t: bool(t.unretrievable.functions)),
    }


def import_swebench_verified(
    n: int = 50,
    seed: int = 0,
    revision: str = DEFAULT_REVISION,
    out: Path | None = None,
    *,
    rows: list[dict] | None = None,
    label_fn: Callable[[str, str, str], LabelResult] = label_at_commit,
    progress: Callable[[str], None] = lambda message: None,
) -> ImportReport:
    """Sample n rows (balanced over repos), label them, and write a task file plus a meta file.

    A row that cannot be labeled, or that gives an invalid task (for example an empty query), is
    skipped with the reason and replaced by the next row. Git or network errors stop the import,
    so a repo is never silently missing. If fewer than n tasks are found, nothing is written, so
    a failed run never replaces a committed task file.
    """
    if rows is None:
        progress(f"downloading {DATASET} at {revision[:12]}")
        rows = load_rows(download(revision))
    tasks: list[Task] = []
    skipped: list[dict] = []
    for row in balanced_order(rows, seed):
        if len(tasks) >= n:
            break
        progress(f"[{len(tasks) + 1}/{n}] {row['instance_id']}")
        try:
            label = label_fn(row["repo"], row["base_commit"], row["patch"])
        except LabelError as exc:
            skipped.append({"id": row["instance_id"], "reason": str(exc)})
            continue
        if not label.gold.files:
            skipped.append({"id": row["instance_id"], "reason": "the patch changes no code file at the base commit"})
            continue
        task = row_to_task(row, label)
        problems = validate(task)
        if problems:
            skipped.append({"id": row["instance_id"], "reason": "invalid task: " + "; ".join(problems)})
            continue
        tasks.append(task)

    tasks.sort(key=lambda t: (t.repo, t.id))
    report = ImportReport(tasks, skipped, label_stats(tasks))
    if out is not None and len(tasks) == n:
        save_tasks(out, tasks)
        report.written = True
        meta = {
            "dataset": DATASET,
            "revision": revision,
            "n": n,
            "seed": seed,
            "cmeval_version": __version__,
            "labeler": LABELER_VERSION,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "skipped": skipped,
            "stats": report.stats,
        }
        meta_path = Path(out).with_suffix(".meta.json")
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return report
