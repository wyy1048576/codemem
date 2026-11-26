"""Split the change of a task again, with the repo's own rule for test files.

The collector puts each changed file of a fix in one class by its folder and extension
(patches.classify_path). Code goes to the task's patch, tests go to test_patch, and every other
file is dropped. So a task loses the files of its fix that are not code of a known language:
test data, snapshots and fixtures on the test side, build files, data and configuration on the
fix side. duckdb loses its sqllogictest files (test/**/*.test), so most duckdb tasks have no test
change at all. Such a task can come out invalid, or need a file that the agent never sees. The
plan sets what counts as a test per repo, in its recipe.

This module takes the whole change of the fix from the clone again, from the base commit to the
fix commit, with binary files in full (git diff --binary). It puts each file on one side:

  patch       the task's code patch as it is, and every other file that is not a test and not
              left out (build files, data, configuration, documentation)
  test_patch  files that the collector classes as test, and files that match the recipe's
              test_paths (default: made from the folders of the recipe's test_files)
  left out    files that match leave_out (default: CI files and change logs), with the pattern

A file that the collector classes as code always stays in the patch. The code files must be the
same as in the task's patch, with the same number of changed lines; else the task is not split
and stays as it is. So the gold labels, which come from the code files, stay valid, and
generate.difficulty, which counts code files only, gives the same class.

A task whose change has no file to add stays byte-identical, so its validation fingerprint and
saved records stay valid. A changed task gets the tag "resplit" (what moved), and the tag
"dependency_files" when its fix changes a file that names dependencies: the image has the
dependencies of the base commit, and the tests run with the network off.

The fix commit: the task has no sha of it. For a merge or a squash merge it is the child of the
base commit on the first-parent line of the default branch. For a rebase merge it is a later
commit on that line. The first commit on the line whose code files match the task's patch is
taken.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
from pathlib import Path

from . import __version__, repos
from .files import now, sha256_file, write_json
from .generate import Recipe, changed_files, changed_lines, difficulty
from .patches import TEST_DIRS, TOP_TEST_DIRS, classify_path, diff_sections, file_paths
from .tasks import Task, load_tasks, save_tasks

KIND = "resplit"
# CI files and change logs: no build and no test reads them.
DEFAULT_LEAVE_OUT = (".github/**", ".circleci/**", ".azure-pipelines/**", ".gitlab-ci.yml", "**/CHANGELOG*",
                     "**/newsfragments/**")
# Files that name a repo's dependencies.
DEFAULT_DEPENDENCY_PATHS = ("**/requirements*.txt", "**/requirements/*.txt", "**/constraints*.txt", "**/pyproject.toml",
                            "**/setup.cfg", "**/environment*.yml", "**/uv.lock", "**/poetry.lock", "**/package.json",
                            "**/package-lock.json", "**/yarn.lock", "**/pnpm-lock.yaml", "**/Cargo.toml",
                            "**/Cargo.lock", "**/go.mod", "**/go.sum", "**/vcpkg.json", "**/conanfile.*")
# How far down the first-parent line the fix commit of a rebase merge can be.
MAX_FIX_STEPS = 50


class ResplitError(RuntimeError):
    """A task cannot be split again (no fix commit found, or its code files differ)."""


def match(path: str, patterns: tuple[str, ...]) -> str | None:
    """The first glob that the path matches, or None. "*" also crosses "/", as in a recipe's
    test_files; "a/**/b" also matches "a/b", and "**/b" also matches "b" at the top."""
    for p in patterns:
        if fnmatchcase(path, p) or fnmatchcase(path, p.replace("/**/", "/")) or (
                p.startswith("**/") and fnmatchcase(path, p[3:])):
            return p
    return None


def default_test_paths(recipe: Recipe) -> tuple[str, ...]:
    """Test folders made from the recipe's test_files: each glob up to its first wildcard, cut
    after the first folder with a test name (tests, test, testing...). So "pandas/tests/**/test_*.py"
    gives "pandas/tests/**", and "tests/library/**/*.spec.ts" gives "tests/**"."""
    names = TEST_DIRS | TOP_TEST_DIRS
    found = set()
    for suite in recipe.suites:
        for glob in suite.test_files:
            parts = []
            for part in glob.split("/")[:-1]:
                if any(c in part for c in "*?["):
                    break
                parts.append(part)
                if part.lower() in names:
                    break
            if parts:
                found.add("/".join(parts) + "/**")
    return tuple(sorted(found))


@dataclass(frozen=True)
class Rules:
    test_paths: tuple[str, ...]
    leave_out: tuple[str, ...]
    dependency_paths: tuple[str, ...]
    test_paths_default: bool = False


def rules(recipe: Recipe) -> Rules:
    """The recipe's rules, with the defaults for the fields that it does not give."""
    return Rules(test_paths=recipe.test_paths or default_test_paths(recipe),
                 leave_out=DEFAULT_LEAVE_OUT if recipe.leave_out is None else recipe.leave_out,
                 dependency_paths=DEFAULT_DEPENDENCY_PATHS if recipe.dependency_paths is None else recipe.dependency_paths,
                 test_paths_default=not recipe.test_paths)


