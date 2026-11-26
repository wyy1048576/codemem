"""codemem indexes for end-to-end runs of the setup `tool`, and the codemem program that builds and serves them.

`cmeval e2e index` builds the index of each task on the host, before any run (plan section 4.5, rule 2). Each run
starts from a private copy of it. The layout:

  CMEVAL_HOME/e2e/indexes/<recipe>/<task id>/index/      the codemem index folder
  CMEVAL_HOME/e2e/indexes/<recipe>/<task id>/src/        a git worktree of the task's base commit
  CMEVAL_HOME/e2e/indexes/<recipe>/<task id>/index.json  task_id, repo, base_commit, codemem_commit, seconds, and
                                                         summary (the last line that codemem printed)
  CMEVAL_HOME/e2e/indexes/<recipe>/<task id>/index.log   the output of codemem

The paths in a codemem index are relative, so the index of src/ also works for /testbed in the task's container.
The index is tied to the device and number type of the embedder. When codemem opens an index of the GPU
(float16, cuda) on the CPU, it embeds every text again, which takes hours. So the container of a run gets the GPU.

The build and every run search with the same index, the exact one (CODEMEM_ENV). Left to itself, codemem picks
the search index by the memory of the place it runs in: all of the host's for a build, the container's limit for
a run. A large index that the build saved as the exact one would then be rebuilt as the compact one at the start
of every run, and the agent's first searches would be answered from keywords only.

The codemem program is <codemem checkout>/.venv/bin/codemem (or CMEVAL_CODEMEM_BIN). The runner mounts the
checkout and the Python install of its environment into the container at their own paths.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from . import repos
from .files import write_json
from .generate import GenerateError, Recipe, _run
from .paths import e2e_dir
from .tasks import Task

CODEMEM_BIN_ENV = "CMEVAL_CODEMEM_BIN"
# What codemem gets in its environment wherever the eval starts it: the build of an index here, and the server
# of a run (e2e_run.codemem_mcp_config). One search index for both, whatever memory each place has.
CODEMEM_ENV = {"CODEMEM_VECTOR_BACKEND": "faiss"}
# eval/src/cmeval/ is three levels below the root of the codemem repo.
REPO_ROOT = Path(__file__).resolve().parents[3]
# Folders of the system. A Python install there cannot be mounted: it would hide the container's own files.
SYSTEM_ROOTS = (Path("/"), Path("/usr"), Path("/usr/local"))


def codemem_bin() -> Path:
    """The codemem program of a virtual environment on the host. It must exist and be executable."""
    path = Path(os.path.abspath(os.environ.get(CODEMEM_BIN_ENV) or REPO_ROOT / ".venv" / "bin" / "codemem"))
    if not path.is_file() or not os.access(path, os.X_OK):
        raise GenerateError(f"codemem program {path} does not exist or is not executable; run `uv sync` in the "
                            f"codemem checkout, or set {CODEMEM_BIN_ENV}")
    return path


def codemem_checkout(program: Path) -> Path:
    """The codemem checkout of a program at <checkout>/.venv/bin/codemem."""
    return program.parent.parent.parent


def codemem_python_root(program: Path) -> Path | None:
    """The Python install that the program's environment links to (uv keeps each one in its own folder). None
    when the install is inside the checkout: the mount of the checkout holds it."""
    python = program.parent / "python"
    if not python.exists():
        raise GenerateError(f"no python beside {program}; codemem must be installed in a virtual environment")
    root = Path(os.path.realpath(python)).parent.parent
    # uv links the environment to an alias folder (cpython-3.11-...), which links to the real one
    # (cpython-3.11.18-...). Both must be in the container, so mount the folder that holds both.
    link = Path(os.readlink(python)) if python.is_symlink() else python
    link = link if link.is_absolute() else python.parent / link
    alias = Path(os.path.abspath(link)).parent.parent
    if alias != root and alias.parent == root.parent:
        root = root.parent
    if root in SYSTEM_ROOTS:
        raise GenerateError(f"the Python of {program} is in {root}, a folder of the system; make the environment "
                            "with a Python that uv installed")
    checkout = Path(os.path.realpath(codemem_checkout(program)))
    return None if root.is_relative_to(checkout) else root


def codemem_commit(checkout: Path) -> str | None:
    """The git commit of the codemem checkout, with "-dirty" when the files of src/ have changes."""
    try:
        head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10)
        dirty = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain", "--", "src"],
                               capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if head.returncode != 0:
        return None
    return head.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")


def hf_cache() -> Path:
    """The Hugging Face cache of the host, where codemem's embedding model is."""
    return Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")


