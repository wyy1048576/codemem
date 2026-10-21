import json

import numpy as np
import pytest

from codemem.embedder import l2_normalize
from codemem.schema import Chunk, text_hash
from codemem.store import FaissVectorStore, IndexLock, Store
from codemem.tokenize import fts_match_query


def _chunk(name, path="pkg/mod.py", code=None, calls=()):
    code = code or f"def {name}():\n    return 1"
    return Chunk(
        key=f"{path}::{name}", path=path, qualname=name, name=name, kind="function",
        start_line=1, end_line=2, signature=f"def {name}():", docstring="", code=code,
        content_hash=text_hash(code), calls=list(calls),
    )


def _vecs(n, dim=8, seed=0):
    return l2_normalize(np.random.default_rng(seed).normal(size=(n, dim)))


def _in_sync(store, vec_type):
    vs = store.vectors(vec_type)
    rows = set(store.embedding_hashes(vec_type))
    chunk_ids = {c.chunk_id for c in store.iter_chunks()}
    return (vs.ids() if vs else set()) == rows and rows <= chunk_ids


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "idx")
    yield s
    s.close()


def test_faiss_vector_store_upsert_remove_search_filter():
    vs = FaissVectorStore(8)
    v = _vecs(4)
    vs.upsert([10, 20, 30, 40], v)
    assert vs.ids() == {10, 20, 30, 40}
    assert vs.search(v[2], 1)[0][0] == 30
    vs.upsert([30], v[0:1])  # update in place, no duplicate
    assert len(vs) == 4 and vs.search(v[0], 2)[0][0] in (10, 30)
    vs.remove([10])
    assert vs.ids() == {20, 30, 40}
    assert [i for i, _ in vs.search(v[3], 4, allowed_ids=[20, 30])] and all(
        i in (20, 30) for i, _ in vs.search(v[3], 4, allowed_ids=[20, 30])
    )
    assert vs.search(v[3], 4, allowed_ids=[]) == []
    with pytest.raises(ValueError):
        vs.upsert([1], _vecs(1, dim=4))


def test_chunk_upsert_keeps_id_and_refreshes_fts_and_calls(store):
    with store.transaction():
        cid = store.upsert_chunk(_chunk("revoke_session", calls=["delete"]))
    with store.transaction():
        cid2 = store.upsert_chunk(_chunk("revoke_session", code="def revoke_session():\n    purge()", calls=["purge"]))
    assert cid == cid2
    assert store.all_calls() == [(cid, "purge")]
    assert store.bm25_search(fts_match_query("purge"), 10, (10, 5, 1)) == [cid]
    assert store.bm25_search(fts_match_query("return"), 10, (10, 5, 1)) == []


def test_add_update_delete_keeps_sqlite_and_faiss_in_sync(store):
    with store.transaction():
        ids = [store.upsert_chunk(_chunk(n)) for n in ("a", "b", "c")]
        store.put_embeddings("code", "fake:8", ids, ["h1", "h2", "h3"], _vecs(3))
    store.save_vectors()
    assert _in_sync(store, "code")

    with store.transaction():  # update one vector
        store.put_embeddings("code", "fake:8", [ids[1]], ["h2b"], _vecs(1, seed=5))
    assert store.embedding_hashes("code")[ids[1]] == "h2b" and _in_sync(store, "code")

    with store.transaction():  # delete a chunk -> row, FTS, vector all gone
        store.delete_chunks([ids[0]])
    assert _in_sync(store, "code") and store.get_chunk(ids[0]) is None
    assert store.bm25_search('"a"', 10, (10, 5, 1)) == []

    with store.transaction():
        store.remove_embeddings("code", [ids[2]])
    assert _in_sync(store, "code") and store.vectors("code").ids() == {ids[1]}

    with store.transaction():
        store.delete_file("pkg/mod.py")
    assert _in_sync(store, "code") and store.counts()["chunks"] == 0