# ---- git

def _first_parent_line(task: Task, ref: str) -> list[str]:
    """Commits after the base commit on the first-parent line of ref, oldest first."""
    repos.ensure_commit(task.repo, task.base_commit)
    out = repos._git("rev-list", "--first-parent", "--reverse", f"{task.base_commit}..{ref}",
                     cwd=repos.clone_path(task.repo)).stdout.split()
    return out[:MAX_FIX_STEPS]


def full_diff(repo: str, old: str, new: str) -> str:
    """The whole change from old to new, as repos.diff makes it, with binary files in full."""
    repos.ensure_commit(repo, old)
    repos.ensure_commit(repo, new)
    proc = repos._git("-c", "core.quotepath=false", "diff", "-M", "--binary", "--no-color", "--no-ext-diff", old, new,
                      cwd=repos.clone_path(repo), text=False)
    return proc.stdout.decode("utf-8", "replace")


def same_code(diff: str, task: Task) -> bool:
    """True when the code files of a whole change are the task's code files, with as many changed lines."""
    code = "".join(s for kind, _, s, _ in classify_sections(diff, Rules((), (), ())) if kind == "code")
    return changed_files(code) == changed_files(task.patch) and changed_lines(code) == changed_lines(task.patch)


def fix_change(task: Task, ref: str = "HEAD") -> tuple[str, str]:
    """(fix commit, whole change from the base commit to it). See the module docstring."""
    line = _first_parent_line(task, ref)
    if not line:
        raise ResplitError(f"no commit after {task.base_commit[:12]} on {ref}")
    if repos.parents(task.repo, line[0])[:1] != [task.base_commit]:
        raise ResplitError(f"{task.base_commit[:12]} is not on the first-parent line of {ref}")
    for commit in line if task.fix.merge_type == "rebase" else line[:1]:
        diff = full_diff(task.repo, task.base_commit, commit)
        if same_code(diff, task):
            return commit, diff
    raise ResplitError("no commit after the base commit has the code files of the task's patch")


# ---- the split

def classify_sections(diff: str, rules: Rules) -> list[tuple[str, str, str, str]]:
    """(side, path, diff of the file, reason) for each file of a whole change. side is code,
    test, fix or out; the reason names the rule."""
    result = []
    for section in diff_sections(diff):
        old, new = file_paths(section)
        path = new or old
        if not path:
            continue  # text before the first diff
        file_class = classify_path(old or new)[0]
        binary = "\nGIT binary patch\n" in section or "\nBinary files " in section
        test_glob = match(path, rules.test_paths) or (match(old, rules.test_paths) if old else None)
        out_glob = match(path, rules.leave_out)
        if file_class == "code" and not binary:
            result.append(("code", path, section, "code file"))
        elif file_class == "test":
            result.append(("test", path, section, "test file (collector)"))
        elif test_glob:
            result.append(("test", path, section, f"test_paths {test_glob}"))
        elif out_glob:
            result.append(("out", path, section, f"leave_out {out_glob}"))
        else:
            result.append(("fix", path, section, "not code, not a test"))
    return result


@dataclass
class Outcome:
    task: Task                  # the new task, or the old one when nothing changed
    changed: bool = False
    test_added: list[str] = field(default_factory=list)
    fix_added: list[str] = field(default_factory=list)
    left_out: list[tuple[str, str]] = field(default_factory=list)   # (path, reason)
    dependency_files: list[str] = field(default_factory=list)
    problem: str | None = None
    had_test_patch: bool = False  # the task before the split


