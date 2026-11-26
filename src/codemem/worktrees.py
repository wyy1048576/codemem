"""How an index follows git worktrees (docs/architecture.md §4.6).

A repository can have several checkouts: the main one, and one for each `git worktree add`. Each
checkout has its own index folder, named after its path. This module does two things for them:

- a checkout with no index starts from a copy of the index of another checkout of the same
  repository, so its first full check re-chunks only the files whose content differs;
- the index of a linked worktree is deleted once the worktree is gone.

Both apply to default index folders only (`config.default_index_dir`), never to a folder the
caller chose.

It also says which folders are linked worktrees of a repository (`is_worktree_of`). A checkout's
scan and its watcher leave out the ones that lie inside the checkout, so that its index holds its
own files only.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import unicodedata
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any, TypeVar

from .config import Config, codemem_home, default_index_dir
from .indexer import git_head
from .store import SCHEMA_VERSION, IndexLock
from .watcher import git_dir

log = logging.getLogger(__name__)
T = TypeVar("T")

DB = "index.db"
RECORD = "worktree.json"  # in a linked worktree's index folder: the worktree and its repository
COPY_LOCK_WAIT = 300.0  # another process is copying into the same folder: wait, then use its index
# Meta rows that describe the checkout an index was built for. A copy starts without them, so
# it does not count as this checkout's index until a full check has compared it with the files.
# `database_id` names the database a saved search index belongs to: a copy that kept it would
# pass for its source, and the two would then read each other's saved files.
_CHECKOUT_META = ("indexed_at", "last_scan_at", "last_update", "coverage", "repo_path", "database_id")
# Every file codemem writes into an index folder. Clean-up deletes these and nothing else, the
# record last: a clean-up that was interrupted is then finished by the next one.
_OWN_FILES = (
    DB, f"{DB}-wal", f"{DB}-shm", f"{DB}-journal", f"{DB}.copy-*", "vec_*", "write.lock", f"{RECORD}.*.tmp", RECORD,
)


# --------------------------------------------------------------------------- git


def git_common_dir(root: Path) -> Path | None:
    """The git folder that every checkout of a repository shares: the main checkout's `.git/`, or
    a bare repository. A linked worktree's own git folder names it in its `commondir` file."""
    own = git_dir(root)
    if own is None:
        return None
    try:
        target = Path((own / "commondir").read_text("utf-8").strip())
    except FileNotFoundError:
        return own.resolve()
    except (OSError, ValueError):
        return None
    return (target if target.is_absolute() else own / target).resolve()


def is_linked_worktree(root: Path) -> bool:
    """`root` is a checkout made by `git worktree add`: its git folder has a `commondir` file.
    The main checkout's git folder has none, and neither has a submodule's."""
    own = git_dir(root)
    return own is not None and (own / "commondir").is_file()


def is_worktree_of(folder: Path, common: Path) -> bool:
    """`folder` is a linked worktree of the repository whose shared git folder is `common`: another
    checkout of that repository. It is what a checkout's scan and watcher leave out when such a
    worktree lies inside the checkout (indexer.py, watcher.py): agent hosts put them in
    `<repo>/.claude/worktrees/<name>/`, and each has an index of its own.

    Narrow on purpose. A submodule also has a `.git` file, but its git folder shares nothing
    (`is_linked_worktree`). A worktree of another repository shares that repository's git folder.
    A repository of its own has a `.git` folder. None of them counts."""
    if not (folder / ".git").is_file():  # nearly every folder: one look, and no more
        return False
    shared = git_common_dir(folder) if is_linked_worktree(folder) else None
    try:
        return shared is not None and os.path.samefile(shared, common)  # one folder, however it is spelled
    except OSError:
        return False


def linked_worktrees(common: Path, *, certain: bool = False) -> list[Path]:
    """The folders of the linked worktrees git has registered: each
    `<common>/worktrees/<id>/gitdir` holds the path of one worktree's `.git` file. An entry that
    cannot be read is left out. With `certain` it raises instead: "git does not list it" must
    never be concluded from a list that could not be read."""
    try:
        admins = sorted((common / "worktrees").iterdir())
    except FileNotFoundError:  # git removes the folder with its last worktree
        return []
    except OSError:
        if certain:
            raise
        return []
    out = []
    for admin in admins:
        try:
            dot_git = Path((admin / "gitdir").read_text("utf-8").strip())
        except (OSError, ValueError):
            if certain:
                raise
            continue
        out.append((dot_git if dot_git.is_absolute() else admin / dot_git).resolve().parent)
    return out


def checkouts(common: Path) -> list[Path]:
    """Every checkout of the repository whose shared git folder is `common`: the main one (a bare
    repository has none), then the linked worktrees."""
    return ([common.parent] if common.name == ".git" else []) + linked_worktrees(common)


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))


def _spelling_free(path: Path) -> str:
    """A path without its letter case and Unicode form. On a disk that ignores case, git and
    codemem can hold two spellings of one folder; where "the same folder" is the safe answer,
    paths are compared this way."""
    return unicodedata.normalize("NFC", str(path)).casefold()


