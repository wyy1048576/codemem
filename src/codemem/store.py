"""Storage: SQLite (metadata, FTS5, call graph) + one FAISS index per vector type.

Consistency model
-----------------
SQLite is the source of truth for chunks and for *which texts are embedded*
(`embeddings` table). FAISS lives in memory and is saved to disk at the end
of an update (and periodically during long ones). Each `vec_<type>.faiss` has a
sidecar `vec_<type>.ids.json` mapping chunk_id -> text_hash for the vectors in
that file. On open, `reconcile()` drops `embeddings` rows that don't match the
sidecar, so after a crash those texts are simply re-embedded.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from .schema import Chunk
from .texts import Ref
from .tokenize import to_fts_text

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY, content_hash TEXT NOT NULL, mtime REAL NOT NULL, size INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL,
    qualname TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    class_name TEXT,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature TEXT NOT NULL,
    docstring TEXT NOT NULL,
    code TEXT NOT NULL,
    content_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
CREATE INDEX IF NOT EXISTS chunks_name ON chunks(name);
CREATE TABLE IF NOT EXISTS calls (caller_id INTEGER NOT NULL, callee_name TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS calls_caller ON calls(caller_id);
CREATE TABLE IF NOT EXISTS edges (
    caller_id INTEGER NOT NULL, callee_id INTEGER NOT NULL, PRIMARY KEY (caller_id, callee_id)
);
CREATE INDEX IF NOT EXISTS edges_callee ON edges(callee_id);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    name_tokens, signature_tokens, body_tokens, tokenize = "unicode61 tokenchars '_'"
);
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id INTEGER NOT NULL, vec_type TEXT NOT NULL, text_hash TEXT NOT NULL, model TEXT NOT NULL,
    PRIMARY KEY (chunk_id, vec_type)
);
"""

_CHUNK_COLS = (
    "chunk_id, key, path, qualname, name, kind, class_name, start_line, end_line, "
    "signature, docstring, code, content_hash"
)


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)  # atomic on Windows and POSIX


# --------------------------------------------------------------------------- vectors


class VectorStore(ABC):
    """Swappable vector index keyed by chunk_id. Vectors must be L2-normalized."""

    dim: int

    @abstractmethod
    def upsert(self, ids: Sequence[int], vecs: np.ndarray) -> None: ...

    @abstractmethod
    def remove(self, ids: Iterable[int]) -> None: ...

    @abstractmethod
    def search(
        self, query: np.ndarray, k: int, allowed_ids: Sequence[int] | None = None
    ) -> list[tuple[int, float]]: ...

    @abstractmethod
    def ids(self) -> set[int]: ...

    @abstractmethod
    def __len__(self) -> int: ...


class FaissVectorStore(VectorStore):
    """Exact inner-product search; IndexIDMap2 so chunk_id is the FAISS id."""

    def __init__(self, dim: int, index: Any = None):
        self.dim = dim
        self.index = index if index is not None else faiss.IndexIDMap2(faiss.IndexFlatIP(dim))

    def upsert(self, ids: Sequence[int], vecs: np.ndarray) -> None:
        if len(ids) == 0:
            return
        id_arr = np.asarray(ids, dtype=np.int64)
        vecs = np.ascontiguousarray(vecs, dtype=np.float32)
        if vecs.shape != (len(id_arr), self.dim):
            raise ValueError(f"expected vectors of shape ({len(id_arr)}, {self.dim}), got {vecs.shape}")
        self.index.remove_ids(id_arr)
        self.index.add_with_ids(vecs, id_arr)

    def remove(self, ids: Iterable[int]) -> None:
        id_arr = np.asarray(list(ids), dtype=np.int64)
        if len(id_arr):
            self.index.remove_ids(id_arr)

    def search(self, query, k, allowed_ids=None):
        if self.index.ntotal == 0 or k <= 0:
            return []
        q = np.ascontiguousarray(np.asarray(query, dtype=np.float32).reshape(1, -1))
        params = None
        if allowed_ids is not None:
            if len(allowed_ids) == 0:
                return []
            selector = faiss.IDSelectorBatch(np.asarray(allowed_ids, dtype=np.int64))
            params = faiss.SearchParameters(sel=selector)
        scores, ids = self.index.search(q, min(k, self.index.ntotal), params=params)
        return [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1]

    def ids(self) -> set[int]:
        return set(faiss.vector_to_array(self.index.id_map).tolist())

    def __len__(self) -> int:
        return int(self.index.ntotal)

    def save(self, path: Path) -> None:
        _atomic_write(path, faiss.serialize_index(self.index).tobytes())

    @classmethod
    def load(cls, path: Path) -> FaissVectorStore:
        # Read through Python (not faiss.read_index) so non-ASCII Windows paths work.
        index = faiss.deserialize_index(np.frombuffer(path.read_bytes(), dtype=np.uint8))
        return cls(index.d, index)