def resplit_task(task: Task, diff: str, rules: Rules) -> Outcome:
    """Split one task with its whole change `diff`. Raises ResplitError when the code files differ."""
    sections = classify_sections(diff, rules)
    code = "".join(s for side, _, s, _ in sections if side == "code")
    if changed_files(code) != changed_files(task.patch) or changed_lines(code) != changed_lines(task.patch):
        raise ResplitError("the code files of the fix commit differ from the task's patch")
    old_tests = set(changed_files(task.test_patch or ""))
    test = [(p, s) for side, p, s, _ in sections if side == "test"]
    fix = [(p, s) for side, p, s, _ in sections if side == "fix"]
    left_out = [(p, reason) for side, p, _, reason in sections if side == "out"]
    test_added = sorted({p for p, _ in test} - old_tests)
    fix_added = [p for p, _ in fix]
    if not test_added and not fix_added:
        return Outcome(task, left_out=left_out, had_test_patch=bool(task.test_patch))
    overlap = sorted(set(task.gold.files) & {p for p, _ in test})
    if overlap:
        raise ResplitError(f"gold files would be test files: {overlap}")
    dependencies = [p for p in fix_added if match(p, rules.dependency_paths)]
    new_patch = task.patch + "".join(s for _, s in fix)
    if difficulty(new_patch) != difficulty(task.patch):
        raise ResplitError("the difficulty class would change")
    tags = {**task.tags,
            "has_test_patch": bool(test),
            "resplit": {"test_added": test_added, "fix_added": fix_added, "left_out": [p for p, _ in left_out]},
            "dependency_files": dependencies}
    new = replace(task, patch=new_patch, test_patch="".join(s for _, s in test) or None, tags=tags)
    return Outcome(new, True, test_added, fix_added, left_out, dependencies, had_test_patch=bool(task.test_patch))


def resplit_tasks(recipe: Recipe, tasks: list[Task], ref: str = "HEAD") -> tuple[list[Outcome], Rules]:
    """Split every task of the recipe's repo. A task that cannot be split stays as it is, with
    its problem in the outcome."""
    used = rules(recipe)
    outcomes = []
    for task in tasks:
        if task.repo != recipe.repo:
            continue
        try:
            _, diff = fix_change(task, ref)
            outcomes.append(resplit_task(task, diff, used))
        except (ResplitError, repos.RepoError) as exc:
            outcomes.append(Outcome(task, problem=str(exc), had_test_patch=bool(task.test_patch)))
    return outcomes, used


def summary(outcomes: list[Outcome]) -> dict:
    """Counts for the meta file and the report."""
    changed = [o for o in outcomes if o.changed]
    reasons = Counter(reason for o in outcomes for _, reason in o.left_out)
    return {
        "tasks": len(outcomes),
        "changed": len(changed),
        "unchanged": sum(1 for o in outcomes if not o.changed and not o.problem),
        "not_split": {o.task.id: o.problem for o in outcomes if o.problem},
        "with_test_files_added": sum(1 for o in changed if o.test_added),
        "with_fix_files_added": sum(1 for o in changed if o.fix_added),
        "test_files_added": sum(len(o.test_added) for o in changed),
        "fix_files_added": sum(len(o.fix_added) for o in changed),
        "files_left_out": dict(sorted(reasons.items())),
        "with_dependency_files": sum(1 for o in changed if o.dependency_files),
        "with_test_patch_before": sum(1 for o in outcomes if o.had_test_patch),
        "with_test_patch_after": sum(1 for o in outcomes if o.task.test_patch),
    }


@dataclass
class ResplitResult:
    out: Path | None
    tasks: list[Task]
    meta: dict


def resplit_file(recipe: Recipe, tasks_file: Path | str, out: Path | str | None, ref: str = "HEAD") -> ResplitResult:
    """Split the tasks of the recipe's repo in a task file again. With `out`, write them (and
    only them) to a new task file with a meta file; without it, only count (a dry run)."""
    tasks_file = Path(tasks_file)
    if out is not None and Path(out).resolve() == tasks_file.resolve():
        raise ResplitError(f"{out} would write over the source {tasks_file}; choose another --out")
    source_sha = sha256_file(tasks_file)
    tasks = load_tasks(tasks_file)
    outcomes, used = resplit_tasks(recipe, tasks, ref)
    if not outcomes:
        raise ResplitError(f"no task of {recipe.repo} in {tasks_file}")

    from .run import _eval_git  # the commit of the code that made the file

    meta = {
        "kind": KIND,
        "source": tasks_file.name,
        "source_sha256": source_sha,
        "repo": recipe.repo,
        "recipe": recipe.name,
        "test_paths": list(used.test_paths),
        "test_paths_from_test_files": used.test_paths_default,
        "leave_out": list(used.leave_out),
        "dependency_paths": list(used.dependency_paths),
        "rule": ("patch: the task's code patch as it was, and every other file that is not a test and is not "
                 "left out. test_patch: files the collector classes as test, and files that match test_paths. "
                 "Code files, gold labels and difficulty do not change. A task with nothing to add is unchanged."),
        **summary(outcomes),
        "cmeval_version": __version__,
        "cmeval_git": _eval_git(),
        "created": now(),
    }
    new_tasks = [o.task for o in outcomes]
    if out is not None:
        out = Path(out)
        save_tasks(out, new_tasks)
        write_json(out.with_suffix(".meta.json"), meta)
    return ResplitResult(Path(out) if out is not None else None, new_tasks, meta)
