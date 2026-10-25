"""Locations of large local data (clones, worktrees, indexes, runs, token cache).

Everything lives under CMEVAL_HOME (default ~/.cmeval), outside git. The helpers only
return paths. Callers create directories when they need them.
"""

from __future__ import annotations

import os
from pathlib import Path


def cmeval_home() -> Path:
    return Path(os.environ.get("CMEVAL_HOME") or Path.home() / ".cmeval")


def repos_dir() -> Path:
    """One full clone for each repo: <owner>__<name>.git"""
    return cmeval_home() / "repos"


def worktrees_dir() -> Path:
    """Snapshots at one commit: <owner>__<name>@<sha12>"""
    return cmeval_home() / "worktrees"


def indexes_dir() -> Path:
    return cmeval_home() / "indexes"


def runs_dir() -> Path:
    return cmeval_home() / "runs"


def token_cache_dir() -> Path:
    return cmeval_home() / "token-cache"


def datasets_dir() -> Path:
    """Downloaded public datasets, pinned by revision."""
    return cmeval_home() / "datasets"


def gh_cache_dir() -> Path:
    """GitHub API responses, one JSON file for each request."""
    return cmeval_home() / "gh-cache"


def collect_dir() -> Path:
    """Collection output before it becomes tasks: <config name>/<owner>__<name>/."""
    return cmeval_home() / "collect"


def tmp_dir() -> Path:
    """Short-lived data, for example shallow clones for repo-stats."""
    return cmeval_home() / "tmp"


def default_results_dir() -> Path:
    """eval/results in the repo."""
    return Path(__file__).resolve().parents[2] / "results"


def default_tasks_dir() -> Path:
    """eval/tasks in the repo, where task files (answer keys) are kept in git."""
    return Path(__file__).resolve().parents[2] / "tasks"
