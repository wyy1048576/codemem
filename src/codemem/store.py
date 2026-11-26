"""Storage: SQLite (chunks, FTS5, call graph, vectors) + one in-memory search index per vector type.

Consistency model
-----------------
SQLite is the source of truth for everything, vectors included: each row of `vectors` holds one
float16 vector at the model's full dimension, with the chunk, part (window) and text hash it
came from. The search index is derived from those rows. It is a `VectorStore` backend: `faiss`,
an exact inner-product index over vector ids that holds the same 2-byte numbers; `compact`,
which keeps small codes of each vector and scores its best candidates from the rows; or a class
named in config. By default (`auto`) it is the exact one while that fits a memory budget, and
the compact one when it does not (Store._pick). It is truncated to `embedding_dim` if set, kept
in memory and saved as `vec_<type><suffix>` with a `vec_<type>.json` note of the epoch it
reflects (and the database, backend and options it was saved from, the checksum of the file,
and the id of the save). Every transaction that changes a vector type's rows bumps its epoch in
`meta`, and the index is patched right after the commit (never before, so it never holds an
uncommitted vector). Vector rows never change in place: a new vector is a new row with a new
id. So an index that is behind (a saved file from before a crash, or another process wrote)
catches up by comparing vector ids and applying only the difference. A missing file, one whose
bytes are not the bytes that were saved, and one saved from a later state than the database is
in (Store.save_vectors) are rebuilt from the rows, which needs no model, and outside the vector
lock (Store._type_index). docs/architecture.md §5 lists the tables.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import math
import os
import sqlite3
import threading
import time
import uuid
import zlib
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import faiss
import numpy as np

from .config import COMPACT_MAX_DIM, DEFAULT_VECTOR_BACKEND, vector_memory_budget
from .plugins import load_object
from .schema import CALLABLE_KINDS, Chunk
from .texts import Ref
from .tokenize import to_fts_text
from .vectorcache import from_blob, to_blob

log = logging.getLogger(__name__)

SCHEMA_VERSION = 4

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
-- Keyword search reads only the word lists, so the table keeps no copy of its text (content = '').
-- Removing a row passes its five fields again (Store._fts_fields).
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    name_tokens, path_tokens, signature_tokens, doc_tokens, body_tokens, content = '',
    tokenize = "unicode61 tokenchars '_'"
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
CREATE INDEX IF NOT EXISTS vectors_hash ON vectors(embedder, text_hash);
-- Covers the read of where every vector came from (a search index's start), so it never reads
-- the pages that hold the vectors themselves. It also answers every lookup by vector type, or by
-- type and chunk: an index of only those two columns, which older indexes have, is dropped.
CREATE INDEX IF NOT EXISTS vectors_owner ON vectors(vec_type, chunk_id, part, n_parts, start_off, end_off);
DROP INDEX IF EXISTS vectors_type;
"""
# Every table any schema version has created, dropped when an older index is rebuilt.
_OLD_TABLES = ("meta", "files", "chunks", "calls", "edges", "fts_vocab", "fts", "embeddings", "vectors", "dirty_texts")

_CHUNK_COLS = (
    "chunk_id, key, path, language, kind, subkind, name, qualname, class_name, parent_key, start_line, "
    "end_line, signature, docstring, code, skeleton, content_hash, is_test, lead_comment"
)


def _temp_path(path: Path) -> Path:
    # A name of its own per process and thread: two writers never share a half-written temp file.
    return path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")


_REPLACE_TRIES = 6  # a rename that is refused is tried this many times in all, ...
_REPLACE_WAIT = 0.02  # ... after this many seconds, then twice as long each time: 0.62 s in all


def _replace(tmp: Path, path: Path) -> None:
    """Move `tmp` over `path` in one step (atomic on Windows and POSIX). Windows refuses the move
    with PermissionError while another handle holds one of the two files open: a second codemem
    process that reads `path` at its start, a virus scanner, the search indexer. Such a handle
    is gone a moment later, so a refused move is tried again a few times before the error is
    raised. Elsewhere a PermissionError is about the folder's permissions and stays: the tries
    then cost their 0.6 s and end in the same error."""
    wait = _REPLACE_WAIT
    for left in range(_REPLACE_TRIES - 1, -1, -1):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if not left:
                raise
            time.sleep(wait)
            wait *= 2


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = _temp_path(path)
    try:
        tmp.write_bytes(data)
        _replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)  # still there only when the write or the move failed


def bm25_weights5(weights: Sequence[float]) -> tuple[float, ...]:
    """name, path, signature, doc, body. A 3-value list from older configs (name, signature, body) is mapped to it."""
    w = tuple(float(x) for x in weights)
    if len(w) == 3:
        return (w[0], 0.0, w[1], w[2], w[2])
    if len(w) != 5:
        raise ValueError(f"bm25 weights need 5 values (name, path, signature, doc, body) or 3, got {len(w)}")
    return w


# --------------------------------------------------------------------------- vectors


# What a backend reads stored vectors with (VectorStore.bind): ids -> (the ids found, their vectors).
Fetch = Callable[[Sequence[int]], tuple[np.ndarray, np.ndarray]]


class VectorStore(ABC):
    """The in-memory search index of one vector type, keyed by vector id: FAISS by default, or a
    subclass named in config (`vector_backend = "module:Class"`, docs/architecture.md §5). It is
    built as Class(dim) and filled from the vectors stored in SQLite, already truncated and
    L2-normalized. The store calls one index from one thread at a time: the thread that builds or
    loads it, and after that whoever holds the store's vector lock. The indexes of two vector
    types can be called at the same time (one loads while the other is searched), so an index
    keeps its state in itself.

    `search(query, k, allowed_ids)` returns at most k (id, score) pairs, best first, with the real
    similarity as the score (equal scores are ties); fewer than k only when no other vector
    qualifies; only ids in `allowed_ids` when it is given. An approximate index (HNSW, IVF) can
    miss some, as it does anywhere else. The store never asks for a query of zeros: it has no
    direction, every vector would tie, and the store answers it with nothing.

    A backend that keeps less than the vectors themselves can read them back to score with:
    `bind(fetch)` hands it the function for that.

    Saving is optional: `to_bytes` gives the index for `vec_<type><suffix>`, and `from_bytes`
    reads it back at the next start. A backend that returns None is rebuilt from the stored
    vectors instead, which needs no model."""

    dim: int
    suffix: str = ".vec"

    def bind(self, fetch: Fetch) -> None:
        """Called once, right after the store builds or loads this index. `fetch(ids)` reads
        vectors from SQLite and returns the ids that still have a row and their vectors, row for
        row, exactly as `upsert` got them; an id whose row another process deleted is left out.
        It runs on the calling thread. A backend that holds the vectors needs nothing from it."""

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

    @classmethod
    def bytes_per_vector(cls, dim: int, **options: Any) -> int | None:
        """About how much memory one vector of `dim` numbers takes in this index, with the 32
        bytes the store keeps of where it came from. None when a backend does not say."""
        return None


_OWNER_BYTES = 32  # what the store keeps in memory of where a vector came from (_TypeIndex)


class FaissVectorStore(VectorStore):
    """Exact inner-product search; IndexIDMap2 so the vector id is the FAISS id. It keeps each
    number in 2 bytes, like the rows: they are rounded to float16 before they are stored, so 4
    bytes would hold the same values at twice the memory."""

    suffix = ".faiss"

    @classmethod
    def bytes_per_vector(cls, dim: int, **options: Any) -> int:
        # Measured: a process keeps 1,853 bytes per vector of 896 numbers (200,000 vectors). That is
        # 1,792 for the numbers, 8 for the id, 32 for where the vector came from, and 21 that
        # FAISS's id map takes: 32 beside the numbers, taken a little high.
        return 2 * dim + 32 + _OWNER_BYTES

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


