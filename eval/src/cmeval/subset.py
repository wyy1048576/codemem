"""A fixed random subset of a task file, for runs that cannot afford every task.

The subset is its own task file (with a meta file), so a run, its score, and its report name it by
sha256 like any other task file. The draw is per repo: each matching task of a repo is ranked by the
sha256 of "<seed>:<repo>:<task id>", and the N with the lowest values are kept. That depends only on
the seed, the repo, and the ids (not on the Python version or the order of the input), so the same
inputs always give the same subset, and adding a repo never changes the draw of another.

Meta file (the out path with .meta.json in place of .jsonl): source file and sha256, split, filter,
repos, per_repo, seed, the matching and chosen counts for each repo, the chosen ids, cmeval version
and commit.
"""

from __future__ import annotations

import hashlib
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
    """n ids of one repo, the ones whose sha256 of "<seed>:<repo>:<id>" is lowest (all if n or fewer), sorted."""
    def rank(task_id: str) -> str:
        return hashlib.sha256(f"{seed}:{repo}:{task_id}".encode("utf-8")).hexdigest()
    return sorted(sorted(set(ids), key=lambda i: (rank(i), i))[:n])


def subset(tasks_file: Path | str, out: Path | str, *, per_repo: int, seed: str, split: str | None = "dev",
           where: list[str] | None = None, repos: list[str] | None = None) -> SubsetResult:
    tasks_file, out = Path(tasks_file), Path(out)
    meta_path = out.with_suffix(".meta.json")
    if per_repo < 1:
        raise SubsetError(f"per_repo must be 1 or more, got {per_repo}")
    if out.resolve() == tasks_file.resolve() or meta_path.resolve() == tasks_file.with_suffix(".meta.json").resolve():
        raise SubsetError(f"{out} would write over the source {tasks_file} or its meta file; choose another --out")
    source_sha = sha256_file(tasks_file) if tasks_file.is_file() else None  # before anything is written
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
    if not by_repo:
        raise SubsetError("no task matches the split and the filter")
    # Repos are matched without case, as --where does, and kept sorted and unique, so the same subset
    # always gives the same file whatever the order of --repo.
    real = {name.lower(): name for name in by_repo}
    asked = sorted({r.lower() for r in repos}) if repos else sorted(real)
    unknown = [r for r in asked if r not in real]
    if unknown:
        what = f"{split} task" if split else "task"
        raise SubsetError(f"no matching {what} in {unknown}; repos with matches: {sorted(by_repo)}")
    names = sorted(real[r] for r in asked)

    chosen: list[Task] = []
    available, picked = {}, {}
    for repo in names:
        group = {t.id: t for t in by_repo[repo]}
        ids = draw(list(group), per_repo, seed, repo)
        available[repo] = len(group)
        picked[repo] = ids
        chosen += [group[i] for i in ids]
    short = [r for r in names if available[r] < per_repo]

    from .run import _eval_git  # the commit of the code that made the subset

    meta = {  # complete before any file is written, so a failure leaves no half-made subset
        "kind": "subset",
        "source": tasks_file.name,
        "source_sha256": source_sha,
        "split": split,
        "where": where or [],
        "repos": names,
        "per_repo": per_repo,
        "seed": seed,
        "draw": "lowest sha256 of '<seed>:<repo>:<task id>'",
        "available": available,
        "chosen": {repo: len(ids) for repo, ids in picked.items()},
        "short": short,
        "task_ids": picked,
        "tasks": len(chosen),
        "cmeval_version": __version__,
        "cmeval_git": _eval_git(),
        "created": now(),
    }
    save_tasks(out, chosen)
    write_json(meta_path, meta)
    return SubsetResult(out, chosen, available, short)