# --------------------------------------------------------------------------- lock


class IndexLock:
    """Exclusive writer lock on <index_dir>/write.lock. Released by the OS if the process dies."""

    def __init__(self, index_dir: Path):
        self.path = Path(index_dir) / "write.lock"
        self._fh = None

    def acquire(self, timeout: float = 30.0) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fh = fh
                return
            except OSError:
                if time.monotonic() >= deadline:
                    fh.close()
                    raise TimeoutError(f"another codemem process is writing to {self.path.parent}")
                time.sleep(0.1)

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> IndexLock:
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


# --------------------------------------------------------------------------- store


def _row_to_chunk(row: sqlite3.Row) -> Chunk:
    return Chunk(
        chunk_id=row["chunk_id"], key=row["key"], path=row["path"], qualname=row["qualname"],
        name=row["name"], kind=row["kind"], class_name=row["class_name"],
        start_line=row["start_line"], end_line=row["end_line"], signature=row["signature"],
        docstring=row["docstring"], code=row["code"], content_hash=row["content_hash"],
    )


def _like_prefix(prefix: str) -> str:
    prefix = prefix.replace("\\", "/").removeprefix("./").lstrip("/")
    return prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


class Store:
    def __init__(self, index_dir: Path | str, *, bm25_stem: bool = False, bm25_stopwords: bool = False):
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.index_dir / "index.db"
        self.tok_opts = {"stem": bm25_stem, "stopwords": bm25_stopwords}
        self._local = threading.local()
        self._vec_lock = threading.RLock()
        self._vectors: dict[str, FaissVectorStore] = {}
        self._vectors_loaded: set[str] = set()
        self._dirty: set[str] = set()
        self._all_conns: list[sqlite3.Connection] = []
        conn = self.conn
        conn.executescript(_SCHEMA)
        if self.get_meta("schema_version") is None:
            self.set_meta("schema_version", SCHEMA_VERSION)

    # ---- connections
    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
            self._all_conns.append(conn)
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.conn
        if conn.in_transaction:  # nested: join the outer transaction
            yield conn
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")

    def close_thread_conn(self) -> None:
        """Close the calling thread's connection (for short-lived worker threads)."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            self._local.conn = None
            if conn in self._all_conns:
                self._all_conns.remove(conn)
            conn.close()

    def close(self) -> None:
        for conn in self._all_conns:
            try:
                conn.close()
            except sqlite3.ProgrammingError:
                pass
        self._all_conns.clear()
        self._local = threading.local()

    # ---- meta
    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_meta(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    # ---- files
    def get_files(self) -> dict[str, tuple[str, float, int]]:
        rows = self.conn.execute("SELECT path, content_hash, mtime, size FROM files")
        return {r["path"]: (r["content_hash"], r["mtime"], r["size"]) for r in rows}

    def upsert_file(self, path: str, content_hash: str, mtime: float, size: int) -> None:
        self.conn.execute(
            "INSERT INTO files(path, content_hash, mtime, size) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET content_hash=excluded.content_hash, "
            "mtime=excluded.mtime, size=excluded.size",
            (path, content_hash, mtime, size),
        )

    def delete_file(self, path: str) -> list[int]:
        ids = [r[0] for r in self.conn.execute("SELECT chunk_id FROM chunks WHERE path = ?", (path,))]
        self.delete_chunks(ids)
        self.conn.execute("DELETE FROM files WHERE path = ?", (path,))
        return ids

    # ---- chunks
    def upsert_chunk(self, chunk: Chunk) -> int:
        """Insert or update by `key` (chunk_id is stable across updates). Also refreshes FTS + calls."""
        conn = self.conn
        values = (
            chunk.path, chunk.qualname, chunk.name, chunk.kind, chunk.class_name, chunk.start_line,
            chunk.end_line, chunk.signature, chunk.docstring, chunk.code, chunk.content_hash,
        )
        row = conn.execute("SELECT chunk_id FROM chunks WHERE key = ?", (chunk.key,)).fetchone()
        if row:
            chunk_id = row[0]
            conn.execute(
                "UPDATE chunks SET path=?, qualname=?, name=?, kind=?, class_name=?, start_line=?, "
                "end_line=?, signature=?, docstring=?, code=?, content_hash=? WHERE chunk_id=?",
                (*values, chunk_id),
            )
            conn.execute("DELETE FROM fts WHERE rowid = ?", (chunk_id,))
            conn.execute("DELETE FROM calls WHERE caller_id = ?", (chunk_id,))
        else:
            cur = conn.execute(
                "INSERT INTO chunks(key, path, qualname, name, kind, class_name, start_line, end_line, "
                "signature, docstring, code, content_hash) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (chunk.key, *values),
            )
            chunk_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO fts(rowid, name_tokens, signature_tokens, body_tokens) VALUES(?, ?, ?, ?)",
            (
                chunk_id,
                to_fts_text(f"{chunk.qualname} {chunk.name}", **self.tok_opts),
                to_fts_text(chunk.signature, **self.tok_opts),
                to_fts_text(f"{chunk.docstring}\n{chunk.code}", **self.tok_opts),
            ),
        )
        conn.executemany(
            "INSERT INTO calls(caller_id, callee_name) VALUES(?, ?)", [(chunk_id, c) for c in chunk.calls]
        )
        chunk.chunk_id = chunk_id
        return chunk_id

    def delete_chunks(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        if not ids:
            return
        conn = self.conn
        params = [(i,) for i in ids]
        conn.executemany("DELETE FROM chunks WHERE chunk_id = ?", params)
        conn.executemany("DELETE FROM fts WHERE rowid = ?", params)
        conn.executemany("DELETE FROM calls WHERE caller_id = ?", params)
        conn.executemany("DELETE FROM edges WHERE caller_id = ? OR callee_id = ?", [(i, i) for i in ids])
        vec_types = [r[0] for r in conn.execute("SELECT DISTINCT vec_type FROM embeddings")]
        conn.executemany("DELETE FROM embeddings WHERE chunk_id = ?", params)
        for vec_type in vec_types:
            vs = self.vectors(vec_type)
            if vs is not None:
                with self._vec_lock:
                    vs.remove(ids)
                self._dirty.add(vec_type)

    def chunks_for_path(self, path: str) -> list[Chunk]:
        rows = self.conn.execute(f"SELECT {_CHUNK_COLS} FROM chunks WHERE path = ? ORDER BY start_line", (path,))
        return [_row_to_chunk(r) for r in rows]

    def get_chunks(self, ids: Iterable[int]) -> dict[int, Chunk]:
        ids = list(ids)
        out: dict[int, Chunk] = {}
        for start in range(0, len(ids), 500):
            batch = ids[start : start + 500]
            marks = ",".join("?" * len(batch))
            for r in self.conn.execute(f"SELECT {_CHUNK_COLS} FROM chunks WHERE chunk_id IN ({marks})", batch):
                out[r["chunk_id"]] = _row_to_chunk(r)
        return out

    def get_chunk(self, chunk_id: int) -> Chunk | None:
        return self.get_chunks([chunk_id]).get(chunk_id)

    def get_chunk_by_key(self, key: str) -> Chunk | None:
        r = self.conn.execute(f"SELECT {_CHUNK_COLS} FROM chunks WHERE key = ?", (key,)).fetchone()
        return _row_to_chunk(r) if r else None

    def find_chunk_at(self, path: str, line: int) -> Chunk | None:
        """Innermost function/method containing `line`, else the file header."""
        r = self.conn.execute(
            f"SELECT {_CHUNK_COLS} FROM chunks WHERE path = ? AND start_line <= ? AND end_line >= ? "
            "ORDER BY kind = 'file_header', end_line - start_line LIMIT 1",
            (path.replace("\\", "/"), line, line),
        ).fetchone()
        return _row_to_chunk(r) if r else None

    def iter_chunks(self) -> Iterator[Chunk]:
        for r in self.conn.execute(f"SELECT {_CHUNK_COLS} FROM chunks ORDER BY chunk_id"):
            yield _row_to_chunk(r)

    def ids_with_prefix(self, prefix: str) -> list[int]:
        rows = self.conn.execute("SELECT chunk_id FROM chunks WHERE path LIKE ? ESCAPE '!'", (_like_prefix(prefix),))
        return [r[0] for r in rows]

    # ---- call graph
    def definitions(self) -> list[tuple[int, str]]:
        rows = self.conn.execute("SELECT chunk_id, name FROM chunks WHERE kind != 'file_header'")
        return [(r[0], r[1]) for r in rows]

    def all_calls(self) -> list[tuple[int, str]]:
        return [(r[0], r[1]) for r in self.conn.execute("SELECT caller_id, callee_name FROM calls")]

    def replace_edges(self, edges: Iterable[tuple[int, int]]) -> None:
        self.conn.execute("DELETE FROM edges")
        self.conn.executemany("INSERT INTO edges(caller_id, callee_id) VALUES(?, ?)", sorted(edges))

    def caller_refs(self) -> dict[int, list[Ref]]:
        out: dict[int, list[Ref]] = {}
        rows = self.conn.execute(
            "SELECT e.callee_id, c.chunk_id, c.qualname, c.name, c.path, c.start_line "
            "FROM edges e JOIN chunks c ON c.chunk_id = e.caller_id"
        )
        for r in rows:
            out.setdefault(r[0], []).append(Ref(r[1], r[2], r[3], r[4], r[5]))
        return out

    def callers_of(self, chunk_id: int) -> list[Chunk]:
        ids = [r[0] for r in self.conn.execute("SELECT caller_id FROM edges WHERE callee_id = ?", (chunk_id,))]
        return sorted(self.get_chunks(ids).values(), key=lambda c: (c.path, c.start_line))

    def callees_of(self, chunk_id: int) -> list[Chunk]:
        ids = [r[0] for r in self.conn.execute("SELECT callee_id FROM edges WHERE caller_id = ?", (chunk_id,))]
        return sorted(self.get_chunks(ids).values(), key=lambda c: (c.path, c.start_line))

    # ---- BM25
    def bm25_search(
        self, match: str, n: int, weights: Sequence[float], path_prefix: str | None = None
    ) -> list[int]:
        sql = "SELECT f.rowid FROM fts f"
        params: list[Any] = [match]
        where = "fts MATCH ?"
        if path_prefix:
            sql += " JOIN chunks c ON c.chunk_id = f.rowid"
            where += " AND c.path LIKE ? ESCAPE '!'"
            params.append(_like_prefix(path_prefix))
        w = [float(x) for x in weights]
        sql += f" WHERE {where} ORDER BY bm25(fts, ?, ?, ?) LIMIT ?"
        return [r[0] for r in self.conn.execute(sql, (*params, *w, n))]

    # ---- embeddings / vectors
    def _vec_path(self, vec_type: str) -> Path:
        return self.index_dir / f"vec_{vec_type}.faiss"

    def _sidecar_path(self, vec_type: str) -> Path:
        return self.index_dir / f"vec_{vec_type}.ids.json"

    def vectors(self, vec_type: str) -> FaissVectorStore | None:
        with self._vec_lock:
            if vec_type not in self._vectors_loaded:
                self._vectors_loaded.add(vec_type)
                path = self._vec_path(vec_type)
                if path.is_file():
                    try:
                        self._vectors[vec_type] = FaissVectorStore.load(path)
                    except Exception:  # corrupt file: rebuild this vec type
                        log.exception("could not load %s; it will be rebuilt", path)
            return self._vectors.get(vec_type)

    def vec_types(self) -> list[str]:
        """Vector types that have stored embeddings."""
        return [r[0] for r in self.conn.execute("SELECT DISTINCT vec_type FROM embeddings ORDER BY vec_type")]

    def ensure_vec_type(self, vec_type: str, model_id: str) -> bool:
        """Drop a vec type whose stored model differs from `model_id`. Returns True if reset."""
        stored = self.get_meta(f"vec.{vec_type}.model")
        if stored == model_id:
            return False
        if stored is not None:
            log.info("model for %s changed (%s -> %s); rebuilding that vector set", vec_type, stored, model_id)
        self.drop_vec_type(vec_type)
        self.set_meta(f"vec.{vec_type}.model", model_id)
        return stored is not None

    def drop_vec_type(self, vec_type: str) -> None:
        self.conn.execute("DELETE FROM embeddings WHERE vec_type = ?", (vec_type,))
        self.conn.execute("DELETE FROM meta WHERE key IN (?, ?)", (f"vec.{vec_type}.model", f"vec.{vec_type}.dim"))
        with self._vec_lock:
            self._vectors.pop(vec_type, None)
            self._vectors_loaded.add(vec_type)
            self._dirty.add(vec_type)
        for p in (self._vec_path(vec_type), self._sidecar_path(vec_type)):
            p.unlink(missing_ok=True)

    def embedding_hashes(self, vec_type: str) -> dict[int, str]:
        rows = self.conn.execute("SELECT chunk_id, text_hash FROM embeddings WHERE vec_type = ?", (vec_type,))
        return {r[0]: r[1] for r in rows}

    def put_embeddings(
        self, vec_type: str, model_id: str, ids: Sequence[int], hashes: Sequence[str], vecs: np.ndarray
    ) -> None:
        if not len(ids):
            return
        dim = int(vecs.shape[1])
        with self._vec_lock:
            vs = self.vectors(vec_type)
            if vs is None or vs.dim != dim:
                if vs is not None:
                    log.info("dimension of %s changed (%d -> %d); rebuilding", vec_type, vs.dim, dim)
                    self.conn.execute("DELETE FROM embeddings WHERE vec_type = ?", (vec_type,))
                vs = self._vectors[vec_type] = FaissVectorStore(dim)
            vs.upsert(ids, vecs)
            self._dirty.add(vec_type)
        self.set_meta(f"vec.{vec_type}.dim", dim)
        self.conn.executemany(
            "INSERT INTO embeddings(chunk_id, vec_type, text_hash, model) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(chunk_id, vec_type) DO UPDATE SET text_hash=excluded.text_hash, model=excluded.model",
            [(int(i), vec_type, h, model_id) for i, h in zip(ids, hashes)],
        )

    def remove_embeddings(self, vec_type: str, ids: Iterable[int]) -> None:
        ids = list(ids)
        if not ids:
            return
        self.conn.executemany(
            "DELETE FROM embeddings WHERE chunk_id = ? AND vec_type = ?", [(i, vec_type) for i in ids]
        )
        with self._vec_lock:
            vs = self.vectors(vec_type)
            if vs is not None:
                vs.remove(ids)
                self._dirty.add(vec_type)

    def vector_search(
        self, vec_type: str, query: np.ndarray, n: int, allowed_ids: Sequence[int] | None = None
    ) -> list[tuple[int, float]]:
        with self._vec_lock:
            vs = self.vectors(vec_type)
            return vs.search(query, n, allowed_ids) if vs is not None else []

    def save_vectors(self) -> None:
        """Persist dirty FAISS indexes + sidecars. Call after committing embedding rows."""
        with self._vec_lock:
            for vec_type in sorted(self._dirty):
                vs = self._vectors.get(vec_type)
                if vs is None:
                    continue
                hashes = self.embedding_hashes(vec_type)
                ids = vs.ids()
                sidecar = {str(i): hashes[i] for i in ids if i in hashes}
                vs.save(self._vec_path(vec_type))
                _atomic_write(self._sidecar_path(vec_type), json.dumps(sidecar).encode("utf-8"))
            self._dirty.clear()

    def reconcile(self) -> dict[str, int]:
        """Make `embeddings` agree with what the saved FAISS files contain. Writer-only."""
        dropped: dict[str, int] = {}
        for vec_type in self.vec_types():
            vs = self.vectors(vec_type)
            sidecar_path = self._sidecar_path(vec_type)
            saved: dict[int, str] = {}
            if vs is not None and sidecar_path.is_file():
                try:
                    saved = {int(k): v for k, v in json.loads(sidecar_path.read_text("utf-8")).items()}
                except (ValueError, OSError):
                    saved = {}
                if set(saved) != vs.ids():  # crashed between the two writes: distrust both
                    saved = {}
            if not saved and vs is not None:
                with self._vec_lock:
                    self._vectors.pop(vec_type, None)
            rows = self.embedding_hashes(vec_type)
            stale = [i for i, h in rows.items() if saved.get(i) != h]
            if stale:
                self.conn.executemany(
                    "DELETE FROM embeddings WHERE chunk_id = ? AND vec_type = ?", [(i, vec_type) for i in stale]
                )
                dropped[vec_type] = len(stale)
            orphans = set(saved) - set(rows)
            if orphans and vec_type in self._vectors:
                with self._vec_lock:
                    self._vectors[vec_type].remove(orphans)
                self._dirty.add(vec_type)
        if dropped:
            log.warning("reconciled vectors after an interrupted update: %s", dropped)
        return dropped

    # ---- stats
    def counts(self) -> dict[str, Any]:
        c = self.conn
        by_kind = {r[0]: r[1] for r in c.execute("SELECT kind, COUNT(*) FROM chunks GROUP BY kind")}
        vectors = {
            r[0]: r[1] for r in c.execute("SELECT vec_type, COUNT(*) FROM embeddings GROUP BY vec_type")
        }
        return {
            "files": c.execute("SELECT COUNT(*) FROM files").fetchone()[0],
            "chunks": sum(by_kind.values()),
            "chunks_by_kind": by_kind,
            "edges": c.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "vectors": vectors,
        }
