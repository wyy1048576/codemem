"""Throwaway git repositories for the worktree and branch-switch tests.

`two_commits()` turns a copy of the sample repo into a repository with two commits that differ in
every way a branch switch can: a changed file, an added file, a moved file and a deleted file.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

# What differs between the two commits, as stage A sees it on a switch in each direction.
TO_B = {"files_changed": 3, "files_deleted": 2}  # sessions.py, audit.py, accounts.py; routes.py, users.py
TO_A = {"files_changed": 3, "files_deleted": 2}  # sessions.py, routes.py, users.py; audit.py, accounts.py
UNCHANGED = ("auth/db.py::Table.delete", "tests/test_users.py::test_disabled_user_loses_sessions")
ONLY_ON_A = ("api/routes.py::logout", "auth/users.py::disable_user")
ONLY_ON_B = ("auth/audit.py::record_audit_event", "auth/accounts.py::disable_user", "auth/sessions.py::expire_sessions")


def git(repo: Path, *args: str) -> str:
    """Run git in `repo` with its own identity, whatever the user's git config says."""
    res = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "-c", "advice.detachedHead=false", *args],
        check=True, capture_output=True, text=True,
    )
    return res.stdout.strip()


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def two_commits(repo: Path) -> tuple[str, str]:
    """Make `repo` (a copy of the sample repo) a git repository: commit A on `main`, checked out,
    and commit B on `feature`. Returns both commit ids."""
    git(repo, "init", "-q", "-b", "main")
    a = commit(repo, "A")
    git(repo, "checkout", "-q", "-b", "feature")
    sessions = repo / "auth" / "sessions.py"
    sessions.write_text(  # changed: one body edited, one function added
        sessions.read_text().replace(
            "    db.sessions.delete(session_id)\n", "    db.sessions.delete(session_id)\n    db.log(session_id)\n"
        )
        + "\n\ndef expire_sessions(limit):\n    for session in db.sessions.find(old=limit):\n        revoke_session(session.sid)\n"
    )
    (repo / "auth" / "audit.py").write_text(  # added
        "from . import db\n\n\ndef record_audit_event(user, action):\n    db.users.insert(user.id, action)\n"
    )
    git(repo, "mv", "auth/users.py", "auth/accounts.py")  # moved
    git(repo, "rm", "-q", "api/routes.py")  # deleted
    b = commit(repo, "B")
    git(repo, "checkout", "-q", "main")
    return a, b


def add_worktree(repo: Path, folder: Path, *args: str) -> Path:
    """`git worktree add` at `folder`: outside the repo's folder, as `git worktree add ../name`
    does, or inside it, where agent hosts put them (`.claude/worktrees/<name>`)."""
    git(repo, "worktree", "add", "-q", str(folder), *args)
    return folder.resolve()
