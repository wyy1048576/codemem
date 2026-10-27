"""Storage: SQLite (chunks, FTS5, call graph, vectors) + one in-memory search index per vector type.

Consistency model
-----------------
SQLite is the source of truth for everything, vectors included: each row of `vectors` holds one
float16 vector at the model's full dimension, with the chunk, part (window) and text hash it
came from. The search index is derived from those rows: by default FAISS, an exact inner-product
index over vector ids that holds the same 2-byte numbers (or another `VectorStore` backend,
named in config), truncated to `embedding_dim` if set, kept in memory and saved as
`vec_<type>.faiss` with a `vec_<type>.json` note of the epoch it reflects (and the backend that
wrote it). Every transaction that changes a vector type's
rows bumps its epoch in `meta`, and FAISS is patched right after the commit (never before, so it
never holds an uncommitted vector). Vector rows never change in place: a new vector is a new row
with a new id. So an index that is behind (a saved file from before a crash, or another process
wrote) catches up by comparing vector ids and applying only the difference; a missing or corrupt
file is rebuilt from the rows, which needs no model. docs/architecture.md §5 lists the tables.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import faiss
import numpy as np

from .plugins import load_object
from .schema import CALLABLE_KINDS, Chunk
from .texts import Ref
from .tokenize import to_fts_text
from .vectorcache import from_blob, to_blob

log = logging.getLogger(__name__)

SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY, language TEXT NOT NULL, content_hash TEXT NOT NULL, mtime REAL NOT NULL,
    size INTEGER NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL,
    language TEXT NOT NULL,
    kind TEXT NOT NULL,
    subkind TEXT NOT NULL,
    name TEXT NOT NULL,
    qualname TEXT NOT NULL,
    class_name TEXT,
    parent_key TEXT,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature TEXT NOT NULL,
    docstring TEXT NOT NULL,
    code TEXT NOT NULL,
    skeleton TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    is_test INTEGER NOT NULL,
    lead_comment TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
CREATE INDEX IF NOT EXISTS chunks_name ON chunks(name);
CREATE INDEX IF NOT EXISTS chunks_parent ON chunks(parent_key);
-- Covers caller lookups (usage texts), so they never read the pages that hold code.
CREATE INDEX IF NOT EXISTS chunks_ref ON chunks(chunk_id, path, start_line, qualname, name, kind, is_test);
CREATE TABLE IF NOT EXISTS calls (caller_id INTEGER NOT NULL, callee_name TEXT NOT NULL, line INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS calls_caller ON calls(caller_id);
CREATE INDEX IF NOT EXISTS calls_callee ON calls(callee_name);
CREATE TABLE IF NOT EXISTS dirty_texts (chunk_id INTEGER PRIMARY KEY, seq INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS edges (
    caller_id INTEGER NOT NULL, callee_id INTEGER NOT NULL, PRIMARY KEY (caller_id, callee_id)
);
CREATE INDEX IF NOT EXISTS edges_callee ON edges(callee_id);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    name_tokens, path_tokens, signature_tokens, doc_tokens, body_tokens, tokenize = "unicode61 tokenchars '_'"
);
CREATE VIRTUAL TABLE IF NOT EXISTS fts_vocab USING fts5vocab(fts, 'row');
CREATE TABLE IF NOT EXISTS vectors (
    vector_id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id INTEGER NOT NULL,
    vec_type TEXT NOT NULL,
    part INTEGER NOT NULL,
    n_parts INTEGER NOT NULL,
    start_off INTEGER NOT NULL,
    end_off INTEGER NOT NULL,
    text_hash TEXT NOT NULL,
    embedder TEXT NOT NULL,
    dim INTEGER NOT NULL,
    data BLOB NOT NULL,
    UNIQUE (chunk_id, vec_type, part)
);
CREATE INDEX IF NOT EXISTS vectors_type ON vectors(vec_type, chunk_id);
CREATE INDEX IF NOT EXISTS vectors_hash ON vectors(embedder, text_hash);
"""
# Every table any schema version has created, dropped when an older index is rebuilt.
_OLD_TABLES = ("meta", "files", "chunks", "calls", "edges", "fts_vocab", "fts", "embeddings", "vectors", "dirty_texts")

_CHUNK_COLS = (
    "chunk_id, key, path, language, kind, subkind, name, qualname, class_name, parent_key, start_line, "
    "end_line, signature, docstring, code, skeleton, content_hash, is_test, lead_comment"
)


def _atomic_write(path: Path, data: bytes) -> None:
    # A name of its own per process and thread: two writers never share a half-written temp file.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)  # atomic on Windows and POSIX


def bm25_weights5(weights: Sequence[float]) -> tuple[float, ...]:
    """name, path, signature, doc, body. A 3-value list from older configs (name, signature, body) is mapped to it."""
    w = tuple(float(x) for x in weights)
    if len(w) == 3:
        return (w[0], 0.0, w[1], w[2], w[2])
    if len(w) != 5:
        raise ValueError(f"bm25 weights need 5 values (name, path, signature, doc, body) or 3, got {len(w)}")
    return w


# --------------------------------------------------------------------------- vectors


class VectorStore(ABC):
    """The in-memory search index of one vector type, keyed by vector id: FAISS by default, or a
    subclass named in config (`vector_backend = "module:Class"`, docs/architecture.md §5). It is
    built as Class(dim) and filled from the vectors stored in SQLite, already truncated and
    L2-normalized; the store calls it under its lock, one call at a time.

    `search(query, k, allowed_ids)` returns at most k (id, score) pairs, best first, with the real
    similarity as the score (equal scores are ties); fewer than k only when no other vector
    qualifies; only ids in `allowed_ids` when it is given. An approximate index (HNSW, IVF) can
    miss some, as it does anywhere else.

    Saving is optional: `to_bytes` gives the index for `vec_<type><suffix>`, and `from_bytes`
    reads it back at the next start. A backend that returns None is rebuilt from the stored
    vectors instead, which needs no model."""

    dim: int
    suffix: str = ".vec"

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

    def to_bytes(self) -> bytes | None:
        return None

    @classmethod
    def from_bytes(cls, data: bytes) -> VectorStore:
        raise NotImplementedError(f"{cls.__name__} is not saved")


class FaissVectorStore(VectorStore):
    """Exact inner-product search; IndexIDMap2 so the vector id is the FAISS id. It keeps each
    number in 2 bytes, like the rows: they are rounded to float16 before they are stored, so 4
    bytes would hold the same values at twice the memory."""

    suffix = ".faiss"

    def __init__(self, dim: int, index: Any = None):
        self.dim = dim
        self.index = index if index is not None else faiss.IndexIDMap2(
            faiss.IndexScalarQuantizer(dim, faiss.ScalarQuantizer.QT_fp16, faiss.METRIC_INNER_PRODUCT)
        )

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

    def to_bytes(self) -> bytes:
        return faiss.serialize_index(self.index).tobytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> FaissVectorStore:
        # Bytes read through Python (not faiss.read_index), so non-ASCII Windows paths work.
        index = faiss.deserialize_index(np.frombuffer(data, dtype=np.uint8))
        inner = faiss.downcast_index(index.index)
        if isinstance(inner, faiss.IndexScalarQuantizer):
            return cls(index.d, index)
        # A file of 4-byte numbers: the same values, moved into a 2-byte index (the file is
        # rewritten in the new form at the next save).
        store = cls(index.d)
        store.upsert(faiss.vector_to_array(index.id_map), inner.reconstruct_n(0, inner.ntotal))
        return store