def index_root(recipe: Recipe, task: Task) -> Path:
    return e2e_dir() / "indexes" / recipe.name / task.id


def read_index_meta(recipe: Recipe, task: Task) -> dict | None:
    path = index_root(recipe, task) / "index.json"
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def index_state(recipe: Recipe, task: Task) -> str:
    """ok, missing, or "another commit" (index.json is for another base commit)."""
    meta = read_index_meta(recipe, task)
    if meta is None or not (index_root(recipe, task) / "index").is_dir():
        return "missing"
    return "ok" if meta.get("base_commit") == task.base_commit else "another commit"


def ensure_worktree(task: Task, src: Path) -> None:
    """A git worktree of the task's base commit at src, made from the repo's clone when it does not exist."""
    if src.exists():
        if repos.head(src) != task.base_commit:
            raise GenerateError(f"{task.id}: {src} is not at the base commit {task.base_commit}; remove it")
        return
    repos.ensure_commit(task.repo, task.base_commit)
    clone = repos.clone_path(task.repo)
    src.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "--git-dir", str(clone), "worktree", "prune"])
    proc = _run(["git", "--git-dir", str(clone), "worktree", "add", "--detach", str(src), task.base_commit])
    if proc.returncode != 0:
        raise GenerateError(f"{task.id}: cannot make the worktree {src}: {proc.stderr.strip()}")


def _summary(log: Path) -> str | None:
    """The line "indexed N files ..." of codemem's output, or its last line."""
    lines = [line.strip() for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    found = [line for line in lines if line.startswith("indexed ")]
    return found[-1] if found else (lines[-1] if lines else None)


def index_task(recipe: Recipe, task: Task, *, program: Path, commit: str | None, force: bool = False) -> dict | None:
    """Build the task's index. Returns index.json, or None when it exists for the same base commit and the same
    codemem commit (and force is off). A build always starts from an empty index folder."""
    root = index_root(recipe, task)
    meta = read_index_meta(recipe, task)
    if (not force and meta and meta.get("base_commit") == task.base_commit and meta.get("codemem_commit") == commit
            and (root / "index").is_dir()):
        return None
    src, index, log = root / "src", root / "index", root / "index.log"
    ensure_worktree(task, src)
    (root / "index.json").unlink(missing_ok=True)
    if index.exists():
        shutil.rmtree(index)
    log.unlink(missing_ok=True)
    t0 = time.monotonic()
    proc = _run([str(program), "index", str(src), "--index-dir", str(index)], log=log,
                env={**os.environ, **CODEMEM_ENV})
    seconds = round(time.monotonic() - t0, 1)
    if proc.returncode != 0:
        raise GenerateError(f"{task.id}: codemem index ended with exit code {proc.returncode}; see {log}")
    meta = {"task_id": task.id, "repo": task.repo, "base_commit": task.base_commit, "codemem_commit": commit,
            "seconds": seconds, "summary": _summary(log)}
    write_json(root / "index.json", meta)
    return meta


def index_tasks(recipe: Recipe, tasks: list[Task], *, force: bool = False,
                progress: Callable[[str], None] = lambda message: None) -> int:
    """Build the index of each task, one at a time (codemem uses the GPU). Returns the number of failed tasks."""
    program = codemem_bin()
    commit = codemem_commit(codemem_checkout(program))
    failed = 0
    for task in tasks:
        try:
            meta = index_task(recipe, task, program=program, commit=commit, force=force)
        except (GenerateError, repos.RepoError) as exc:
            failed += 1
            progress(f"{task.id}: failed: {exc}")
            continue
        if meta is None:
            progress(f"{task.id}: skipped, the index exists for codemem {commit}")
        else:
            progress(f"{task.id}: {meta['seconds']} s, {meta['summary']}")
    return failed
