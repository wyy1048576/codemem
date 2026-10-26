"""A fixed random subset of a task file, for runs that cannot afford every task.

The subset is its own task file (with a meta file), so a run, its score, and its report name it by
sha256 like any other task file. The draw is per repo: the matching tasks of a repo are sorted by
id, and a random generator seeded with "<seed>:<repo>" picks N of them. The same inputs always give
the same subset, and adding a repo never changes the draw of another.

Meta file <out>.meta.json: source file and sha256, split, filter, repos, per_repo, seed, the
matching and chosen counts for each repo, the chosen ids, cmeval version and commit.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .files import now, sha256_file, write_json
from .tasks import Task, WhereError, check_where_keys, load_tasks, parse_where, save_tasks, select, task_matches


class SubsetError(RuntimeError):
    """The subset cannot be made (bad filter, unknown repo, nothing matches)."""


@dataclass
class SubsetResult:
    out: Path
    tasks: list[Task]
    available: dict[str, int] = field(default_factory=dict)  # matching tasks for each repo
    short: list[str] = field(default_factory=list)  # repos with fewer matching tasks than per_repo


def draw(ids: list[str], n: int, seed: str, repo: str) -> list[str]:
    """n ids of one repo, picked at random with a fixed seed (all of them if there are n or fewer)."""
    ordered = sorted(ids)
    if len(ordered) <= n:
        return ordered
    return sorted(random.Random(f"{seed}:{repo}").sample(ordered, n))


def subset(tasks_file: Path | str, out: Path | str, *, per_repo: int, seed: str, split: str | None = "dev",
           where: list[str] | None = None, repos: list[str] | None = None) -> SubsetResult:
    tasks_file, out = Path(tasks_file), Path(out)
    if per_repo < 1:
        raise SubsetError(f"per_repo must be 1 or more, got {per_repo}")
    try:
        conditions = parse_where(where)
        pool = select(load_tasks(tasks_file), split)
        check_where_keys(pool, conditions)
    except (WhereError, ValueError) as exc:
        raise SubsetError(str(exc)) from None
    by_repo: dict[str, list[Task]] = defaultdict(list)
    for task in pool:
        if task_matches(task, conditions):
            by_repo[task.repo].append(task)
    names = repos or sorted(by_repo)
    unknown = [r for r in names if r not in by_repo]
    if unknown:
        what = f"{split} task" if split else "task"
        raise SubsetError(f"no matching {what} in {unknown}; repos with matches: {sorted(by_repo)}")

    chosen: list[Task] = []
    available, picked = {}, {}
    for repo in names:
        group = {t.id: t for t in by_repo[repo]}
        ids = draw(list(group), per_repo, seed, repo)
        available[repo] = len(group)
        picked[repo] = ids
        chosen += [group[i] for i in ids]
    short = [r for r in names if available[r] < per_repo]

    out.parent.mkdir(parents=True, exist_ok=True)
    save_tasks(out, chosen)
    from .run import _eval_git  # the commit of the code that made the subset

    write_json(out.with_suffix(".meta.json"), {
        "kind": "subset",
        "source": tasks_file.name,
        "source_sha256": sha256_file(tasks_file),
        "split": split,
        "where": where or [],
        "repos": names,
        "per_repo": per_repo,
        "seed": seed,
        "available": available,
        "chosen": {repo: len(ids) for repo, ids in picked.items()},
        "short": short,
        "task_ids": picked,
        "tasks": len(chosen),
        "cmeval_version": __version__,
        "cmeval_git": _eval_git(),
        "created": now(),
    })
    return SubsetResult(out, chosen, available, short)