def test_persistence_and_reconcile_after_interrupted_update(tmp_path):
    s = Store(tmp_path / "idx")
    with s.transaction():
        ids = [s.upsert_chunk(_chunk(n)) for n in ("a", "b")]
        s.put_embeddings("code", "fake:8", ids, ["h1", "h2"], _vecs(2))
    s.save_vectors()
    # Simulate a crash: an updated hash is committed to SQLite but the FAISS file is never saved.
    with s.transaction():
        s.put_embeddings("code", "fake:8", [ids[0]], ["h1-new"], _vecs(1, seed=3))
    s.close()

    s2 = Store(tmp_path / "idx")
    assert s2.vectors("code").ids() == set(ids)
    assert s2.reconcile() == {"code": 1}
    assert s2.embedding_hashes("code") == {ids[1]: "h2"}  # a is re-embedded next update
    s2.close()


def test_reconcile_distrusts_mismatched_sidecar(tmp_path):
    s = Store(tmp_path / "idx")
    with s.transaction():
        ids = [s.upsert_chunk(_chunk(n)) for n in ("a", "b")]
        s.put_embeddings("code", "fake:8", ids, ["h1", "h2"], _vecs(2))
    s.save_vectors()
    (tmp_path / "idx" / "vec_code.ids.json").write_text(json.dumps({str(ids[0]): "h1"}))
    s.close()
    s2 = Store(tmp_path / "idx")
    assert s2.reconcile() == {"code": 2}
    assert s2.embedding_hashes("code") == {}
    s2.close()


def test_model_change_rebuilds_only_that_vec_type(store):
    with store.transaction():
        cid = store.upsert_chunk(_chunk("a"))
        store.ensure_vec_type("code", "fake:8")
        store.ensure_vec_type("usage", "fake:8")
        store.put_embeddings("code", "fake:8", [cid], ["h"], _vecs(1))
        store.put_embeddings("usage", "fake:8", [cid], ["u"], _vecs(1))
    store.save_vectors()
    with store.transaction():
        assert store.ensure_vec_type("code", "fake:8") is False
        assert store.ensure_vec_type("code", "other-model") is True
    assert store.embedding_hashes("code") == {} and store.vectors("code") is None
    assert store.embedding_hashes("usage") == {cid: "u"}


def test_path_prefix_filters_and_like_escaping(store):
    with store.transaction():
        a = store.upsert_chunk(_chunk("run_job", path="src/jobs/run.py"))
        b = store.upsert_chunk(_chunk("run_job", path="src/jobs_old/run.py"))
        c = store.upsert_chunk(_chunk("run_job", path="tests/test_run.py"))
    assert set(store.ids_with_prefix("src/")) == {a, b}
    assert store.ids_with_prefix("src/jobs/") == [a]
    assert store.ids_with_prefix("src\\jobs_") == [b]  # '_' is literal, backslashes normalized
    assert store.bm25_search('"run_job"', 10, (10, 5, 1), path_prefix="./tests") == [c]


def test_find_chunk_at_prefers_innermost(store):
    outer = _chunk("outer")
    outer.start_line, outer.end_line = 1, 10
    inner = _chunk("outer.inner")
    inner.start_line, inner.end_line = 3, 5
    with store.transaction():
        store.upsert_chunk(outer)
        iid = store.upsert_chunk(inner)
    assert store.find_chunk_at("pkg/mod.py", 4).chunk_id == iid
    assert store.find_chunk_at("pkg\\mod.py", 8).qualname == "outer"
    assert store.find_chunk_at("pkg/mod.py", 99) is None


def test_transaction_rollback(store):
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.upsert_chunk(_chunk("a"))
            raise RuntimeError
    assert store.counts()["chunks"] == 0


def test_index_lock_is_exclusive(tmp_path):
    with IndexLock(tmp_path):
        other = IndexLock(tmp_path)
        with pytest.raises(TimeoutError):
            other.acquire(timeout=0.2)
    with IndexLock(tmp_path):  # released -> acquirable again
        pass
