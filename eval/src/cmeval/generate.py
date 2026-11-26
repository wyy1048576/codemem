"""Tasks with a test environment: build an image for a task, and validate its tests.

A collected task has the issue, the commit before the fix, the fix, and the test change. This
module adds the two steps that make it a task for an end-to-end run:

  build     an image of the repo at the task's commit, from the repo's recipe
  validate  run the task's test files before and after the real fix, several times

A recipe is one TOML file for each repo, in eval/envs/. Its fields:

  repo          "owner/name"
  base_image    the image that all tasks of the repo start from
  base_setup    shell commands, run once for the repo
  deps_files    files of the task's commit that the dependency step reads
  deps          shell commands that install the dependencies. "{exclude_newer}" becomes the end
                of the week (Sunday, UTC) of the task's commit. So a task can get packages of up
                to 6 days after its commit, and none that are newer
  build         shell commands, run in /testbed after the source of the commit is there
  refresh       shell commands, run after a patch is applied and before the tests
  env           variables that are set in the image, for the build and for the tests
  test_files    globs: which changed files of the test patch are given to the test command
  test          the test command. "{files}" and "{junit}" are replaced
  suite         for a repo with more than one test command: a list of tables, each with its own
                test_files and test. It replaces the two fields above
  parser        how results are read. Only "junit" exists
  timeout_min   the limit for one suite in one test run
  tag_match     a glob for the tag that the image's commit gets (git describe --match), for a
                repo that also has tags of other things, such as the crates of a part in Rust

A task is valid when at least one test does not pass in any run before the fix (it fails, it is
skipped, or it is missing) and passes in every run after it, no test that passed before the fix
fails after it or changes its result between runs, and no test run passes its time limit.

A task image and a validation record have a fingerprint: a short hash of the recipe fields and the
task fields that made them. An image, a record or a test list with another fingerprint is not
used. Docker is called through its command line. Output is kept under CMEVAL_HOME/generate/.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
import json
import os
import random
import re
import shlex
import shutil
import subprocess
import threading
import time
import tomllib
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, NamedTuple

from . import repos
from .patches import diff_sections, file_paths
from .paths import cmeval_home
from .tasks import Task

IMAGE_PREFIX = "cmeval-env"
CACHE_MOUNT = "--mount=type=cache,target=/root/.cache"
DEFAULT_REPEATS = 3
ADMISSION_N = 10
ADMISSION_PASS = 6
# Shares of an admission sample: easy, medium, hard.
ADMISSION_MIX = (("easy", 3), ("medium", 4), ("hard", 3))

FAIL, PASS, SKIP = "fail", "pass", "skip"
# Exit codes of `timeout`: 124 when the command stops after TERM, 137 when it needs KILL.
TIMEOUT_CODES = (124, 137)
BUILD_TIMEOUT_MIN = 60  # the limit for one docker build
FINGERPRINT_LABEL = "cmeval.fingerprint"
# Change this number when the validation script or the rules of judge() change, so old records are not used.
VALIDATION_VERSION = 1

# Tasks are built side by side, and git cannot change one clone from two threads at once.
_CLONE_LOCK = threading.Lock()


class GenerateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Suite:
    test_files: tuple[str, ...]
    test: str


@dataclass(frozen=True)
class Recipe:
    name: str
    repo: str
    base_image: str
    test: str = ""
    base_setup: tuple[str, ...] = ()
    deps_files: tuple[str, ...] = ()
    deps: tuple[str, ...] = ()
    build: tuple[str, ...] = ()
    refresh: tuple[str, ...] = ()
    test_files: tuple[str, ...] = ("**",)
    parser: str = "junit"
    timeout_min: int = 10
    env: tuple[tuple[str, str], ...] = ()
    suite: tuple[Suite, ...] = ()
    tag_match: str = ""

    @property
    def suites(self) -> tuple[Suite, ...]:
        return self.suite or (Suite(self.test_files, self.test),)


def default_envs_dir() -> Path:
    """eval/envs in the repo: one recipe for each repo."""
    return Path(__file__).resolve().parents[2] / "envs"


def generate_dir() -> Path:
    """Build contexts, logs and results: <recipe>/<task id>/."""
    return cmeval_home() / "generate"


def load_recipe(name_or_path: str | Path) -> Recipe:
    path = Path(name_or_path)
    if path.suffix != ".toml":
        path = default_envs_dir() / f"{name_or_path}.toml"
    if not path.exists():
        raise GenerateError(f"{path}: no such recipe")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    known = set(Recipe.__dataclass_fields__) - {"name"}
    unknown = sorted(set(data) - known)
    if unknown:
        raise GenerateError(f"{path}: unknown fields: {', '.join(unknown)}")
    for key in ("repo", "base_image"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise GenerateError(f"{path}: '{key}' is missing")
    suites = data.pop("suite", [])
    if bool(suites) == bool(data.get("test")):
        raise GenerateError(f"{path}: give 'test', or a list of 'suite' tables, and not both")
    for entry in suites:
        if set(entry) != {"test_files", "test"}:
            raise GenerateError(f"{path}: a suite has the fields test_files and test")
    data["suite"] = [Suite(tuple(entry["test_files"]), entry["test"]) for entry in suites]
    data["env"] = sorted((str(k), str(v)) for k, v in data.get("env", {}).items())
    if data.get("parser", "junit") != "junit":
        raise GenerateError(f"{path}: parser '{data['parser']}' does not exist")
    values = {k: tuple(v) if isinstance(v, list) else v for k, v in data.items()}
    return Recipe(name=path.stem, **values)


# ---- difficulty and the test files of a task

def changed_files(patch: str) -> list[str]:
    """Paths of a unified diff, as they are after the change. A deleted file has its old path."""
    paths = (file_paths(section) for section in diff_sections(patch))
    return sorted({new or old for old, new in paths if new or old})


def files_after(patch: str) -> list[str]:
    """Paths of a unified diff that exist after the change. A deleted file is left out."""
    return sorted({new for _, new in (file_paths(section) for section in diff_sections(patch)) if new})


def changed_lines(patch: str) -> int:
    return sum(1 for line in patch.splitlines()
               if line[:1] in "+-" and not line.startswith(("+++", "---")))


def difficulty(patch: str) -> str:
    """Size class of the real fix: easy (1 file, at most 15 changed lines), medium (at most 2
    files and 100 lines), or hard."""
    files, lines = len(changed_files(patch)), changed_lines(patch)
    if files == 1 and lines <= 15:
        return "easy"
    if files <= 2 and lines <= 100:
        return "medium"
    return "hard"


def _glob_match(path: str, pattern: str) -> bool:
    # fnmatch lets "*" cross "/", so "a/**/test_*.py" also matches files right below "a/".
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern.replace("/**/", "/"))


def suite_files(suite: Suite, task: Task) -> list[str]:
    # A test file that the test patch deletes does not exist when the tests run.
    files = files_after(task.test_patch or "")
    return [f for f in files if any(_glob_match(f, pattern) for pattern in suite.test_files)]


def task_test_files(recipe: Recipe, task: Task) -> list[str]:
    """The files of the task's test patch that a test command gets."""
    return sorted({f for suite in recipe.suites for f in suite_files(suite, task)})