def _is_gone(path: Path) -> bool:
    """`path` certainly does not exist. No permission to look, or a disk that does not answer, is
    not "gone"."""
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return True
    except OSError:
        return False
    return False


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
        # A `-wal`, `-shm` or `-journal` file without its database is left from an index deleted
        # by hand: SQLite would replay it into the copy.
        if any((index_dir / f"{DB}{suffix}").exists() for suffix in ("", "-wal", "-shm", "-journal")):
            return False
        # Also left from an index that is gone: a copy that was interrupted, and saved search
        # indexes. The store matches those to vector rows by id, and the copy brings another
        # index's ids.
        for stale in (*index_dir.glob(f"{DB}.copy-*"), *index_dir.glob("vec_*")):
            if stale.is_file():
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


# --------------------------------------------------------------------------- clean-up


def _read_record(folder: Path) -> tuple[Path, Path] | None:
    """(worktree folder, shared git folder) from an index folder's record, or None."""
    try:
        record = json.loads((folder / RECORD).read_text("utf-8"))
        worktree, repository = record["worktree"], record["repository"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(worktree, str) or not isinstance(repository, str) or not worktree or not repository:
        return None
    return Path(worktree), Path(repository)


def record_worktree(root: Path, index_dir: Path) -> None:
    """Note in a linked worktree's default index folder which worktree it serves, so that the
    folder can be found and deleted once the worktree is gone. Any other checkout's index folder
    has no record."""
    common = git_common_dir(root)
    path = index_dir / RECORD
    if common is None or not is_linked_worktree(root):
        # The folder of a removed worktree is in use again, by another kind of checkout: this
        # index is that checkout's now, and no clean-up may take it for the worktree's.
        path.unlink(missing_ok=True)
        return
    record = {"worktree": str(root.resolve()), "repository": str(common)}
    try:
        if json.loads(path.read_text("utf-8")) == record:
            return
    except (OSError, ValueError):
        pass
    index_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{RECORD}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record, indent=1), "utf-8")
    os.replace(tmp, path)


def removable_indexes(root: Path) -> list[Path]:
    """Index folders of linked worktrees of `root`'s repository that are gone.

    A folder qualifies only if all of this holds, so that nothing else can ever be deleted:
    it is a real folder directly inside codemem's index folder; it has a record, which codemem
    keeps only in a linked worktree's default index folder; the record names this repository;
    the folder's name is the one codemem gives that worktree's index; the worktree's folder
    certainly does not exist; and git no longer has the worktree registered (a folder that is
    only missing for now, on a drive that is not mounted, stays registered). If git's list of
    worktrees cannot be read, no folder qualifies."""
    common = git_common_dir(root)
    indexes = codemem_home() / "indexes"
    if common is None or not indexes.is_dir():
        return []
    try:
        listed = {_spelling_free(p) for p in ([common.parent] if common.name == ".git" else [])}
        listed |= {_spelling_free(p) for p in linked_worktrees(common, certain=True)}
    except (OSError, ValueError):
        return []
    out = []
    for folder in sorted(indexes.iterdir()):
        record = None if folder.is_symlink() or not folder.is_dir() else _read_record(folder)
        if record is None:
            continue
        worktree, repository = record
        if (
            _same(repository, common)
            and default_index_dir(worktree).name == folder.name
            and _is_gone(worktree)
            and _spelling_free(worktree.resolve()) not in listed
        ):
            out.append(folder)
    return out


def remove_index(folder: Path) -> None:
    """Delete the files codemem wrote into an index folder, then the folder if nothing else is
    in it. Skipped while a codemem process is writing that index."""
    lock = IndexLock(folder)
    try:
        lock.acquire(timeout=0)
    except TimeoutError:
        return
    lock.release()
    for pattern in _OWN_FILES:
        for path in folder.glob(pattern):
            if path.is_file() and not path.is_symlink():
                path.unlink()
    try:
        folder.rmdir()
    except OSError:  # something codemem did not write is in it: it stays
        log.info("left %s in place: it holds files codemem did not write", folder)


# --------------------------------------------------------------------------- the entry point


def _attempt(what: str, step: Callable[[], T]) -> T | None:
    """One step of preparing an index folder. A failure costs time, never the start of codemem."""
    try:
        return step()
    except Exception:
        log.warning("could not %s", what, exc_info=True)
        return None


def prepare_index(root: Path, index_dir: Path, config: Config) -> Path | None:
    """What every codemem start does before it opens a checkout's default index folder: delete
    the indexes of this repository's removed worktrees, start a new index from a copy if another
    checkout has one, and record whether the folder serves a linked worktree. Returns the index
    folder that was copied, or None: the index is then built from nothing."""

    def clean_up() -> None:
        for folder in removable_indexes(root):
            log.info("the worktree of the index %s is gone; deleting the index", folder)
            remove_index(folder)

    def start_from_a_copy() -> Path | None:
        if (index_dir / DB).exists():
            return None
        source = copy_source(root, config.index_settings())
        if source is None or not copy_index(source, index_dir):
            return None
        log.info("the index for %s starts as a copy of %s", root, source)
        return source

    _attempt("delete the indexes of removed worktrees", clean_up)
    source = _attempt(f"start the index in {index_dir} from a copy", start_from_a_copy)
    _attempt(f"record which checkout the index in {index_dir} serves", lambda: record_worktree(root, index_dir))
    return source
