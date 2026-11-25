"""The vector cache: (embedder key, text hash) -> vector, one bounded file shared by every index.

Stage B of the indexer looks a changed text up here before it calls the model, so a rebuild,
another commit or a branch switch embeds only texts this machine has not seen. Vectors are float16
at the model's full length. The file is SQLite in WAL mode, shared by several processes. Three
things shape its layout (docs/architecture.md §5):

- one table per embedder holds the vectors, in slots 1..n with no gaps. All its rows have one
  size, so they fill 32 KB pages, and the last row can take the place of a deleted one. The file
  therefore shrinks by what is deleted;
- the key table `entry` maps (embedder id, hash) to a slot and holds the time of last use. A read
  is one lookup there and one in the vector table. Marking an entry as used rewrites only a small
  page, and an index on the time gives the least recently used entries without a scan;
- a size cap: past it, the least recently used entries are deleted until the file is under 90%
  of it. An evicted vector is embedded again when its text comes back.

The cache only saves work. Nothing here raises into an index update: a failure is logged, and the
caller goes on as if the cache were empty.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from itertools import groupby
from operator import itemgetter
from pathlib import Path
from typing import Any, TypeVar

import numpy as np

from .config import Config, codemem_home

log = logging.getLogger(__name__)

CACHE_FILE = "vector_cache.db"
ROW_FORMAT_FILE = "vectors.db"  # a cache with one row per vector in a single table: imported, then deleted

_LAYOUT = 1  # PRAGMA user_version of a file this code reads and writes
# The smallest page that packs vectors of 768 to 1,024 numbers within 7% of their size and still
# holds three of 4,096 (measured: docs/architecture.md §5).
_PAGE_SIZE = 32768
_SCHEMA = (
    "CREATE TABLE embedder(id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, dim INTEGER NOT NULL)",
    "CREATE TABLE entry(embedder INTEGER NOT NULL, hash BLOB NOT NULL, slot INTEGER NOT NULL, used INTEGER NOT NULL, "
    "PRIMARY KEY (embedder, hash)) WITHOUT ROWID",
    "CREATE INDEX entry_used ON entry(used)",
)
_VECTORS = "CREATE TABLE vec_{}(slot INTEGER PRIMARY KEY, hash BLOB NOT NULL, data BLOB NOT NULL)"
_OLD_ROWS = (
    "SELECT embedder, text_hash, dim, data FROM cache WHERE (embedder, text_hash) > (?, ?) "
    "ORDER BY embedder, text_hash LIMIT ?"
)

_BUSY_SECONDS = 60.0  # how long a statement waits for another process's lock
_RETRY_SECONDS = 60.0  # after a failure the file is left alone this long
_KEYS = 500  # keys per statement
_DAY = 86400
_TARGET = 0.9  # eviction stops under this share of the cap
_CHECK = 0.01  # a put looks at the file size once per this share of the cap written
_EVICT_ROWS = 256  # entries deleted per transaction, so other writers get their turn
_EVICT_SECONDS = 0.25  # the eviction one put may do: a search can be waiting for that put
_IMPORT_ROWS = 2000
_HEX = re.compile(r"(?:[0-9a-f]{2})+")

Key = bytes | str
T = TypeVar("T")


def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float16).tobytes()


def from_blob(data: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float16, count=dim)


def _pack(text_hash: str) -> Key:
    """A hex hash as bytes, half its length. Any other string stays text, which SQLite keeps apart."""
    return bytes.fromhex(text_hash) if _HEX.fullmatch(text_hash) else text_hash


def _unpack(key: Key) -> str:
    return key.hex() if isinstance(key, bytes) else key


def _now() -> int:
    return int(time.time())


def _marks(n: int) -> str:
    return ",".join("?" * n)


def cap_bytes(config: Config) -> int:
    return int(config.vector_cache_max_gb * 1e9)


def machine_cache(config: Config) -> VectorCache:
    """The cache under the codemem home, with the configured cap."""
    folder = codemem_home() / "cache"
    return VectorCache(folder / CACHE_FILE, max_bytes=cap_bytes(config), import_from=folder / ROW_FORMAT_FILE)


class VectorCache:
    def __init__(self, path: Path | str, *, max_bytes: int = 0, import_from: Path | str | None = None):
        self.path = Path(path)
        self.max_bytes = max_bytes  # 0 = no cap
        self._import_from = Path(import_from) if import_from else None
        self._local = threading.local()
        # Every thread's connection, with its thread: close() must not close one a running thread uses.
        self._all: dict[int, tuple[threading.Thread, sqlite3.Connection]] = {}
        self._lock = threading.Lock()
        self._setup = threading.Lock()  # the schema and the import: once, before any thread reads
        self._ready = False
        self._retry_at = 0.0
        self._unchecked = float("inf")  # bytes written since the size was last looked at; the first put looks
        self._evicting = False  # over the cap and not yet back under the target

    # ---- connections
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=_BUSY_SECONDS, isolation_level=None, check_same_thread=False)
            try:
                if conn.execute("PRAGMA page_count").fetchone()[0] == 0:
                    # Both are fixed once the file has its first page.
                    conn.execute(f"PRAGMA page_size = {_PAGE_SIZE}")
                    conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")
                conn.execute("PRAGMA cache_size = -16000")  # up to 16 MB of pages per connection: one put's worth
                conn.execute("PRAGMA journal_size_limit = 67108864")  # a WAL that grew is cut back to 64 MB
                self._prepare(conn)
            except BaseException:
                conn.close()
                raise
            self._local.conn = conn
            with self._lock:
                self._all[id(conn)] = (threading.current_thread(), conn)
        return conn

    def _prepare(self, conn: sqlite3.Connection) -> None:
        with self._setup:
            if self._ready:
                return
            if conn.execute("PRAGMA user_version").fetchone()[0] != _LAYOUT:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    if conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]:
                        if conn.execute("PRAGMA user_version").fetchone()[0] != _LAYOUT:
                            raise sqlite3.DatabaseError(f"{self.path} is not a vector cache in layout {_LAYOUT}")
                    else:
                        for statement in _SCHEMA:
                            conn.execute(statement)
                        conn.execute(f"PRAGMA user_version = {_LAYOUT}")
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
            try:
                self._import(conn)
            except (sqlite3.Error, OSError) as e:
                # Its file stays, so the next process tries again.
                log.warning("could not import the vector cache at %s: %s", self._import_from, e)
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
            self._ready = True

    def _try(self, work: Callable[..., T], *args: Any) -> T | None:
        """`work(connection, *args)`, or None if the file cannot be used: a failure is logged, never raised."""
        if time.monotonic() < self._retry_at:
            return None
        try:
            return work(self._conn(), *args)
        except (sqlite3.Error, OSError) as e:
            log.warning("the vector cache at %s failed (%s); going on without it for %.0f s", self.path, e, _RETRY_SECONDS)
            self._retry_at = time.monotonic() + _RETRY_SECONDS
            self._drop(getattr(self._local, "conn", None))  # the next try starts from a new connection
            return None

    def _drop(self, conn: sqlite3.Connection | None) -> None:
        if conn is None:
            return
        with self._lock:
            self._all.pop(id(conn), None)
        self._local.conn = None
        try:
            conn.close()  # rolls an open transaction back
        except sqlite3.Error:
            pass

    def close(self) -> None:
        """Close this thread's connection and those of threads that have ended. A thread that is
        still running keeps its own: closing it under that thread's query crashes the process."""
        me = threading.current_thread()
        with self._lock:
            done = [k for k, (thread, _) in self._all.items() if thread is me or not thread.is_alive()]
            conns = [self._all.pop(k)[1] for k in done]
        for conn in conns:
            try:
                conn.close()
            except sqlite3.ProgrammingError:
                pass
        self._local.conn = None

    # ---- reading
    def get_many(self, embedder: str, hashes: Iterable[str], *, touch: bool = False) -> dict[str, np.ndarray]:
        """The vectors the cache holds for `hashes`, by hash. `touch` also marks them as used."""
        keys = [_pack(h) for h in dict.fromkeys(hashes)]
        dim, rows = self._try(self._read, embedder, keys, touch) or (0, [])
        return {_unpack(key): from_blob(data, dim) for key, data in rows}

    def fetch(self, embedder: str, hashes: Sequence[str], *, touch: bool = False) -> tuple[np.ndarray, np.ndarray]:
        """The vectors of `hashes`, in that order: a float16 array with one row per hash, and a
        mask of the rows found. A row that was not found is zeros. An embedder the cache has no
        vectors of gives rows of length 0."""
        places: dict[Key, list[int]] = defaultdict(list)
        for i, h in enumerate(hashes):
            places[_pack(h)].append(i)
        dim, rows = self._try(self._read, embedder, list(places), touch) or (0, [])
        vecs = np.zeros((len(hashes), dim), dtype=np.float16)
        found = np.zeros(len(hashes), dtype=bool)
        if rows:
            # One copy for all rows: row by row costs as much again as reading them.
            read = np.frombuffer(b"".join(data for _, data in rows), dtype=np.float16).reshape(len(rows), dim)
            to = [i for key, _ in rows for i in places[key]]
            vecs[to] = read[[r for r, (key, _) in enumerate(rows) for _ in places[key]]]
            found[to] = True
        return vecs, found

    def _read(self, conn: sqlite3.Connection, embedder: str, keys: list[Key], touch: bool) -> tuple[int, list[tuple[Key, bytes]]]:
        known = conn.execute("SELECT id, dim FROM embedder WHERE key = ?", (embedder,)).fetchone()
        if known is None:
            return 0, []
        eid, dim = known
        out: list[tuple[Key, bytes]] = []
        stale: list[Key] = []
        today = _now() // _DAY * _DAY
        for start in range(0, len(keys), _KEYS):
            batch = keys[start : start + _KEYS]
            # One statement, so one snapshot: an eviction that moves rows between slots cannot split it.
            rows = conn.execute(
                f"SELECT e.hash, e.used, v.data FROM entry e JOIN vec_{eid} v ON v.slot = e.slot "
                f"WHERE e.embedder = ? AND e.hash IN ({_marks(len(batch))}) AND length(v.data) = ?",
                (eid, *batch, 2 * dim),
            )
            for key, used, data in rows:
                out.append((key, data))
                if touch and used < today:
                    stale.append(key)
        self._stamp(conn, eid, stale)
        return dim, out

    # ---- last use
    def touch(self, embedder: str, hashes: Iterable[str]) -> list[str]:
        """Mark `hashes` as used now, and return those the cache does not hold. An entry is written
        once a day at most: a stamp from today is left alone. If the file cannot be read, [] comes
        back: nothing is known to be missing."""
        hashes = list(dict.fromkeys(hashes))
        missing = self._try(self._touch, embedder, hashes)
        return [] if missing is None else missing

    def _touch(self, conn: sqlite3.Connection, embedder: str, hashes: list[str]) -> list[str]:
        known = conn.execute("SELECT id FROM embedder WHERE key = ?", (embedder,)).fetchone()
        if known is None:
            return hashes
        today = _now() // _DAY * _DAY
        missing: list[str] = []
        stale: list[Key] = []
        for start in range(0, len(hashes), _KEYS):
            batch = hashes[start : start + _KEYS]
            keys = [_pack(h) for h in batch]
            held = self._held(conn, known[0], keys)
            stale += [key for key, used in held.items() if used < today]
            missing += [h for h, key in zip(batch, keys) if key not in held]
        self._stamp(conn, known[0], stale)
        return missing

    def _held(self, conn: sqlite3.Connection, eid: int, keys: list[Key]) -> dict[Key, int]:
        """Of `keys` (one batch), those the cache holds, with their time of last use."""
        rows = conn.execute(f"SELECT hash, used FROM entry WHERE embedder = ? AND hash IN ({_marks(len(keys))})", (eid, *keys))
        return dict(rows.fetchall())

    def _stamp(self, conn: sqlite3.Connection, eid: int, keys: list[Key]) -> None:
        """Set the time of last use of `keys` to now, in one transaction: a transaction writes each
        page it changes once, and a few hundred keys already change most pages of the key table."""
        if not keys:
            return
        now = _now()
        own = not conn.in_transaction
        if own:
            conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executemany("UPDATE entry SET used = ? WHERE embedder = ? AND hash = ?", [(now, eid, key) for key in keys])
            if own:
                conn.execute("COMMIT")
        except BaseException:
            if own:
                conn.execute("ROLLBACK")
            raise

    # ---- writing
    def put_many(self, embedder: str, hashes: Sequence[str], vecs: np.ndarray) -> None:
        """Store vectors (rows of `vecs`) under their hashes. A hash the cache already holds keeps
        its vector and counts as used."""
        if not len(hashes):
            return
        rows = np.ascontiguousarray(vecs, dtype=np.float16)
        written = self._try(
            self._store, embedder, [_pack(h) for h in hashes], [row.tobytes() for row in rows], int(rows.shape[1]), _now(), True
        )
        if written and self.max_bytes:
            self._try(self._check_size, written)

    def _store(self, conn: sqlite3.Connection, embedder: str, keys: list[Key], blobs: list[bytes], dim: int, used: int,
               touch: bool) -> int:
        """Add the entries the cache does not hold yet, in one transaction. Returns the bytes added."""
        conn.execute("BEGIN IMMEDIATE")
        try:
            known = conn.execute("SELECT id, dim FROM embedder WHERE key = ?", (embedder,)).fetchone()
            if known is None:
                eid = conn.execute("INSERT INTO embedder(key, dim) VALUES (?, ?)", (embedder, dim)).lastrowid
                conn.execute(_VECTORS.format(eid))
            elif known[1] != dim:
                # One embedder, one length: the rows of its table replace each other on eviction.
                log.warning("not cached: vectors of %d numbers for %s, whose vectors have %d", dim, embedder, known[1])
                conn.execute("ROLLBACK")
                return 0
            else:
                eid = known[0]
            new = dict(zip(keys, blobs))
            stale: list[Key] = []
            today = used // _DAY * _DAY
            for start in range(0, len(keys), _KEYS):
                for key, last in self._held(conn, eid, keys[start : start + _KEYS]).items():
                    new.pop(key, None)
                    if last < today:
                        stale.append(key)
            if touch:
                self._stamp(conn, eid, stale)
            last_slot = conn.execute(f"SELECT COALESCE(MAX(slot), 0) FROM vec_{eid}").fetchone()[0]
            slots = range(last_slot + 1, last_slot + 1 + len(new))
            conn.executemany(
                f"INSERT INTO vec_{eid}(slot, hash, data) VALUES (?, ?, ?)",
                [(slot, key, blob) for slot, (key, blob) in zip(slots, new.items())],
            )
            conn.executemany(
                "INSERT INTO entry(embedder, hash, slot, used) VALUES (?, ?, ?, ?)",
                [(eid, key, slot, used) for slot, key in zip(slots, new)],
            )
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        return sum(len(blob) for blob in new.values())

    # ---- the cap
    def _check_size(self, conn: sqlite3.Connection, written: int) -> int:
        with self._lock:
            self._unchecked += written
            if not self._evicting and self._unchecked < self.max_bytes * _CHECK:
                return 0
            self._unchecked = 0
        return self._evict(conn, _EVICT_SECONDS)

    def evict(self, max_seconds: float | None = None) -> int:
        """If the file is over its cap, delete the least recently used entries until it is under
        90% of the cap, and give the freed pages back to the file system. With `max_seconds` it
        stops after about that long, and the next call goes on. Returns the entries deleted."""
        return self._try(self._evict, max_seconds) or 0

    def _evict(self, conn: sqlite3.Connection, max_seconds: float | None) -> int:
        page = conn.execute("PRAGMA page_size").fetchone()[0]

        def size(free: bool) -> int:
            """The file's pages in bytes, with or without the free ones."""
            unused = 0 if free else conn.execute("PRAGMA freelist_count").fetchone()[0]
            return (conn.execute("PRAGMA page_count").fetchone()[0] - unused) * page

        if not self.max_bytes or (size(free=True) <= self.max_bytes and not self._evicting):
            return 0
        if not self._evicting:
            log.info("the vector cache at %s is over its cap of %d bytes: deleting the least recently used", self.path, self.max_bytes)
        self._evicting = True
        until = None if max_seconds is None else time.monotonic() + max_seconds
        deleted = 0
        # What is in use decides when to stop: if free pages could not be given back, deleting more would not help.
        while size(free=False) > self.max_bytes * _TARGET:
            n = self._evict_batch(conn)
            deleted += n
            if n == 0:
                break
            conn.executescript("PRAGMA incremental_vacuum")  # execute() would stop after one page
            if until is not None and time.monotonic() >= until:
                return deleted
        self._evicting = False
        conn.executescript("PRAGMA incremental_vacuum")
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall()  # the file shrinks when the WAL is copied back
        log.info("the vector cache at %s is at %d bytes after eviction", self.path, size(free=True))
        return deleted

    def _evict_batch(self, conn: sqlite3.Connection) -> int:
        """Delete the `_EVICT_ROWS` least recently used entries. In each vector table the last rows
        move into the freed slots, so the slots stay 1..n and the freed pages are the table's last."""
        conn.execute("BEGIN IMMEDIATE")
        try:
            victims = conn.execute(
                "SELECT embedder, hash, slot FROM entry INDEXED BY entry_used ORDER BY used LIMIT ?", (_EVICT_ROWS,)
            ).fetchall()
            for eid, group in groupby(sorted(victims, key=itemgetter(0)), key=itemgetter(0)):
                gone = {slot: key for _, key, slot in group}
                last_slot = conn.execute(f"SELECT COALESCE(MAX(slot), 0) FROM vec_{eid}").fetchone()[0]
                end = last_slot - len(gone)  # the slots that stay in use: 1..end
                movers = [
                    row for row in conn.execute(f"SELECT slot, hash, data FROM vec_{eid} WHERE slot > ?", (end,))
                    if row[0] not in gone
                ]
                holes = sorted(slot for slot in gone if slot <= end)
                if len(movers) != len(holes):
                    raise sqlite3.DatabaseError(f"vec_{eid} in {self.path} has gaps in its slots")
                # Written over the deleted row, which has the same size: its page is not rebuilt.
                conn.executemany(
                    f"UPDATE vec_{eid} SET hash = ?, data = ? WHERE slot = ?",
                    [(key, data, hole) for (_, key, data), hole in zip(movers, holes)],
                )
                conn.executemany(
                    "UPDATE entry SET slot = ? WHERE embedder = ? AND hash = ?",
                    [(hole, eid, key) for (_, key, _), hole in zip(movers, holes)],
                )
                conn.execute(f"DELETE FROM vec_{eid} WHERE slot > ?", (end,))
                conn.executemany("DELETE FROM entry WHERE embedder = ? AND hash = ?", [(eid, key) for key in gone.values()])
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return len(victims)

    # ---- counts
    def count(self, embedder: str | None = None) -> int:
        stats = self.stats()
        if stats is None:
            return 0
        if embedder is None:
            return stats["entries"]
        return stats["embedders"].get(embedder, {}).get("entries", 0)

    def stats(self) -> dict[str, Any] | None:
        """Entries, the file's size in bytes as the cap counts it (its pages), the cap, and the
        entries and vector length of each embedder. None if the file cannot be read."""
        return self._try(self._stats)

    def _stats(self, conn: sqlite3.Connection) -> dict[str, Any]:
        embedders = {
            key: {"entries": conn.execute(f"SELECT COALESCE(MAX(slot), 0) FROM vec_{eid}").fetchone()[0], "dim": dim}
            for eid, key, dim in conn.execute("SELECT id, key, dim FROM embedder ORDER BY key").fetchall()
        }
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
        return {
            "path": str(self.path),
            "entries": sum(e["entries"] for e in embedders.values()),
            "bytes": pages * conn.execute("PRAGMA page_size").fetchone()[0],
            "max_bytes": self.max_bytes,
            "embedders": embedders,
        }

    # ---- a cache file in the row format
    def _import(self, conn: sqlite3.Connection) -> None:
        """Copy every vector of the row-format file into this one, in key order and in batches, then
        delete that file. Entries already here are skipped, so a copy that was interrupted, or that
        two processes run at once, ends complete."""
        src = self._import_from
        if src is None or not src.is_file():
            return
        try:
            old = sqlite3.connect(f"{src.resolve().as_uri()}?mode=rw", uri=True, timeout=_BUSY_SECONDS)  # rw: never create it
        except sqlite3.OperationalError:
            return  # another process finished the copy and deleted it
        try:
            if not old.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cache'").fetchone():
                return
            total = old.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            log.warning("importing %d vectors from %s into %s; this happens once", total, src, self.path)
            used = int(src.stat().st_mtime)  # the last time anything was added there
            last, done, said = ("", ""), 0, time.monotonic()
            while rows := old.execute(_OLD_ROWS, (*last, _IMPORT_ROWS)).fetchall():
                last = rows[-1][:2]
                for (embedder, dim), group in groupby(rows, key=lambda r: (r[0], r[2])):
                    good = [(_pack(h), data) for _, h, _, data in group if len(data) == 2 * dim]
                    written = self._store(conn, embedder, [k for k, _ in good], [d for _, d in good], dim, used, False) if good else 0
                    if written and self.max_bytes:
                        self._check_size(conn, written)
                done += len(rows)
                if time.monotonic() - said > 5:
                    log.info("importing the vector cache: %d of %d vectors", done, total)
                    said = time.monotonic()
        finally:
            old.close()
        # Durable before the source goes: a WAL commit alone is not synced to disk.
        if conn.execute("PRAGMA wal_checkpoint(FULL)").fetchone()[0]:
            return  # a reader held it up: the next start finds everything copied, and deletes the file then
        try:
            for name in (src.name, f"{src.name}-wal", f"{src.name}-shm"):
                src.with_name(name).unlink(missing_ok=True)
        except OSError:  # open in another process (Windows): the next start deletes it
            log.info("imported %d vectors; %s cannot be deleted yet", done, src)
            return
        log.warning("imported %d vectors; %s is deleted", done, src)