def vector_backend_class(name: str) -> type[VectorStore]:
    """`faiss` or "module:Class" -> the VectorStore subclass."""
    if name == "faiss":
        return FaissVectorStore
    cls = load_object(name)
    if not (isinstance(cls, type) and issubclass(cls, VectorStore)):
        raise TypeError(f"{name} must be a subclass of codemem.store.VectorStore")
    return cls


def prepare(vecs: np.ndarray, dim: int) -> np.ndarray:
    """Float32 vectors truncated to `dim` (Matryoshka) and L2-normalized again."""
    out = np.asarray(vecs, dtype=np.float32)
    if out.ndim == 1:
        out = out.reshape(1, -1)
    out = np.ascontiguousarray(out[:, :dim])
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.where(norms == 0, 1.0, norms)


class VectorRow(NamedTuple):
    chunk_id: int
    part: int
    n_parts: int
    start_off: int
    end_off: int
    text_hash: str


@dataclass
class VectorHit:
    chunk_id: int
    score: float
    vector_id: int
    part: int
    n_parts: int
    start_off: int
    end_off: int


class _TypeIndex:
    """The in-memory search index of one vector type and where each vector came from."""

    def __init__(self, dim: int, epoch: int, store: VectorStore):
        self.store = store
        self.dim = dim
        self.epoch = epoch
        self.owner: dict[int, tuple[int, int, int, int, int]] = {}  # vector id -> chunk, part, n, start, end
        self.by_chunk: dict[int, list[int]] = defaultdict(list)
        self.dirty = False

    def add(self, vector_ids: Sequence[int], info: Sequence[tuple[int, int, int, int, int]], vecs: np.ndarray) -> None:
        # Normalizing again moves the numbers off float16 values; rounding them back gives every
        # backend the same numbers, which a 2-byte index holds exactly.
        self.store.upsert(vector_ids, prepare(vecs, self.dim).astype(np.float16).astype(np.float32))
        for vid, row in zip(vector_ids, info):
            self.owner[vid] = row
            self.by_chunk[row[0]].append(vid)

    def remove(self, vector_ids: Iterable[int]) -> None:
        vector_ids = [v for v in vector_ids if v in self.owner]
        self.store.remove(vector_ids)
        for vid in vector_ids:
            chunk_id = self.owner.pop(vid)[0]
            vids = self.by_chunk.get(chunk_id)
            if vids is not None:
                vids.remove(vid)
                if not vids:
                    del self.by_chunk[chunk_id]


# --------------------------------------------------------------------------- lock


def _fetch_whole_ties(fetch: Callable[[int], list[tuple[int, float]]], n: int) -> list[tuple[int, float]]:
    """fetch(size) gives the best `size` (id, score) pairs. Fetch more until the group of equal
    scores at position n is complete, so the order of a tie never depends on where the cut is."""
    if n <= 0:
        return []
    size = n + 1
    while True:
        hits = fetch(size)
        if len(hits) < size or hits[-1][1] != hits[n - 1][1]:
            return hits
        size *= 2


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


class FileRow(NamedTuple):
    content_hash: str
    mtime: float
    size: int
    language: str
    status: str  # ok | skipped
    reason: str = ""  # for skipped files: too_large | generated | minified | binary


@dataclass(frozen=True)
class ChunkFilter:
    """Restricts which chunks a search may return. Empty = everything."""

    path_prefix: str | None = None
    kinds: tuple[str, ...] | None = None
    languages: tuple[str, ...] | None = None
    exclude_tests: bool = False
    only_tests: bool = False

    @property
    def active(self) -> bool:
        return bool(
            self.path_prefix or self.kinds is not None or self.languages is not None or self.exclude_tests
            or self.only_tests
        )

    def where(self, alias: str = "c") -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if self.path_prefix:
            clauses.append(f"{alias}.path LIKE ? ESCAPE '!'")
            params.append(_like_prefix(self.path_prefix))
        if self.kinds is not None:
            clauses.append(f"{alias}.kind IN ({','.join('?' * len(self.kinds))})" if self.kinds else "0")
            params.extend(self.kinds)
        if self.languages is not None:
            clauses.append(f"{alias}.language IN ({','.join('?' * len(self.languages))})" if self.languages else "0")
            params.extend(self.languages)
        if self.exclude_tests:
            clauses.append(f"{alias}.is_test = 0")
        if self.only_tests:
            clauses.append(f"{alias}.is_test = 1")
        return " AND ".join(clauses) or "1", params


def _row_to_chunk(row: sqlite3.Row) -> Chunk:
    return Chunk(
        chunk_id=row["chunk_id"], key=row["key"], path=row["path"], qualname=row["qualname"],
        name=row["name"], kind=row["kind"], class_name=row["class_name"],
        start_line=row["start_line"], end_line=row["end_line"], signature=row["signature"],
        docstring=row["docstring"], code=row["code"], content_hash=row["content_hash"],
        language=row["language"], subkind=row["subkind"], parent_key=row["parent_key"],
        is_test=bool(row["is_test"]), skeleton=row["skeleton"], lead_comment=row["lead_comment"],
    )


def _like_prefix(prefix: str) -> str:
    prefix = prefix.replace("\\", "/").removeprefix("./").lstrip("/")
    return prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def _family(language: str) -> str:
    from .languages import LANGUAGES

    spec = LANGUAGES.get(language)
    return spec.family if spec else language


