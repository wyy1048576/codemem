"""Repo clones and snapshots.

One bare clone for each repo in CMEVAL_HOME/repos. Snapshots are git worktrees in
CMEVAL_HOME/worktrees, which share the clone's objects:
- fixed snapshots, named <owner>__<name>@<sha12>, stay at one commit;
- movable worktrees, named <owner>__<name>@live-<name>, move from commit to commit (the runner
  steps one index forward through time).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .paths import repos_dir, worktrees_dir

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
LIVE_MARK = "@live-"


class RepoError(RuntimeError):
    """A git command failed, or a repo or worktree is not in the expected state."""


def _git(*args: str, cwd: Path | None = None, check: bool = True, text: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}  # never wait for a password prompt
    proc = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=text)
    if check and proc.returncode != 0:
        stderr = proc.stderr if text else proc.stderr.decode("utf-8", "replace")
        raise RepoError(f"git {' '.join(args)} failed: {stderr.strip()}")
    return proc


def slug(repo: str) -> str:
    owner, name = repo.split("/")
    return f"{owner}__{name}"


def clone_path(repo: str) -> Path:
    return repos_dir() / f"{slug(repo)}.git"


def ensure_clone(repo: str, url: str | None = None) -> Path:
    """Clone the repo once (bare) and return the clone path.

    core.autocrlf is always false in the clone (its worktrees inherit it). Git for Windows
    converts line endings on checkout by default, and then file contents, hit texts, and token
    counts would differ from other machines.
    """
    path = clone_path(repo)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".partial")
        shutil.rmtree(tmp, ignore_errors=True)
        _git("clone", "--bare", "--quiet", "-c", "core.autocrlf=false", url or f"https://github.com/{repo}.git", str(tmp))
        tmp.rename(path)  # a stopped clone never looks like a finished one
    _git("config", "core.autocrlf", "false", cwd=path)  # also for clones made before this setting
    return path


def shallow_clone(repo: str, branch: str, dest: Path, url: str | None = None) -> str:
    """Check out only the newest commit of one branch into dest (no history). Returns its sha.

    Much smaller than a full clone. For numbers about today's code only; the collector and the
    runner need the full clone from ensure_clone.
    """
    _git("clone", "--depth", "1", "--single-branch", "--branch", branch, "--no-tags", "--quiet",
         "-c", "core.autocrlf=false", url or f"https://github.com/{repo}.git", str(dest))
    return _git("rev-parse", "HEAD", cwd=dest).stdout.strip()


def has_commit(repo: str, sha: str) -> bool:
    clone = clone_path(repo)
    if not clone.exists():
        return False
    return _git("cat-file", "-e", f"{sha}^{{commit}}", cwd=clone, check=False).returncode == 0


def ensure_commit(repo: str, sha: str) -> None:
    """Make sure the clone has the commit: fetch branches, then the commit itself by sha."""
    if not _SHA_RE.match(sha):
        raise RepoError(f"{sha!r} is not a full 40-character commit sha")
    clone = ensure_clone(repo)
    if has_commit(repo, sha):
        return
    _git("fetch", "--quiet", "origin", "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*", cwd=clone)
    if not has_commit(repo, sha):
        _git("fetch", "--quiet", "origin", sha, cwd=clone, check=False)
    if not has_commit(repo, sha):
        raise RepoError(f"commit {sha} not found in {repo}")


def commit_time(repo: str, sha: str) -> int:
    """Committer time of a commit (Unix seconds). The runner sorts tasks by it."""
    ensure_commit(repo, sha)
    return int(_git("show", "-s", "--format=%ct", sha, cwd=clone_path(repo)).stdout.strip())


def read_file(repo: str, commit: str, path: str) -> str | None:
    """File content at a commit, or None if the file does not exist there. Needs no worktree."""
    ensure_commit(repo, commit)
    # Bytes, not text mode: text mode would translate line endings and could shift line numbers.
    proc = _git("show", f"{commit}:{path}", cwd=clone_path(repo), check=False, text=False)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace")
        if "does not exist" in stderr:
            return None
        raise RepoError(f"git show {commit}:{path} failed: {stderr.strip()}")
    return proc.stdout.decode("utf-8", "replace")


def parents(repo: str, sha: str) -> list[str]:
    """The parent commits of a commit, first parent first."""
    ensure_commit(repo, sha)
    return _git("rev-list", "--parents", "-n", "1", sha, cwd=clone_path(repo)).stdout.split()[1:]


def ancestor(repo: str, sha: str, n: int) -> str:
    """The full sha of `sha~n` (n first-parent steps back)."""
    return _git("rev-parse", "--verify", f"{sha}~{n}^{{commit}}", cwd=clone_path(repo)).stdout.strip()


def subjects(repo: str, sha: str, n: int) -> list[str]:
    """First lines of the messages of `sha` and its n - 1 first-parent ancestors, oldest first."""
    out = _git("log", "--first-parent", f"-n{n}", "--format=%s", sha, cwd=clone_path(repo)).stdout
    return out.splitlines()[::-1]


def diff(repo: str, old: str, new: str) -> str:
    """Unified diff from old to new (renames found), the way git prints it. Needs no worktree."""
    ensure_commit(repo, old)
    ensure_commit(repo, new)
    proc = _git("-c", "core.quotepath=false", "diff", "-M", "--no-color", "--no-ext-diff", old, new,
                cwd=clone_path(repo), text=False)
    return proc.stdout.decode("utf-8", "replace")


def tracked_files(repo: str, commit: str) -> list[str]:
    """Every file path in the tree of a commit (no worktree needed)."""
    ensure_commit(repo, commit)
    proc = _git("-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", commit, cwd=clone_path(repo), text=False)
    return proc.stdout.decode("utf-8", "replace").splitlines()


def apply_check(repo: str, base: str, patch: str) -> str | None:
    """None if the patch applies cleanly to the tree of `base`, else git's message.

    It uses a temporary index file, so it works in the bare clone and changes nothing.
    """
    ensure_commit(repo, base)
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        clone = clone_path(repo)
        subprocess.run(["git", "read-tree", base], cwd=clone, env=env, check=True, capture_output=True)
        proc = subprocess.run(["git", "apply", "--check", "--cached", "-"], cwd=clone, env=env,
                              input=patch.encode("utf-8"), capture_output=True)
    return None if proc.returncode == 0 else proc.stderr.decode("utf-8", "replace").strip()


def head(worktree: Path) -> str:
    return _git("rev-parse", "HEAD", cwd=worktree).stdout.strip()


def is_clean(worktree: Path) -> bool:
    return _git("status", "--porcelain", "--untracked-files=all", cwd=worktree).stdout == ""


def live_path(repo: str, name: str) -> Path:
    """Folder of the movable worktree "name" for this repo."""
    if not re.match(r"^[A-Za-z0-9_.-]+$", name):
        raise RepoError(f"worktree name {name!r} may only use letters, digits, '_', '.', '-'")
    return worktrees_dir() / f"{slug(repo)}{LIVE_MARK}{name}"


def discard_live(repo: str, name: str) -> None:
    """Remove the movable worktree "name" if it exists, in any state.

    A process that was stopped during a checkout can leave the worktree with local changes or
    a stale index.lock, and then move_to refuses it. The runner discards it and makes a new one.
    """
    path = live_path(repo, name)
    if not path.exists():
        return
    try:
        remove_worktree(path)
    except RepoError:
        shutil.rmtree(path, ignore_errors=True)
        _git("worktree", "prune", cwd=clone_path(repo))


def checkout(repo: str, commit: str, name: str | None = None) -> Path:
    """A clean worktree at the commit.

    name=None: a fixed snapshot for this commit. name="x": the movable worktree "x" for this repo,
    moved to the commit.
    """
    ensure_commit(repo, commit)
    path = worktrees_dir() / f"{slug(repo)}@{commit[:12]}" if name is None else live_path(repo, name)

    if path.exists():
        if name is not None:
            move_to(path, commit)
        elif head(path) != commit or not is_clean(path):
            raise RepoError(f"snapshot {path} is not a clean checkout of {commit}")
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    # Forget worktrees whose folder was deleted by hand; git would refuse to add them again.
    _git("worktree", "prune", cwd=clone_path(repo))
    _git("worktree", "add", "--detach", "--quiet", str(path), commit, cwd=clone_path(repo))
    return path


def move_to(worktree: Path, commit: str) -> None:
    """Move a movable worktree to another commit. Refuses if the worktree has local changes."""
    worktree = Path(worktree)
    if LIVE_MARK not in worktree.name:
        raise RepoError(f"{worktree} is a fixed snapshot; only movable ({LIVE_MARK}) worktrees can move")
    if not is_clean(worktree):
        raise RepoError(f"{worktree} has local changes; refusing to move it")
    repo = worktree.name.split(LIVE_MARK)[0].replace("__", "/", 1)
    ensure_commit(repo, commit)
    _git("checkout", "--detach", "--quiet", commit, cwd=worktree)


def remove_worktree(worktree: Path) -> None:
    worktree = Path(worktree).resolve()
    common = Path(_git("rev-parse", "--git-common-dir", cwd=worktree).stdout.strip())
    clone = common if common.is_absolute() else (worktree / common).resolve()
    _git("worktree", "remove", "--force", str(worktree), cwd=clone)
