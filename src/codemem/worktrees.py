"""How an index follows git worktrees (docs/architecture.md §4.6).

A repository can have several checkouts: the main one, and one for each `git worktree add`. Each
checkout has its own index folder, named after its path. A checkout with no index starts from a
copy of the index of another checkout of the same repository, so its first full check re-chunks
only the files whose content differs.

This applies to default index folders only (`config.default_index_dir`), never to a folder the
caller chose.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .config import default_index_dir
from .indexer import git_head
from .store import SCHEMA_VERSION, IndexLock
from .watcher import git_dir

log = logging.getLogger(__name__)

DB = "index.db"
COPY_LOCK_WAIT = 300.0  # another process is copying into the same folder: wait, then use its index
# Meta rows that describe the checkout an index was built for. A copy starts without them, so
# it does not count as this checkout's index until a full check has compared it with the files.
_CHECKOUT_META = ("indexed_at", "last_scan_at", "last_update", "coverage", "repo_path")


# --------------------------------------------------------------------------- git


def git_common_dir(root: Path) -> Path | None:
    """The git folder that every checkout of a repository shares: the main checkout's `.git/`, or
    a bare repository. A linked worktree's own git folder names it in its `commondir` file."""
    own = git_dir(root)
    if own is None:
        return None
    try:
        target = Path((own / "commondir").read_text("utf-8").strip())
    except OSError:
        return own.resolve()
    return (target if target.is_absolute() else own / target).resolve()


def is_linked_worktree(root: Path) -> bool:
    """`root` is a checkout made by `git worktree add`: its git folder has a `commondir` file.
    The main checkout's git folder has none, and neither has a submodule's."""
    own = git_dir(root)
    return own is not None and (own / "commondir").is_file()


def checkouts(common: Path) -> list[Path]:
    """Every checkout of the repository whose shared git folder is `common`: the main one (a bare
    repository has none), then the linked worktrees git has registered. Each
    `<common>/worktrees/<id>/gitdir` holds the path of one worktree's `.git` file."""
    out = [common.parent] if common.name == ".git" else []
    try:
        admins = sorted((common / "worktrees").iterdir())
    except OSError:
        return out
    for admin in admins:
        try:
            dot_git = Path((admin / "gitdir").read_text("utf-8").strip())
        except OSError:
            continue
        out.append((dot_git if dot_git.is_absolute() else admin / dot_git).resolve().parent)
    return out


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))


# --------------------------------------------------------------------------- starting from a copy


def _meta(index_dir: Path) -> dict[str, Any] | None:
    """The `meta` rows of the index in `index_dir`, read without changing it. None if there is
    no index this codemem can read."""
    db = index_dir / DB
    if not db.is_file():
        return None
    try:
        with closing(sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=5)) as conn:
            meta = {key: json.loads(value) for key, value in conn.execute("SELECT key, value FROM meta")}
    except (sqlite3.Error, ValueError):
        return None
    return meta if meta.get("schema_version") == SCHEMA_VERSION else None


def copy_source(root: Path, settings: dict[str, Any]) -> Path | None:
    """The index folder a new index for the checkout `root` starts from, or None.

    Candidates are the default indexes of the repository's other checkouts that were built with
    the same index settings (the first update would rebuild or re-embed any other). Every
    candidate gives a correct index: the choice only decides how many files the first full check
    re-chunks. So the order is: an index built at the commit `root` is on (it differs by
    uncommitted edits only); then the main checkout's (worktrees are usually cut from it); then
    the most recently updated one."""
    common = git_common_dir(root)
    if common is None:
        return None
    head = git_head(root)
    settings = json.loads(json.dumps(settings))  # as the index stores them
    best: tuple[tuple[bool, bool, float], Path] | None = None
    for position, checkout in enumerate(checkouts(common)):
        if _same(checkout, root):
            continue
        index_dir = default_index_dir(checkout)
        meta = _meta(index_dir)
        if meta is None or meta.get("indexed_at") is None or meta.get("index_settings") != settings:
            continue
        is_main = position == 0 and common.name == ".git"
        rank = (head is not None and meta.get("indexed_commit") == head, is_main, float(meta["indexed_at"]))
        if best is None or rank > best[0]:
            best = (rank, index_dir)
    return best[1] if best else None


def copy_index(source: Path, index_dir: Path) -> bool:
    """Start the index in `index_dir` as a copy of the one in `source`. False, and nothing
    changed, if `index_dir` already holds an index.

    The copy is a SQLite backup: one consistent snapshot, even while another process writes the
    source. It then loses what described the source's checkout: every file's date, so the first
    full check reads every file and re-chunks those whose content hash differs, and the meta rows
    of `_CHECKOUT_META`. The saved search index files are not copied: they are rebuilt from the
    vector rows."""
    src, dst = source / DB, index_dir / DB
    if dst.exists() or not src.is_file():
        return False
    index_dir.mkdir(parents=True, exist_ok=True)
    lock = IndexLock(index_dir)
    lock.acquire(timeout=COPY_LOCK_WAIT)  # one process at a time decides and copies
    try:
        # A `-wal` or `-shm` file without its database is left from an index deleted by hand:
        # SQLite would replay it into the copy.
        if any((index_dir / f"{DB}{suffix}").exists() for suffix in ("", "-wal", "-shm")):
            return False
        for stale in index_dir.glob(f"{DB}.copy-*"):  # a copy that was interrupted
            stale.unlink()
        tmp = index_dir / f"{DB}.copy-{os.getpid()}"
        try:
            with (
                closing(sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro", uri=True)) as src_conn,
                closing(sqlite3.connect(tmp, isolation_level=None)) as dst_conn,
            ):
                src_conn.backup(dst_conn)
                # One file: nothing of the copy may sit in a `-wal` when it gets its final name.
                if dst_conn.execute("PRAGMA journal_mode = DELETE").fetchone()[0] != "delete":
                    raise sqlite3.OperationalError("the copy stayed in WAL mode")
                dst_conn.execute("BEGIN")
                dst_conn.execute("UPDATE files SET mtime = 0")
                marks = ",".join("?" * len(_CHECKOUT_META))
                dst_conn.execute(f"DELETE FROM meta WHERE key IN ({marks})", _CHECKOUT_META)
                dst_conn.execute("COMMIT")
            try:
                os.link(tmp, dst)  # unlike a rename, never replaces an index another process just made
            except FileExistsError:
                return False
        finally:
            for leftover in index_dir.glob(f"{DB}.copy-*"):
                leftover.unlink()
    finally:
        lock.release()
    return True


# --------------------------------------------------------------------------- the entry point


def prepare_index(root: Path, index_dir: Path, settings: dict[str, Any]) -> Path | None:
    """What every codemem start does before it opens a checkout's default index folder: start a
    new index from a copy if another checkout of the repository has one. Returns the index
    folder that was copied, or None. A failure here costs time, never the start: the index is
    then built from nothing."""
    try:
        if (index_dir / DB).exists():
            return None
        source = copy_source(root, settings)
        if source is None or not copy_index(source, index_dir):
            return None
        log.info("the index for %s starts as a copy of %s", root, source)
        return source
    except Exception:
        log.warning("could not start the index in %s from a copy", index_dir, exc_info=True)
        return None