def admission_sample(recipe: Recipe, tasks: list[Task], n: int = ADMISSION_N, seed: str | None = None) -> list[Task]:
    """A fixed sample of the repo's tasks with tests: 3 easy, 4 medium, 3 hard for n = 10."""
    pool: dict[str, list[Task]] = {"easy": [], "medium": [], "hard": []}
    for task in sorted(tasks, key=lambda t: t.id):
        if task.repo == recipe.repo and task.test_patch and task_test_files(recipe, task):
            pool[difficulty(task.patch)].append(task)
    rng = random.Random(seed or f"admission-{recipe.name}-1")
    chosen: list[Task] = []
    for level, share in ADMISSION_MIX:
        want = round(share * n / ADMISSION_N)
        chosen += rng.sample(pool[level], min(want, len(pool[level])))
    return chosen


# ---- docker

def _run(cmd: list[str], *, log: Path | None = None, timeout: float | None = None, cwd: Path | None = None,
         env: dict | None = None) -> subprocess.CompletedProcess:
    if log is None:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    with open(log, "ab") as out:
        out.write(f"\n$ {' '.join(cmd)}\n".encode())
        out.flush()
        return subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, timeout=timeout, cwd=cwd, env=env)


def image_exists(tag: str) -> bool:
    return _run(["docker", "image", "inspect", tag]).returncode == 0


