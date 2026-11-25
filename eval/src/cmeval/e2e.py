"""End-to-end runs: grade what a coding agent left behind (plan section 4.7).

The grader takes the agent's changes as a unified diff and judges them in a fresh container of
the task's image (made by `cmeval generate`):

  1. apply the agent's changes
  2. put the hidden test files in place. They are the test files of the real pull request, and
     they overwrite any version of those files that the agent wrote
  3. run the task's test command

The task is completed when every fail_to_pass test passes and every pass_to_pass test passes.
Both lists come from the task's validation (tests.json). Everything else is not completed:
changes that do not apply, a build that breaks, a failing test, an empty change.

The grader check runs the grader on the real fix and on an empty change of each task. The real
fix must complete the task, and the empty change must not.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from .generate import (PASS, GenerateError, Recipe, image_exists, image_fingerprint, image_label, read_results,
                       read_times, refresh_lines, run_in_container, task_tag, test_run_line, tests_path,
                       validation_fingerprint)
from .patches import diff_sections as _sections, file_paths
from .paths import e2e_dir
from .tasks import Task

MAX_FAILED_SHOWN = 50

REASONS = ("ok", "empty change", "changes do not apply", "hidden tests do not apply", "build failed",
           "tests timed out", "no test results", "tests failed")

# The lines that run.sh writes to times.txt when a step fails, and the reason of each.
_STEP_REASONS = (("agent patch failed", "changes do not apply"), ("test patch failed", "hidden tests do not apply"),
                 ("refresh failed", "build failed"))


# ---- patches

def split_patch(patch: str) -> list[tuple[str, str]]:
    """A git unified diff, cut into one part for each file: (path after the change, text of the
    part). A deleted file has its old path. Text before the first diff has the path "".
    The parts put together give the input again."""
    parts = []
    for section in _sections(patch):
        old, new = file_paths(section)
        parts.append((new or old or "", section))
    return parts


def drop_files(patch: str, files: set[str]) -> str:
    """The patch without the diffs of these paths. A diff is dropped when its path before or its
    path after the change is in `files`."""
    return "".join(section for section in _sections(patch) if not (set(file_paths(section)) & files))


def patch_files(patch: str) -> set[str]:
    """Every path of a patch, before and after the change."""
    return {path for section in _sections(patch) for path in file_paths(section) if path}


def is_empty(patch: str) -> bool:
    """True when the patch has no diff of a file."""
    return not patch_files(patch)


# ---- grading

def _grade_script(recipe: Recipe, task: Task, has_agent_patch: bool) -> str:
    """The shell script that grades a change inside the task's container. It writes to /work."""
    agent = ("git apply --whitespace=nowarn /work/agent.patch"
             " || { echo 'agent patch failed' >> /work/times.txt; exit 3; }\n") if has_agent_patch else ""
    return (
        # The files must be readable outside the container, also after a step fails.
        "trap 'chmod -R a+rwX /work' EXIT\n"
        "cd /testbed\n"
        f"{agent}"
        "git apply --whitespace=nowarn /work/test.patch || { echo 'test patch failed' >> /work/times.txt; exit 4; }\n"
        f"{refresh_lines(recipe)}\n"
        f"{test_run_line(recipe, task, 'grade')}\n"
    )


def _failed_step(times_text: str) -> str | None:
    """The reason of the first step that failed, from the lines of times.txt."""
    for marker, reason in _STEP_REASONS:
        if marker in times_text:
            return reason
    return None


def verdict(results: dict[str, str], tests: dict, *, empty: bool = False, failed_step: str | None = None) -> dict:
    """Judge one graded run. `results` are the test results, `tests` the two lists of tests.json,
    `failed_step` the reason of a step that failed before the tests (see _STEP_REASONS), or
    "tests timed out"."""
    f2p, p2p = tests.get("fail_to_pass", []), tests.get("pass_to_pass", [])
    missed = [t for t in f2p + p2p if results.get(t) != PASS]
    if failed_step:
        reason = failed_step
    elif not results:
        reason = "no test results"
    elif missed:
        reason = "tests failed"
    else:
        reason = "ok"
    record = {
        "completed": reason == "ok" and not empty,
        "reason": reason,
        "fail_to_pass_total": len(f2p),
        "fail_to_pass_passed": sum(1 for t in f2p if results.get(t) == PASS),
        "pass_to_pass_total": len(p2p),
        "pass_to_pass_passed": sum(1 for t in p2p if results.get(t) == PASS),
        "failed_tests": missed[:MAX_FAILED_SHOWN],
        "passes_without_change": False,
    }
    if empty:
        # An empty change never completes a task. When the tests pass without a change, the task is bad.
        record.update(reason="empty change", passes_without_change=reason == "ok")
    return record


