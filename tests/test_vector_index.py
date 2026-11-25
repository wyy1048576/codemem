"""What every search index shares (docs/architecture.md §5): where each vector came from, and how
many vectors a search asks its index for."""

import numpy as np
import pytest

from codemem.embedder import l2_normalize
from codemem.schema import Chunk, text_hash
from codemem.store import FaissVectorStore, Store, VectorRow, _TypeIndex, for_index

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


# ---------------------------------------------------------------- how many vectors a search asks for


def test_type_index_says_how_many_vectors_hold_the_best_chunks():
    ti = _TypeIndex(8, 0, FaissVectorStore(8))
    assert ti.vectors_for(51) == 51
    ids, info = _rows(1, 10)
    ti.add(ids, info, _vecs(10, dim=8))
    assert ti.vectors_for(51) == 102  # two vectors a chunk: twice as many vectors as chunks wanted
    ti.remove([2, 3])
    ti.add([20, 21, 22], [(200, 0, 1, 0, 1), (201, 0, 1, 0, 1), (202, 0, 1, 0, 1)], _vecs(3, dim=8))
    assert ti.vectors_for(51) == 81  # 11 vectors that count as 7 chunks: 8 halves of two-part chunks, 3 whole ones
    ti.remove(range(1, 11))
    assert ti.vectors_for(51) == 51  # one vector a chunk: as many vectors as chunks


def test_one_backend_search_is_enough_when_chunks_have_several_vectors(tmp_path):
    """The store asks for more vectors than chunks when chunks have parts, so that the best n
    chunks are complete at once; it still asks again when they are not."""
    store = Store(tmp_path / "idx", vector_backend="faiss")
    ids = _add_chunks(store, 200)
    v = _vecs(400, seed=6)
    v[1::2] = l2_normalize(v[::2] + 0.05 * v[1::2])  # the two parts of a chunk lie close together
    rows = [VectorRow(c, part, 2, 0, 1, f"h{c}.{part}") for c in ids for part in range(2)]
    store.put_vectors("code", EMBEDDER, rows, v)
    ti = store._type_index("code")
    asked: list[int] = []
    search = ti.store.search
    ti.store.search = lambda q, k, allowed=None: asked.append(k) or search(q, k, allowed)

    def best_chunks(q, n):
        scores = (for_index(v, 16) @ for_index(q, 16)[0]).reshape(200, 2).max(axis=1)
        return [ids[i] for i in np.argsort(-scores)[:n]]

    q = _vecs(1, seed=1000)[0]
    assert [h.chunk_id for h in store.vector_search("code", q, 10)] == best_chunks(q, 10)
    assert asked == [22]  # 11 chunks of two vectors each
    asked.clear()
    many = np.repeat(v[:1], 30, axis=0) + 1e-3 * _vecs(30, seed=8)
    store.put_vectors("code", EMBEDDER, [VectorRow(ids[0], part, 30, 0, 1, f"x{part}") for part in range(30)], many)
    hits = store.vector_search("code", v[0], 10)  # 30 parts of one chunk lead: one search is not enough
    assert hits[0].chunk_id == ids[0] and len({h.chunk_id for h in hits}) == 10 and len(asked) > 1 and asked[0] == 24
    store.close()
