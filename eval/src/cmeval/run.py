"""The runner: every system in a config on every task, with raw hits and timings saved to files.

Scoring and the report read these files later, so a new metric never needs a new run.

Per repo, one movable worktree steps through the tasks in commit-date order. Systems that share
an index_key share one index folder: the first system of the group builds (first task) or
updates it, the others only update (Decision 5). A stopped run continues where it stopped.

Run folder CMEVAL_HOME/runs/<run_id>/:
    meta.json        inputs (with hashes), settings, each system's describe(), machine, status
    <system>.jsonl   one line for each task: task_id, commit, search_ms, hits
    index.jsonl      one line for each build or update: repo, commit, index_key, mode, report
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__, repos
from .files import append_jsonl as _append_jsonl
from .files import drop_unfinished_line, read_jsonl
from .files import now as _now
from .files import sha256_file as _sha256
from .files import write_json as _write_json
from .paths import indexes_dir, runs_dir
from .retriever import Retriever, RetrieverError, check_hits
from .systems import load_systems, make_system
from .tasks import Task, load_tasks, select

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
WARMUP_QUERY = "warm up"
# Settings that must match when a run is resumed. Filters (repos, limit) may change between runs.
RESUME_KEYS = ("tasks_sha256", "config_sha256", "split", "index_mode", "k")


class RunError(RuntimeError):
    """The run cannot continue (leak check, broken hit contract, other inputs under one run id)."""


@dataclass
class RunSummary:
    run_dir: Path
    tasks: int = 0
    systems: int = 0
    searched: int = 0  # timed searches written in this run
    skipped: int = 0  # task and system pairs already done (resume)
    seconds: float = 0.0
    index_calls: int = 0
    by_repo: dict[str, int] = field(default_factory=dict)


def _eval_git() -> dict[str, Any]:
    here = Path(__file__).resolve().parent
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=here, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=here, capture_output=True, text=True)
    if sha.returncode != 0:
        return {"sha": None, "dirty": None}
    return {"sha": sha.stdout.strip(), "dirty": bool(dirty.stdout.strip())}


def _read_run_file(path: Path) -> list[dict]:
    try:
        return read_jsonl(path)
    except ValueError as exc:
        raise RunError(f"cannot resume: {exc}") from None


def order_tasks(tasks: list[Task]) -> dict[str, list[Task]]:
    """Tasks grouped by repo (sorted), each group in commit-date order of base_commit, ties by ID."""
    by_repo: dict[str, list[Task]] = {}
    for task in tasks:
        by_repo.setdefault(task.repo, []).append(task)
    return {
        repo: sorted(group, key=lambda t: (repos.commit_time(repo, t.base_commit), t.id))
        for repo, group in sorted(by_repo.items())
    }


def run(
    tasks_file: Path | str,
    config_file: Path | str,
    run_id: str,
    *,
    split: str = "dev",
    repo_filter: list[str] | None = None,
    limit_per_repo: int | None = None,
    index_mode: str = "update",
    k: int = 50,
    keep_indexes: bool = False,
    progress: Callable[[str], None] = lambda message: None,
) -> RunSummary:
    if not _RUN_ID_RE.match(run_id):
        raise RunError(f"run id {run_id!r} may only use letters, digits, '_', '.', '-'")
    if index_mode not in ("update", "rebuild"):
        raise RunError(f"index mode {index_mode!r} must be 'update' or 'rebuild'")
    start = time.perf_counter()
    tasks_file, config_file = Path(tasks_file), Path(config_file)

    # ---- inputs
    tasks = select(load_tasks(tasks_file), split)
    if repo_filter:
        tasks = [t for t in tasks if t.repo in set(repo_filter)]
    specs = load_systems(config_file)
    systems: list[Retriever] = [make_system(spec) for spec in specs]
    ordered = order_tasks(tasks)
    if limit_per_repo is not None:
        ordered = {repo: group[:limit_per_repo] for repo, group in ordered.items()}

    # ---- run folder and meta (resume only with the same inputs)
    run_dir = runs_dir() / run_id
    meta_path = run_dir / "meta.json"
    meta = {
        "run_id": run_id,
        "cmeval_version": __version__,
        "cmeval_git": _eval_git(),
        "tasks_file": str(tasks_file.resolve()),
        "tasks_sha256": _sha256(tasks_file),
        "config_file": str(config_file.resolve()),
        "config_sha256": _sha256(config_file),
        "config_text": config_file.read_text(encoding="utf-8"),
        "split": split,
        "index_mode": index_mode,
        "k": k,
        "systems": [
            {"name": spec.name, "adapter": spec.adapter, "granularity": s.granularity,
             "index_key": s.index_key(), "describe": s.describe()}
            for spec, s in zip(specs, systems)
        ],
        "machine": {"platform": platform.platform(), "processor": platform.processor() or platform.machine(),
                    "python": sys.version.split()[0]},
    }
    if meta_path.exists():
        old = json.loads(meta_path.read_text(encoding="utf-8"))
        changed = [key for key in RESUME_KEYS if old.get(key) != meta[key]]
        if changed:
            raise RunError(f"run id {run_id!r} exists with other inputs ({', '.join(changed)}); use a new run id")
        meta["started"] = old.get("started")
        meta["resumed"] = old.get("resumed", 0) + 1
    else:
        meta["started"] = _now()
    run_dir.mkdir(parents=True, exist_ok=True)
    meta.update(status="running", filters={"repos": repo_filter, "limit_per_repo": limit_per_repo})
    _write_json(meta_path, meta)

    summary = RunSummary(run_dir=run_dir, tasks=sum(len(g) for g in ordered.values()), systems=len(systems))
    out_files = {s.name: run_dir / f"{s.name}.jsonl" for s in systems}
    index_file = run_dir / "index.jsonl"
    for path in (*out_files.values(), index_file):
        if drop_unfinished_line(path):
            progress(f"{path.name}: dropped an unfinished last line from a stopped run")
    done = {s.name: {line["task_id"] for line in _read_run_file(out_files[s.name])} for s in systems}
    # (repo, index_key) pairs with a finished build or update. An index folder without one holds
    # a build that was stopped: it is deleted and built again from empty, so the results and the
    # build time are the same as in a run that never stopped.
    indexed = {(r["repo"], r["index_key"]) for r in _read_run_file(index_file)}
    groups: dict[str, list[Retriever]] = {}
    for s in systems:
        groups.setdefault(s.index_key(), []).append(s)
    warmed: set[str] = set()
    index_root = indexes_dir() / run_id

    try:
        for repo_number, (repo, group_tasks) in enumerate(ordered.items(), start=1):
            todo = [t for t in group_tasks if any(t.id not in done[s.name] for s in systems)]
            summary.skipped += sum(1 for t in group_tasks for s in systems if t.id in done[s.name])
            if not todo:
                continue
            # Always a new worktree: one left by a stopped run may be half checked out.
            repos.discard_live(repo, f"run-{run_id}")
            worktree = repos.checkout(repo, todo[0].base_commit, name=f"run-{run_id}")
            try:
                for task_number, task in enumerate(todo, start=1):
                    progress(f"[repo {repo_number}/{len(ordered)}] {repo}  task {task_number}/{len(todo)}  {task.id}")
                    repos.move_to(worktree, task.base_commit)
                    if repos.head(worktree) != task.base_commit:  # leak check: never search the wrong code
                        raise RunError(f"{task.id}: worktree is at {repos.head(worktree)}, not {task.base_commit}")
                    for key, members in groups.items():
                        if all(task.id in done[m.name] for m in members):
                            continue  # resume: this group already searched this task
                        index_dir = index_root / repos.slug(repo) / key
                        if index_dir.exists() and (repo, key) not in indexed:
                            shutil.rmtree(index_dir)  # no service has it open yet: this is a new process
                        for position, system in enumerate(members):
                            fresh = position == 0 and (index_mode == "rebuild" or not index_dir.exists())
                            index_dir.mkdir(parents=True, exist_ok=True)
                            report = (system.build if fresh else system.update)(worktree, index_dir)
                            summary.index_calls += 1
                            _append_jsonl(index_file, {
                                "repo": repo, "commit": task.base_commit, "task_id": task.id, "index_key": key,
                                "system": system.name, "mode": "build" if fresh else "update", "report": report.to_dict(),
                            })
                            indexed.add((repo, key))
                    for system in systems:
                        if task.id in done[system.name]:
                            continue
                        if system.name not in warmed:  # the first search may load a model: never time it
                            system.search(WARMUP_QUERY, 1)
                            warmed.add(system.name)
                        t0 = time.perf_counter()
                        hits = system.search(task.query, k)
                        search_ms = (time.perf_counter() - t0) * 1000
                        try:
                            check_hits(hits, system.granularity, k, system.name)
                        except RetrieverError as exc:
                            raise RunError(f"{task.id}: {exc}") from None
                        _append_jsonl(out_files[system.name], {
                            "task_id": task.id, "commit": task.base_commit, "search_ms": round(search_ms, 3),
                            "hits": [h.to_dict() for h in hits],
                        })
                        done[system.name].add(task.id)
                        summary.searched += 1
                    summary.by_repo[repo] = summary.by_repo.get(repo, 0) + 1
            finally:
                for system in systems:
                    system.close()  # frees in-memory state for this repo; index folders stay for resume
                repos.remove_worktree(worktree)
    except BaseException as exc:
        meta.update(status="failed", error=f"{type(exc).__name__}: {exc}", ended=_now())
        _write_json(meta_path, meta)
        raise

    if not keep_indexes:
        shutil.rmtree(index_root, ignore_errors=True)
    summary.seconds = time.perf_counter() - start
    meta.update(status="done", ended=_now(), error=None, searched=summary.searched, skipped=summary.skipped)
    _write_json(meta_path, meta)
    return summary