def load_tests(recipe: Recipe, task: Task) -> dict:
    path = tests_path(recipe, task)
    if not path.exists():
        raise GenerateError(f"{task.id}: no tests.json; validate the task with cmeval generate first ({path})")
    tests = json.loads(path.read_text(encoding="utf-8"))
    # The lists are only good for the recipe and the task that they were made from.
    if tests.get("fingerprint") != validation_fingerprint(recipe, task, tests.get("repeats")):
        raise GenerateError(f"{task.id}: tests.json was made from another version of the recipe or the task; "
                            f"run cmeval generate again ({path})")
    return tests


def grade(recipe: Recipe, task: Task, agent_patch: str, out: Path, cpus: int = 8) -> dict:
    """Grade an agent's change in a fresh container of the task's image. `out` is made again and
    holds the inputs, the logs, and grade.json. Returns the record."""
    tests = load_tests(recipe, task)
    tag = task_tag(recipe, task)
    if not image_exists(tag):
        raise GenerateError(f"{task.id}: image {tag} does not exist; build it with cmeval generate")
    if image_label(tag) != image_fingerprint(recipe, task):
        raise GenerateError(f"{task.id}: image {tag} was built from another version of the recipe or the task; "
                            "run cmeval generate again")
    # The hidden test files win over the agent's version of them.
    patch = drop_files(agent_patch, patch_files(task.test_patch or ""))
    empty = is_empty(patch)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "agent.patch").write_text(patch, encoding="utf-8")
    (out / "test.patch").write_text(task.test_patch or "", encoding="utf-8")
    (out / "run.sh").write_text(_grade_script(recipe, task, has_agent_patch=not empty), encoding="utf-8")
    # Each suite has its own limit inside the container. One more limit is for the patches and the refresh.
    limit = recipe.timeout_min * 60 * (len(recipe.suites) + 1)
    start = time.monotonic()
    finished = run_in_container(tag, out, prefix="cmeval-grade", limit=limit, cpus=cpus)
    seconds = time.monotonic() - start

    times_text = (out / "times.txt").read_text(encoding="utf-8") if (out / "times.txt").exists() else ""
    runs = [run for run in read_times(out) if run.name == "grade"]
    failed_step = _failed_step(times_text)
    if failed_step is None and (not finished or any(run.timed_out for run in runs)):
        failed_step = "tests timed out"
    unreadable: list[Path] = []
    record = verdict(read_results(out, "grade", unreadable), tests, empty=empty, failed_step=failed_step)
    record.update(grade_s=round(seconds, 1), test_run_s=round(sum(run.ms for run in runs) / 1000, 1) if runs else None,
                  junit_unreadable=len(unreadable))
    (out / "grade.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


# ---- grader check

def grader_check_dir(recipe: Recipe, task: Task) -> Path:
    return e2e_dir() / "grader-check" / recipe.name / task.id


def check_task(recipe: Recipe, task: Task, cpus: int = 8) -> dict:
    """Grade the real fix and an empty change of one task."""
    folder = grader_check_dir(recipe, task)
    start = time.monotonic()
    record: dict = {"id": task.id, "passed": False}
    try:
        gold = grade(recipe, task, task.patch, folder / "gold", cpus=cpus)
        empty = grade(recipe, task, "", folder / "empty", cpus=cpus)
    except (GenerateError, subprocess.TimeoutExpired, OSError) as exc:
        record.update(problem=f"error: {exc}", error=True, seconds=round(time.monotonic() - start, 1))
        return record
    problems = []
    if not gold["completed"]:
        problems.append("the real fix does not complete the task")
    if empty["passes_without_change"]:
        problems.append("the tests pass without a change")
    elif empty["completed"]:
        problems.append("the empty change completes the task")
    record.update(passed=not problems, problem="; ".join(problems) or "ok", gold=gold, empty=empty,
                  seconds=round(time.monotonic() - start, 1))
    return record


def grader_check(recipe: Recipe, tasks: list[Task], *, jobs: int = 1, cpus: int = 8,
                 progress: Callable[[str], None] = lambda message: None) -> list[dict]:
    """The grader check of each task that has tests.json, `jobs` at a time. Records come back in
    the order of `tasks`."""
    tasks = [t for t in tasks if tests_path(recipe, t).exists()]

    def one(task: Task) -> dict:
        record = check_task(recipe, task, cpus=cpus)
        progress(format_check(record))
        return record

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(one, tasks))


def format_check(record: dict) -> str:
    gold = record.get("gold", {}).get("reason", "-")
    empty = record.get("empty", {}).get("reason", "-")
    if record.get("empty", {}).get("passes_without_change"):
        empty += " (tests pass)"
    return f"{record['id']}  {record['problem']}  gold: {gold}  empty: {empty}  {record['seconds']} s"
