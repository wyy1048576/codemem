import json
import numpy as np
import pytest

from codemem.embedder import l2_normalize
from codemem.schema import Chunk, text_hash
from codemem.store import SCHEMA_VERSION, ChunkFilter, FaissVectorStore, IndexLock, Store, VectorRow
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
    """The search index holds exactly the stored rows, and every row belongs to a chunk."""
    rows = {vid for vid, _ in store.vector_rows(vec_type).values()}
    ti = store._type_index(vec_type)
    chunk_ids = {c.chunk_id for c in store.iter_chunks()}
    owners = {cid for cid, _ in store.vector_rows(vec_type)}
    return (ti.store.ids() if ti else set()) == rows and owners <= chunk_ids


def _rows(ids, hashes, parts=None):
    parts = parts or [0] * len(ids)
    return [VectorRow(i, p, 1, 0, 1, h) for i, p, h in zip(ids, parts, hashes)]


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
    assert store.all_calls() == [(cid, "purge", "python")]
    assert store.bm25_search(fts_match_query("purge"), 10, (10, 5, 1)) == [cid]
    assert store.bm25_search(fts_match_query("return"), 10, (10, 5, 1)) == []


def test_add_update_delete_keeps_sqlite_and_faiss_in_sync(store):
    with store.transaction():
        ids = [store.upsert_chunk(_chunk(n)) for n in ("a", "b", "c")]
        store.put_vectors("code", "fake:8|doc", _rows(ids, ["h1", "h2", "h3"]), _vecs(3))
    store.save_vectors()
    assert _in_sync(store, "code") and len(store.vector_rows("code")) == 3

    store.put_vectors("code", "fake:8|doc", _rows([ids[1]], ["h2b"]), _vecs(1, seed=5))  # replace one
    assert store.vector_rows("code")[(ids[1], 0)][1] == "h2b" and _in_sync(store, "code")

    with store.transaction():  # delete a chunk -> row, FTS, vector all gone
        store.delete_chunks([ids[0]])
    assert _in_sync(store, "code") and store.get_chunk(ids[0]) is None
    assert store.bm25_search('"a"', 10, (10, 5, 1)) == []

    vid = store.vector_rows("code")[(ids[2], 0)][0]
    store.delete_vectors("code", [vid])
    assert _in_sync(store, "code") and set(store.vector_rows("code")) == {(ids[1], 0)}

    with store.transaction():
        store.delete_file("pkg/mod.py")
    assert _in_sync(store, "code") and store.counts()["chunks"] == 0


def test_a_rolled_back_transaction_leaves_the_search_index_alone(store):
    with store.transaction():
        cid = store.upsert_chunk(_chunk("a"))
    store.put_vectors("code", "fake:8|doc", _rows([cid], ["h"]), _vecs(1))
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.put_vectors("code", "fake:8|doc", _rows([cid], ["h-new"]), _vecs(1, seed=9))
            raise RuntimeError
    assert store.vector_rows("code")[(cid, 0)][1] == "h" and _in_sync(store, "code")


def test_crash_before_saving_the_search_index_is_repaired_from_the_rows(tmp_path):
    s = Store(tmp_path / "idx")
    with s.transaction():
        ids = [s.upsert_chunk(_chunk(n)) for n in ("a", "b")]
    s.put_vectors("code", "fake:8|doc", _rows(ids, ["h1", "h2"]), _vecs(2))
    s.save_vectors()
    # A change is committed, but the process dies before the search index is saved again.
    s.put_vectors("code", "fake:8|doc", _rows([ids[0]], ["h1-new"]), _vecs(1, seed=3))
    s.close()

    s2 = Store(tmp_path / "idx")
    assert _in_sync(s2, "code")  # rebuilt from the rows: no model needed, nothing re-embedded
    hit = s2.vector_search("code", _vecs(1, seed=3)[0], 1)[0]
    assert (hit.chunk_id, round(hit.score, 2)) == (ids[0], 1.0)
    s2.close()


def test_a_corrupt_index_file_is_rebuilt(tmp_path):
    s = Store(tmp_path / "idx")
    with s.transaction():
        cid = s.upsert_chunk(_chunk("a"))
    s.put_vectors("code", "fake:8|doc", _rows([cid], ["h"]), _vecs(1))
    s.save_vectors()
    s.close()
    (tmp_path / "idx" / "vec_code.faiss").write_bytes(b"garbage")
    s2 = Store(tmp_path / "idx")
    assert [h.chunk_id for h in s2.vector_search("code", _vecs(1)[0], 1)] == [cid]
    s2.close()


