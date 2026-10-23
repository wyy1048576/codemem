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
    """Clone the repo once (bare) and return the clone path."""
    path = clone_path(repo)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".partial")
        shutil.rmtree(tmp, ignore_errors=True)
        _git("clone", "--bare", "--quiet", url or f"https://github.com/{repo}.git", str(tmp))
        tmp.rename(path)  # a stopped clone never looks like a finished one
    return path


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


def head(worktree: Path) -> str:
    return _git("rev-parse", "HEAD", cwd=worktree).stdout.strip()


def is_clean(worktree: Path) -> bool:
    return _git("status", "--porcelain", "--untracked-files=all", cwd=worktree).stdout == ""


def checkout(repo: str, commit: str, name: str | None = None) -> Path:
    """A clean worktree at the commit.

    name=None: a fixed snapshot for this commit. name="x": the movable worktree "x" for this repo,
    moved to the commit.
    """
    ensure_commit(repo, commit)
    if name is None:
        path = worktrees_dir() / f"{slug(repo)}@{commit[:12]}"
    else:
        if not re.match(r"^[A-Za-z0-9_.-]+$", name):
            raise RepoError(f"worktree name {name!r} may only use letters, digits, '_', '.', '-'")
        path = worktrees_dir() / f"{slug(repo)}{LIVE_MARK}{name}"

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