def image_label(tag: str) -> str | None:
    """The fingerprint label of an image. None when the image or the label does not exist."""
    proc = _run(["docker", "image", "inspect", "-f", "{{json .Config.Labels}}", tag])
    if proc.returncode != 0:
        return None
    try:
        labels = json.loads(proc.stdout or "null")
    except ValueError:
        return None
    return labels.get(FINGERPRINT_LABEL) if isinstance(labels, dict) else None


def _docker_build(context: Path, tag: str, log: Path, *, label: str | None = None, no_cache: bool = False) -> None:
    env = {**os.environ, "DOCKER_BUILDKIT": "1"}
    options = ["--label", f"{FINGERPRINT_LABEL}={label}"] if label else []
    options += ["--no-cache"] if no_cache else []
    try:
        proc = _run(["docker", "build", "--progress=plain", *options, "-t", tag, str(context)], log=log, env=env,
                    timeout=BUILD_TIMEOUT_MIN * 60)
    except subprocess.TimeoutExpired:
        raise GenerateError(f"docker build of {tag} passed its limit of {BUILD_TIMEOUT_MIN} min; see {log}") from None
    if proc.returncode != 0:
        raise GenerateError(f"docker build of {tag} failed; see {log}")


def run_in_container(tag: str, work: Path, *, prefix: str, limit: float, cpus: int) -> bool:
    """Run /work/run.sh in a new container of the image, with `work` at /work and no network. The
    container has a name, so it can be removed when the limit passes or another error occurs (it
    does not stop when its client is killed). Returns False when the limit passed."""
    name = f"{prefix}-{uuid.uuid4().hex[:12]}"
    try:
        _run(["docker", "run", "--rm", "--name", name, "--network", "none", f"--cpus={cpus}", "-v", f"{work}:/work",
              tag, "bash", "/work/run.sh"], log=work / "docker.log", timeout=limit)
    except subprocess.TimeoutExpired:
        _run(["docker", "rm", "-f", name])
        return False
    except BaseException:
        _run(["docker", "rm", "-f", name])
        raise
    return True


def _run_lines(commands: tuple[str, ...]) -> str:
    return "".join(f"RUN {CACHE_MOUNT} {command}\n" for command in commands)


def base_tag(recipe: Recipe) -> str:
    digest = hashlib.sha256(json.dumps([recipe.base_image, recipe.base_setup, recipe.env]).encode()).hexdigest()[:12]
    return f"{IMAGE_PREFIX}/{recipe.name}:base-{digest}"