def _batches(items: Sequence[Any], size: int = 500) -> Iterator[Sequence[Any]]:
    """SQLite caps the number of `?` in one statement; query long id lists in slices."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


class Store:
    def __init__(
        self, index_dir: Path | str, *, bm25_stem: bool = False, bm25_stopwords: bool = False,
        vector_backend: str = "faiss",
    ):
        self.vector_backend = vector_backend
        self._backend = vector_backend_class(vector_backend)
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.index_dir / "index.db"
        self.tok_opts = {"stem": bm25_stem, "stopwords": bm25_stopwords}
        self._local = threading.local()
        self._vec_lock = threading.RLock()
        self._save_lock = threading.Lock()
        self._types: dict[str, _TypeIndex] = {}
        # Every thread's connection, with its thread: close() must not close one a running thread uses.
        self._all_conns: dict[int, tuple[threading.Thread, sqlite3.Connection]] = {}
        self._conns_lock = threading.Lock()
        self._open_schema()

    def _schema_version(self) -> int | None:
        conn = self.conn
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'").fetchone():
            return None
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        return json.loads(row[0]) if row else 0

    def _open_schema(self) -> None:
        conn = self.conn
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        version = self._schema_version()
        if version is not None and version > SCHEMA_VERSION:
            # Never wipe an index a newer codemem is still using.
            raise RuntimeError(
                f"the index at {self.index_dir} was built by a newer codemem (schema {version}, this one reads "
                f"{SCHEMA_VERSION}); upgrade codemem or use another --index-dir"
            )
        if version is not None and version < SCHEMA_VERSION:
            # Rebuild an older index, but only while no other process writes to it.
            with IndexLock(self.index_dir):
                if (self._schema_version() or 0) < SCHEMA_VERSION:
                    log.warning(
                        "index at %s has schema version %s; rebuilding it for version %s",
                        self.index_dir, version, SCHEMA_VERSION,
                    )
                    for table in _OLD_TABLES:
                        conn.execute(f"DROP TABLE IF EXISTS {table}")
                    for p in self.index_dir.glob("vec_*"):
                        p.unlink(missing_ok=True)
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not tables:
            conn.execute("PRAGMA auto_vacuum = INCREMENTAL")  # must precede the first table
            conn.execute("VACUUM")
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
            conn.execute("PRAGMA cache_size=-65536")  # up to 64 MB of pages per connection, as used
            self._local.conn = conn
            with self._conns_lock:
                self._all_conns[id(conn)] = (threading.current_thread(), conn)
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One write transaction. Changes to the in-memory vector indexes registered during it
        run after the commit, and are dropped on rollback."""
        conn = self.conn
        if conn.in_transaction:  # nested: join the outer transaction
            yield conn
            return
        self._local.after_commit = []
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            self._local.after_commit = []
            raise
        hooks, self._local.after_commit = self._local.after_commit, []
        if not hooks:
            conn.execute("COMMIT")
            return
        # Hold the vector lock from the commit until the in-memory indexes are patched: a search
        # in between would see the new epoch with the old index, and compare every vector id.
        with self._vec_lock:
            conn.execute("COMMIT")
            for hook in hooks:
                hook()

    @contextmanager
    def _read_snapshot(self) -> Iterator[None]:
        """Several reads that see one committed state (a read transaction), unless inside a write."""
        conn = self.conn
        if conn.in_transaction:
            yield
            return
        conn.execute("BEGIN")
        try:
            yield
        finally:
            conn.execute("COMMIT")

    def _after_commit(self, hook: Callable[[], None]) -> None:
        hooks = getattr(self._local, "after_commit", None)
        if hooks is None or not self.conn.in_transaction:
            hook()
        else:
            hooks.append(hook)

    def close_thread_conn(self) -> None:
        """Close the calling thread's connection (for short-lived worker threads)."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            self._local.conn = None
            with self._conns_lock:
                self._all_conns.pop(id(conn), None)
            conn.close()

    def close(self) -> None:
        """Close this thread's connection and those of threads that have ended. A thread that is
        still running keeps its own: closing a connection under another thread's query crashes the
        process (they are opened with check_same_thread=False). It closes with that thread."""
        me = threading.current_thread()
        with self._conns_lock:
            done = [k for k, (thread, _) in self._all_conns.items() if thread is me or not thread.is_alive()]
            conns = [self._all_conns.pop(k)[1] for k in done]
        for conn in conns:
            try:
                conn.close()
            except sqlite3.ProgrammingError:
                pass
        self._local.conn = None

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
    def get_files(self) -> dict[str, FileRow]:
        rows = self.conn.execute("SELECT path, content_hash, mtime, size, language, status, reason FROM files")
        return {
            r["path"]: FileRow(r["content_hash"], r["mtime"], r["size"], r["language"], r["status"], r["reason"])
            for r in rows
        }

    def upsert_file(
        self, path: str, content_hash: str, mtime: float, size: int, language: str = "python", status: str = "ok",
        reason: str = "",
    ) -> None:
        self.conn.execute(
            "INSERT INTO files(path, language, content_hash, mtime, size, status, reason) VALUES(?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET language=excluded.language, content_hash=excluded.content_hash, "
            "mtime=excluded.mtime, size=excluded.size, status=excluded.status, reason=excluded.reason",
            (path, language, content_hash, mtime, size, status, reason),
        )

    def delete_file(self, path: str) -> list[int]:
        ids = [r[0] for r in self.conn.execute("SELECT chunk_id FROM chunks WHERE path = ?", (path,))]
        self.delete_chunks(ids)
        self.conn.execute("DELETE FROM files WHERE path = ?", (path,))
        return ids

    def move_chunks(self, moves: Sequence[tuple[int, int, int, int]]) -> None:
        """Chunks whose content is unchanged but whose lines moved: (chunk id, new start line, new
        end line, lines moved). Only the line numbers change: of the chunk, and of its calls (0 is
        "line unknown" and stays 0). Keyword rows, links and vectors hold no line numbers."""
        self.conn.executemany(
            "UPDATE chunks SET start_line = ?, end_line = ? WHERE chunk_id = ?", [(s, e, i) for i, s, e, _ in moves]
        )
        self.conn.executemany(
            "UPDATE calls SET line = line + ? WHERE caller_id = ? AND line > 0", [(d, i) for i, _, _, d in moves]
        )

    # ---- chunks
    def upsert_chunk(self, chunk: Chunk) -> int:
        """Insert or update by `key` (chunk_id is stable across updates). Also refreshes FTS + calls."""
        conn = self.conn
        values = (
            chunk.path, chunk.language, chunk.kind, chunk.subkind, chunk.name, chunk.qualname, chunk.class_name,
            chunk.parent_key, chunk.start_line, chunk.end_line, chunk.signature, chunk.docstring, chunk.code,
            chunk.skeleton, chunk.content_hash, int(chunk.is_test), chunk.lead_comment,
        )
        row = conn.execute("SELECT chunk_id FROM chunks WHERE key = ?", (chunk.key,)).fetchone()
        if row:
            chunk_id = row[0]
            conn.execute(
                "UPDATE chunks SET path=?, language=?, kind=?, subkind=?, name=?, qualname=?, class_name=?, "
                "parent_key=?, start_line=?, end_line=?, signature=?, docstring=?, code=?, skeleton=?, "
                "content_hash=?, is_test=?, lead_comment=? WHERE chunk_id=?",
                (*values, chunk_id),
            )
            conn.execute("DELETE FROM fts WHERE rowid = ?", (chunk_id,))
            conn.execute("DELETE FROM calls WHERE caller_id = ?", (chunk_id,))
        else:
            cur = conn.execute(
                "INSERT INTO chunks(key, path, language, kind, subkind, name, qualname, class_name, parent_key, "
                "start_line, end_line, signature, docstring, code, skeleton, content_hash, is_test, lead_comment) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (chunk.key, *values),
            )
            chunk_id = int(cur.lastrowid)
        body = chunk.skeleton if chunk.kind == "class" and chunk.skeleton else chunk.code
        conn.execute(
            "INSERT INTO fts(rowid, name_tokens, path_tokens, signature_tokens, doc_tokens, body_tokens) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (
                chunk_id,
                to_fts_text(f"{chunk.qualname} {chunk.name}", **self.tok_opts),
                to_fts_text(chunk.path, **self.tok_opts),
                to_fts_text(chunk.signature, **self.tok_opts),
                to_fts_text(f"{chunk.docstring}\n{chunk.lead_comment}", **self.tok_opts),
                to_fts_text(body, **self.tok_opts),
            ),
        )
        lines = list(chunk.call_lines) + [0] * (len(chunk.calls) - len(chunk.call_lines))
        conn.executemany(
            "INSERT INTO calls(caller_id, callee_name, line) VALUES(?, ?, ?)",
            [(chunk_id, c, line) for c, line in zip(chunk.calls, lines)],
        )
        chunk.chunk_id = chunk_id
        return chunk_id

    def delete_chunks(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        if not ids:
            return
        conn = self.conn
        params = [(i,) for i in ids]
        by_type: dict[str, list[int]] = defaultdict(list)
        for start in range(0, len(ids), 500):
            batch = ids[start : start + 500]
            marks = ",".join("?" * len(batch))
            for r in conn.execute(f"SELECT vector_id, vec_type FROM vectors WHERE chunk_id IN ({marks})", batch):
                by_type[r[1]].append(r[0])
        conn.executemany("DELETE FROM chunks WHERE chunk_id = ?", params)
        conn.executemany("DELETE FROM fts WHERE rowid = ?", params)
        conn.executemany("DELETE FROM calls WHERE caller_id = ?", params)
        conn.executemany("DELETE FROM edges WHERE caller_id = ? OR callee_id = ?", [(i, i) for i in ids])
        conn.executemany("DELETE FROM dirty_texts WHERE chunk_id = ?", params)
        for vec_type, vector_ids in by_type.items():
            self.delete_vectors(vec_type, vector_ids)

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
        """Innermost function/method containing `line`, else the innermost class, else the block."""
        r = self.conn.execute(
            f"SELECT {_CHUNK_COLS} FROM chunks WHERE path = ? AND start_line <= ? AND end_line >= ? "
            "ORDER BY kind = 'block', kind = 'class', end_line - start_line LIMIT 1",
            (path.replace("\\", "/"), line, line),
        ).fetchone()
        return _row_to_chunk(r) if r else None

    def children_of(self, key: str) -> list[Chunk]:
        rows = self.conn.execute(f"SELECT {_CHUNK_COLS} FROM chunks WHERE parent_key = ? ORDER BY start_line", (key,))
        return [_row_to_chunk(r) for r in rows]

    def iter_chunks(self) -> Iterator[Chunk]:
        for r in self.conn.execute(f"SELECT {_CHUNK_COLS} FROM chunks ORDER BY chunk_id"):
            yield _row_to_chunk(r)

    def chunks_for_paths(self, paths: Iterable[str]) -> list[Chunk]:
        out: list[Chunk] = []
        for batch in _batches(list(dict.fromkeys(paths))):
            marks = ",".join("?" * len(batch))
            out.extend(_row_to_chunk(r) for r in self.conn.execute(
                f"SELECT {_CHUNK_COLS} FROM chunks WHERE path IN ({marks}) ORDER BY path, start_line", batch
            ))
        return out

    def chunk_ids(self) -> set[int]:
        return {r[0] for r in self.conn.execute("SELECT chunk_id FROM chunks")}

    def file_paths_under(self, rel_dir: str) -> list[str]:
        """Indexed (or skipped) files inside a repo-relative folder."""
        return [r[0] for r in self.conn.execute(
            "SELECT path FROM files WHERE path LIKE ? ESCAPE '!'", (_like_prefix(rel_dir.rstrip("/") + "/"),)
        )]

    def ids_with_prefix(self, prefix: str) -> list[int]:
        return self.filter_ids(ChunkFilter(path_prefix=prefix))

    def filter_ids(self, flt: ChunkFilter) -> list[int]:
        where, params = flt.where("c")
        return [r[0] for r in self.conn.execute(f"SELECT c.chunk_id FROM chunks c WHERE {where}", params)]

    # ---- call graph
    def definitions(self) -> list[tuple[int, str, str]]:
        """(chunk_id, name, language family) of everything a call can resolve to."""
        marks = ",".join("?" * len(CALLABLE_KINDS))
        rows = self.conn.execute(f"SELECT chunk_id, name, language FROM chunks WHERE kind IN ({marks})", CALLABLE_KINDS)
        return [(r[0], r[1], _family(r[2])) for r in rows]

    def all_calls(self) -> list[tuple[int, str, str]]:
        rows = self.conn.execute(
            "SELECT k.caller_id, k.callee_name, c.language FROM calls k JOIN chunks c ON c.chunk_id = k.caller_id"
        )
        return [(r[0], r[1], _family(r[2])) for r in rows]

    def replace_edges(self, edges: Iterable[tuple[int, int]]) -> None:
        self.conn.execute("DELETE FROM edges")
        self.conn.executemany("INSERT INTO edges(caller_id, callee_id) VALUES(?, ?)", sorted(edges))

    def caller_refs(self, ids: Iterable[int] | None = None, limit: int | None = None) -> dict[int, list[Ref]]:
        """callee id -> its callers, for every chunk or only for `ids`. With `limit`, at most that
        many test callers and that many other callers per callee, the first in (path, line,
        qualname, kind) order: all a usage text can show (a name like `append` gathers thousands)."""
        out: dict[int, list[Ref]] = {}
        inner = (
            "SELECT e.callee_id, c.chunk_id, c.qualname, c.name, c.path, c.start_line, c.is_test, c.kind, "
            "ROW_NUMBER() OVER (PARTITION BY e.callee_id, c.is_test "
            "ORDER BY c.path, c.start_line, c.qualname, c.kind) AS rn "
            "FROM edges e JOIN chunks c ON c.chunk_id = e.caller_id"
        )
        keep = "rn <= ?" if limit is not None else "1"
        lim = (limit,) if limit is not None else ()
        if ids is None:
            queries = [(f"SELECT * FROM ({inner}) WHERE {keep}", lim)]
        else:
            queries = [
                (f"SELECT * FROM ({inner} WHERE e.callee_id IN ({','.join('?' * len(b))})) WHERE {keep}", (*b, *lim))
                for b in _batches(sorted(set(ids)))
            ]
        for query, params in queries:
            for r in self.conn.execute(query, params):
                out.setdefault(r[0], []).append(Ref(r[1], r[2], r[3], r[4], r[5], bool(r[6]), r[7]))
        return out

    # ---- call graph, for one part of the repo (incremental updates)
    def definitions_named(self, names: Iterable[str]) -> list[tuple[int, str, str]]:
        """(chunk_id, name, language family) of every definition with one of these names."""
        out: list[tuple[int, str, str]] = []
        kinds = ",".join("?" * len(CALLABLE_KINDS))
        for batch in _batches(sorted(set(names))):
            rows = self.conn.execute(
                f"SELECT chunk_id, name, language FROM chunks WHERE kind IN ({kinds}) AND name IN ({','.join('?' * len(batch))})",
                (*CALLABLE_KINDS, *batch),
            )
            out.extend((r[0], r[1], _family(r[2])) for r in rows)
        return out

    def _calls_where(self, column: str, values: Iterable[Any]) -> list[tuple[int, str, str]]:
        out: list[tuple[int, str, str]] = []
        for batch in _batches(sorted(set(values))):
            rows = self.conn.execute(
                "SELECT k.caller_id, k.callee_name, c.language FROM calls k JOIN chunks c ON c.chunk_id = k.caller_id "
                f"WHERE k.{column} IN ({','.join('?' * len(batch))})",
                tuple(batch),
            )
            out.extend((r[0], r[1], _family(r[2])) for r in rows)
        return out

    def calls_of(self, caller_ids: Iterable[int]) -> list[tuple[int, str, str]]:
        """(caller_id, callee_name, family) of every call these chunks make."""
        return self._calls_where("caller_id", caller_ids)

    def calls_to_names(self, names: Iterable[str]) -> list[tuple[int, str, str]]:
        """(caller_id, callee_name, family) of every call, anywhere, to one of these names."""
        return self._calls_where("callee_name", names)

    def edges_from(self, caller_ids: Iterable[int]) -> set[tuple[int, int]]:
        out: set[tuple[int, int]] = set()
        for batch in _batches(sorted(set(caller_ids))):
            out.update(
                (r[0], r[1]) for r in self.conn.execute(
                    f"SELECT caller_id, callee_id FROM edges WHERE caller_id IN ({','.join('?' * len(batch))})", tuple(batch)
                )
            )
        return out

    def replace_edges_from(self, caller_ids: Iterable[int], edges: Iterable[tuple[int, int]]) -> None:
        """Replace the outgoing edges of these callers (and only theirs) with `edges`."""
        for batch in _batches(sorted(set(caller_ids))):
            self.conn.execute(f"DELETE FROM edges WHERE caller_id IN ({','.join('?' * len(batch))})", tuple(batch))
        self.conn.executemany("INSERT OR IGNORE INTO edges(caller_id, callee_id) VALUES(?, ?)", sorted(edges))

    def edge_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

    # ---- the queue of chunks whose texts must be rebuilt (stage B of an update)
    def next_dirty_seq(self) -> int:
        seq = int(self.get_meta("dirty_seq", 0)) + 1
        self.set_meta("dirty_seq", seq)
        return seq

    def mark_dirty(self, chunk_ids: Iterable[int], seq: int) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO dirty_texts(chunk_id, seq) VALUES(?, ?)", [(i, seq) for i in sorted(set(chunk_ids))]
        )

    def mark_all_dirty(self, seq: int) -> None:
        self.conn.execute("INSERT OR REPLACE INTO dirty_texts(chunk_id, seq) SELECT chunk_id, ? FROM chunks", (seq,))

    def dirty_batch(self, limit: int, skip: Iterable[int] = (), only: Iterable[int] | None = None) -> dict[int, int]:
        """Up to `limit` queued chunk ids -> the sequence number they were queued with. Newest edits
        first: an agent's next search is most likely about the code it just changed."""
        skip = set(skip)
        if only is not None:
            rows = sorted(self.dirty_seqs(only).items(), key=lambda r: (-r[1], r[0]))
            return dict([(i, s) for i, s in rows if i not in skip][:limit])
        rows = self.conn.execute(
            "SELECT chunk_id, seq FROM dirty_texts ORDER BY seq DESC, chunk_id LIMIT ?", (limit + len(skip),)
        )
        return dict(list((r[0], r[1]) for r in rows if r[0] not in skip)[:limit])

    def dirty_seqs(self, chunk_ids: Iterable[int]) -> dict[int, int]:
        out: dict[int, int] = {}
        for batch in _batches(sorted(set(chunk_ids))):
            out.update(
                (r[0], r[1]) for r in self.conn.execute(
                    f"SELECT chunk_id, seq FROM dirty_texts WHERE chunk_id IN ({','.join('?' * len(batch))})", tuple(batch)
                )
            )
        return out

    def clear_dirty(self, seqs: dict[int, int]) -> None:
        """Drop queue rows, but only those not queued again since (same sequence number)."""
        self.conn.executemany("DELETE FROM dirty_texts WHERE chunk_id = ? AND seq = ?", sorted(seqs.items()))

    def dirty_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM dirty_texts").fetchone()[0]

    def pending_paths(self, limit: int = 3) -> tuple[int, list[str]]:
        """How many files have queued chunks, and the `limit` with the most (for a freshness note)."""
        rows = self.conn.execute(
            "SELECT c.path, COUNT(*) AS n FROM dirty_texts d JOIN chunks c ON c.chunk_id = d.chunk_id "
            "GROUP BY c.path ORDER BY n DESC, c.path"
        ).fetchall()
        return len(rows), [r[0] for r in rows[:limit]]

    def callers_of(self, chunk_id: int) -> list[Chunk]:
        ids = [r[0] for r in self.conn.execute("SELECT caller_id FROM edges WHERE callee_id = ?", (chunk_id,))]
        return sorted(self.get_chunks(ids).values(), key=lambda c: (c.path, c.start_line))

    def callees_of(self, chunk_id: int) -> list[Chunk]:
        ids = [r[0] for r in self.conn.execute("SELECT callee_id FROM edges WHERE caller_id = ?", (chunk_id,))]
        return sorted(self.get_chunks(ids).values(), key=lambda c: (c.path, c.start_line))

    # ---- BM25
    def chunk_total(self) -> int:
        """How many chunks the keyword index holds (its small per-row table, not `chunks`)."""
        try:
            return self.conn.execute("SELECT COUNT(*) FROM fts_docsize").fetchone()[0]
        except sqlite3.OperationalError:
            return self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    def term_doc_counts(self, terms: Iterable[str]) -> dict[str, int]:
        """How many chunks hold each term, from the FTS vocabulary (no posting lists are read)."""
        out: dict[str, int] = {}
        for batch in _batches(sorted(set(terms))):
            marks = ",".join("?" * len(batch))
            out.update(self.conn.execute(f"SELECT term, doc FROM fts_vocab WHERE term IN ({marks})", tuple(batch)).fetchall())
        return out

    def bm25_search(
        self, match: str, n: int, weights: Sequence[float], path_prefix: str | None = None,
        flt: ChunkFilter | None = None,
    ) -> list[int]:
        w = bm25_weights5(weights)
        flt = flt or ChunkFilter()
        if path_prefix:
            flt = ChunkFilter(path_prefix, flt.kinds, flt.languages, flt.exclude_tests)
        sql = "SELECT f.rowid, bm25(fts, ?, ?, ?, ?, ?) AS s FROM fts f"
        params: list[Any] = [*w, match]
        where = "fts MATCH ?"
        if flt.active:
            clause, extra = flt.where("c")
            sql += " JOIN chunks c ON c.chunk_id = f.rowid"
            where += f" AND {clause}"
            params.extend(extra)
        sql += f" WHERE {where} ORDER BY s LIMIT ?"
        hits = _fetch_whole_ties(lambda size: [(r[0], r[1]) for r in self.conn.execute(sql, (*params, size))], n)
        return [i for i, _ in self._order_ties(hits, n, higher_is_better=False)]

    # ---- vectors: bookkeeping
    def _data_path(self, vec_type: str) -> Path:
        return self.index_dir / f"vec_{vec_type}{self._backend.suffix}"

    def _note_path(self, vec_type: str) -> Path:
        return self.index_dir / f"vec_{vec_type}.json"

    def _read_note(self, vec_type: str) -> dict[str, Any] | None:
        try:
            return json.loads(self._note_path(vec_type).read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def _noted_file(self, vec_type: str, note: dict[str, Any] | None) -> Path | None:
        """The saved index a note describes (notes from before backends were pluggable: FAISS)."""
        return self.index_dir / note.get("file", f"vec_{vec_type}.faiss") if note else None

    def use_vector_backend(self, name: str) -> None:
        """Search with another backend from now on. Each vector type's index is rebuilt from the
        stored vectors when it is next used; nothing is re-embedded."""
        backend = vector_backend_class(name)
        with self._vec_lock:
            self.vector_backend, self._backend = name, backend
            self._types.clear()

    def vec_types(self) -> list[str]:
        """Vector types that have stored vectors (one index probe per known type: search calls this)."""
        known = [r[0][len("vec."):-len(".full_dim")] for r in self.conn.execute(
            "SELECT key FROM meta WHERE key LIKE 'vec.%.full_dim'"
        )]
        return sorted(
            t for t in known
            if self.conn.execute("SELECT 1 FROM vectors WHERE vec_type = ? LIMIT 1", (t,)).fetchone()
        )

    def _epoch(self, vec_type: str) -> int:
        return int(self.get_meta(f"vec.{vec_type}.epoch", 0))

    def _bump_epoch(self, vec_type: str) -> int:
        epoch = self._epoch(vec_type) + 1
        self.set_meta(f"vec.{vec_type}.epoch", epoch)
        return epoch

    def vector_dim(self, vec_type: str) -> int | None:
        """Dimension the search index uses for a vector type (after any truncation)."""
        full = self.get_meta(f"vec.{vec_type}.full_dim")
        if full is None:
            return None
        setting = self.get_meta(f"vec.{vec_type}.dim_setting")
        return min(int(setting), int(full)) if setting else int(full)

    def ensure_vec_type(self, vec_type: str, embedder: str, dim_setting: int | None = None) -> bool:
        """Drop a vector type's rows if they came from another embedder (returns True then). A
        changed `dim_setting` (Matryoshka truncation) only rebuilds the search index."""
        stored = self.get_meta(f"vec.{vec_type}.embedder")
        reset = stored is not None and stored != embedder
        if reset:
            log.info("embedder for %s changed (%s -> %s); re-embedding that vector type", vec_type, stored, embedder)
            self.drop_vec_type(vec_type)
        self.set_meta(f"vec.{vec_type}.embedder", embedder)
        if self.get_meta(f"vec.{vec_type}.dim_setting") != dim_setting:
            self.set_meta(f"vec.{vec_type}.dim_setting", dim_setting)
            self._bump_epoch(vec_type)
            self._after_commit(lambda: self._forget(vec_type))
        return reset

    def drop_vec_type(self, vec_type: str) -> None:
        self.conn.execute("DELETE FROM vectors WHERE vec_type = ?", (vec_type,))
        for key in ("embedder", "full_dim", "dim_setting"):
            self.conn.execute("DELETE FROM meta WHERE key = ?", (f"vec.{vec_type}.{key}",))
        self._bump_epoch(vec_type)

        def forget() -> None:
            self._forget(vec_type)
            for p in (self._noted_file(vec_type, self._read_note(vec_type)), self._data_path(vec_type),
                      self._note_path(vec_type)):
                if p is not None:
                    p.unlink(missing_ok=True)

        self._after_commit(forget)

    def _forget(self, vec_type: str) -> None:
        with self._vec_lock:
            self._types.pop(vec_type, None)

    def vector_rows(self, vec_type: str) -> dict[tuple[int, int], tuple[int, str]]:
        """(chunk_id, part) -> (vector_id, text_hash) for every stored vector of a type."""
        rows = self.conn.execute(
            "SELECT chunk_id, part, vector_id, text_hash FROM vectors WHERE vec_type = ?", (vec_type,)
        )
        return {(r[0], r[1]): (r[2], r[3]) for r in rows}

    def vector_parts(self, vec_type: str, chunk_ids: Iterable[int]) -> dict[tuple[int, int], tuple[int, str, int, int, int]]:
        """(chunk_id, part) -> (vector_id, text_hash, n_parts, start_off, end_off) for these chunks."""
        out: dict[tuple[int, int], tuple[int, str, int, int, int]] = {}
        for batch in _batches(sorted(set(chunk_ids))):
            rows = self.conn.execute(
                "SELECT chunk_id, part, vector_id, text_hash, n_parts, start_off, end_off FROM vectors "
                f"WHERE vec_type = ? AND chunk_id IN ({','.join('?' * len(batch))})",
                (vec_type, *batch),
            )
            out.update(((r[0], r[1]), (r[2], r[3], r[4], r[5], r[6])) for r in rows)
        return out

    def find_vectors(self, embedder: str, text_hashes: Iterable[str]) -> dict[str, np.ndarray]:
        """Stored vectors for these texts, from any chunk or type (equal text, equal vector)."""
        hashes = list(dict.fromkeys(text_hashes))
        out: dict[str, np.ndarray] = {}
        for start in range(0, len(hashes), 500):
            batch = hashes[start : start + 500]
            marks = ",".join("?" * len(batch))
            rows = self.conn.execute(
                f"SELECT text_hash, dim, data FROM vectors WHERE embedder = ? AND text_hash IN ({marks})", (embedder, *batch)
            )
            for r in rows:
                out.setdefault(r[0], from_blob(r[2], r[1]))
        return out

    def put_vectors(self, vec_type: str, embedder: str, rows: Sequence[VectorRow], vecs: np.ndarray) -> None:
        """Store vectors (replacing any at the same chunk and part); searchable after the commit."""
        if not len(rows):
            return
        # Round to float16 here, so the search index holds exactly what the rows hold: an index
        # rebuilt from the rows later gives the same scores.
        vecs = np.asarray(vecs, dtype=np.float16)
        dim = int(vecs.shape[1])
        with self.transaction() as conn:
            full = self.get_meta(f"vec.{vec_type}.full_dim")
            if full is not None and int(full) != dim:
                log.info("dimension of %s changed (%d -> %d); dropping its old vectors", vec_type, full, dim)
                self.drop_vec_type(vec_type)
                self.set_meta(f"vec.{vec_type}.embedder", embedder)
            self.set_meta(f"vec.{vec_type}.full_dim", dim)
            wanted = {(r.chunk_id, r.part) for r in rows}
            chunk_ids = sorted({r.chunk_id for r in rows})
            old: list[int] = []
            for start in range(0, len(chunk_ids), 500):
                batch = chunk_ids[start : start + 500]
                marks = ",".join("?" * len(batch))
                for vid, chunk_id, part in conn.execute(
                    f"SELECT vector_id, chunk_id, part FROM vectors WHERE vec_type = ? AND chunk_id IN ({marks})",
                    (vec_type, *batch),
                ):
                    if (chunk_id, part) in wanted:
                        old.append(vid)
            if old:
                conn.executemany("DELETE FROM vectors WHERE vector_id = ?", [(v,) for v in old])
            new_ids: list[int] = []
            for r, v in zip(rows, vecs):
                cur = conn.execute(
                    "INSERT INTO vectors(chunk_id, vec_type, part, n_parts, start_off, end_off, text_hash, embedder, "
                    "dim, data) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (r.chunk_id, vec_type, r.part, r.n_parts, r.start_off, r.end_off, r.text_hash, embedder, dim,
                     to_blob(v)),
                )
                new_ids.append(int(cur.lastrowid))
            epoch = self._bump_epoch(vec_type)
            info = [(r.chunk_id, r.part, r.n_parts, r.start_off, r.end_off) for r in rows]

            def apply() -> None:
                with self._vec_lock:
                    ti = self._types.get(vec_type)
                    if ti is not None and ti.epoch == epoch:
                        return  # a reader already reloaded it after the commit
                    if ti is None:
                        # Not loaded yet: load it from the committed rows (which include these),
                        # so save_vectors() can persist it.
                        self._type_index(vec_type)
                        return
                    if ti.epoch != epoch - 1:
                        self._catch_up(ti, vec_type, epoch)  # it missed another process's change
                        return
                    ti.remove(old)
                    ti.add(new_ids, info, vecs)
                    ti.epoch = epoch
                    ti.dirty = True

            self._after_commit(apply)

    def delete_vectors(self, vec_type: str, vector_ids: Sequence[int]) -> None:
        vector_ids = list(vector_ids)
        if not vector_ids:
            return
        with self.transaction() as conn:
            conn.executemany("DELETE FROM vectors WHERE vector_id = ?", [(v,) for v in vector_ids])
            epoch = self._bump_epoch(vec_type)

            def apply() -> None:
                with self._vec_lock:
                    ti = self._types.get(vec_type)
                    if ti is None or ti.epoch == epoch:
                        return  # loaded lazily on first use, or a reader already reloaded it
                    if ti.epoch != epoch - 1:
                        self._catch_up(ti, vec_type, epoch)  # it missed another process's change
                        return
                    ti.remove(vector_ids)
                    ti.epoch = epoch
                    ti.dirty = True

            self._after_commit(apply)

    # ---- vectors: the search index
    def _type_index(self, vec_type: str) -> _TypeIndex | None:
        """The in-memory index of a vector type, loaded or rebuilt if missing or out of date."""
        with self._vec_lock, self._read_snapshot():
            epoch = self._epoch(vec_type)
            ti = self._types.get(vec_type)
            if ti is not None and ti.epoch == epoch:
                return ti
            dim = self.vector_dim(vec_type)
            if dim is None:
                self._types.pop(vec_type, None)
                return None
            if ti is not None and ti.dim == dim:
                self._catch_up(ti, vec_type, epoch)  # another process wrote: apply only the difference
            else:
                ti = self._load_saved(vec_type, epoch, dim) or self._rebuild(vec_type, epoch, dim)
            self._types[vec_type] = ti
            return ti

    def _catch_up(self, ti: _TypeIndex, vec_type: str, epoch: int) -> None:
        """Bring an in-memory index to the committed rows by their ids. Vector rows never change in
        place (a new vector is a new row, and AUTOINCREMENT never reuses an id), so the set of ids
        says everything."""
        now = {r[0] for r in self.conn.execute("SELECT vector_id FROM vectors WHERE vec_type = ?", (vec_type,))}
        have = set(ti.owner)
        ti.remove(have - now)
        self._add_rows(ti, now - have)
        ti.epoch = epoch
        ti.dirty = True

    def _add_rows(self, ti: _TypeIndex, vector_ids: Iterable[int]) -> None:
        for batch in _batches(sorted(vector_ids), 4096):
            rows = self.conn.execute(
                "SELECT vector_id, chunk_id, part, n_parts, start_off, end_off, dim, data FROM vectors "
                f"WHERE vector_id IN ({','.join('?' * len(batch))})",
                tuple(batch),
            ).fetchall()
            if rows:
                ti.add([r[0] for r in rows], [(r[1], r[2], r[3], r[4], r[5]) for r in rows],
                       np.stack([from_blob(r[7], r[6]) for r in rows]))

    def _owner_rows(self, vec_type: str) -> list[tuple[int, tuple[int, int, int, int, int]]]:
        rows = self.conn.execute(
            "SELECT vector_id, chunk_id, part, n_parts, start_off, end_off FROM vectors WHERE vec_type = ?", (vec_type,)
        )
        return [(r[0], (r[1], r[2], r[3], r[4], r[5])) for r in rows]

    def _load_saved(self, vec_type: str, epoch: int, dim: int) -> _TypeIndex | None:
        """The saved index file, reconciled with the committed rows by vector id: vectors whose
        row is gone are dropped, rows the file lacks are added. Rows never change in place, so
        this is exact whichever epoch the file was saved at (another process, a crash, a save
        that is behind), and it costs only the difference instead of a full rebuild. No file, or
        one from another backend: None, and the index is rebuilt from the rows."""
        note = self._read_note(vec_type)
        if note is None or note.get("backend", "faiss") != self.vector_backend:
            return None
        path = self._noted_file(vec_type, note)
        if not path.is_file() or note.get("dim") != dim or note.get("embedder") != self.get_meta(f"vec.{vec_type}.embedder"):
            return None
        try:
            store = self._backend.from_bytes(path.read_bytes())
        except Exception:  # corrupt or partial file: rebuild from the rows
            log.exception("could not load %s; rebuilding it from the stored vectors", path)
            return None
        if store.dim != dim:
            return None
        ti = _TypeIndex(dim, epoch, store)
        rows = dict(self._owner_rows(vec_type))
        in_file = store.ids()
        stale = in_file - rows.keys()
        if stale:
            store.remove(stale)
        for vid in in_file & rows.keys():
            ti.owner[vid] = rows[vid]
            ti.by_chunk[rows[vid][0]].append(vid)
        missing = rows.keys() - in_file
        self._add_rows(ti, missing)
        ti.dirty = bool(stale or missing)
        return ti

    def _rebuild(self, vec_type: str, epoch: int, dim: int) -> _TypeIndex:
        ti = _TypeIndex(dim, epoch, self._backend(dim))
        rows = self.conn.execute(
            "SELECT vector_id, chunk_id, part, n_parts, start_off, end_off, dim, data FROM vectors "
            "WHERE vec_type = ? ORDER BY vector_id",
            (vec_type,),
        )
        batch_ids: list[int] = []
        batch_info: list[tuple[int, int, int, int, int]] = []
        batch_vecs: list[np.ndarray] = []
        for r in rows:
            batch_ids.append(r[0])
            batch_info.append((r[1], r[2], r[3], r[4], r[5]))
            batch_vecs.append(from_blob(r[7], r[6]))
            if len(batch_ids) >= 4096:
                ti.add(batch_ids, batch_info, np.stack(batch_vecs))
                batch_ids, batch_info, batch_vecs = [], [], []
        if batch_ids:
            ti.add(batch_ids, batch_info, np.stack(batch_vecs))
        ti.dirty = True
        return ti

    def vector_search(
        self, vec_type: str, query: np.ndarray, n: int, allowed_ids: Sequence[int] | None = None
    ) -> list[VectorHit]:
        """The n best chunks for a query by one vector type. A chunk with several parts scores its
        best part. Equal scores are ordered by location."""
        with self._vec_lock:
            ti = self._type_index(vec_type)
            if ti is None or len(ti.store) == 0 or n <= 0:
                return []
            q = prepare(np.asarray(query), ti.dim)[0]
            allowed_vids = None
            if allowed_ids is not None:
                allowed_vids = [v for c in allowed_ids for v in ti.by_chunk.get(c, ())]
                if not allowed_vids:
                    return []
            best: dict[int, tuple[float, int]] = {}
            size = n + 1
            while True:
                hits = ti.store.search(q, size, allowed_vids)
                best = {}
                for vid, score in hits:
                    chunk_id = ti.owner[vid][0]
                    if chunk_id not in best or score > best[chunk_id][0]:
                        best[chunk_id] = (score, vid)
                if len(hits) < size:
                    break  # every candidate was seen
                if len(best) > n:
                    nth = sorted((s for s, _ in best.values()), reverse=True)[n - 1]
                    if hits[-1][1] < nth:
                        break  # every unseen vector scores below the n-th chunk: the top n is complete
                size *= 2
            parts = {chunk_id: ti.owner[vid] for chunk_id, (_, vid) in best.items()}
        ranked = self._order_ties([(c, s) for c, (s, _) in best.items()], n, higher_is_better=True)
        out: list[VectorHit] = []
        for chunk_id, score in ranked:
            _, part, n_parts, start_off, end_off = parts[chunk_id]
            out.append(VectorHit(chunk_id, score, best[chunk_id][1], part, n_parts, start_off, end_off))
        return out

    def _order_ties(self, hits: list[tuple[int, float]], n: int, higher_is_better: bool) -> list[tuple[int, float]]:
        """The first n hits (best first), with equal scores ordered by location (path, start line, key).

        Equal scores come from copies of the same code. SQLite and FAISS give them in rowid or
        insertion order, and both depend on the history of the index. Locations are read only
        when there are equal scores, so a search without ties costs nothing extra.
        """
        sign = -1 if higher_is_better else 1
        hits = sorted(hits, key=lambda h: (sign * h[1], h[0]))
        tied: set[int] = set()
        for (a, score_a), (b, score_b) in zip(hits, hits[1:]):
            if score_a == score_b:
                tied.update((a, b))
        if not tied:
            return hits[:n]
        place: dict[int, tuple[str, int, str]] = {}
        ids = list(tied)
        for start in range(0, len(ids), 500):
            batch = ids[start : start + 500]
            marks = ",".join("?" * len(batch))
            for r in self.conn.execute(f"SELECT chunk_id, path, start_line, key FROM chunks WHERE chunk_id IN ({marks})", batch):
                place[r[0]] = (r[1], r[2], r[3])
        # A hit without a chunk row (deleted by a writer) goes last in its group.
        ordered = sorted(hits, key=lambda h: (sign * h[1], h[0] not in place, place.get(h[0], ("", 0, ""))))
        return ordered[:n]

    def save_vectors(self) -> None:
        """Persist the in-memory indexes that changed, with the epoch they reflect. The indexes are
        copied while holding the vector lock (fast) and written after it is released, so searches
        don't wait for the disk. Saves run one at a time; data first, note second. A backend that
        is not saved leaves no file, and is rebuilt from the stored vectors at the next start."""
        with self._save_lock:
            copies = []
            with self._vec_lock:
                for vec_type, ti in sorted(self._types.items()):
                    if not ti.dirty:
                        continue
                    note = {"epoch": ti.epoch, "dim": ti.dim, "count": len(ti.store),
                            "embedder": self.get_meta(f"vec.{vec_type}.embedder"),
                            "backend": self.vector_backend, "file": self._data_path(vec_type).name}
                    copies.append((vec_type, ti.store.to_bytes(), note))
                    ti.dirty = False
            for vec_type, data, note in copies:
                old = self._noted_file(vec_type, self._read_note(vec_type))
                if data is None:
                    self._note_path(vec_type).unlink(missing_ok=True)
                else:
                    _atomic_write(self.index_dir / note["file"], data)
                    _atomic_write(self._note_path(vec_type), json.dumps(note).encode("utf-8"))
                if old is not None and old.name != (note["file"] if data is not None else None):
                    old.unlink(missing_ok=True)  # another backend's file: no note describes it any more

    def vectors_unsaved(self) -> bool:
        """Whether an in-memory index has changes its file doesn't have yet."""
        with self._vec_lock:
            return any(ti.dirty for ti in self._types.values())

    def load_vectors(self) -> None:
        """Load (or rebuild) every vector type's search index now instead of on first search."""
        for vec_type in self.vec_types():
            self._type_index(vec_type)

    # ---- maintenance and stats
    def vacuum_if_sparse(self, min_free_share: float = 0.25) -> bool:
        """Give free pages back to the OS after large deletions (the index file never shrinks otherwise)."""
        pages = self.conn.execute("PRAGMA page_count").fetchone()[0]
        free = self.conn.execute("PRAGMA freelist_count").fetchone()[0]
        if pages and free / pages >= min_free_share:
            self.conn.execute("PRAGMA incremental_vacuum")
            return True
        return False

    def skipped_files(self, limit: int = 10) -> dict[str, Any]:
        """Files kept out of the index (or only partly parsed), by reason, with a few examples."""
        c = self.conn
        by_reason = {r[0]: r[1] for r in c.execute("SELECT reason, COUNT(*) FROM files WHERE reason != '' GROUP BY reason")}
        examples = [
            {"path": r[0], "reason": r[1], "size": r[2]}
            for r in c.execute(
                "SELECT path, reason, size FROM files WHERE reason != '' ORDER BY status = 'ok', size DESC LIMIT ?", (limit,)
            )
        ]
        return {"by_reason": by_reason, "examples": examples}

    def counts(self) -> dict[str, Any]:
        c = self.conn
        by_kind = {r[0]: r[1] for r in c.execute("SELECT kind, COUNT(*) FROM chunks GROUP BY kind")}
        by_language = {r[0]: r[1] for r in c.execute("SELECT language, COUNT(*) FROM chunks GROUP BY language")}
        vectors = {r[0]: r[1] for r in c.execute("SELECT vec_type, COUNT(*) FROM vectors GROUP BY vec_type")}
        return {
            "files": c.execute("SELECT COUNT(*) FROM files WHERE status = 'ok'").fetchone()[0],
            "chunks": sum(by_kind.values()),
            "chunks_by_kind": by_kind,
            "chunks_by_language": by_language,
            "edges": c.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "vectors": vectors,
        }

    # ---- comparing two indexes
    def snapshot(self) -> dict[str, Any]:
        """Everything stored, keyed by chunk key and path, never by id: an updated index and a
        rebuild of the same files must give equal snapshots (ids and file dates may differ)."""
        c = self.conn
        key_of = {r[0]: r[1] for r in c.execute("SELECT chunk_id, key FROM chunks")}
        chunks = {}
        for r in c.execute(f"SELECT {_CHUNK_COLS} FROM chunks"):
            chunks[r["key"]] = tuple(r[col] for col in r.keys() if col not in ("chunk_id", "key", "code"))
        calls: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for r in c.execute("SELECT caller_id, callee_name, line FROM calls"):
            calls[key_of[r[0]]].append((r[1], r[2]))
        fts = {}
        for r in c.execute("SELECT rowid, name_tokens, path_tokens, signature_tokens, doc_tokens, body_tokens FROM fts"):
            fts[key_of.get(r[0], f"<missing chunk {r[0]}>")] = tuple(r[1:])
        vectors = {}
        for r in c.execute("SELECT chunk_id, vec_type, part, n_parts, start_off, end_off, text_hash, embedder FROM vectors"):
            vectors[(key_of.get(r[0], f"<missing chunk {r[0]}>"), r[1], r[2])] = tuple(r[3:])
        return {
            "files": {
                r[0]: tuple(r[1:]) for r in c.execute("SELECT path, content_hash, size, language, status, reason FROM files")
            },
            "chunks": chunks,
            "calls": {k: sorted(v) for k, v in calls.items()},
            "edges": sorted((key_of[r[0]], key_of[r[1]]) for r in c.execute("SELECT caller_id, callee_id FROM edges")),
            "fts": fts,
            "vectors": vectors,
            "pending": sorted(key_of.get(r[0], str(r[0])) for r in c.execute("SELECT chunk_id FROM dirty_texts")),
        }


def diff_snapshots(a: dict[str, Any], b: dict[str, Any], limit: int = 20) -> list[str]:
    """Readable differences between two `Store.snapshot()`s (empty when they are equal)."""
    out: list[str] = []
    for part in a:
        x, y = a[part], b[part]
        if x == y:
            continue
        if isinstance(x, dict):
            for key in sorted(set(x) | set(y), key=str):
                if x.get(key) != y.get(key):
                    out.append(f"{part}[{key}]: {x.get(key)!r} != {y.get(key)!r}")
        else:
            out.append(f"{part}: only in first {sorted(set(x) - set(y))[:5]}, only in second {sorted(set(y) - set(x))[:5]}")
    return out[:limit] + ([f"... {len(out) - limit} more"] if len(out) > limit else [])
