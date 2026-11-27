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

The codemem program is <codemem checkout>/.venv/bin/codemem (or CMEVAL_CODEMEM_BIN). The runner mounts only
what the program reads at run time, each at its own path and read-only: the environment (<checkout>/.venv), the
package source that the editable install of `uv sync` points to (<checkout>/src), and the Python install that the
environment links to (codemem_mount_paths, codemem_python_root). The rest of the checkout stays out of the
container: its eval/tasks/ files hold the real fixes and the hidden tests of the tasks.
"""

from __future__ import annotations

import json
import os
import re
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


# The second line of a script that uv or pip makes when the path of its Python holds a space.
_SH_EXEC = re.compile(r"""^'''exec' '(.+)' "\$0" "\$@"$""")


def _script_python(program: Path) -> str | None:
    """The Python that a script of an environment starts: "#!<python>", or uv's form for a path with a space
    ("#!/bin/sh", then "'''exec' '<python>' ..."). None for any other first lines."""
    try:
        lines = program.read_bytes()[:4096].decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    if not lines or not lines[0].startswith("#!") or not lines[0][2:].strip():
        return None
    if lines[0].strip() != "#!/bin/sh":
        return lines[0][2:].split()[0]
    match = _SH_EXEC.match(lines[1]) if len(lines) > 1 else None
    return match.group(1) if match else None


def _pth_paths(site: Path) -> list[tuple[Path, Path]]:
    """The folders that the .pth files of site-packages add to sys.path, as (pth file, folder). Python skips
    lines that start with "#" and runs lines that start with "import"; a relative path is relative to site."""
    found = []
    for pth in sorted(site.glob("*.pth")):
        for line in pth.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or re.match(r"import[ \t]", line):
                continue
            found.append((pth, Path(line) if os.path.isabs(line) else site / line))
    return found


def codemem_mount_paths(program: Path) -> list[Path]:
    """The folders of the checkout that the program reads at run time: its environment (the folder above bin/),
    and the package source when the install is editable (<checkout>/src, named in a .pth file). The container
    gets these and the Python install (codemem_python_root), and nothing else of the checkout.

    The check fails when the layout is not this one: the script does not start the environment's Python, a .pth
    file adds a folder outside the environment that is not <checkout>/src, the Python is in the checkout but
    outside the environment, an editable finder module
    (__editable__*) maps the package to paths that this check cannot read, or codemem is not installed."""
    venv = program.parent.parent
    src = codemem_checkout(program) / "src"
    python = _script_python(program)
    if python is None or not Path(python).is_relative_to(venv):
        raise GenerateError(f"{program} does not start the Python of its environment {venv} (it starts "
                            f"{python}); make the environment with `uv sync` in the codemem checkout")
    sites = sorted(venv.glob("lib/python*/site-packages"))
    if len(sites) != 1:
        raise GenerateError(f"{venv} has {len(sites)} site-packages folders, expected 1")
    site = sites[0]
    finders = sorted(p.name for p in site.glob("__editable__*"))
    if finders:
        raise GenerateError(f"{site} has editable finder modules ({', '.join(finders)}); the runner cannot tell "
                            "which folders they read. Make the environment with `uv sync`")
    real_venv, real_src = Path(os.path.realpath(venv)), Path(os.path.realpath(src))
    real_python = Path(os.path.realpath(python))
    if real_python.is_relative_to(os.path.realpath(src.parent)) and not real_python.is_relative_to(real_venv):
        raise GenerateError(f"the Python of {venv} is {real_python}: in the checkout, but outside the environment, "
                            "so the container would not have it")
    editable = None
    for pth, folder in _pth_paths(site):
        if not folder.exists():
            continue  # Python skips it, and the container does not have it either
        real = Path(os.path.realpath(folder))
        if real == real_src:
            editable = folder
        elif not real.is_relative_to(real_venv):
            raise GenerateError(f"{pth} adds {folder} to the path of codemem's Python. It is outside {venv} and "
                                f"is not {src}, so the container would not have it")
    if editable is None and not (site / "codemem").is_dir():
        raise GenerateError(f"codemem is not installed in {venv}: no .pth file names {src}, and {site} has no "
                            "codemem folder")
    return [venv] + ([editable] if editable else [])


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