_VECTOR_READ_CACHE_KB = 2000  # the page cache of a thread's connection for re-scoring reads
_ROTATION_SEED = 20261125
_QUERY_BITS = 4  # FAISS takes estimates against a query rounded to this many bits per number
_PER_RESULT = 4  # candidates scored exactly for each result asked for
# With fine codes, how many of the scan's best they rank again: at least this many, ...
# (2,000 lost one result of a top 50 in each of two real indexes, at places 2,021 and 2,178 of the
# scan, both for a question about another repo: docs/architecture.md §5)
_RANKED = 4000
_RANKED_PER_CANDIDATE = 4  # ... this many for each candidate, ...
_RANKED_ONE_IN = 50  # ... and one in this many of the vectors the search may return.
_NO_THRESHOLD = -1e30  # below every estimate: FAISS's range search then returns all it is given
_RABITQ_SINCE = (1, 15, 1)  # the FAISS those calls were checked against (docs/decisions.md §2)


def _has_rabitq() -> bool:
    """Whether the installed FAISS is one the compact index was checked against."""
    version = tuple(int(part) for part in faiss.__version__.split(".")[:3] if part.isdigit())
    return version >= _RABITQ_SINCE and hasattr(faiss, "IndexRaBitQ")


def _require_rabitq() -> None:
    """One sentence, not a native crash, when the installed FAISS cannot make the compact index."""
    if not _has_rabitq():
        raise RuntimeError(
            f'vector_backend = "compact" needs FAISS {".".join(map(str, _RABITQ_SINCE))} or newer for its RaBitQ '
            f"codes; this is FAISS {faiss.__version__}"
        )


@functools.lru_cache(maxsize=2)
def _rotation(dim: int) -> tuple[np.ndarray, str]:
    """The random rotation the compact codes are made after, and a hash that names it in saved
    files. One fixed rotation per length: equal vectors get equal codes in every index, and a
    file is only read by a process that makes the same rotation."""
    rotation, _ = np.linalg.qr(np.random.default_rng(_ROTATION_SEED).standard_normal((dim, dim), dtype=np.float32))
    rotation.setflags(write=False)  # shared by every index of this length
    return rotation, hashlib.sha1(rotation.tobytes()).hexdigest()[:16]


def _rabitq(dim: int, bits: int) -> Any:
    """An empty FAISS index of RaBitQ codes at `bits` bits per number, with its centre at zero.
    RaBitQ codes a vector minus a centre, which train() sets to the mean of what it is shown. One
    zero vector makes the centre zero: a code then depends only on its own vector, so an index
    patched edit by edit holds the same codes as one rebuilt from the rows."""
    index = faiss.IndexRaBitQ(dim, faiss.METRIC_INNER_PRODUCT, bits)
    index.train(np.zeros((1, dim), dtype=np.float32))
    return index


