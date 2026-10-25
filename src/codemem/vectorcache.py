"""Content-addressed vector cache shared by every index: (embedder key, text hash) -> vector.

An index stores its own vectors (so an index folder is self-contained); this cache only saves
recomputation. Rebuilding an index, indexing another commit of the same repo, or building a
variant that differs in one text type finds most texts here and embeds only the rest. Vectors
are float16 at the model's full dimension. Several processes may share the file (SQLite WAL).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    embedder TEXT NOT NULL, text_hash TEXT NOT NULL, dim INTEGER NOT NULL, data BLOB NOT NULL,
    PRIMARY KEY (embedder, text_hash)
) WITHOUT ROWID;
"""


def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float16).tobytes()


def from_blob(data: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float16, count=dim)


class VectorCache:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        # Every thread's connection, with its thread: close() must not close one a running thread uses.
        self._all: dict[int, tuple[threading.Thread, sqlite3.Connection]] = {}
        self._lock = threading.Lock()
        self._conn().executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=60, isolation_level=None, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
            with self._lock:
                self._all[id(conn)] = (threading.current_thread(), conn)
        return conn

    def get_many(self, embedder: str, hashes: Iterable[str]) -> dict[str, np.ndarray]:
        hashes = list(dict.fromkeys(hashes))
        out: dict[str, np.ndarray] = {}
        conn = self._conn()
        for start in range(0, len(hashes), 500):
            batch = hashes[start : start + 500]
            marks = ",".join("?" * len(batch))
            rows = conn.execute(
                f"SELECT text_hash, dim, data FROM cache WHERE embedder = ? AND text_hash IN ({marks})", (embedder, *batch)
            )
            for text_hash, dim, data in rows:
                out[text_hash] = from_blob(data, dim)
        return out

    def put_many(self, embedder: str, hashes: Sequence[str], vecs: np.ndarray) -> None:
        if not len(hashes):
            return
        dim = int(vecs.shape[1])
        rows = [(embedder, h, dim, to_blob(v)) for h, v in zip(hashes, vecs)]
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany("INSERT OR IGNORE INTO cache(embedder, text_hash, dim, data) VALUES(?, ?, ?, ?)", rows)
            conn.execute("COMMIT")
        except sqlite3.Error:
            # The cache only saves work: never let it break an index update.
            log.exception("could not write the vector cache at %s", self.path)
            if conn.in_transaction:
                conn.execute("ROLLBACK")

    def count(self, embedder: str | None = None) -> int:
        if embedder is None:
            return self._conn().execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        return self._conn().execute("SELECT COUNT(*) FROM cache WHERE embedder = ?", (embedder,)).fetchone()[0]

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