def build_base(recipe: Recipe) -> str:
    """The image that all tasks of the repo start from. Built once."""
    tag = base_tag(recipe)
    if image_exists(tag):
        return tag
    context = generate_dir() / recipe.name / "_base"
    context.mkdir(parents=True, exist_ok=True)
    dockerfile = (
        f"FROM {recipe.base_image}\n"
        + "".join(f"ENV {key}={json.dumps(value)}\n" for key, value in recipe.env)
        + _run_lines(recipe.base_setup)
        + "RUN git config --system user.email cmeval@localhost && git config --system user.name cmeval"
        + " && git config --system --add safe.directory '*'\n"
    )
    (context / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    _docker_build(context, tag, context / "build.log")
    return tag


def exclude_newer(commit_time: int) -> str:
    """The end of the week (Sunday, UTC) of a commit, as a date and time for the dependency step."""
    day = dt.datetime.fromtimestamp(commit_time, dt.timezone.utc).date()
    sunday = day + dt.timedelta(days=6 - day.weekday())
    return f"{sunday.isoformat()}T23:59:59Z"


def task_tag(recipe: Recipe, task: Task) -> str:
    return f"{IMAGE_PREFIX}/{recipe.name}:{task.id.lower()}"


def _digest(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def image_fingerprint(recipe: Recipe, task: Task) -> str:
    """A short hash of what makes a task image: the recipe fields of the build and the task's commit."""
    data = {"repo": recipe.repo, "base_image": recipe.base_image, "base_setup": recipe.base_setup,
            "env": recipe.env, "deps_files": recipe.deps_files, "deps": recipe.deps, "build": recipe.build,
            "task_repo": task.repo, "base_commit": task.base_commit}
    # Only when it is set, so that the images of recipes without it keep their fingerprint.
    if recipe.tag_match:
        data["tag_match"] = recipe.tag_match
    return _digest(data)


def validation_fingerprint(recipe: Recipe, task: Task, repeats: int | None) -> str:
    """A short hash of what makes a validation: the image fingerprint, the recipe fields of the tests, the
    task's two patches, and the number of runs. result.json and tests.json keep it."""
    return _digest({"image": image_fingerprint(recipe, task), "refresh": recipe.refresh,
                    "suites": [[suite.test_files, suite.test] for suite in recipe.suites], "parser": recipe.parser,
                    "timeout_min": recipe.timeout_min, "patch": task.patch, "test_patch": task.test_patch or "",
                    "repeats": repeats, "version": VALIDATION_VERSION})


def _export_source(repo: str, commit: str, dest: Path) -> None:
    """The files of a commit, without git's export rules (a plain checkout)."""
    repos.ensure_commit(repo, commit)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    index = dest.parent / "index.tmp"
    env = {**os.environ, "GIT_INDEX_FILE": str(index), "GIT_DIR": str(repos.clone_path(repo)),
           "GIT_WORK_TREE": str(dest)}
    try:
        for args in (["read-tree", commit], ["checkout-index", "-a", "-f"]):
            proc = subprocess.run(["git", "-c", "core.autocrlf=false", *args], env=env, capture_output=True, text=True)
            if proc.returncode != 0:
                raise GenerateError(f"git {args[0]} {commit[:12]} failed: {proc.stderr.strip()}")
    finally:
        index.unlink(missing_ok=True)


def nearest_tag(repo: str, commit: str, match: str = "") -> str | None:
    """The newest tag that is an ancestor of the commit, or None. With match, only tags that match the glob."""
    repos.ensure_commit(repo, commit)
    options = ["--match", match] if match else []
    proc = subprocess.run(["git", "describe", "--tags", "--abbrev=0", *options, commit], cwd=repos.clone_path(repo),
                          capture_output=True, text=True)
    name = proc.stdout.strip()
    return name if proc.returncode == 0 and re.fullmatch(r"[\w.+/-]+", name) else None


def task_dir(recipe: Recipe, task: Task) -> Path:
    return generate_dir() / recipe.name / task.id


def tests_path(recipe: Recipe, task: Task) -> Path:
    """The tests that a valid task is graded on: fail_to_pass and pass_to_pass."""
    return task_dir(recipe, task) / "tests.json"


def build_task_image(recipe: Recipe, task: Task, force: bool = False) -> tuple[str, float]:
    """Build the image of one task. Returns the tag and the build time in seconds (0 if it existed).
    An image is used again only when its label has the current fingerprint. Else, or with force,
    it is built again and the tag goes to the new image."""
    tag = task_tag(recipe, task)
    fingerprint = image_fingerprint(recipe, task)
    if not force and image_label(tag) == fingerprint:
        return tag, 0.0
    base = build_base(recipe)
    folder = task_dir(recipe, task)
    context = folder / "context"
    with _CLONE_LOCK:
        _export_source(task.repo, task.base_commit, context / "src")
        commit_time = repos.commit_time(task.repo, task.base_commit)
        # Build tools that read the version from git (versioneer, setuptools-scm) need a tag. The
        # image has no history, so the nearest tag of the real history is put on its one commit.
        tag_name = nearest_tag(task.repo, task.base_commit, recipe.tag_match)
    deps = context / "deps"
    deps.mkdir(exist_ok=True)
    for name in recipe.deps_files:
        source = context / "src" / name
        if not source.exists():
            raise GenerateError(f"{task.id}: {name} does not exist at {task.base_commit[:12]}")
        (deps / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, deps / name)
    when = exclude_newer(commit_time)
    tag_step = f" && git tag '{tag_name}'" if tag_name else ""
    dockerfile = (
        f"FROM {base}\n"
        "COPY deps/ /deps/\n"
        "WORKDIR /deps\n"
        + _run_lines(tuple(c.replace("{exclude_newer}", when) for c in recipe.deps))
        + "COPY src/ /testbed/\n"
        "WORKDIR /testbed\n"
        f"RUN git init -q && git add -A && git commit -qm base{tag_step}\n"
        + _run_lines(recipe.build)
    )
    (context / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    start = time.monotonic()
    try:
        _docker_build(context, tag, folder / "build.log", label=fingerprint, no_cache=force)
    finally:
        shutil.rmtree(context / "src", ignore_errors=True)  # the image holds it now
    return tag, time.monotonic() - start


# ---- validation

def parse_junit(path: Path) -> dict[str, str]:
    """Test id -> pass, fail or skip, from a JUnit XML file. An error counts as a failure."""
    results: dict[str, str] = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        test_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        tags = {child.tag for child in case}
        outcome = FAIL if tags & {"failure", "error"} else SKIP if "skipped" in tags else PASS
        # A test can appear twice (set-up error and call). A failure wins.
        if results.get(test_id) != FAIL:
            results[test_id] = outcome
    return results


@dataclass
class Verdict:
    valid: bool
    reason: str
    fail_to_pass: list[str] = field(default_factory=list)
    pass_to_pass: list[str] = field(default_factory=list)
    broken: list[str] = field(default_factory=list)   # passed before the fix, not stable after
    flaky: list[str] = field(default_factory=list)    # changed result between runs of one phase
    # Fail-to-pass tests that failed, were skipped, or were missing in at least one run before the fix.
    # A test can count in more than one of the three.
    failed_before: int = 0
    skipped_before: int = 0
    missing_before: int = 0


def judge(before: list[dict[str, str]], after: list[dict[str, str]]) -> Verdict:
    """Compare the runs before the fix with the runs after it."""
    if not before or not after or not all(before) or not all(after):
        return Verdict(False, "a test run gave no results")
    verdict = Verdict(False, "")
    for test_id in sorted(set().union(*before, *after)):
        b = {run.get(test_id) for run in before}
        a = {run.get(test_id) for run in after}
        # Before the fix, a mix of fail, skip and missing is not flaky: the test does not pass in any run.
        if len(a) > 1 or (len(b) > 1 and PASS in b):
            verdict.flaky.append(test_id)
        elif a == {PASS} and PASS not in b:
            # A test that the fix adds can be missing before, for example when its file did not import.
            # A test can also be skipped before, for example when it needs a name that the fix adds.
            verdict.fail_to_pass.append(test_id)
            verdict.failed_before += FAIL in b
            verdict.skipped_before += SKIP in b
            verdict.missing_before += None in b
        elif a == {PASS} and b == {PASS}:
            verdict.pass_to_pass.append(test_id)
        elif b == {PASS}:
            verdict.broken.append(test_id)
    if verdict.broken:
        verdict.reason = f"{len(verdict.broken)} tests passed before the fix and not after it"
    elif verdict.flaky:
        verdict.reason = f"{len(verdict.flaky)} tests changed their result between runs"
    elif not verdict.fail_to_pass:
        verdict.reason = "no test went from failing to passing"
    else:
        verdict.valid, verdict.reason = True, "ok"
    return verdict


def test_run_line(recipe: Recipe, task: Task, name: str) -> str:
    """One shell line that runs every suite that has files of the task, one after the other.
    Suite k writes /work/<name>.<k>.xml and /work/<name>.<k>.log, and one line to /work/times.txt:
    the name, k, the exit code, and the milliseconds (see read_times)."""
    limit = recipe.timeout_min * 60
    parts = []
    for k, suite in enumerate(recipe.suites):
        files = suite_files(suite, task)
        if not files:
            continue
        test = suite.test.replace("{files}", " ".join(f"'{f}'" for f in files))
        test = test.replace("{junit}", f"/work/{name}.{k}.xml")
        # The command goes through a shell, so it can start with variables and use pipes.
        parts.append(f"s=$(date +%s%N); timeout -k 30 {limit} bash -c {shlex.quote(test)} > /work/{name}.{k}.log 2>&1; "
                     f"r=$?; e=$(date +%s%N); echo \"{name} {k} $r $(( (e - s) / 1000000 ))\" >> /work/times.txt")
    return "; ".join(parts) or ":"


def refresh_lines(recipe: Recipe) -> str:
    return "\n".join(f"{c} >> /work/refresh.log 2>&1 || echo \"refresh failed\" >> /work/times.txt"
                     for c in recipe.refresh)


def read_results(work: Path, name: str, unreadable: list[Path] | None = None) -> dict[str, str]:
    """The merged results of one test run (all suites). A JUnit file that does not parse adds
    nothing; its path goes to `unreadable` when that list is given."""
    merged: dict[str, str] = {}
    for path in sorted(work.glob(f"{name}.*.xml")):
        try:
            merged.update(parse_junit(path))
        except ET.ParseError:
            if unreadable is not None:
                unreadable.append(path)
    return merged


class SuiteRun(NamedTuple):
    """One line of times.txt: one suite in one test run."""
    name: str       # the test run, for example "before-2" or "grade"
    suite: int      # the index of the suite in the recipe
    exit_code: int
    ms: int

    @property
    def timed_out(self) -> bool:
        return self.exit_code in TIMEOUT_CODES


def read_times(work: Path) -> list[SuiteRun]:
    """The suite runs in /work/times.txt. The lines of a step that failed are left out."""
    path = work / "times.txt"
    runs = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        parts = line.split()
        if len(parts) == 4 and all(part.isdigit() for part in parts[1:]):
            runs.append(SuiteRun(parts[0], int(parts[1]), int(parts[2]), int(parts[3])))
    return runs


def _script(recipe: Recipe, task: Task, repeats: int) -> str:
    """The shell script that validates a task inside its container. It writes to /work."""
    def runs(phase: str) -> str:
        return "\n".join(test_run_line(recipe, task, f"{phase}-{i}") for i in range(1, repeats + 1))

    return (
        # The files must be readable outside the container, also after a step fails.
        "trap 'chmod -R a+rwX /work' EXIT\n"
        "cd /testbed\n"
        "git apply --whitespace=nowarn /work/test.patch || { echo 'test patch failed' >> /work/times.txt; exit 3; }\n"
        f"{runs('before')}\n"
        "git apply --whitespace=nowarn /work/fix.patch || { echo 'fix patch failed' >> /work/times.txt; exit 4; }\n"
        f"{refresh_lines(recipe)}\n"
        f"{runs('after')}\n"
    )


# The lines that run.sh writes to times.txt when a step fails. The first one found is the reason.
_STEP_FAILURES = ("test patch failed", "fix patch failed", "refresh failed")


def validate_task(recipe: Recipe, task: Task, tag: str, repeats: int = DEFAULT_REPEATS, cpus: int = 8) -> dict:
    """Run the task's test files before and after the real fix. Returns the result record."""
    files = task_test_files(recipe, task)
    fingerprint = validation_fingerprint(recipe, task, repeats)
    # A task that is not valid now must have no test lists from an earlier validation.
    tests_path(recipe, task).unlink(missing_ok=True)
    work = task_dir(recipe, task) / "work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / "test.patch").write_text(task.test_patch or "", encoding="utf-8")
    (work / "fix.patch").write_text(task.patch, encoding="utf-8")
    (work / "run.sh").write_text(_script(recipe, task, repeats), encoding="utf-8")
    # Each suite of each run has its own limit inside the container. One more limit is for the patches and the refresh.
    suites = sum(1 for suite in recipe.suites if suite_files(suite, task))
    limit = recipe.timeout_min * 60 * (2 * repeats * suites + 1)
    start = time.monotonic()
    finished = run_in_container(tag, work, prefix="cmeval-validate", limit=limit, cpus=cpus)
    seconds = time.monotonic() - start

    unreadable: list[Path] = []

    def results(phase: str) -> list[dict[str, str]]:
        return [read_results(work, f"{phase}-{i}", unreadable) for i in range(1, repeats + 1)]

    verdict = judge(results("before"), results("after"))
    times_text = (work / "times.txt").read_text(encoding="utf-8") if (work / "times.txt").exists() else ""
    runs = [run for run in read_times(work) if run.name.startswith(("before-", "after-"))]
    whole_runs: dict[str, int] = {}
    for run in runs:
        whole_runs[run.name] = whole_runs.get(run.name, 0) + run.ms
    timed_out = [f"{run.name}.{run.suite}" for run in runs if run.timed_out]
    problem = next((marker for marker in _STEP_FAILURES if marker in times_text), None)
    if problem is None and not finished:
        problem = "the container passed its time limit"
    elif problem is None and timed_out:
        problem = "a test run timed out"
    elif problem is None and unreadable:
        problem = f"{len(unreadable)} JUnit files do not parse"
    if problem:
        # The test lists stay in the record, to help find the cause. tests.json is not written.
        verdict.valid, verdict.reason = False, problem
    if verdict.valid:
        # The two lists that a later run is graded on.
        lists = {"fingerprint": fingerprint, "repeats": repeats,
                 "fail_to_pass": verdict.fail_to_pass, "pass_to_pass": verdict.pass_to_pass}
        tests_path(recipe, task).write_text(json.dumps(lists) + "\n", encoding="utf-8")
    return {
        "valid": verdict.valid,
        "reason": verdict.reason,
        "fingerprint": fingerprint,
        "image_fingerprint": image_fingerprint(recipe, task),
        "test_files": files,
        "fail_to_pass": verdict.fail_to_pass,
        "n_pass_to_pass": len(verdict.pass_to_pass),
        "fail_to_pass_failed_before": verdict.failed_before,
        "fail_to_pass_skipped_before": verdict.skipped_before,
        "fail_to_pass_missing_before": verdict.missing_before,
        "broken": verdict.broken[:50],
        "flaky": verdict.flaky[:50],
        "timed_out": timed_out,
        "junit_unreadable": len(unreadable),
        "validate_s": round(seconds, 1),
        # The slowest suite in one run: admission() compares it with the limit of one suite.
        "slowest_test_run_s": round(max(run.ms for run in runs) / 1000, 1) if runs else None,
        "slowest_whole_run_s": round(max(whole_runs.values()) / 1000, 1) if whole_runs else None,
        "repeats": repeats,
    }


def generate_task(recipe: Recipe, task: Task, repeats: int = DEFAULT_REPEATS, cpus: int = 8, force: bool = False) -> dict:
    """Build and validate one task. The record of a validation is saved. A saved record is used
    again when its fingerprint is the current one, and, for a valid task, when the image has the
    current fingerprint too. force builds the image again and validates again."""
    folder = task_dir(recipe, task)
    saved = folder / "result.json"
    fingerprint = validation_fingerprint(recipe, task, repeats)
    if saved.exists() and not force:
        record = json.loads(saved.read_text(encoding="utf-8"))
        if record.get("fingerprint") == fingerprint and (
                not record.get("valid") or image_label(task_tag(recipe, task)) == image_fingerprint(recipe, task)):
            return record
    # The old record and test lists must not stay when this attempt fails.
    saved.unlink(missing_ok=True)
    tests_path(recipe, task).unlink(missing_ok=True)
    folder.mkdir(parents=True, exist_ok=True)
    record: dict = {"id": task.id, "repo": task.repo, "base_commit": task.base_commit,
                    "difficulty": difficulty(task.patch), "recipe": recipe.name, "valid": False}
    try:
        tag, build_s = build_task_image(recipe, task, force=force)
        record.update(image=tag, build_s=round(build_s, 1))
        record.update(validate_task(recipe, task, tag, repeats=repeats, cpus=cpus))
    except (GenerateError, repos.RepoError, subprocess.TimeoutExpired) as exc:
        # Not saved: a build that failed is tried again by the next call.
        record["reason"] = f"error: {exc}"
        return record
    saved.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def generate(recipe: Recipe, tasks: list[Task], *, jobs: int = 2, repeats: int = DEFAULT_REPEATS, cpus: int = 8,
             force: bool = False, progress: Callable[[str], None] = lambda message: None) -> list[dict]:
    """Build and validate tasks, `jobs` at a time. Records come back in the order of `tasks`."""
    build_base(recipe)

    def one(task: Task) -> dict:
        record = generate_task(recipe, task, repeats=repeats, cpus=cpus, force=force)
        progress(format_record(record))
        return record

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(one, tasks))


def format_record(record: dict) -> str:
    mark = "valid  " if record["valid"] else "invalid"
    f2p = len(record.get("fail_to_pass", []))
    return (f"{mark} {record['id']} {record['difficulty']:<6} build {record.get('build_s', '-')} s, "
            f"slowest suite run {record.get('slowest_test_run_s', '-')} s, fail-to-pass {f2p}, "
            f"pass-to-pass {record.get('n_pass_to_pass', '-')}: {record.get('reason', '')}")


def admission(recipe: Recipe, records: list[dict]) -> dict:
    """The admission check: at least 6 of 10 sampled tasks are valid, each suite run within the limit."""
    limit = recipe.timeout_min * 60
    good = [r for r in records if r["valid"] and (r.get("slowest_test_run_s") or 0) <= limit]
    need = round(ADMISSION_PASS * len(records) / ADMISSION_N)
    return {"recipe": recipe.name, "repo": recipe.repo, "sampled": len(records), "valid_in_time": len(good),
            "needed": need, "admitted": len(good) >= need and bool(records)}