class CompactVectorStore(VectorStore):
    """Codes of each vector in memory, exact scores from the stored vectors
    (docs/architecture.md §5). It is built as CompactVectorStore(index_dim, **options), the
    options being the config's `[compact]` table.

    The codes are RaBitQ's, from FAISS, of the first `dim` numbers of the vector (0 = all of
    them, at most COMPACT_MAX_DIM; `code_dim` once resolved), scaled to length 1 and rotated.
    An index of longer vectors is coded on their first COMPACT_MAX_DIM numbers, and logs a
    warning when it is made: its searches can miss what only the other numbers tell apart.
    Every vector has a coarse code, 1 bit per number plus 8 bytes: that is what a search scans.
    With `bits` above 1 it also has a fine code of `bits` bits per number, and the scan's best
    (4,000 or more: `_candidates`) are ranked again by their fine estimates. The best of that, at
    least `rescore` and at least 4 per result asked for, are the candidates: their vectors are
    read through `fetch` and scored exactly, so every score a search returns is the real
    similarity. With no more vectors to choose from than it would score, it scores them all and
    skips the codes.

    FAISS can also scan fine codes by itself. It then takes a code's fine estimate whenever its
    first bit leaves it a chance against the best found so far: a tenth to a quarter of the
    codes, each at 25 times the cost of a 1-bit estimate, so that a search took 2 to 4 times as
    long as with the exact index. And which codes that is depends on the order they are held in.
    Here a search takes the fine estimate of the scan's best only, and its candidates depend
    only on the vectors held.

    FAISS holds the codes by position; `_ids` maps a position to its vector id, and the codes are
    kept in the order of those ids, so two indexes that hold the same vectors are the same bytes.
    A mistake in a FAISS call can end the process instead of raising, so whatever goes into one
    is checked here first: lengths, number types, and the size of every selector."""

    suffix = ".rabitq"

    def __init__(self, index_dim: int, /, *, bits: int = 4, dim: int = 0, rescore: int = 200):
        self.code_dim = self._code_dim(index_dim, bits, dim, rescore)
        self.dim = index_dim
        self.bits = bits
        self.rescore = rescore
        self._rotation, self._rotation_id = _rotation(self.code_dim)
        self._coarse = _rabitq(self.code_dim, 1)
        self._fine = _rabitq(self.code_dim, bits) if bits > 1 else None
        self._ids = np.empty(0, dtype=np.int64)
        self._fetch: Fetch | None = None
        if not dim and self.code_dim < index_dim:
            # Asked to code every number, and the longest code is shorter: said once, here, where
            # the index is made. Vectors that differ only past the code are told apart by no code.
            log.warning(
                "the compact search index codes the first %d numbers of each vector, and these vectors have %d: it "
                'can miss results that only the other numbers tell apart. The exact index (vector_backend = "faiss") '
                "compares every number, and embedding_dim = %d or less cuts the vectors themselves",
                self.code_dim, index_dim, self.code_dim,
            )

    @staticmethod
    def _code_dim(index_dim: int, bits: int, dim: int, rescore: int) -> int:
        """How many numbers of a vector are coded. It refuses, with a sentence, what FAISS was not
        checked with, so it runs before FAISS is given any of these."""
        _require_rabitq()
        given = (index_dim, bits, dim, rescore)
        if not all(type(v) is int for v in given):
            raise ValueError(f"the index's dim, and bits, dim and rescore, must be whole numbers, got {given}")
        if index_dim < 1 or not 1 <= bits <= 8 or not 0 <= dim <= COMPACT_MAX_DIM or rescore < 1:
            raise ValueError(
                f"need an index dim of 1 or more, bits 1 to 8, dim 0 to {COMPACT_MAX_DIM} and rescore of 1 or more, "
                f"got {given}"
            )
        return min(index_dim, dim or index_dim, COMPACT_MAX_DIM)

    @property
    def _indexes(self) -> list[Any]:
        return [self._coarse] if self._fine is None else [self._coarse, self._fine]

    @property
    def code_bytes(self) -> int:
        """Bytes of codes per vector."""
        return sum(index.code_size for index in self._indexes)

    @classmethod
    def bytes_per_vector(cls, index_dim: int, *, bits: int = 4, dim: int = 0, rescore: int = 200) -> int:
        # The codes, 8 bytes of id and 32 of where the vector came from. Measured at 896 numbers
        # and 4 bits: 657 bytes kept per vector for 628 counted this way; the rest is the rotation
        # (4 bytes for each number, squared, once in the process) and the allocator's slack.
        code_dim = cls._code_dim(index_dim, bits, dim, rescore)
        codes = sum(faiss.IndexRaBitQ(code_dim, faiss.METRIC_INNER_PRODUCT, b).code_size for b in {1, bits})
        return codes + 8 + _OWNER_BYTES

    def bind(self, fetch: Fetch) -> None:
        self._fetch = fetch

    def _coded(self, vecs: np.ndarray) -> np.ndarray:
        """Rows as FAISS takes them: the first `code_dim` numbers, scaled to length 1 and rotated,
        as contiguous float32. A row with a NaN or an infinity is coded as a zero vector."""
        with np.errstate(invalid="ignore"):
            rows = prepare(vecs, self.code_dim)
        rows[~np.isfinite(rows).all(axis=1)] = 0.0
        return np.ascontiguousarray(rows @ self._rotation, dtype=np.float32)

    def _in_step(self) -> None:
        """Every FAISS index holds one code per vector id, or nothing more is asked of FAISS."""
        for index in self._indexes:
            if index.ntotal != len(self._ids):
                raise RuntimeError(f"{len(self._ids)} vector ids for an index of {index.ntotal} codes")

    def _selector(self, chosen: np.ndarray) -> tuple[Any, np.ndarray]:
        """A FAISS selector of the positions where `chosen` is true, and the bitmap it reads.
        FAISS keeps only a pointer to the bitmap, so the caller holds it until the call is over;
        and the bitmap covers every position FAISS can ask about, or FAISS would read outside it."""
        self._in_step()
        if chosen.dtype != np.bool_ or chosen.shape != (len(self._ids),):
            raise RuntimeError(f"a selector over {chosen.shape} positions for an index of {len(self._ids)} codes")
        bitmap = np.packbits(chosen, bitorder="little")
        return faiss.IDSelectorBitmap(len(bitmap), faiss.swig_ptr(bitmap)), bitmap

    def upsert(self, ids: Sequence[int], vecs: np.ndarray) -> None:
        if len(ids) == 0:
            return
        id_arr = np.asarray(ids, dtype=np.int64)
        vecs = np.asarray(vecs, dtype=np.float32)
        if id_arr.ndim != 1 or vecs.shape != (len(id_arr), self.dim):
            raise ValueError(f"expected vectors of shape ({len(id_arr)}, {self.dim}), got {vecs.shape}")
        self._in_step()
        rows = self._coded(vecs)
        # FAISS holds the codes in two indexes and changes them one call at a time. If a call fails
        # after others worked, the index must still hold what it held before: the store then adds
        # the vectors again when it next catches up, where an index left out of step would refuse
        # every call until the process ended.
        held = (self._ids, self._coarse, self._fine)
        at_the_end = (len(self._ids) == 0 or id_arr[0] > self._ids[-1]) and bool((id_arr[1:] > id_arr[:-1]).all())
        try:
            if not at_the_end:
                # Ids are handed out in increasing order, so this is rare: an id that is held
                # already, or older than the newest held (a saved index or a catch-up brings
                # those). Codes are then dropped and moved as well, which FAISS cannot take back:
                # it is done on copies, and they take the indexes' place when all of it worked.
                self._coarse, self._fine = (
                    None if index is None else faiss.deserialize_index(faiss.serialize_index(index))
                    for index in (self._coarse, self._fine)
                )
                self.remove(id_arr)
            for index in self._indexes:
                index.add(rows)
            self._ids = np.concatenate([self._ids, id_arr])
            self._in_step()
            if not (self._ids[1:] > self._ids[:-1]).all():
                order = np.argsort(self._ids, kind="stable")  # move them to their place
                for index in self._indexes:
                    index.permute_entries(order)  # the code at position i becomes the one that was at order[i]
                self._ids = self._ids[order]
        except BaseException:
            self._ids, self._coarse, self._fine = held
            for index in self._indexes:
                if index.ntotal > len(self._ids):  # codes this call added at its end: take them off again
                    added = np.packbits(np.arange(index.ntotal) >= len(self._ids), bitorder="little")
                    index.remove_ids(faiss.IDSelectorBitmap(len(added), faiss.swig_ptr(added)))  # `added` outlives the call
            raise

    def remove(self, ids: Iterable[int]) -> None:
        gone = np.isin(self._ids, np.fromiter(ids, dtype=np.int64))
        if gone.any():
            selector, bitmap = self._selector(gone)  # `bitmap` is what the selector reads: it outlives the calls
            for index in self._indexes:
                index.remove_ids(selector)  # FAISS closes the gaps without reordering
            self._ids = self._ids[~gone]

    def search(self, query, k, allowed_ids=None):
        if k <= 0 or len(self._ids) == 0:
            return []
        if self._fetch is None:
            raise RuntimeError("CompactVectorStore scores from the stored vectors: call bind(fetch) first")
        q = np.asarray(query, dtype=np.float32).reshape(-1)
        if q.shape != (self.dim,):
            raise ValueError(f"expected a query of {self.dim} numbers, got {q.shape[0]}")
        if not np.isfinite(q).all():
            return []
        allowed = None if allowed_ids is None else np.isin(self._ids, np.asarray(allowed_ids, dtype=np.int64))
        qualifying = len(self._ids) if allowed is None else int(np.count_nonzero(allowed))
        size = max(self.rescore, _PER_RESULT * int(k))
        while True:
            if qualifying <= size:  # few enough to score every one exactly, without the codes
                candidates = self._ids if allowed is None else self._ids[allowed]
            else:
                candidates = self._ids[self._candidates(q, size, allowed)]
            found, vecs = self._fetch(candidates)
            # Summed row by row, not `vecs @ q`: BLAS adds a row's products in an order that
            # depends on where the row sits, so copies of one vector would get unequal scores.
            with np.errstate(invalid="ignore"):
                scores = (vecs * q).sum(axis=1)
            real = np.isfinite(scores)  # a stored vector with a NaN or an infinity has no score
            found, scores = found[real], scores[real]
            order = np.lexsort((found, -scores))[:k]
            if len(order) == k or qualifying <= size:
                return [(int(found[i]), float(scores[i])) for i in order]
            size *= 2  # another process deleted candidates' rows: take more candidates

    def _candidates(self, q: np.ndarray, size: int, allowed: np.ndarray | None) -> np.ndarray:
        """Positions of the `size` best codes for a query, and of every code that ties with the
        last of them. Which they are depends on the vectors held, never on their order."""
        self._in_step()
        x = self._coded(q)
        if self._fine is None:
            return self._scan(x, size, allowed)
        qualifying = len(self._ids) if allowed is None else int(np.count_nonzero(allowed))
        ranked = max(_RANKED, _RANKED_PER_CANDIDATE * size, qualifying // _RANKED_ONE_IN)
        ranked_again = np.zeros(len(self._ids), dtype=bool)
        ranked_again[self._scan(x, ranked, allowed)] = True
        selector, bitmap = self._selector(ranked_again)  # `bitmap` is what the selector reads
        params = faiss.RaBitQSearchParameters(qb=_QUERY_BITS, centered=False, sel=selector)
        _, estimates, positions = self._fine.range_search(x, _NO_THRESHOLD, params=params)
        if len(positions) <= size:
            return positions
        cut = np.partition(estimates, len(estimates) - size)[len(estimates) - size]  # the size-th best
        return positions[estimates >= cut]

    def _scan(self, x: np.ndarray, size: int, allowed: np.ndarray | None) -> np.ndarray:
        """Positions of the `size` coarse codes that score best against a coded query, and of
        every code that ties with the last of them; all the allowed ones when they are no more."""
        if size >= (len(self._ids) if allowed is None else np.count_nonzero(allowed)):
            return np.arange(len(self._ids)) if allowed is None else np.flatnonzero(allowed)
        # `bitmap` is what the selector reads: it has to outlive the search.
        selector, bitmap = (None, None) if allowed is None else self._selector(allowed)
        params = faiss.RaBitQSearchParameters(qb=_QUERY_BITS, centered=False, sel=selector)
        ask = size + 1
        while True:
            estimates, positions = self._coarse.search(x, min(ask, self._coarse.ntotal), params=params)
            valid = positions[0] >= 0
            estimates, positions = estimates[0][valid], positions[0][valid]
            if len(positions) <= size:
                return positions
            if len(positions) < ask or estimates[-1] != estimates[size - 1]:
                return positions[estimates >= estimates[size - 1]]
            ask *= 2

    def ids(self) -> set[int]:
        return set(self._ids.tolist())

    def __len__(self) -> int:
        return len(self._ids)

    def to_bytes(self) -> bytes:
        """One line of JSON (what the codes were made with, the size of each FAISS index, and a
        checksum of the rest), the vector ids, the FAISS indexes: the coarse one, then the fine."""
        indexes = [faiss.serialize_index(index).tobytes() for index in self._indexes]
        body = b"".join((self._ids.astype("<i8").tobytes(), *indexes))
        head = {"dim": self.dim, "code_dim": self.code_dim, "bits": self.bits, "count": len(self._ids),
                "rotation": self._rotation_id, "index_bytes": [len(index) for index in indexes],
                "crc32": zlib.crc32(body)}
        return json.dumps(head).encode("utf-8") + b"\n" + body

    @classmethod
    def from_bytes(cls, data: bytes, **options: int) -> CompactVectorStore:
        """Read a saved index, or raise: FAISS gets the bytes only when they are the bytes that
        were saved, and its indexes are used only when they are the ones the options describe."""
        end = data.find(b"\n")
        head = json.loads(data[:end]) if end >= 0 else {}
        body = memoryview(data)[end + 1:]  # a view: the file's bytes are not copied a second time
        if zlib.crc32(body) != head.get("crc32"):
            raise ValueError("the file is damaged or incomplete")
        store = cls(head["dim"], **options)
        count, sizes = head["count"], head.get("index_bytes")
        if (head["code_dim"], head["bits"], head["rotation"]) != (store.code_dim, store.bits, store._rotation_id):
            raise ValueError("the file's codes were made with other options, or with another rotation")
        if (type(count) is not int or count < 0 or not isinstance(sizes, list) or len(sizes) != len(store._indexes)
                or not all(type(size) is int and size > 0 for size in sizes) or 8 * count + sum(sizes) != len(body)):
            raise ValueError("the file does not hold the vector ids and indexes its first line names")
        store._ids = np.frombuffer(body, dtype="<i8", count=count).astype(np.int64)
        if not (store._ids[1:] > store._ids[:-1]).all():
            raise ValueError("the file's vector ids are not in order")
        loaded, at = [], 8 * count
        for size, empty in zip(sizes, store._indexes):
            # The object deserialize_index returns owns the C++ index: it is kept as it is. A second
            # Python object for it (faiss.downcast_index) would outlive it and point at freed memory.
            index = faiss.deserialize_index(np.frombuffer(body, dtype=np.uint8, count=size, offset=at))
            at += size
            if not (
                isinstance(index, faiss.IndexRaBitQ) and index.thisown and index.is_trained
                and index.d == store.code_dim and index.rabitq.nb_bits == empty.rabitq.nb_bits
                and index.metric_type == faiss.METRIC_INNER_PRODUCT and index.code_size == empty.code_size
                and index.ntotal == count and index.codes.size() == count * index.code_size
                and index.center.size() == index.d and not faiss.vector_to_array(index.center).any()
            ):
                raise ValueError("a FAISS index of the file is not the one its first line describes")
            loaded.append(index)
        store._coarse, store._fine = loaded[0], (loaded[1] if len(loaded) > 1 else None)
        return store


class _InUse(NamedTuple):
    """The search index a store's vector types are searched with."""

    name: str  # faiss | compact | "module:Class"
    options: dict[str, Any]
    cls: type[VectorStore]
    why: str  # the reason, for `codemem status`


_BACK_TO_EXACT = 0.8  # `auto`: an index that is compact goes back to exact only under this share of the budget
_NOT_LOADED = object()  # Store._loaded: the type has vectors, and its index is not in memory


def vector_backend_class(name: str) -> type[VectorStore]:
    """`faiss`, `compact` or "module:Class" -> the VectorStore subclass."""
    if name == "faiss":
        return FaissVectorStore
    if name == "compact":
        _require_rabitq()
        return CompactVectorStore
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


def for_index(vecs: np.ndarray, dim: int) -> np.ndarray:
    """Stored vectors as a search index gets them: `prepare`d, then rounded to 2 bytes per number
    again. Normalizing moves the numbers off float16 values; rounding them back gives every
    backend the same numbers, which a 2-byte index holds exactly."""
    return prepare(vecs, dim).astype(np.float16).astype(np.float32)


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


# Where one vector of a search index came from: 32 bytes.
_OWNER = np.dtype([
    ("vector", np.int64), ("chunk", np.int64), ("part", np.int32), ("n_parts", np.int32),
    ("start_off", np.int32), ("end_off", np.int32),
])


def _owners(vector_ids: Sequence[int], info: Sequence[Sequence[int]]) -> np.ndarray:
    """Vector ids and their (chunk, part, n_parts, start_off, end_off), as an `_OWNER` table."""
    table = np.empty(len(vector_ids), dtype=_OWNER)
    table["vector"] = vector_ids
    columns = np.asarray(info, dtype=np.int64).reshape(len(vector_ids), 5)
    for name, column in zip(_OWNER.names[1:], columns.T):
        table[name] = column
    return table


class _TypeIndex:
    """The in-memory search index of one vector type and where each vector came from: one
    `_OWNER` row per vector, sorted by vector id, read with `find` and `vectors_of`."""

    def __init__(self, dim: int, epoch: int, store: VectorStore):
        self.store = store
        self.dim = dim
        self.epoch = epoch
        self.dirty = False
        self._table = np.empty(0, dtype=_OWNER)
        self._held: list[np.ndarray] = []  # rows not merged into the table yet
        self._per_chunk: float | None = None  # vectors per chunk, for the table as it is

    @property
    def table(self) -> np.ndarray:
        if self._held:
            table = np.concatenate([self._table, *self._held])
            self._held = []
            ids = table["vector"]
            if not (ids[1:] > ids[:-1]).all():
                # Ids are handed out in increasing order, so this is rare: a saved index or a
                # catch-up brings rows older than the newest held. An id held twice keeps its last row.
                table = table[np.argsort(ids, kind="stable")]
                table = table[np.append(table["vector"][1:] != table["vector"][:-1], True)]
            self._table = table
        return self._table

    def add(self, vector_ids: Sequence[int], info: Sequence[tuple[int, int, int, int, int]], vecs: np.ndarray) -> None:
        self.store.upsert(vector_ids, for_index(vecs, self.dim))
        self.hold(_owners(vector_ids, info))

    def hold(self, owners: np.ndarray) -> None:
        """Record where vectors came from that the backend already holds."""
        self._held.append(owners)
        self._per_chunk = None

    def remove(self, vector_ids: Iterable[int]) -> None:
        table = self.table
        gone = np.isin(table["vector"], np.fromiter(vector_ids, dtype=np.int64))
        if gone.any():
            self.store.remove(table["vector"][gone].tolist())
            self._table = table[~gone]
            self._per_chunk = None

    def vectors_for(self, n: int) -> int:
        """How many of the best vectors to ask for when the n best chunks are wanted: n when every
        chunk has one vector, more when chunks have several parts (each row counts as 1/n_parts
        of a chunk). An estimate: the search asks again when it was too few."""
        if self._per_chunk is None:
            parts = np.maximum(self.table["n_parts"], 1)
            self._per_chunk = len(parts) / float((1.0 / parts).sum()) if len(parts) else 1.0
        return math.ceil(n * self._per_chunk)

    def find(self, vector_ids: Sequence[int]) -> np.ndarray:
        """The rows of these vectors, in the order asked."""
        table = self.table
        ids = np.asarray(vector_ids, dtype=np.int64)
        if not len(ids):
            return table[:0]
        at = np.minimum(np.searchsorted(table["vector"], ids), len(table) - 1)
        if not len(table) or (table["vector"][at] != ids).any():
            raise KeyError("a vector id that the search index does not hold")
        return table[at]

    def vectors_of(self, chunk_ids: Sequence[int]) -> np.ndarray:
        """The ids of every vector of these chunks."""
        table = self.table
        return table["vector"][np.isin(table["chunk"], np.asarray(chunk_ids, dtype=np.int64))]


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
        vector_backend: str = DEFAULT_VECTOR_BACKEND, vector_options: Mapping[str, Any] | None = None,
        vector_memory_mb: int = 0,
    ):
        """`vector_backend` is `auto`, `faiss`, `compact` or "module:Class". `vector_options` are
        a backend's own settings, passed to it by keyword when it is built and when its saved
        file is read (Config.vector_options()): for `auto`, the compact index's, used when that
        is the index it picks. `vector_memory_mb` is the budget `auto` picks by (_pick)."""
        self.vector_backend = vector_backend
        self.vector_options = dict(vector_options or {})
        self.vector_memory_mb = vector_memory_mb
        self._in_use = self._named()  # None for `auto`, until the first index is loaded or built
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.index_dir / "index.db"
        self.tok_opts = {"stem": bm25_stem, "stopwords": bm25_stopwords}
        self._local = threading.local()
        self._vec_lock = threading.RLock()
        self._save_lock = threading.Lock()
        self._types: dict[str, _TypeIndex] = {}
        # Vector types whose index a thread is loading or rebuilding now (set when it is done), how
        # far each rebuild is, and a number that changes with the backend: an index loaded for an
        # earlier backend is dropped, not installed.
        self._loading: dict[str, threading.Event] = {}
        self._progress: dict[str, tuple[float, int, int]] = {}  # started (monotonic), vectors done, vectors in all
        self._generation = 0
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
        if self.get_meta("database_id") is None:
            # A new database, or one that came without an identity (an older index, or a copy made
            # to start another index). Of two processes that open it together, the first one's stays.
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('database_id', ?)", (json.dumps(uuid.uuid4().hex),)
            )

    # ---- connections
    def _connect(self, cache_kb: int) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(f"PRAGMA cache_size=-{cache_kb}")  # at most this much of pages, as used
        with self._conns_lock:
            self._all_conns[id(conn)] = (threading.current_thread(), conn)
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._local.conn = self._connect(65536)  # up to 64 MB of pages per thread
        return conn

    @property
    def _vector_reader(self) -> sqlite3.Connection:
        """The calling thread's second connection, read-only, for the vectors a re-scoring search
        index reads back. Each search reads a few hundred rows, other ones every time: through
        `conn` they would fill its page cache (64 MB after 100 searches at 200,000 vectors) and
        push out the pages that keyword search and cards use. This one keeps 2 MB."""
        conn = getattr(self._local, "vector_reader", None)
        if conn is None:
            conn = self._local.vector_reader = self._connect(_VECTOR_READ_CACHE_KB)
            conn.execute("PRAGMA query_only=ON")
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
        """Close the calling thread's connections (for short-lived worker threads)."""
        for name in ("conn", "vector_reader"):
            conn = getattr(self._local, name, None)
            if conn is not None:
                setattr(self._local, name, None)
                with self._conns_lock:
                    self._all_conns.pop(id(conn), None)
                conn.close()

    def close(self) -> None:
        """Close this thread's connections and those of threads that have ended. A thread that is
        still running keeps its own: closing a connection under another thread's query crashes the
        process (they are opened with check_same_thread=False). They close with that thread."""
        me = threading.current_thread()
        with self._conns_lock:
            done = [k for k, (thread, _) in self._all_conns.items() if thread is me or not thread.is_alive()]
            conns = [self._all_conns.pop(k)[1] for k in done]
        for conn in conns:
            try:
                conn.close()
            except sqlite3.ProgrammingError:
                pass
        self._local.conn = self._local.vector_reader = None

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
            self._fts_delete([chunk_id])  # before the update: the old fields name the words to remove
            conn.execute(
                "UPDATE chunks SET path=?, language=?, kind=?, subkind=?, name=?, qualname=?, class_name=?, "
                "parent_key=?, start_line=?, end_line=?, signature=?, docstring=?, code=?, skeleton=?, "
                "content_hash=?, is_test=?, lead_comment=? WHERE chunk_id=?",
                (*values, chunk_id),
            )
            conn.execute("DELETE FROM calls WHERE caller_id = ?", (chunk_id,))
        else:
            cur = conn.execute(
                "INSERT INTO chunks(key, path, language, kind, subkind, name, qualname, class_name, parent_key, "
                "start_line, end_line, signature, docstring, code, skeleton, content_hash, is_test, lead_comment) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (chunk.key, *values),
            )
            chunk_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO fts(rowid, name_tokens, path_tokens, signature_tokens, doc_tokens, body_tokens) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (
                chunk_id,
                *self._fts_fields(
                    chunk.qualname, chunk.name, chunk.path, chunk.signature, chunk.docstring, chunk.lead_comment,
                    chunk.kind, chunk.skeleton, chunk.code,
                ),
            ),
        )
        lines = list(chunk.call_lines) + [0] * (len(chunk.calls) - len(chunk.call_lines))
        conn.executemany(
            "INSERT INTO calls(caller_id, callee_name, line) VALUES(?, ?, ?)",
            [(chunk_id, c, line) for c, line in zip(chunk.calls, lines)],
        )
        chunk.chunk_id = chunk_id
        return chunk_id

    def _fts_fields(
        self, qualname: str, name: str, path: str, signature: str, docstring: str, lead_comment: str,
        kind: str, skeleton: str, code: str,
    ) -> tuple[str, str, str, str, str]:
        """A chunk's five keyword fields: name, path, signature, doc, body. The keyword table keeps no
        copy of them, and removing a row must pass exactly what was added, so both go through here.
        The token options are index settings, fixed for an index's life."""
        body = skeleton if kind == "class" and skeleton else code
        opts = self.tok_opts
        return (
            to_fts_text(f"{qualname} {name}", **opts),
            to_fts_text(path, **opts),
            to_fts_text(signature, **opts),
            to_fts_text(f"{docstring}\n{lead_comment}", **opts),
            to_fts_text(body, **opts),
        )

    def _fts_delete(self, ids: Sequence[int]) -> None:
        """Remove chunks' keyword rows. Call it while their chunk rows still hold what was indexed."""
        conn = self.conn
        for batch in _batches(list(ids)):
            marks = ",".join("?" * len(batch))
            rows = [
                tuple(r) for r in conn.execute(
                    "SELECT chunk_id, qualname, name, path, signature, docstring, lead_comment, kind, skeleton, code "
                    f"FROM chunks WHERE chunk_id IN ({marks})", tuple(batch),
                )
            ]
            conn.executemany(
                "INSERT INTO fts(fts, rowid, name_tokens, path_tokens, signature_tokens, doc_tokens, body_tokens) "
                "VALUES('delete', ?, ?, ?, ?, ?, ?)",
                [(r[0], *self._fts_fields(*r[1:])) for r in rows],
            )

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
        self._fts_delete(ids)
        conn.executemany("DELETE FROM chunks WHERE chunk_id = ?", params)
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
        return self.index_dir / f"vec_{vec_type}{self._search_index().cls.suffix}"

    def _note_path(self, vec_type: str) -> Path:
        return self.index_dir / f"vec_{vec_type}.json"

    def _read_note(self, vec_type: str) -> dict[str, Any] | None:
        try:
            note = json.loads(self._note_path(vec_type).read_text("utf-8"))
        except (OSError, ValueError):
            return None
        return note if isinstance(note, dict) else None

    def _noted_file(self, vec_type: str, note: dict[str, Any] | None) -> Path | None:
        """The saved index a note describes: this folder's `vec_<type>` file of the backend the
        note names (none: a note from before backends were pluggable, so FAISS). A note is a file
        that whoever can write to the folder can write, and the file it names is read by a start
        and deleted by a save. So its `file` counts only when it is that very name. With a path,
        or the name of anything else in the folder, it is no note: None."""
        if not note:
            return None
        use, backend = self._search_index(), note.get("backend", "faiss")
        for name, cls in ((use.name, use.cls), ("faiss", FaissVectorStore), ("compact", CompactVectorStore)):
            if backend == name:
                path = self.index_dir / f"vec_{vec_type}{cls.suffix}"
                return path if note.get("file", path.name) == path.name else None
        return None  # a plugin that is not the one in use: the suffix of its files is not known here

    def database_id(self) -> str:
        """This database's identity: a random token set when it is created. A saved search index
        names it in its note and is read back only into that database. Vector ids start again at
        1 in a new database, so the file of an index that was deleted would match other vectors
        by id."""
        return self.get_meta("database_id")

    def use_vector_backend(
        self, name: str, options: Mapping[str, Any] | None = None, memory_mb: int | None = None
    ) -> None:
        """Search with another backend, other options of the same one, or another budget for
        `auto`, from now on. Each vector type's index is loaded or rebuilt from the stored vectors
        when it is next used; nothing is re-embedded."""
        vector_backend_class("faiss" if name == "auto" else name)  # a backend that does not load is refused here
        with self._vec_lock:
            self.vector_backend, self.vector_options = name, dict(options or {})
            if memory_mb is not None:
                self.vector_memory_mb = memory_mb
            self._in_use = self._named()
            self._types.clear()
            self._generation += 1

    def _named(self) -> _InUse | None:
        """The backend the configuration names, or None for `auto`."""
        if self.vector_backend == "auto":
            return None
        cls = vector_backend_class(self.vector_backend)
        return _InUse(self.vector_backend, self.vector_options, cls, f'vector_backend = "{self.vector_backend}"')

    def _search_index(self) -> _InUse:
        """What this store's vector types are searched with: the backend the configuration names,
        or what `auto` picked. `auto` picks once, when the first index is loaded or built, and
        the pick holds while the store is open: an index that grows past the budget meanwhile
        stays as it is until the next start (or the next update that saves)."""
        with self._vec_lock:
            if self._in_use is None:
                self._in_use = self._pick(self._saved_as_compact())
                log.info("search index of %s: %s (%s)", self.index_dir, self._in_use.name, self._in_use.why)
            return self._in_use

    def _exact_bytes(self) -> int:
        """What the exact indexes of every vector type would take in memory, together."""
        counts = self.conn.execute("SELECT vec_type, COUNT(*) FROM vectors GROUP BY vec_type").fetchall()
        return sum(n * FaissVectorStore.bytes_per_vector(self.vector_dim(vec_type) or 0) for vec_type, n in counts)

    def _saved_as_compact(self) -> bool:
        """Whether this database's saved search indexes are compact ones. Only the vector types
        that have vectors count: a type that lost them all keeps the note of its last save, which
        says nothing of the index as it is."""
        notes = (self._read_note(vec_type) for vec_type in self.vec_types())
        return any(n.get("backend") == "compact" and n.get("database") == self.database_id() for n in notes if n)

    def _pick(self, compact_now: bool) -> _InUse:
        """`auto`: the exact index for every vector type while their exact indexes fit the budget
        together, the compact one for every type when they do not. Exact is the more faithful
        and, on an index that fits, the faster of the two; compact is what keeps a large index
        within the memory a machine can spare. An index that is compact goes back to exact only
        well under the budget, so that one near it does not change at every start. Where the
        installed FAISS cannot make the compact index, the pick is always exact."""
        need = self._exact_bytes()
        budget, of = vector_memory_budget(self.vector_memory_mb)
        exact, limit = f"{need / 1e6:,.0f} MB", f"{budget / 1e6:,.0f} MB ({of})"
        if not _has_rabitq():
            fits, why = True, f"this FAISS, {faiss.__version__}, cannot make the compact index"
        elif need <= budget * (_BACK_TO_EXACT if compact_now else 1):
            fits, why = True, f"the exact index takes {exact}, within the budget of {limit}"
        elif need <= budget:
            fits = False
            why = (f"the exact index would take {exact}: the index is compact, and goes back to exact under "
                   f"{_BACK_TO_EXACT:.0%} of the budget of {limit}")
        else:
            fits, why = False, f"the exact index would take {exact}, over the budget of {limit}"
        if fits:
            return _InUse("faiss", {}, FaissVectorStore, f"auto: {why}")
        return _InUse("compact", self.vector_options, CompactVectorStore, f"auto: {why}")

    def search_index_status(self) -> dict[str, Any]:
        """Which search index the vector types use, why, and about how much memory each takes
        (for `codemem status`). `next` is set when `auto` would pick the other index now: it does
        at the next start."""
        use = self._search_index()
        types: dict[str, Any] = {}
        for vec_type, n in self.conn.execute("SELECT vec_type, COUNT(*) FROM vectors GROUP BY vec_type").fetchall():
            dim = self.vector_dim(vec_type)
            per = use.cls.bytes_per_vector(dim, **use.options) if dim else None
            types[vec_type] = {"index": use.name, "vectors": n,
                               "memory_mb": None if per is None else round(n * per / 1e6, 1)}
        info: dict[str, Any] = {"setting": self.vector_backend, "index": use.name, "why": use.why, "types": types}
        if self.vector_backend == "auto":
            info["exact_mb"] = round(self._exact_bytes() / 1e6, 1)
            info["budget_mb"] = round(vector_memory_budget(self.vector_memory_mb)[0] / 1e6, 1)
            now = self._pick(use.name == "compact")
            if now.name != use.name:
                info["next"] = {"index": now.name, "why": now.why}
        return info

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
        for key in ("embedder", "full_dim", "dim_setting", "save_id"):
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

    def vector_hashes(self) -> dict[str, list[str]]:
        """The text hashes of every stored vector, by embedder key: what this index holds of the
        vector cache's entries."""
        out: dict[str, list[str]] = {}
        for embedder, text_hash in self.conn.execute("SELECT DISTINCT embedder, text_hash FROM vectors"):
            out.setdefault(embedder, []).append(text_hash)
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
            first = conn.execute("SELECT 1 FROM vectors WHERE vec_type = ? LIMIT 1", (vec_type,)).fetchone() is None
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
                        # Not loaded. A type's first vectors start its index here, so that the
                        # index grows with every batch of a build. An index of earlier vectors
                        # is loaded when it is first used, from rows that include these: loading
                        # it here would hold this commit, and all who wait for it, for as long as
                        # a rebuild takes.
                        if first and vec_type not in self._loading:
                            self._load(vec_type, self._generation)
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
        """The in-memory index of a vector type, loaded or rebuilt if missing or out of date.

        Loading happens outside the vector lock. A rebuild reads and codes every vector (half a
        minute for 200,000 in the compact form, with FAISS on one thread), and a write's commit, a
        status call or a search that can answer without vectors must not wait for that. One thread
        loads a type; others that ask for it meanwhile wait for that thread, on an event, not on
        the lock. So this is never called while holding the vector lock: the loading thread needs
        the lock at its end."""
        while True:
            with self._vec_lock:
                ti = self._loaded(vec_type)
                if ti is not _NOT_LOADED:
                    return ti
                done = self._loading.get(vec_type)
                mine = done is None
                if mine:
                    done = self._loading[vec_type] = threading.Event()
                    generation = self._generation
            if not mine:
                done.wait()
                continue
            try:
                self._load(vec_type, generation)
            finally:
                with self._vec_lock:
                    del self._loading[vec_type]
                done.set()

    def _loaded(self, vec_type: str) -> _TypeIndex | None | object:
        """Under the vector lock: the in-memory index of a vector type, brought up to the committed
        rows; None when the type has no vectors; `_NOT_LOADED` when it has to be loaded first."""
        with self._read_snapshot():
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
                return ti
            return _NOT_LOADED

    def _load(self, vec_type: str, generation: int) -> None:
        """Load a vector type's index from its saved file, or rebuild it from the rows, and install
        it. The rows are read as one committed state. What was written while it loaded is applied
        at the end, under the lock, by vector id."""
        with self._read_snapshot():
            epoch, dim = self._epoch(vec_type), self.vector_dim(vec_type)
            if dim is None:
                return
            ti = self._load_saved(vec_type, epoch, dim) or self._rebuild(vec_type, epoch, dim)
        with self._vec_lock, self._read_snapshot():
            if generation != self._generation or self.vector_dim(vec_type) != dim:
                return  # another backend, or another length, since it began: whoever needs it loads again
            now = self._epoch(vec_type)
            if now != ti.epoch:
                self._catch_up(ti, vec_type, now)
            self._types[vec_type] = ti

    def vectors_loaded(self) -> bool:
        """Whether every vector type's search index is in memory: a search then waits for no load."""
        with self._vec_lock:
            return all(vec_type in self._types for vec_type in self.vec_types())

    def load_eta(self) -> float | None:
        """Seconds until the rebuild that is running is expected to end, from its pace so far.
        None when none is running, or when one has only begun."""
        now = time.monotonic()
        left = [(now - started) * (total - done) / done for started, done, total in list(self._progress.values()) if done]
        return max(left) if left else None

    def _catch_up(self, ti: _TypeIndex, vec_type: str, epoch: int) -> None:
        """Bring an in-memory index to the committed rows by their ids. Vector rows never change in
        place (a new vector is a new row, and AUTOINCREMENT never reuses an id), so the set of ids
        says everything."""
        rows = self.conn.execute("SELECT vector_id FROM vectors WHERE vec_type = ?", (vec_type,))
        now = np.fromiter((r[0] for r in rows), dtype=np.int64)
        have = ti.table["vector"]
        ti.remove(np.setdiff1d(have, now))
        self._add_rows(ti, np.setdiff1d(now, have).tolist())
        ti.epoch = epoch
        ti.dirty = True

    def _add_rows(self, ti: _TypeIndex, vector_ids: Sequence[int]) -> None:
        for batch in _batches(sorted(vector_ids), 4096):
            rows = self.conn.execute(
                "SELECT vector_id, chunk_id, part, n_parts, start_off, end_off, dim, data FROM vectors "
                f"WHERE vector_id IN ({','.join('?' * len(batch))})",
                tuple(batch),
            ).fetchall()
            if rows:
                ti.add([r[0] for r in rows], [(r[1], r[2], r[3], r[4], r[5]) for r in rows],
                       np.stack([from_blob(r[7], r[6]) for r in rows]))

    def _stored_owners(self, vec_type: str) -> np.ndarray:
        """Where every stored vector of a type came from, sorted by vector id."""
        rows = self.conn.execute(
            "SELECT vector_id, chunk_id, part, n_parts, start_off, end_off FROM vectors WHERE vec_type = ?", (vec_type,)
        )
        flat = np.fromiter((x for r in rows for x in r), dtype=np.int64).reshape(-1, 6)
        flat = flat[np.argsort(flat[:, 0], kind="stable")]  # the covering index gives them by chunk
        return _owners(flat[:, 0], flat[:, 1:])

    def _stored_vectors(self, dim: int, vector_ids: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
        """What a backend's `fetch` reads (VectorStore.bind): the ids among these that have a row,
        and their vectors as the index got them.

        It reads through the calling thread's vector reader. Each statement there is its own read
        of the database as it is now, and is read to its end, so nothing stays open between
        searches to hold the write-ahead log back. "Now" is late enough: an index holds a vector
        only once its row is committed (it is patched after the commit, under the lock the search
        holds). A caller that is inside a transaction or a read snapshot of its own gets the rows
        that transaction sees, from its own connection."""
        conn = self.conn if self.conn.in_transaction else self._vector_reader
        ids: list[int] = []
        blobs: list[bytes] = []
        for batch in _batches(np.asarray(vector_ids, dtype=np.int64).tolist()):
            rows = conn.execute(
                f"SELECT vector_id, data FROM vectors WHERE vector_id IN ({','.join('?' * len(batch))})", batch
            ).fetchall()
            for vector_id, data in rows:
                ids.append(vector_id)
                blobs.append(data)
        if not ids:
            return np.empty(0, dtype=np.int64), np.empty((0, dim), dtype=np.float32)
        # One vector type's rows all have one length, so the blobs join into one table.
        vecs = np.frombuffer(b"".join(blobs), dtype=np.float16).reshape(len(ids), -1)
        return np.asarray(ids, dtype=np.int64), for_index(vecs, dim)

    def _bound(self, store: VectorStore, dim: int) -> VectorStore:
        store.bind(functools.partial(self._stored_vectors, dim))
        return store

    def _usable_note(self, vec_type: str, dim: int | None) -> dict[str, Any] | None:
        """The note of a vector type's saved index, when a start can read that index: it was saved
        from this database, by the backend in use with its options, for this length and embedder,
        it holds the checksum of its file, and the file is there. Whatever epoch it was saved at,
        as long as the database has not gone back behind that save: the note and `meta` then hold
        the same `save_id` (save_vectors)."""
        use = self._search_index()
        note = self._read_note(vec_type)
        path = self._noted_file(vec_type, note)
        if (note is None or path is None or note.get("database") != self.database_id()
                or not note.get("save_id") or note.get("save_id") != self.get_meta(f"vec.{vec_type}.save_id")
                or note.get("backend", "faiss") != use.name or note.get("options", {}) != use.options
                or note.get("dim") != dim or note.get("embedder") != self.get_meta(f"vec.{vec_type}.embedder")
                or type(note.get("crc32")) is not int or not path.is_file()):
            return None
        return note

    def _load_saved(self, vec_type: str, epoch: int, dim: int) -> _TypeIndex | None:
        """The saved index file, reconciled with the committed rows by vector id: vectors whose
        row is gone are dropped, rows the file lacks are added. Rows never change in place, so
        this is exact whichever epoch the file was saved at (another process, a crash, a save
        that is behind), and it costs only the difference instead of a full rebuild. No file, one
        from another database, another backend or other options, or one whose bytes are not the
        bytes that were saved: None, and the index is rebuilt from the rows."""
        use = self._search_index()
        note = self._usable_note(vec_type, dim)
        if note is None:
            return None
        path = self._noted_file(vec_type, note)
        try:
            data = path.read_bytes()
            if zlib.crc32(data) != note["crc32"]:
                # Damaged, cut short, or another index's file under this note. A backend can read
                # such bytes without a word and score with them, or allocate without end: it gets none.
                log.warning("%s is not the file its note describes; rebuilding it from the stored vectors", path)
                return None
            store = use.cls.from_bytes(data, **use.options)
        except Exception:  # a file that cannot be read: rebuild from the rows
            log.exception("could not load %s; rebuilding it from the stored vectors", path)
            return None
        if store.dim != dim:
            return None
        ti = _TypeIndex(dim, epoch, self._bound(store, dim))
        owners = self._stored_owners(vec_type)
        in_file = np.fromiter(store.ids(), dtype=np.int64)
        stale = np.setdiff1d(in_file, owners["vector"])
        if len(stale):
            store.remove(stale.tolist())
        held = np.isin(owners["vector"], in_file)
        ti.hold(owners[held])
        missing = owners["vector"][~held]
        self._add_rows(ti, missing.tolist())
        ti.dirty = bool(len(stale) or len(missing))
        return ti

    def _rebuild(self, vec_type: str, epoch: int, dim: int) -> _TypeIndex:
        use = self._search_index()
        ti = _TypeIndex(dim, epoch, self._bound(use.cls(dim, **use.options), dim))
        total = self.conn.execute("SELECT COUNT(*) FROM vectors WHERE vec_type = ?", (vec_type,)).fetchone()[0]
        started, done = time.monotonic(), 0
        # Straight down the table, which is in vector-id order. Through an index on the type,
        # SQLite would then sort the rows, vectors and all: 2.4 to 3.3 s to read 200,000 rows, not 0.9 s.
        rows = self.conn.execute(
            "SELECT vector_id, chunk_id, part, n_parts, start_off, end_off, dim, data FROM vectors NOT INDEXED "
            "WHERE vec_type = ? ORDER BY vector_id",
            (vec_type,),
        )
        batch_ids: list[int] = []
        batch_info: list[tuple[int, int, int, int, int]] = []
        batch_vecs: list[np.ndarray] = []
        try:
            for r in rows:
                batch_ids.append(r[0])
                batch_info.append((r[1], r[2], r[3], r[4], r[5]))
                batch_vecs.append(from_blob(r[7], r[6]))
                if len(batch_ids) >= (4096 if done else 512):  # a small first batch: the pace is known early
                    ti.add(batch_ids, batch_info, np.stack(batch_vecs))
                    done += len(batch_ids)
                    self._progress[vec_type] = (started, done, total)  # for load_eta()
                    batch_ids, batch_info, batch_vecs = [], [], []
            if batch_ids:
                ti.add(batch_ids, batch_info, np.stack(batch_vecs))
        finally:
            self._progress.pop(vec_type, None)
        ti.dirty = True
        return ti

    def vector_search(
        self, vec_type: str, query: np.ndarray, n: int, allowed_ids: Sequence[int] | None = None
    ) -> list[VectorHit]:
        """The n best chunks for a query by one vector type. A chunk with several parts scores its
        best part. Equal scores are ordered by location. A query of zeros has no best chunks: it
        returns nothing. A type whose index is not in memory is loaded first: this waits for that."""
        while True:
            with self._vec_lock:
                ti = self._loaded(vec_type)
                if ti is not _NOT_LOADED:
                    best, owners = self._best_chunks(ti, query, n, allowed_ids)
                    break
            self._type_index(vec_type)
        parts = {chunk_id: where for _, chunk_id, *where in owners}  # part, n_parts, start_off, end_off
        ranked = self._order_ties([(c, s) for c, (s, _) in best.items()], n, higher_is_better=True)
        return [VectorHit(chunk_id, score, best[chunk_id][1], *parts[chunk_id]) for chunk_id, score in ranked]

    def _best_chunks(
        self, ti: _TypeIndex | None, query: np.ndarray, n: int, allowed_ids: Sequence[int] | None
    ) -> tuple[dict[int, tuple[float, int]], list]:
        """Under the vector lock: each chunk's best vector for a query, as chunk -> (score, vector
        id), for at least the n best chunks, and where those vectors came from."""
        if ti is None or len(ti.store) == 0 or n <= 0:
            return {}, []
        q = prepare(np.asarray(query), ti.dim)[0]
        if not q.any():
            # No direction (zeros, or numbers so large that their length overflows): every vector
            # scores 0. Ties are taken whole, here and in the index, so the search would go on
            # until it had seen every vector: the compact index read every row a dozen times.
            return {}, []
        allowed_vids = None
        if allowed_ids is not None:
            allowed = ti.vectors_of(allowed_ids)
            if not len(allowed):
                return {}, []
            if len(allowed) < len(ti.table):  # a filter that keeps every vector is no filter
                allowed_vids = allowed.tolist()
        best: dict[int, tuple[float, int]] = {}
        size = ti.vectors_for(n + 1)
        while True:
            hits = ti.store.search(q, size, allowed_vids)
            chunks = ti.find([vid for vid, _ in hits])["chunk"].tolist()
            best = {}
            for (vid, score), chunk_id in zip(hits, chunks):
                if chunk_id not in best or score > best[chunk_id][0]:
                    best[chunk_id] = (score, vid)
            if len(hits) < size:
                break  # every candidate was seen
            if len(best) > n:
                nth = sorted((s for s, _ in best.values()), reverse=True)[n - 1]
                if hits[-1][1] < nth:
                    break  # every unseen vector scores below the n-th chunk: the top n is complete
            size *= 2
        return best, ti.find([vid for _, vid in best.values()]).tolist()

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

    def save_vectors(self, *, stale: bool = False) -> None:
        """Persist the in-memory indexes that changed, with the epoch they reflect. The indexes are
        copied while holding the vector lock (fast) and written after it is released, so searches
        don't wait for the disk. Saves run one at a time; data first, note second. The note holds
        the checksum of the data: a start reads no other bytes under it (_load_saved). A backend
        that is not saved leaves no file, and is rebuilt from the stored vectors at the next start.

        Each save has a random `save_id`, written into the note and into `meta`. A start matches
        a saved index to the rows by vector id, which is right for the state of the database the
        index was saved from and for later ones only: a database that went back (an `index.db`
        put back from a copy, commits lost in a power cut) hands the same ids out again, for
        other vectors. `meta` goes back with it, so the two ids then differ and the index is
        rebuilt. The id is committed after the index is copied: a state that holds it comes after
        every row of the copy. The file is written under a temporary name first. One short
        transaction then sets the id, moves the file in place and writes the note, which also
        keeps the saves of two processes apart. A save that stops before it leaves the earlier
        file, note and id, which agree; one that stops inside it leaves those, or a file and a
        note that fail one of the two checks. Both moves are tried again for a moment where
        Windows refuses them because another handle holds the file (_replace).

        With `stale` (an update that ends by saving: the CLI's, the eval's), the files are first
        made what the next start needs, so that no search has to wait for it: `auto` picks again,
        as a start would, and a vector type whose file is missing, behind the rows, or another
        backend's is loaded, or rebuilt from the rows, and so written too."""
        if stale:
            self._load_stale()
        with self._save_lock:
            copies = []
            with self._vec_lock:
                use = self._search_index()
                for vec_type, ti in sorted(self._types.items()):
                    if not ti.dirty:
                        continue
                    note = {"epoch": ti.epoch, "dim": ti.dim, "count": len(ti.store),
                            "embedder": self.get_meta(f"vec.{vec_type}.embedder"), "database": self.database_id(),
                            "save_id": uuid.uuid4().hex, "backend": use.name, "file": self._data_path(vec_type).name}
                    if use.options:
                        note["options"] = use.options
                    copies.append((vec_type, ti.store.to_bytes(), note))
                    ti.dirty = False
            for vec_type, data, note in copies:
                old = self._noted_file(vec_type, self._read_note(vec_type))
                if data is None:
                    self._note_path(vec_type).unlink(missing_ok=True)
                else:
                    note["crc32"] = zlib.crc32(data)
                    path = self.index_dir / note["file"]
                    tmp = _temp_path(path)
                    try:
                        tmp.write_bytes(data)  # the long write: nothing a start reads has changed yet
                        with self.transaction():
                            self.set_meta(f"vec.{vec_type}.save_id", note["save_id"])
                            _replace(tmp, path)
                            _atomic_write(self._note_path(vec_type), json.dumps(note).encode("utf-8"))
                    finally:
                        tmp.unlink(missing_ok=True)
                if old is not None and old.name != (note["file"] if data is not None else None):
                    old.unlink(missing_ok=True)  # another backend's file: no note describes it any more

    def _load_stale(self) -> None:
        with self._vec_lock:
            use = self._search_index()
            if self.vector_backend == "auto":
                again = self._pick(use.name == "compact")
                if again.name != use.name:
                    log.info("search index of %s: %s from here on (%s)", self.index_dir, again.name, again.why)
                    self._in_use, use = again, again
                    self._types.clear()
                    self._generation += 1
        if use.cls.to_bytes is VectorStore.to_bytes:
            return  # a backend that is not saved
        for vec_type in self.vec_types():
            with self._vec_lock:
                current = vec_type in self._types
            if not current:
                note = self._usable_note(vec_type, self.vector_dim(vec_type))
                current = note is not None and note.get("epoch") == self._epoch(vec_type)
            if not current:
                self._type_index(vec_type)

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
            # The pragma returns a row for each page it frees, and `execute` takes only the first
            # step: one page a call. So it is called once per free page, in one transaction.
            with self.transaction() as conn:
                for _ in range(free):
                    conn.execute("PRAGMA incremental_vacuum(1)")
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
        # The keyword table keeps no text, so read back what it indexed: each field's words in order.
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.fts_words USING fts5vocab(main, fts, instance)")
        fields = ("name_tokens", "path_tokens", "signature_tokens", "doc_tokens", "body_tokens")
        column = {name: i for i, name in enumerate(fields)}
        words: dict[int, list[list[str]]] = defaultdict(lambda: [[] for _ in fields])
        for r in c.execute("SELECT doc, col, term FROM temp.fts_words ORDER BY doc, col, offset"):
            words[r[0]][column[r[1]]].append(r[2])
        fts = {
            key_of.get(doc, f"<missing chunk {doc}>"): tuple(" ".join(w) for w in per_field)
            for doc, per_field in words.items()
        }
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
