"""What every search index shares (docs/architecture.md §5): where each vector came from."""

import numpy as np
import pytest

from codemem.embedder import l2_normalize
from codemem.schema import Chunk, text_hash
from codemem.store import FaissVectorStore, Store, VectorRow, _TypeIndex

EMBEDDER = "fake|doc"


def _chunk(name, path="pkg/mod.py"):
    code = f"def {name}():\n    return 1"
    return Chunk(
        key=f"{path}::{name}", path=path, qualname=name, name=name, kind="function",
        start_line=1, end_line=2, signature=f"def {name}():", docstring="", code=code,
        content_hash=text_hash(code),
    )


def _vecs(n, dim=16, seed=0):
    return l2_normalize(np.random.default_rng(seed).normal(size=(n, dim)))


def _add_chunks(store, n):
    with store.transaction():
        ids = [store.upsert_chunk(_chunk(f"f{i:03d}")) for i in range(n)]
        store.ensure_vec_type("code", EMBEDDER)
    return ids


def _seed(store, n):
    """n chunks with one vector each; returns the chunk ids."""
    ids = _add_chunks(store, n)
    store.put_vectors("code", EMBEDDER, [VectorRow(c, 0, 1, 0, 1, f"h{c}") for c in ids], _vecs(n))
    return ids


def _rows(first, n, chunk0=100):
    """n vector ids from `first`, two to a chunk, and their (chunk, part, n_parts, start_off, end_off)."""
    info = [(chunk0 + i // 2, i % 2, 2, 10 * (i % 2), 10 * (i % 2) + 9) for i in range(n)]
    return list(range(first, first + n)), info


# ---------------------------------------------------------------- where each vector came from


def test_type_index_finds_vectors_and_chunks_in_32_bytes_a_vector():
    ti = _TypeIndex(8, 0, FaissVectorStore(8))
    ids, info = _rows(1, 10)
    ti.add(ids, info, _vecs(10, dim=8))
    assert ti.table.dtype.itemsize == 32 and ti.table.nbytes == 320 and ti.store.ids() == set(ids)
    assert ti.find([7, 2, 2]).tolist() == [(7, 103, 0, 2, 0, 9), (2, 100, 1, 2, 10, 19), (2, 100, 1, 2, 10, 19)]
    assert ti.find([]).tolist() == [] and ti.vectors_of([]).tolist() == []
    assert ti.vectors_of([104, 100, 999]).tolist() == [1, 2, 9, 10]
    for missing in ([11], [0], [5, 99]):
        with pytest.raises(KeyError):
            ti.find(missing)
    ti.remove([2, 3, 999])  # an id it does not hold is ignored
    assert ti.table["vector"].tolist() == [1, 4, 5, 6, 7, 8, 9, 10] and ti.store.ids() == {1, 4, 5, 6, 7, 8, 9, 10}
    assert ti.vectors_of([100, 101]).tolist() == [1, 4]
    ti.remove(range(1, 11))
    assert len(ti.table) == 0 and len(ti.store) == 0
    with pytest.raises(KeyError):
        ti.find([1])


def test_type_index_keeps_its_table_sorted_when_older_ids_arrive_later():
    """A saved index or a catch-up can bring rows older than the newest held."""
    ti = _TypeIndex(8, 0, FaissVectorStore(8))
    v = _vecs(12, dim=8)
    ti.add([50, 60], [(1, 0, 1, 0, 1), (2, 0, 1, 0, 1)], v[:2])
    ti.hold(np.array([(40, 3, 0, 1, 0, 1), (10, 4, 0, 1, 0, 1)], dtype=ti.table.dtype))  # held by the backend already
    ti.add([55, 5], [(5, 0, 1, 0, 1), (6, 0, 1, 0, 1)], v[2:4])
    assert ti.table["vector"].tolist() == [5, 10, 40, 50, 55, 60]
    assert ti.find([55, 5, 40])["chunk"].tolist() == [5, 6, 3]
    ti.add([50], [(9, 1, 2, 3, 4)], v[4:5])  # an id added again keeps its newest row
    assert ti.table["vector"].tolist() == [5, 10, 40, 50, 55, 60] and ti.find([50]).tolist() == [(50, 9, 1, 2, 3, 4)]
    assert ti.vectors_of([1]).tolist() == [] and ti.vectors_of([9]).tolist() == [50]


def test_a_search_asks_the_backend_for_plain_lists(tmp_path):
    """Plugins get what they always got: lists of ints, and no filter when a filter keeps everything."""
    seen = []

    class Recording(FaissVectorStore):
        def search(self, query, k, allowed_ids=None):
            seen.append(allowed_ids)
            return super().search(query, k, allowed_ids)

    store = Store(tmp_path / "idx", vector_backend="faiss")
    ids = _seed(store, 6)
    store._backend = Recording
    store._types.clear()
    q = _vecs(1, seed=3)[0]
    assert len(store.vector_search("code", q, 3, ids[:2])) == 2 and len(store.vector_search("code", q, 3, ids)) == 3
    assert type(seen[0]) is list and all(type(i) is int for i in seen[0]) and seen[1] is None
    store.close()
