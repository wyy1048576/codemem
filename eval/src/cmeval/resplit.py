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
  test_patch  files that the collector classes as test, files that the task's test_patch has
              already (the Rust and Go collector puts fixtures and #[cfg(test)]-only source files
              there), and files that match the recipe's test_paths (default: made from the folders
              of the recipe's test_files)
  left out    files that match leave_out (default: CI files and change logs), with the pattern

A file that the collector classes as code always stays in the patch. The code files must be the
same as in the task's patch, with the same number of changed lines; else the task is not split
and stays as it is. So the gold labels, which come from the code files, stay valid, and
generate.difficulty, which counts code files only, gives the same class.

A task whose change has no file to add stays byte-identical, so its validation fingerprint and
saved records stay valid. A changed task gets the tag "resplit" (what moved), and two tags on
dependencies (see deps.py): "dependency_needed" lists each third-party requirement that the fix
adds or raises in a file the image installs from (the recipe's dependency_paths). Such a task
leaves the candidate pool (generate.in_pool): the image has the dependencies of the base commit,
and the tests run with the network off. "dependency_other" lists the other changes of dependency
files, with the old and the new requirement text.

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

from . import __version__, deps, repos
from .files import now, sha256_file, write_json
from .generate import Recipe, changed_files, changed_lines, difficulty
from .patches import TEST_DIRS, TOP_TEST_DIRS, classify_path, diff_sections, file_paths
from .tasks import Task, load_tasks, save_tasks

KIND = "resplit"
# CI files, change logs and reStructuredText documentation: no build and no test reads them in
# the repos so far (pandas: doc/source/whatsnew/*.rst). Markdown stays: playwright builds its
# types from docs/src/api/*.md.
DEFAULT_LEAVE_OUT = (".github/**", ".circleci/**", ".azure-pipelines/**", ".gitlab-ci.yml", "**/CHANGELOG*",
                     "**/newsfragments/**", "**/*.rst")
# Files that name a repo's dependencies. A recipe's dependency_paths names the files that its image
# installs from (its deps_files, its lock files, vendored code). A file of this list that the recipe
# does not name is still read, and its changes go to the weak tag only.
DEFAULT_DEPENDENCY_PATHS = ("**/requirements*.txt", "**/requirements/*.txt", "**/constraints*.txt", "**/pyproject.toml",
                            "**/setup.cfg", "**/environment*.yml", "**/uv.lock", "**/poetry.lock", "**/package.json",
                            "**/package-lock.json", "**/yarn.lock", "**/pnpm-lock.yaml", "**/Cargo.toml",
                            "**/Cargo.lock", "**/go.mod", "**/go.sum", "**/vendor/modules.txt", "**/vcpkg.json",
                            "**/conanfile.*", "**/browsers.json", "**/.npmrc")
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
    """Test folders made from the recipe's test_files: each glob cut after its first folder with a
    test name (tests, test, testing...). So "pandas/tests/**/test_*.py" gives "pandas/tests/**",
    "tests/library/**/*.spec.ts" gives "tests/**", and "providers/**/tests/unit/**/test_*.py" gives
    "providers/**/tests/**". A glob without a folder with a test name gives nothing: its files are
    tests by their names, and its folders hold code too ("pkg/**/*_test.go")."""
    names = TEST_DIRS | TOP_TEST_DIRS
    found = set()
    for suite in recipe.suites:
        for glob in suite.test_files:
            parts = []
            for part in glob.split("/")[:-1]:
                parts.append(part)
                if part.lower() in names:
                    found.add("/".join(parts) + "/**")
                    break
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


def task_test_files(task: Task) -> frozenset[str]:
    """Files of the task's test patch: they stay on the test side, also a file that the collector
    would class as code (a .py fixture of ruff, a Rust file with #[cfg(test)] changes only)."""
    return frozenset(changed_files(task.test_patch or ""))


def same_code(diff: str, task: Task) -> bool:
    """True when the code files of a whole change are the task's code files, with as many changed lines."""
    code = "".join(s for kind, _, s, _ in classify_sections(diff, Rules((), (), ()), task_test_files(task))
                   if kind == "code")
    return changed_files(code) == changed_files(task.patch) and changed_lines(code) == changed_lines(task.patch)


def reader(repo: str, old: str, new: str) -> deps.Reader:
    """read(side, path): the text of a file at commit old ("old") or new ("new"), or None."""
    cache: dict[tuple[str, str], str | None] = {}

    def read(side: str, path: str) -> str | None:
        if (side, path) not in cache:
            commit = old if side == "old" else new
            proc = repos._git("show", f"{commit}:{path}", cwd=repos.clone_path(repo), check=False, text=False)
            cache[side, path] = proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else None
        return cache[side, path]

    return read


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

def classify_sections(diff: str, rules: Rules, task_tests: frozenset[str] = frozenset()) -> list[tuple[str, str, str, str]]:
    """(side, path, diff of the file, reason) for each file of a whole change. side is code,
    test, fix or out; the reason names the rule. task_tests: the files of the task's test patch."""
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
        if path in task_tests or (old and old in task_tests):
            result.append(("test", path, section, "test file (task)"))
        elif file_class == "code" and not binary:
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
    dependency_needed: list[dict] = field(default_factory=list)
    dependency_other: dict = field(default_factory=dict)
    problem: str | None = None
    had_test_patch: bool = False  # the task before the split


def resplit_task(task: Task, diff: str, rules: Rules, read: deps.Reader | None = None) -> Outcome:
    """Split one task with its whole change `diff`. read gives the files at the base commit and at
    the fix commit, for the dependency tags (None: files are read from the diff, which is complete
    for a new file only). Raises ResplitError when the code files differ."""
    sections = classify_sections(diff, rules, task_test_files(task))
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
    moved = [(p, file_paths(s)[0]) for p, s in fix]  # (path after the fix, path before it)
    analysis = deps.analyse(moved, read or _diff_reader(fix), rules.dependency_paths, DEFAULT_DEPENDENCY_PATHS, match)
    needed, other = analysis.tags()
    new_patch = task.patch + "".join(s for _, s in fix)
    if difficulty(new_patch) != difficulty(task.patch):
        raise ResplitError("the difficulty class would change")
    tags = {**task.tags,
            "has_test_patch": bool(test),
            "resplit": {"test_added": test_added, "fix_added": fix_added, "left_out": [p for p, _ in left_out]},
            "dependency_needed": needed, "dependency_other": other}
    tags.pop("dependency_files", None)  # the tag of the first version of this module
    new = replace(task, patch=new_patch, test_patch="".join(s for _, s in test) or None, tags=tags)
    return Outcome(new, True, test_added, fix_added, left_out, needed, other, had_test_patch=bool(task.test_patch))


def _diff_reader(fix: list[tuple[str, str]]) -> deps.Reader:
    """A reader that knows only what the diffs show: the whole text of a new or a deleted file."""
    texts: dict[tuple[str, str], str] = {}
    for path, section in fix:
        lines = section.splitlines()
        if "\nnew file mode" in "\n" + "\n".join(lines[:4]):
            texts["new", path] = "".join(line[1:] + "\n" for line in lines if line.startswith("+") and not line.startswith("+++"))
        elif "\ndeleted file mode" in "\n" + "\n".join(lines[:4]):
            texts["old", path] = "".join(line[1:] + "\n" for line in lines if line.startswith("-") and not line.startswith("---"))
    return lambda side, path: texts.get((side, path))


def resplit_tasks(recipe: Recipe, tasks: list[Task], ref: str = "HEAD") -> tuple[list[Outcome], Rules]:
    """Split every task of the recipe's repo. A task that cannot be split stays as it is, with
    its problem in the outcome."""
    used = rules(recipe)
    outcomes = []
    for task in tasks:
        if task.repo != recipe.repo:
            continue
        try:
            commit, diff = fix_change(task, ref)
            outcomes.append(resplit_task(task, diff, used, reader(task.repo, task.base_commit, commit)))
        except (ResplitError, repos.RepoError) as exc:
            outcomes.append(Outcome(task, problem=str(exc), had_test_patch=bool(task.test_patch)))
    return outcomes, used


def summary(outcomes: list[Outcome]) -> dict:
    """Counts for the meta file and the report."""
    changed = [o for o in outcomes if o.changed]
    reasons = Counter(reason for o in outcomes for _, reason in o.left_out)
    needed = Counter(difficulty(o.task.patch) for o in changed if o.dependency_needed)
    other = Counter(difficulty(o.task.patch) for o in changed if o.dependency_other.get("changes") or o.dependency_other.get("files"))
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
        "with_dependency_needed": sum(needed.values()),
        "with_dependency_needed_by_difficulty": {level: needed[level] for level in ("easy", "medium", "hard")},
        "dependency_needed": {o.task.id: o.dependency_needed for o in changed if o.dependency_needed},
        "with_dependency_other": sum(other.values()),
        "with_dependency_other_by_difficulty": {level: other[level] for level in ("easy", "medium", "hard")},
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