def test_embedder_change_drops_only_that_vec_type(store):
    with store.transaction():
        cid = store.upsert_chunk(_chunk("a"))
        assert store.ensure_vec_type("code", "fake:8|doc") is False
        assert store.ensure_vec_type("usage", "fake:8|doc") is False
    store.put_vectors("code", "fake:8|doc", _rows([cid], ["h"]), _vecs(1))
    store.put_vectors("usage", "fake:8|doc", _rows([cid], ["u"]), _vecs(1))
    with store.transaction():
        assert store.ensure_vec_type("code", "fake:8|doc") is False
        assert store.ensure_vec_type("code", "other-model|doc") is True
    assert store.vector_rows("code") == {} and store.vector_search("code", _vecs(1)[0], 5) == []
    assert set(store.vector_rows("usage")) == {(cid, 0)}


def test_matryoshka_dim_change_keeps_the_vectors(store):
    with store.transaction():
        cid = store.upsert_chunk(_chunk("a"))
        store.ensure_vec_type("code", "fake:8|doc", None)
    store.put_vectors("code", "fake:8|doc", _rows([cid], ["h"]), _vecs(1))
    assert store.vector_dim("code") == 8
    with store.transaction():
        assert store.ensure_vec_type("code", "fake:8|doc", 4) is False  # nothing to re-embed
    assert store.vector_dim("code") == 4 and set(store.vector_rows("code")) == {(cid, 0)}
    hit = store.vector_search("code", _vecs(1)[0], 1)[0]  # a full-size query is truncated too
    assert hit.chunk_id == cid and store._type_index("code").dim == 4


def test_long_chunks_score_by_their_best_window(store):
    with store.transaction():
        long_id = store.upsert_chunk(_chunk("long"))
        short_id = store.upsert_chunk(_chunk("short"))
    v = _vecs(3, seed=4)
    rows = [VectorRow(long_id, 0, 2, 0, 9, "p0"), VectorRow(long_id, 1, 2, 8, 20, "p1"), VectorRow(short_id, 0, 1, 0, 1, "s")]
    store.put_vectors("code", "fake:8|doc", rows, v)
    hits = store.vector_search("code", v[1], 2)
    assert [h.chunk_id for h in hits] == [long_id, short_id]  # one result per chunk
    assert (hits[0].part, hits[0].n_parts, hits[0].start_off, hits[0].end_off) == (1, 2, 8, 20)


def test_find_vectors_reuses_equal_texts(store):
    with store.transaction():
        cid = store.upsert_chunk(_chunk("a"))
    v = _vecs(1)
    store.put_vectors("code", "fake:8|doc", _rows([cid], ["same"]), v)
    found = store.find_vectors("fake:8|doc", ["same", "other"])
    assert set(found) == {"same"} and np.allclose(found["same"], v[0], atol=1e-3)
    assert store.find_vectors("another-embedder|doc", ["same"]) == {}


def test_an_older_index_is_rebuilt_for_the_current_schema(tmp_path):
    import sqlite3

    idx = tmp_path / "idx"
    idx.mkdir()
    conn = sqlite3.connect(idx / "index.db")
    conn.executescript(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "INSERT INTO meta VALUES ('schema_version', '1');"
        "CREATE TABLE chunks (chunk_id INTEGER PRIMARY KEY, key TEXT);"
        "CREATE TABLE embeddings (chunk_id INTEGER, vec_type TEXT, text_hash TEXT, model TEXT);"
    )
    conn.commit()
    conn.close()
    (idx / "vec_code.faiss").write_bytes(b"old")
    (idx / "cmeval-built").write_text("")  # files of other tools stay
    s = Store(idx)
    assert s.get_meta("schema_version") == SCHEMA_VERSION and s.counts()["chunks"] == 0
    assert not (idx / "vec_code.faiss").exists() and (idx / "cmeval-built").exists()
    s.close()


def test_a_newer_index_is_refused_not_wiped(tmp_path):
    """A newer codemem may still be using the index: wiping it would destroy its work."""
    idx = tmp_path / "idx"
    s = Store(idx)
    with s.transaction():
        s.upsert_chunk(_chunk("keep_me"))
        s.set_meta("schema_version", SCHEMA_VERSION + 1)
    s.close()
    with pytest.raises(RuntimeError, match="newer codemem"):
        Store(idx)
    import sqlite3

    conn = sqlite3.connect(idx / "index.db")
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 1
    conn.close()


def test_chunk_filter(store):
    with store.transaction():
        a = store.upsert_chunk(_chunk("run_job", path="src/jobs/run.py"))
        t = _chunk("test_run_job", path="tests/test_run.py")
        t.is_test = True
        b = store.upsert_chunk(t)
        c = _chunk("Job", path="src/jobs/job.go")
        c.kind, c.language = "class", "go"
        c_id = store.upsert_chunk(c)
    assert set(store.filter_ids(ChunkFilter(exclude_tests=True))) == {a, c_id}
    assert store.filter_ids(ChunkFilter(kinds=("class",))) == [c_id]
    assert store.filter_ids(ChunkFilter(languages=("python",), path_prefix="tests/")) == [b]
    hits = store.bm25_search(fts_match_query("run job"), 10, (10, 3, 5, 2, 1), flt=ChunkFilter(exclude_tests=True))
    assert a in hits and b not in hits


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


