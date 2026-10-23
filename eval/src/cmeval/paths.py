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