def _seed(store, names, seed=0):
    with store.transaction():
        ids = [store.upsert_chunk(_chunk(n)) for n in names]
        store.ensure_vec_type("code", "fake|doc")
    store.put_vectors("code", "fake|doc", _rows(ids, [f"h{n}" for n in names]), _vecs(len(ids), seed=seed))
    return ids


def test_another_process_writes_and_this_one_catches_up(tmp_path):
    """A second Store on the same folder stands in for another process: after its write, the first
    one applies only the difference to its loaded index instead of rebuilding it."""
    a, b = Store(tmp_path / "idx"), Store(tmp_path / "idx")
    _seed(a, ["one", "two"])
    loaded = b._type_index("code")
    assert len(loaded.store) == 2
    ids = _seed(a, ["three"], seed=1)
    ti = b._type_index("code")
    assert ti is loaded and len(ti.store) == 3 and _in_sync(b, "code")  # caught up, not rebuilt
    hit = b.vector_search("code", _vecs(1, seed=1)[0], 1)[0]
    assert hit.chunk_id == ids[0]
    a.close(), b.close()


def test_a_saved_index_is_reconciled_with_the_rows(tmp_path):
    """A file saved at an older epoch (another process, a crash, a lazy save), even under a newer
    note, is brought up to the committed rows by vector id: it serves exactly what a rebuild would."""
    s = Store(tmp_path / "idx")
    _seed(s, ["one", "two"])
    s.save_vectors()
    old_faiss = (tmp_path / "idx" / "vec_code.faiss").read_bytes()
    vid = next(iter(s.vector_rows("code").values()))[0]
    s.delete_vectors("code", [vid])
    _seed(s, ["three"], seed=2)  # same count as before, different ids
    s.save_vectors()
    s.close()
    (tmp_path / "idx" / "vec_code.faiss").write_bytes(old_faiss)  # older data under a newer note
    s2 = Store(tmp_path / "idx")
    assert _in_sync(s2, "code")
    q = _vecs(1, seed=2)[0]
    hits = [(h.chunk_id, round(h.score, 5)) for h in s2.vector_search("code", q, 3)]
    s2.close()
    for f in (tmp_path / "idx").glob("vec_code.*"):
        f.unlink()
    s3 = Store(tmp_path / "idx")  # no saved file: a full rebuild from the rows
    assert [(h.chunk_id, round(h.score, 5)) for h in s3.vector_search("code", q, 3)] == hits
    s3.close()


def test_searches_during_writes_never_see_a_half_patched_index(tmp_path):
    import threading

    s = Store(tmp_path / "idx")
    _seed(s, [f"f{i}" for i in range(20)])
    errors: list[BaseException] = []
    stop = threading.Event()

    def search():
        try:
            while not stop.is_set():
                s.vector_search("code", _vecs(1, seed=5)[0], 5)
        except BaseException as e:  # noqa: BLE001 - any error fails the test
            errors.append(e)
        finally:
            s.close_thread_conn()

    t = threading.Thread(target=search)
    t.start()
    try:
        for i in range(40):
            vids = [vid for vid, _ in s.vector_rows("code").values()][:2]
            s.delete_vectors("code", vids)
            _seed(s, [f"g{i}a", f"g{i}b"], seed=i)
    finally:
        stop.set()
        t.join()
    assert errors == [] and _in_sync(s, "code")
    s.close()


def _while_another_thread_holds_its_connection(open_conn, close, use):
    """Another thread takes its connection (as it does at the start of a query), then `close`
    runs. That connection must stay usable: closing it mid-query crashes the process."""
    import threading

    took, closed, result = threading.Event(), threading.Event(), {}

    def other():
        conn = open_conn()
        took.set()
        closed.wait(5)
        try:
            result["value"] = use(conn)
        except Exception as e:  # what the old close() caused: "Cannot operate on a closed database"
            result["error"] = repr(e)

    t = threading.Thread(target=other)
    t.start()
    assert took.wait(5)
    close()
    closed.set()
    t.join(5)
    assert "error" not in result, result["error"]


def test_closing_the_store_leaves_a_running_thread_its_connection(tmp_path):
    s = Store(tmp_path / "idx")
    _while_another_thread_holds_its_connection(
        lambda: s.conn, s.close, lambda conn: conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    )
    assert s.get_meta("schema_version") == SCHEMA_VERSION  # the closing thread can still use the store


def test_closing_the_vector_cache_leaves_a_running_thread_its_connection(tmp_path):
    from codemem.vectorcache import VectorCache

    cache = VectorCache(tmp_path / "cache.db")
    _while_another_thread_holds_its_connection(
        cache._conn, cache.close, lambda conn: conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
    )
    cache.put_many("e", ["h"], np.ones((1, 4), dtype=np.float32))
    assert cache.count("e") == 1
