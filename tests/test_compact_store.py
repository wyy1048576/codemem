"""The compact search index (docs/architecture.md §5).

First the scenarios of the vector store on both backends, each held to a brute-force search over
the stored rows. Then what only the compact index does: candidates from codes and scores from
the rows, its saved file, and the checks in front of every FAISS call.
"""

import json
import logging
import sqlite3
import threading

import faiss
import numpy as np
import pytest

from codemem.config import COMPACT_MAX_DIM, Config, config_from_dict
from codemem.embedder import l2_normalize
from codemem.indexer import Indexer
from codemem.schema import Chunk, text_hash
from codemem.service import CodememService
from codemem.store import (
    CompactVectorStore,
    FaissVectorStore,
    Store,
    VectorRow,
    for_index,
    prepare,
    vector_backend_class,
)

EMBEDDER = "fake|doc"
COMPACT = {"bits": 4, "dim": 0, "rescore": 200}
BACKENDS = {"faiss": {}, "compact": COMPACT}


def _chunk(name, path="pkg/mod.py"):
    code = f"def {name}():\n    return 1"
    return Chunk(
        key=f"{path}::{name}", path=path, qualname=name, name=name, kind="function",
        start_line=1, end_line=2, signature=f"def {name}():", docstring="", code=code,
        content_hash=text_hash(code),
    )


def _vecs(n, dim=16, seed=0):
    return l2_normalize(np.random.default_rng(seed).normal(size=(n, dim)))


def _open(path, backend, **options):
    return Store(path, vector_backend=backend, vector_options={**BACKENDS[backend], **options})


def _add_chunks(store, names):
    with store.transaction():
        ids = [store.upsert_chunk(_chunk(n)) for n in names]
        store.ensure_vec_type("code", EMBEDDER)
    return ids


def _seed(store, n, dim=16, seed=0, prefix="f"):
    """n chunks with one vector each; returns the chunk ids."""
    ids = _add_chunks(store, [f"{prefix}{i:04d}" for i in range(n)])
    store.put_vectors("code", EMBEDDER, [VectorRow(c, 0, 1, 0, 1, f"h{c}") for c in ids], _vecs(n, dim, seed))
    return ids


def _brute(store, query, n, allowed=None):
    """The n best chunks by a full pass over the stored rows: (chunk id, score, part), best first."""
    dim = store.vector_dim("code")
    q = prepare(np.asarray(query), dim)[0]
    best: dict[int, tuple[float, int]] = {}
    rows = store.conn.execute("SELECT chunk_id, part, dim, data FROM vectors WHERE vec_type = 'code'")
    for chunk_id, part, full, data in rows:
        if allowed is not None and chunk_id not in allowed:
            continue
        score = float((for_index(np.frombuffer(data, dtype=np.float16, count=full), dim)[0] * q).sum())
        if chunk_id not in best or score > best[chunk_id][0]:
            best[chunk_id] = (score, part)
    ranked = sorted(best.items(), key=lambda item: (-item[1][0], item[0]))[:n]
    return [(chunk_id, score, part) for chunk_id, (score, part) in ranked]


def _same_as_brute_force(store, n_values=(1, 5, 1000), allowed=None, seeds=range(3), dim=16):
    for seed in seeds:
        q = _vecs(1, dim, seed=1000 + seed)[0]
        for n in n_values:
            hits = store.vector_search("code", q, n, allowed)
            want = _brute(store, q, n, None if allowed is None else set(allowed))
            assert [h.chunk_id for h in hits] == [c for c, _, _ in want]
            assert [h.score for h in hits] == pytest.approx([s for _, s, _ in want], abs=1e-5)
            assert [h.part for h in hits] == [p for _, _, p in want]
    return True


def _in_sync(store):
    ti = store._type_index("code")
    rows = {vid for vid, _ in store.vector_rows("code").values()}
    return (ti.store.ids() if ti else set()) == rows and set(ti.table["vector"].tolist() if ti else ()) == rows


@pytest.fixture(params=sorted(BACKENDS))
def backend(request):
    return request.param


@pytest.fixture
def store(tmp_path, backend):
    s = _open(tmp_path / "idx", backend)
    yield s
    s.close()


# ---------------------------------------------------------------- the same scenarios on both backends


def test_adds_replaces_and_deletes_match_a_full_pass_over_the_rows(store):
    ids = _seed(store, 60)
    assert _same_as_brute_force(store) and _in_sync(store)
    store.put_vectors("code", EMBEDDER, [VectorRow(c, 0, 1, 0, 1, f"new{c}") for c in ids[:10]], _vecs(10, seed=7))
    assert _same_as_brute_force(store) and _in_sync(store)  # replaced in place: no second vector per chunk
    assert len(store._type_index("code").store) == 60
    gone = [store.vector_rows("code")[(c, 0)][0] for c in ids[10:15]]
    store.delete_vectors("code", gone)
    with store.transaction():
        store.delete_chunks(ids[15:25])
    assert _same_as_brute_force(store) and _in_sync(store)
    assert len(store._type_index("code").store) == 45
    _seed(store, 5, seed=9, prefix="g")
    assert _same_as_brute_force(store) and _in_sync(store)


def test_a_chunk_filter_keeps_only_its_chunks(store):
    ids = _seed(store, 60)
    for allowed in (ids[:1], ids[::10], ids[::2], ids, ids[5:8] + [10**9]):
        assert _same_as_brute_force(store, allowed=allowed)
    q = _vecs(1, seed=3)[0]
    assert store.vector_search("code", q, 5, []) == [] and store.vector_search("code", q, 5, [10**9]) == []


def test_a_chunk_with_several_vectors_scores_its_best_part(store):
    ids = _add_chunks(store, [f"f{i:02d}" for i in range(30)])
    rows = [VectorRow(c, part, 3, 10 * part, 10 * part + 9, f"h{c}.{part}") for c in ids[:10] for part in range(3)]
    rows += [VectorRow(c, 0, 1, 0, 1, f"h{c}") for c in ids[10:]]
    store.put_vectors("code", EMBEDDER, rows, _vecs(len(rows)))
    assert _same_as_brute_force(store, n_values=(1, 3, 10, 29, 30, 50))
    assert _same_as_brute_force(store, n_values=(4,), allowed=ids[:6])
    hit = store.vector_search("code", _vecs(len(rows))[4], 1)[0]  # the second part of the second chunk
    assert (hit.chunk_id, hit.part, hit.n_parts, hit.start_off, hit.end_off) == (ids[1], 1, 3, 10, 19)
    assert all(type(x) is int for x in (hit.chunk_id, hit.vector_id, hit.part, hit.n_parts, hit.start_off, hit.end_off))


def test_restart_from_the_saved_file(tmp_path, backend, monkeypatch):
    s = _open(tmp_path / "idx", backend)
    ids = _seed(s, 40)
    s.save_vectors()
    s.close()
    note = json.loads((tmp_path / "idx" / "vec_code.json").read_text())
    suffix = {"faiss": ".faiss", "compact": ".rabitq"}[backend]
    assert note["backend"] == backend and note["file"] == f"vec_code{suffix}" and note["count"] == 40
    assert note.get("options", {}) == BACKENDS[backend]
    assert {p.name for p in (tmp_path / "idx").glob("vec_*")} == {"vec_code.json", f"vec_code{suffix}"}

    monkeypatch.setattr(Store, "_rebuild", lambda *a: pytest.fail("the saved file should have been used"))
    s2 = _open(tmp_path / "idx", backend)
    assert _same_as_brute_force(s2) and _in_sync(s2) and not s2.vectors_unsaved()
    s2.delete_vectors("code", [s2.vector_rows("code")[(ids[0], 0)][0]])  # the loaded index takes edits
    _seed(s2, 3, seed=5, prefix="g")
    assert _same_as_brute_force(s2) and _in_sync(s2) and s2.vectors_unsaved()
    s2.close()

    s3 = _open(tmp_path / "idx", backend)  # the file is behind the rows: it catches up by vector id
    assert _same_as_brute_force(s3) and _in_sync(s3) and len(s3._type_index("code").store) == 42
    s3.close()


def test_a_damaged_file_is_rebuilt_from_the_rows(tmp_path, backend, monkeypatch, caplog):
    """The note holds the checksum of the file, and a file with other bytes is not handed to the
    backend: FAISS reads an exact index with one flipped bit as it is, and scores with it."""
    s = _open(tmp_path / "idx", backend)
    _seed(s, 20)
    s.save_vectors()
    s.close()
    path = tmp_path / "idx" / json.loads((tmp_path / "idx" / "vec_code.json").read_text())["file"]
    saved = path.read_bytes()
    one_bit = bytearray(saved)
    one_bit[len(saved) // 2] ^= 0x40  # in a stored number
    cls = {"faiss": FaissVectorStore, "compact": CompactVectorStore}[backend]
    rebuilds = []
    rebuild = Store._rebuild
    with monkeypatch.context() as m:
        m.setattr(Store, "_rebuild", lambda self, *a: rebuilds.append(a) or rebuild(self, *a))
        m.setattr(cls, "from_bytes", lambda *a, **k: pytest.fail("the backend must not be given these bytes"))
        for n, damaged in enumerate((b"garbage", saved[:-9], b"", bytes(one_bit), saved + b"\0"), 1):
            path.write_bytes(damaged)
            caplog.clear()
            with caplog.at_level(logging.WARNING, logger="codemem.store"):
                s2 = _open(tmp_path / "idx", backend)
                assert _same_as_brute_force(s2) and _in_sync(s2) and len(rebuilds) == n
                s2.close()
            assert [r.levelname for r in caplog.records] == ["WARNING"]  # one line, and no traceback
            assert "is not the file its note describes" in caplog.text
    path.write_bytes(saved)  # the bytes that were saved are read
    monkeypatch.setattr(Store, "_rebuild", lambda *a: pytest.fail("the saved file should have been used"))
    s3 = _open(tmp_path / "idx", backend)
    assert _same_as_brute_force(s3) and _in_sync(s3)
    s3.close()


def test_another_process_writes_and_this_one_catches_up(tmp_path, backend):
    """A second Store on the folder stands in for another process."""
    a, b = _open(tmp_path / "idx", backend), _open(tmp_path / "idx", backend)
    ids = _seed(a, 30)
    loaded = b._type_index("code")
    assert _same_as_brute_force(b)
    a.delete_vectors("code", [a.vector_rows("code")[(c, 0)][0] for c in ids[:5]])
    _seed(a, 8, seed=4, prefix="g")
    a.put_vectors("code", EMBEDDER, [VectorRow(ids[6], 0, 1, 0, 1, "again")], _vecs(1, seed=11))
    assert _same_as_brute_force(b) and _in_sync(b)
    assert b._type_index("code") is loaded and len(loaded.store) == 33  # caught up, not rebuilt
    a.close(), b.close()


def test_embedding_dim_cuts_the_vectors_the_index_holds(store):
    ids = _add_chunks(store, [f"f{i:02d}" for i in range(40)])
    with store.transaction():
        store.ensure_vec_type("code", EMBEDDER, 16)
    store.put_vectors("code", EMBEDDER, [VectorRow(c, 0, 1, 0, 1, f"h{c}") for c in ids], _vecs(40, dim=64))
    assert store.vector_dim("code") == 16 and store._type_index("code").store.dim == 16
    assert _same_as_brute_force(store, dim=64)  # a full-size query is cut too
    with store.transaction():
        store.ensure_vec_type("code", EMBEDDER, 32)  # another cut: the index is rebuilt from the rows
    assert store._type_index("code").store.dim == 32 and _same_as_brute_force(store, dim=64)


def test_an_empty_index_and_more_results_asked_for_than_it_holds(store):
    q = _vecs(1, seed=2)[0]
    assert store.vector_search("code", q, 5) == []
    ids = _seed(store, 7)
    assert _same_as_brute_force(store, n_values=(7, 8, 100, 10_000))
    assert store.vector_search("code", q, 0) == []
    with store.transaction():
        store.delete_chunks(ids)
    assert store.vector_search("code", q, 5) == [] and _in_sync(store)


def test_a_query_of_zeros_gets_no_results_and_no_index_is_asked(store, monkeypatch):
    """Every vector scores 0 against it, and ties are taken whole: the search would ask for more
    and more until it had seen every vector, and the compact index would read every row each time."""
    ids = _seed(store, 300)
    backend = store._type_index("code").store
    usual = store.vector_search("code", _vecs(1, seed=3)[0], 5)
    assert len(usual) == 5
    with monkeypatch.context() as m, np.errstate(over="ignore"):
        m.setattr(backend, "search", lambda *a, **k: pytest.fail("the index must not be asked"))
        too_long = _vecs(1, seed=3)[0] * np.float32(1e30)  # its squared length overflows: no direction is left
        for q in (np.zeros(16, dtype=np.float32), np.zeros(16), np.zeros(64), too_long, _vecs(1, seed=3)[0] * 1e-46):
            assert store.vector_search("code", q, 5) == [] and store.vector_search("code", q, 5, ids[:20]) == []
    assert store.vector_search("code", _vecs(1, seed=3)[0], 5) == usual


def test_copies_of_one_vector_tie_and_are_ordered_by_location(store):
    ids = _add_chunks(store, [f"f{i:02d}" for i in range(12)])
    v = _vecs(12)
    v[[2, 5, 7, 11]] = v[0]  # five chunks hold the same vector
    store.put_vectors("code", EMBEDDER, [VectorRow(c, 0, 1, 0, 1, f"h{c}") for c in ids], v)
    copies = [ids[i] for i in (0, 2, 5, 7, 11)]
    for n in (1, 2, 5, 6):
        hits = store.vector_search("code", v[0], n)
        assert [h.chunk_id for h in hits[:5]] == copies[:n]  # key order: the cut never splits the tie at random
        assert len({h.score for h in hits[:5]}) == 1


def test_searches_during_writes_never_see_a_half_patched_index(tmp_path, backend):
    s = _open(tmp_path / "idx", backend)
    _seed(s, 20)
    errors: list[BaseException] = []
    stop = threading.Event()

    def search():
        try:
            while not stop.is_set():
                assert len(s.vector_search("code", _vecs(1, seed=5)[0], 5)) == 5
        except BaseException as e:  # noqa: BLE001 - any error fails the test
            errors.append(e)
        finally:
            s.close_thread_conn()

    t = threading.Thread(target=search)
    t.start()
    try:
        for i in range(30):
            s.delete_vectors("code", [vid for vid, _ in s.vector_rows("code").values()][:2])
            _seed(s, 2, seed=i, prefix=f"g{i}")
    finally:
        stop.set()
        t.join()
    assert errors == [] and _in_sync(s)
    s.close()


# ---------------------------------------------------------------- where the candidates' vectors are read


_READ = "FROM vectors WHERE vector_id IN"


def test_candidates_are_read_through_a_connection_with_a_small_cache(tmp_path):
    s = _open(tmp_path / "idx", "compact")
    _seed(s, 30)
    q = _vecs(1, seed=3)[0]
    main, reader = s.conn, s._vector_reader
    assert reader is not main and reader is s._vector_reader  # one per thread, kept
    assert main.execute("PRAGMA cache_size").fetchone()[0] == -65536
    assert reader.execute("PRAGMA cache_size").fetchone()[0] == -2000
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        reader.execute("DELETE FROM vectors")
    seen: dict[str, list[str]] = {"main": [], "reader": []}
    main.set_trace_callback(seen["main"].append)
    reader.set_trace_callback(seen["reader"].append)
    assert len(s.vector_search("code", q, 3)) == 3
    assert any(_READ in sql for sql in seen["reader"]) and not any(_READ in sql for sql in seen["main"])
    seen["main"].clear(), seen["reader"].clear()
    with s._read_snapshot():  # a caller's own snapshot: the rows it sees, from its connection
        assert len(s.vector_search("code", q, 3)) == 3
    assert any(_READ in sql for sql in seen["main"]) and not any(_READ in sql for sql in seen["reader"])
    s.close()


def test_a_search_inside_a_read_snapshot_returns_what_the_snapshot_holds(tmp_path):
    """Another process deletes vectors after the snapshot began: the search still reads their rows."""
    a, b = _open(tmp_path / "idx", "compact"), _open(tmp_path / "idx", "compact")
    _seed(a, 60)
    q = _vecs(1, seed=3)[0]
    assert _same_as_brute_force(a, n_values=(5,), seeds=range(1))
    with a._read_snapshot():
        want = _brute(a, q, 5)  # the first read fixes the snapshot
        gone = [a.vector_rows("code")[(chunk_id, 0)][0] for chunk_id, _, _ in want[:3]]
        b.delete_vectors("code", gone)
        assert [h.chunk_id for h in a.vector_search("code", q, 5)] == [c for c, _, _ in want]
    now = _brute(a, q, 5)
    assert not {c for c, _, _ in now} & {c for c, _, _ in want[:3]}
    assert [h.chunk_id for h in a.vector_search("code", q, 5)] == [c for c, _, _ in now]
    a.close(), b.close()


def test_reading_candidates_holds_nothing_open_between_searches(tmp_path):
    """A read transaction left open on the reader would keep the write-ahead log from being
    emptied: after a search, a checkpoint from another connection must find no reader in its way."""
    s = _open(tmp_path / "idx", "compact")
    ids = _seed(s, 30)
    q = _vecs(1, seed=3)[0]
    other = sqlite3.connect(tmp_path / "idx" / "index.db", timeout=0, isolation_level=None)
    wal = tmp_path / "idx" / "index.db-wal"

    def emptied() -> bool:
        busy = other.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
        return busy == 0 and wal.stat().st_size == 0

    assert len(s.vector_search("code", q, 3)) == 3 and emptied()
    s.put_vectors("code", EMBEDDER, [VectorRow(ids[0], 0, 1, 0, 1, "again")], _vecs(1, seed=11))
    hit = s.vector_search("code", _vecs(1, seed=11)[0], 1)[0]  # the reader sees the row committed just now
    assert hit.chunk_id == ids[0] and hit.score == pytest.approx(1.0, abs=1e-3) and emptied()
    held = s._vector_reader.execute("SELECT vector_id FROM vectors")
    held.fetchone()  # the same check sees a read that is left open
    s.put_vectors("code", EMBEDDER, [VectorRow(ids[1], 0, 1, 0, 1, "again")], _vecs(1, seed=12))
    assert not emptied()
    held.fetchall()
    assert emptied()
    other.close(), s.close()


def test_closing_closes_the_reader_with_the_thread_s_connection(tmp_path):
    s = _open(tmp_path / "idx", "compact")
    _seed(s, 10)
    q = _vecs(1, seed=3)[0]
    errors: list[BaseException] = []

    def worker():
        try:
            assert len(s.vector_search("code", q, 3)) == 3
            mine = [s.conn, s._vector_reader]
            assert all(id(conn) in s._all_conns for conn in mine)
            s.close_thread_conn()
            assert not any(id(conn) in s._all_conns for conn in mine)
            for conn in mine:
                with pytest.raises(sqlite3.ProgrammingError):
                    conn.execute("SELECT 1")
            assert len(s.vector_search("code", q, 3)) == 3  # both are opened again when needed
            s.close_thread_conn()
        except BaseException as e:  # noqa: BLE001 - any error fails the test
            errors.append(e)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert errors == []
    assert len(s.vector_search("code", q, 3)) == 3
    reader = s._vector_reader
    s.close()
    assert s._all_conns == {} and s._local.vector_reader is None
    with pytest.raises(sqlite3.ProgrammingError):
        reader.execute("SELECT 1")


# ---------------------------------------------------------------- the compact index: codes, then exact scores


def _bound(vs, ids, vecs):
    """A CompactVectorStore filled with `vecs`, reading them back from memory. Returns the dict it
    reads from, so a test can delete rows behind its back."""
    rows = {int(i): v for i, v in zip(ids, vecs)}

    def fetch(wanted):
        found = [int(i) for i in wanted if int(i) in rows]
        vectors = np.stack([rows[i] for i in found]) if found else np.empty((0, vs.dim), np.float32)
        return np.asarray(found, dtype=np.int64), vectors

    vs.upsert(list(ids), vecs)
    vs.bind(fetch)
    return rows


def _clustered(n_clusters, per_cluster, dim, noise, seed=0, queries=100):
    """Cluster centres plus noise, so that every vector has near neighbours; and queries made the same way."""
    rng = np.random.default_rng(seed)
    centres = l2_normalize(rng.normal(size=(n_clusters, dim)))
    spread = noise / np.sqrt(dim)
    docs = np.repeat(centres, per_cluster, axis=0) + spread * rng.normal(size=(n_clusters * per_cluster, dim))
    asked = centres[rng.integers(n_clusters, size=queries)] + spread * rng.normal(size=(queries, dim))
    return l2_normalize(docs), l2_normalize(asked)


def test_compact_vector_store_upsert_remove_search_filter():
    vs = CompactVectorStore(8)
    v = for_index(_vecs(4, dim=8), 8)
    rows = _bound(vs, [10, 20, 30, 40], v)
    assert vs.ids() == {10, 20, 30, 40} and len(vs) == 4
    assert vs.search(v[2], 1)[0] == (30, pytest.approx(float((v[2] * v[2]).sum()), abs=1e-6))
    rows[30] = v[0]
    vs.upsert([30], v[0:1])  # update in place, no duplicate
    assert len(vs) == 4 and [i for i, _ in vs.search(v[0], 2)] == [10, 30]  # equal scores: by id
    vs.remove([10, 999])
    assert vs.ids() == {20, 30, 40}
    assert {i for i, _ in vs.search(v[3], 4, allowed_ids=[20, 30])} == {20, 30}
    assert vs.search(v[3], 4, allowed_ids=[]) == [] and vs.search(v[3], 0) == []
    with pytest.raises(ValueError, match="shape"):
        vs.upsert([1], _vecs(1, dim=4))


def test_a_small_index_is_scored_exactly_without_a_scan(monkeypatch):
    """Up to `rescore` vectors (or 4 per result asked for), every one is read and scored."""
    v = for_index(_vecs(150, dim=32), 32)
    vs, exact = CompactVectorStore(32), FaissVectorStore(32)
    _bound(vs, range(1, 151), v)
    exact.upsert(list(range(1, 151)), v)
    monkeypatch.setattr(vs, "_scan", lambda *a: pytest.fail("no scan is needed"))
    for q in for_index(_vecs(20, dim=32, seed=3), 32):
        got, want = vs.search(q, 10), exact.search(q, 10)
        assert [i for i, _ in got] == [i for i, _ in want]
        assert [s for _, s in got] == pytest.approx([s for _, s in want], abs=1e-6)
    assert len(vs.search(v[0], 60)) == 60 and len(vs.search(v[0], 1000)) == 150


def test_candidates_come_from_the_codes_and_scores_from_the_rows():
    """More vectors than are re-scored: the codes choose, so a result can be missed, but whatever
    is returned carries its real similarity, best first."""
    v = for_index(_vecs(600, dim=64), 64)
    queries = for_index(_vecs(40, dim=64, seed=3), 64)
    vs = CompactVectorStore(64, rescore=40)
    _bound(vs, range(1, 601), v)
    found = 0
    for q in queries:
        hits = vs.search(q, 5)
        true = v @ q
        assert len(hits) == 5 and len({i for i, _ in hits}) == 5
        assert [s for _, s in hits] == pytest.approx([float(true[i - 1]) for i, _ in hits], abs=1e-6)
        assert [s for _, s in hits] == sorted((s for _, s in hits), reverse=True)
        found += len({i for i, _ in hits} & set((np.argsort(-true)[:5] + 1).tolist()))
    assert found / (5 * len(queries)) > 0.8  # 40 candidates of 600 hold most of the exact top 5 (0.96 here)
    wide = CompactVectorStore(64, rescore=600)
    _bound(wide, range(1, 601), v)
    assert [i for i, _ in wide.search(queries[0], 5)] == (np.argsort(-(v @ queries[0]))[:5] + 1).tolist()


def test_at_least_four_candidates_per_result_asked_for():
    v = for_index(_vecs(500, dim=32), 32)
    vs = CompactVectorStore(32, rescore=10)
    _bound(vs, range(1, 501), v)
    asked: list[int] = []
    candidates = vs._candidates
    vs._candidates = lambda q, size, allowed: asked.append(size) or candidates(q, size, allowed)
    assert len(vs.search(v[0], 1)) == 1 and len(vs.search(v[0], 50)) == 50
    assert asked == [10, 200]


def test_a_filtered_scan_returns_only_allowed_ids_whatever_the_share():
    """Random filters over 1%, 10%, 50% and 100% of the ids, against the exact index."""
    docs, queries = _clustered(40, 50, 64, 0.8, queries=12)
    v = for_index(docs, 64)
    ids = np.arange(1, len(v) + 1) * 3  # ids are not positions
    vs, exact = CompactVectorStore(64, rescore=100), FaissVectorStore(64)
    _bound(vs, ids, v)
    exact.upsert(ids.tolist(), v)
    rng = np.random.default_rng(5)
    overlap = []
    for share in (0.01, 0.1, 0.5, 1.0):
        for q in for_index(queries, 64):
            allowed = rng.choice(ids, max(1, int(share * len(ids))), replace=False).tolist()
            got, want = vs.search(q, 10, allowed), exact.search(q, 10, allowed)
            assert len(got) == len(want) == min(10, len(allowed)) and {i for i, _ in got} <= set(allowed)
            true = {int(i): float(s) for i, s in zip(ids, v @ q)}
            assert [s for _, s in got] == pytest.approx([true[i] for i, _ in got], abs=1e-6)
            if len(allowed) <= 100:  # no more than are re-scored: every allowed vector is scored
                assert [i for i, _ in got] == [i for i, _ in want]
            overlap.append(len({i for i, _ in got} & {i for i, _ in want}) / len(want))
    assert np.mean(overlap) >= 0.99


def test_rows_deleted_behind_the_index_are_dropped_and_replaced():
    """Another process deleted candidates' rows and this index has not caught up yet: `fetch`
    returns fewer vectors than asked, and the search takes more candidates."""
    v = for_index(_vecs(400, dim=32), 32)
    vs = CompactVectorStore(32, rescore=8)
    rows = _bound(vs, range(1, 401), v)
    q = for_index(_vecs(1, dim=32, seed=9), 32)[0]
    first = [i for i, _ in vs.search(q, 2)]
    for i in vs._ids[vs._candidates(q, 8, None)].tolist():  # every candidate of that search loses its row
        del rows[i]
    hits = vs.search(q, 2)
    assert len(hits) == 2 and not {i for i, _ in hits} & set(first) and all(i in rows for i, _ in hits)
    rows.clear()
    assert vs.search(q, 2) == []


def _candidate_ids(vs, q, size, allowed=None):
    return set(vs._ids[vs._candidates(q, size, allowed)].tolist())


def _signed_permutation(dim):
    """A rotation that every BLAS multiplies by exactly: each number of a rotated row is one number
    of the row, its sign perhaps flipped. The store's rotation is a float32 matrix product, which
    a BLAS can round differently in a call of another size (docs/architecture.md §5)."""
    rng = np.random.default_rng(dim)
    rotation = np.zeros((dim, dim), dtype=np.float32)
    rotation[np.arange(dim), rng.permutation(dim)] = rng.choice(np.array([-1.0, 1.0], dtype=np.float32), size=dim)
    rotation.setflags(write=False)
    return rotation, f"signed-permutation-{dim}"


@pytest.fixture
def exact_rotation(monkeypatch):
    """Codes that are a function of the vector alone on every BLAS. The tests that hold two
    indexes to the same bits use it: they check the bookkeeping (codes kept with their ids, in id
    order, through removes, moves and failed calls) and the cut through ties, not how a BLAS rounds."""
    monkeypatch.setattr("codemem.store._rotation", _signed_permutation)


@pytest.mark.parametrize("bits", [1, 4])
def test_ties_at_the_candidate_cut_are_all_kept(bits, exact_rotation):
    """Copies of one vector have the same codes. A cut through them takes every copy, so the
    candidates do not depend on the order the codes are held in: the same vectors under other ids
    (as in another database) give the same candidates."""
    v = for_index(_vecs(300, dim=32), 32)
    v[100:160] = v[100]
    other_ids = np.random.default_rng(1).permutation(300) + 1  # vector j has id other_ids[j]: another order
    a, b = CompactVectorStore(32, bits=bits, rescore=8), CompactVectorStore(32, bits=bits, rescore=8)
    _bound(a, range(1, 301), v)
    _bound(b, other_ids.tolist(), v)
    vector_of = {int(i): j + 1 for j, i in enumerate(other_ids)}
    in_a = _candidate_ids(a, v[100], 8)
    in_b = {vector_of[i] for i in _candidate_ids(b, v[100], 8)}
    assert set(range(101, 161)) <= in_a and len(in_a) < 80 and in_a == in_b
    for q in for_index(_vecs(20, dim=32, seed=6), 32):
        assert _candidate_ids(a, q, 8) == {vector_of[i] for i in _candidate_ids(b, q, 8)}
    assert [i for i, _ in a.search(v[100], 2)] == [101, 102]


@pytest.mark.parametrize("bits", [2, 4, 8])
def test_the_same_vectors_in_another_order_give_the_same_candidates(bits, monkeypatch):
    """Vectors with near neighbours, far more of them than candidates, with and without a filter:
    which candidates a search takes depends on the vectors held, never on where their codes sit."""
    monkeypatch.setattr("codemem.store._RANKED", 0)  # 4 per candidate: 100 of the 3,000, so both cuts are met
    docs, queries = _clustered(30, 100, 64, 0.8, queries=30)
    v = for_index(docs, 64)
    other_ids = np.random.default_rng(2).permutation(len(v)) + 1
    a, b = CompactVectorStore(64, bits=bits, rescore=25), CompactVectorStore(64, bits=bits, rescore=25)
    a.upsert(list(range(1, len(v) + 1)), v)
    b.upsert(other_ids.tolist(), v)
    vector_of = {int(i): j + 1 for j, i in enumerate(other_ids)}
    some = np.random.default_rng(3).choice(len(v), 1200, replace=False)
    for q in for_index(queries, 64):
        in_a = _candidate_ids(a, q, 25)
        assert 25 <= len(in_a) < 30 and in_a == {vector_of[i] for i in _candidate_ids(b, q, 25)}
        allowed_a, allowed_b = np.isin(a._ids, some + 1), np.isin(b._ids, other_ids[some])
        in_a = _candidate_ids(a, q, 25, allowed_a)
        assert in_a <= set((some + 1).tolist()) and in_a == {vector_of[i] for i in _candidate_ids(b, q, 25, allowed_b)}


def test_finer_codes_rank_the_scan_s_best_again(monkeypatch):
    """At more than 1 bit a search scans the coarse codes for more than it wants (here 4 times as
    many), takes the fine estimate of those and keeps the best: what FAISS says of each code by itself."""
    monkeypatch.setattr("codemem.store._RANKED", 0)
    docs, queries = _clustered(30, 100, 64, 0.8, queries=20)
    v = for_index(docs, 64)
    vs = CompactVectorStore(64, bits=4, rescore=25)
    vs.upsert(list(range(len(v))), v)
    params = faiss.RaBitQSearchParameters(qb=4, centered=False)
    kept_more = 0
    for q in for_index(queries, 64):
        x = vs._coded(q)
        scanned = set(vs._coarse.search(x, 100, params=params)[1][0].tolist())
        _, estimates, positions = vs._fine.range_search(x, -1e30, params=params)  # every code's fine estimate
        fine = dict(zip(positions.tolist(), estimates.tolist()))
        want = set(sorted(scanned, key=lambda i: -fine[i])[:25])
        got = set(vs._candidates(q, 25, None).tolist())
        assert got == want and got <= scanned
        exact = set(np.argsort(-(v @ q))[:10].tolist())
        coarse_only = set(vs._coarse.search(x, 25, params=params)[1][0].tolist())
        kept_more += len(exact & got) - len(exact & coarse_only)
    assert kept_more > 0  # the fine estimates keep more of the exact top 10 than the scan's own best 25


def test_how_many_of_the_scan_s_best_the_fine_codes_rank(monkeypatch):
    """At least 4,000, at least 4 for each candidate, and at least one in 50 of the vectors the
    search may return."""
    v = for_index(_vecs(6000, dim=16), 16)
    vs = CompactVectorStore(16, bits=2, rescore=10)
    vs.upsert(list(range(len(v))), v)
    asked: list[int] = []
    scan = vs._scan
    monkeypatch.setattr(vs, "_scan", lambda x, size, allowed: asked.append(size) or scan(x, size, allowed))
    half = np.arange(len(v)) < 3000
    for size, allowed in ((10, None), (1200, None), (10, half)):
        assert 10 <= len(vs._candidates(v[0], size, allowed)) <= size + 5
    monkeypatch.setattr("codemem.store._RANKED", 50)
    for size, allowed in ((10, None), (10, half), (40, half)):
        vs._candidates(v[0], size, allowed)
    assert asked == [4000, 4800, 4000, 120, 60, 160]


def _codes(vs):
    tables = [faiss.vector_to_array(index.codes).reshape(len(vs), index.code_size) for index in vs._indexes]
    return {int(i): b"".join(bytes(table[at]) for table in tables) for at, i in enumerate(vs._ids)}


@pytest.mark.parametrize("bits", [1, 4])
def test_an_index_patched_step_by_step_is_the_index_rebuilt_from_the_rows(bits, exact_rotation):
    """The same codes in the same order, whatever edits it went through: the same bytes when
    saved, and the same candidates."""
    v = for_index(_vecs(400, dim=48), 48)
    patched = CompactVectorStore(48, bits=bits, rescore=16)
    patched.upsert(list(range(201, 401)), v[200:])  # the newer half first, as a catch-up can bring it
    patched.upsert(list(range(1, 201)), v[:200])
    patched.remove(range(50, 120))
    patched.upsert(list(range(60, 90)), v[59:89])  # some come back, later than their neighbours
    patched.upsert([300, 10], v[[299, 9]])  # and two are replaced
    kept = sorted(patched.ids())
    rebuilt = CompactVectorStore(48, bits=bits, rescore=16)
    rebuilt.upsert(kept, v[np.asarray(kept) - 1])
    assert patched._ids.tolist() == rebuilt._ids.tolist() == kept
    assert _codes(patched) == _codes(rebuilt) and patched.to_bytes() == rebuilt.to_bytes()
    for q in for_index(_vecs(10, dim=48, seed=4), 48):
        assert patched._candidates(q, 16, None).tolist() == rebuilt._candidates(q, 16, None).tolist()


@pytest.mark.parametrize("options", [{}, {"bits": 2}, {"bits": 4, "dim": 16}, {"dim": 24}])
def test_the_saved_file_holds_ids_and_codes_and_reads_back(options):
    v = for_index(_vecs(300, dim=40), 40)
    vs = CompactVectorStore(40, rescore=16, **options)
    rows = _bound(vs, range(1, 301), v)
    vs.remove(range(1, 20))
    data = vs.to_bytes()
    assert vs.code_bytes == sum(index.code_size for index in vs._indexes) and len(vs._indexes) == 1 + (vs.bits > 1)
    assert len(data) < len(vs) * (vs.code_bytes + 8) + 900  # 8 bytes of id and its codes per vector, and a small head
    back = CompactVectorStore.from_bytes(data, rescore=16, **options)
    back.bind(lambda wanted: (np.asarray(wanted, dtype=np.int64), np.stack([rows[int(i)] for i in wanted])))
    assert back.ids() == vs.ids() and (back.dim, back.code_dim, back.bits) == (vs.dim, vs.code_dim, vs.bits)
    assert all(index.thisown for index in back._indexes)  # the objects FAISS gave own the indexes
    q = for_index(_vecs(1, dim=40, seed=8), 40)[0]
    assert back.search(q, 5) == vs.search(q, 5)
    back.upsert([1000], v[:1])  # a loaded index takes edits, and codes them as the first one does
    vs.upsert([1000], v[:1])
    assert len(back) == 282 and _codes(back) == _codes(vs)


def test_a_file_that_is_not_what_was_saved_is_refused_before_faiss_reads_it(monkeypatch):
    v = for_index(_vecs(50, dim=16), 16)
    vs = CompactVectorStore(16)
    vs.upsert(list(range(50)), v)
    data = vs.to_bytes()
    head, _, body = data.partition(b"\n")
    monkeypatch.setattr(faiss, "deserialize_index", lambda *a: pytest.fail("FAISS must not parse these bytes"))
    flipped = bytearray(data)
    flipped[-20] ^= 1
    for damaged in (b"", b"garbage", head, data[:-1], bytes(flipped), b"{}\n" + body, b"[1]\n" + body):
        with pytest.raises((ValueError, KeyError, AttributeError)):
            CompactVectorStore.from_bytes(damaged)
    for other in ({"bits": 2}, {"dim": 8}):
        with pytest.raises(ValueError, match="other options"):
            CompactVectorStore.from_bytes(data, **other)
    monkeypatch.setattr("codemem.store._rotation", lambda dim: (np.eye(dim, dtype=np.float32), "another-rotation"))
    with pytest.raises(ValueError, match="another rotation"):
        CompactVectorStore.from_bytes(data)


def test_a_file_whose_index_is_not_the_one_described_is_refused():
    import zlib

    def saved(indexes, count, ids, bits=1, **other):
        blobs = [faiss.serialize_index(index).tobytes() for index in indexes]
        body = np.asarray(ids, dtype="<i8").tobytes() + b"".join(blobs)
        head = {"dim": 16, "code_dim": 16, "bits": bits, "count": count, "rotation": CompactVectorStore(16)._rotation_id,
                "index_bytes": [len(blob) for blob in blobs], "crc32": zlib.crc32(body)} | other
        return json.dumps(head).encode() + b"\n" + body

    def rabitq(vectors, bits=1, metric=faiss.METRIC_INNER_PRODUCT, centre=None):
        index = faiss.IndexRaBitQ(16, metric, bits)
        index.train(np.zeros((1, 16), dtype=np.float32) if centre is None else centre)
        index.add(vectors)
        return index

    v = np.ascontiguousarray(for_index(_vecs(6, dim=16), 16))
    right, fine = rabitq(v), rabitq(v, bits=4)
    size = len(faiss.serialize_index(right).tobytes())
    assert len(CompactVectorStore.from_bytes(saved([right], 6, range(6)), bits=1)) == 6
    assert len(CompactVectorStore.from_bytes(saved([right, fine], 6, range(6), bits=4), bits=4)) == 6
    centred = rabitq(v, centre=v)  # a learned centre: its codes are not the ones this store makes
    flat = faiss.IndexFlatIP(16)
    flat.add(v)
    refused = "not the one its first line describes|does not hold the vector ids and indexes|not in order"
    for indexes, count, ids in (([right], 5, range(5)), ([right], 7, range(7)), ([centred], 6, range(6)),
                                ([flat], 6, range(6)), ([rabitq(v, metric=faiss.METRIC_L2)], 6, range(6)),
                                ([right], 6, [0, 1, 2, 4, 3, 5]), ([right], 6, [0, 1, 2, 2, 3, 4]),
                                ([fine], 6, range(6)), ([right, fine], 6, range(6)), ([], 6, range(6))):
        with pytest.raises(ValueError, match=refused):
            CompactVectorStore.from_bytes(saved(indexes, count, ids), bits=1)
    for sizes in ([size - 1], [size + 1], [size, 0], [0, size], [-1], [float(size)], [], size, None, "x"):
        with pytest.raises(ValueError, match=refused):
            CompactVectorStore.from_bytes(saved([right], 6, range(6), index_bytes=sizes), bits=1)
    # at more than 1 bit: a coarse and a fine index, in that order, of the same vectors
    for indexes in ([right], [fine, right], [right, right], [right, rabitq(v, bits=2)], [right, rabitq(v[:5], bits=4)],
                    [rabitq(v[:5]), fine], [right, fine, fine]):
        with pytest.raises(ValueError, match=refused):
            CompactVectorStore.from_bytes(saved(indexes, 6, range(6), bits=4), bits=4)


# ---------------------------------------------------------------- the checks in front of FAISS


@pytest.mark.parametrize("args, kwargs", [
    ((0,), {}), ((-8,), {}), ((8.0,), {}), ((True,), {}),
    ((8,), {"bits": 0}), ((8,), {"bits": 9}), ((8,), {"bits": 1.0}),
    ((8,), {"dim": -1}), ((8,), {"dim": COMPACT_MAX_DIM + 1}),
    ((8,), {"rescore": 0}), ((8,), {"rescore": "200"}),
])
def test_options_faiss_cannot_take_are_refused_with_a_sentence(args, kwargs):
    for hands_them_to_faiss in (CompactVectorStore, CompactVectorStore.bytes_per_vector):
        with pytest.raises(ValueError, match="whole numbers|need an index dim of 1 or more"):
            hands_them_to_faiss(*args, **kwargs)


@pytest.mark.parametrize("options", [{}, {"bits": 1}, {"bits": 2, "dim": 33}, {"bits": 8, "rescore": 500}])
def test_the_memory_counted_for_a_vector_is_its_codes_its_id_and_where_it_came_from(options):
    vs = CompactVectorStore(65, **options)
    assert CompactVectorStore.bytes_per_vector(65, **options) == vs.code_bytes + 8 + 32
    # the numbers of docs/architecture.md §5, at the real model's 896 numbers: 4 bits, and 1 bit
    assert (CompactVectorStore.bytes_per_vector(896), CompactVectorStore.bytes_per_vector(896, bits=1)) == (628, 160)


@pytest.mark.parametrize("dim, code_dim, expect", [(8, 0, 8), (8, 4, 4), (8, 64, 8), (5, 0, 5), (65, 33, 33)])
def test_the_code_covers_the_first_numbers_of_any_length(dim, code_dim, expect):
    vs = CompactVectorStore(dim, bits=1, dim=code_dim, rescore=4)
    v = for_index(_vecs(60, dim=dim), dim)
    _bound(vs, range(1, 61), v)
    assert vs.code_dim == vs._coarse.d == expect and vs.code_bytes == -(-expect // 8) + 8 and vs._fine is None
    assert CompactVectorStore(dim, bits=4, dim=code_dim)._fine.d == expect
    hits = vs.search(v[7], 3)
    assert len(hits) == 3 and hits[0][1] == pytest.approx(max(float(s) for s in v @ v[7]), abs=1e-6)


def test_an_index_wider_than_the_longest_code_is_coded_on_its_first_numbers(monkeypatch, caplog):
    monkeypatch.setattr("codemem.store.COMPACT_MAX_DIM", 16)
    with caplog.at_level(logging.WARNING, logger="codemem.store"):
        vs = CompactVectorStore(40)
        assert (vs.dim, vs.code_dim, vs._coarse.d, vs._fine.d) == (40, 16, 16, 16)
        said = [r.getMessage() for r in caplog.records]  # in the log, once, when the index is made
        assert len(said) == 1 and "codes the first 16 numbers of each vector, and these vectors have 40" in said[0]
        caplog.clear()
        v = for_index(_vecs(60, dim=40), 40)
        _bound(vs, range(1, 61), v)
        assert all(len(vs.search(q, 3)) == 3 for q in v[:5]) and len(vs.to_bytes()) > 0
        assert CompactVectorStore.bytes_per_vector(40) == vs.code_bytes + 8 + 32
        for whole_or_asked_for in (CompactVectorStore(16), CompactVectorStore(12), CompactVectorStore(40, dim=8),
                                   CompactVectorStore(40, dim=16)):
            assert whole_or_asked_for.code_dim <= 16
        assert caplog.records == []  # not by a search, a save or a status, and not for a code length that was asked for
        assert CompactVectorStore.from_bytes(vs.to_bytes()).code_dim == 16 and len(caplog.records) == 1  # made again
    with pytest.raises(ValueError, match="dim 0 to 16"):
        CompactVectorStore(40, dim=17)


def test_the_store_warns_once_for_each_index_of_vectors_longer_than_a_code(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("codemem.store.COMPACT_MAX_DIM", 16)
    said = lambda: [r.getMessage() for r in caplog.records if "codes the first 16 numbers" in r.getMessage()]  # noqa: E731
    with caplog.at_level(logging.WARNING, logger="codemem.store"):
        s = _open(tmp_path / "idx", "compact")
        _seed(s, 100, dim=40)  # few enough for every one to be scored exactly, whatever the codes cover
        assert len(said()) == 1 and _same_as_brute_force(s, dim=40) and s.search_index_status()["index"] == "compact"
        s.save_vectors()
        s.close()
        assert len(said()) == 1
        s = _open(tmp_path / "idx", "compact")  # another start: its index is made from the saved file
        assert _same_as_brute_force(s, dim=40) and len(said()) == 2
        s.close()
        exact = _open(tmp_path / "exact", "faiss")
        _seed(exact, 100, dim=40)
        assert _same_as_brute_force(exact, dim=40) and len(said()) == 2  # the exact index holds every number
        exact.close()


def test_vectors_and_queries_of_the_wrong_shape_raise_before_faiss():
    vs = CompactVectorStore(8, rescore=2)
    v = for_index(_vecs(40, dim=8), 8)
    _bound(vs, range(40), v)
    for bad_ids, bad_vecs in (([1], v[0]), ([1, 2], v[:1]), ([1], _vecs(1, dim=9)), ([[1]], v[:1])):
        with pytest.raises(ValueError, match="shape"):
            vs.upsert(bad_ids, bad_vecs)
    for bad_query in (np.zeros(7, np.float32), np.zeros(9, np.float32), np.zeros((2, 8), np.float32)):
        with pytest.raises(ValueError, match="a query of 8 numbers"):
            vs.search(bad_query, 1)
    assert len(vs) == 40 and [index.ntotal for index in vs._indexes] == [40, 40]
    assert len(vs.search(v[3].astype(np.float64), 5)) == 5  # other number types are converted
    assert len(vs.search(np.asfortranarray(v[3]), np.int64(5))) == 5


def test_numbers_that_are_not_finite_never_reach_faiss():
    v = for_index(_vecs(60, dim=16), 16)
    v[3, 2], v[4, :] = np.nan, np.inf
    vs = CompactVectorStore(16, rescore=4)
    _bound(vs, range(60), v)
    assert np.isfinite(vs._coded(v)).all() and not vs._coded(v)[3].any() and not vs._coded(v)[4].any()
    for q in (v[10], v[20]):
        for k in (3, 60):
            hits = vs.search(q, k)
            assert len(hits) == min(k, 58) and all(np.isfinite(s) for _, s in hits)
            assert not {3, 4} & {i for i, _ in hits}
    bad = v[10].copy()
    bad[0] = np.nan
    assert vs.search(bad, 3) == [] and vs.search(np.full(16, np.inf, np.float32), 3) == []


def test_a_selector_always_covers_every_position():
    vs = CompactVectorStore(8)
    vs.upsert(list(range(21)), for_index(_vecs(21, dim=8), 8))
    selector, bitmap = vs._selector(np.arange(21) % 2 == 0)
    assert selector.n == len(bitmap) == 3 and [i for i in range(40) if selector.is_member(i)] == list(range(0, 21, 2))
    too_short, too_long = np.ones(20, dtype=bool), np.ones(22, dtype=bool)
    for wrong in (too_short, too_long, np.ones(21, dtype=np.uint8), np.ones((21, 1), dtype=bool)):
        with pytest.raises(RuntimeError, match="selector"):
            vs._selector(wrong)


@pytest.mark.parametrize("bits, spoil, message", [
    (1, lambda vs, v: setattr(vs, "_ids", vs._ids[:-1]), "39 vector ids for an index of 40 codes"),
    (4, lambda vs, v: setattr(vs, "_ids", vs._ids[:-1]), "39 vector ids for an index of 40 codes"),
    (4, lambda vs, v: vs._fine.add(vs._coded(v[40:49])), "40 vector ids for an index of 49 codes"),
    (4, lambda vs, v: vs._coarse.add(vs._coded(v[40:49])), "40 vector ids for an index of 49 codes"),
])
def test_ids_and_codes_that_are_out_of_step_raise_before_faiss_is_asked(bits, spoil, message):
    """As a bug would leave them: an id too few, or codes in one index that no id stands for. The
    next call raises: FAISS is not handed a selector, or an order to move codes by, of another length."""
    v = for_index(_vecs(50, dim=8), 8)
    vs = CompactVectorStore(8, bits=bits, rescore=2)
    _bound(vs, range(10, 50), v[:40])
    spoil(vs, v)
    for call in (lambda: vs.search(v[0], 1), lambda: vs.search(v[0], 1, allowed_ids=list(range(10, 40))),
                 lambda: vs.remove([13]), lambda: vs.upsert([50], v[:1]), lambda: vs.upsert([5], v[:1])):
        with pytest.raises(RuntimeError, match=message):
            call()


def _fail_the(monkeypatch, call, nth):
    """Make the nth call of a FAISS method on a code index raise, as FAISS does when it cannot get
    memory. The calls before it go through. Returns the list the calls are counted in."""
    made = []
    real = getattr(faiss.IndexRaBitQ, call)

    def counted(index, *args):
        made.append(index)
        if len(made) == nth:
            raise MemoryError(f"the {call} that fails")
        return real(index, *args)

    monkeypatch.setattr(faiss.IndexRaBitQ, call, counted)
    return made


@pytest.mark.parametrize("bits", [1, 4])
def test_an_upsert_that_fails_part_of_the_way_leaves_the_index_as_it_was(bits, monkeypatch, exact_rotation):
    """A change is several FAISS calls, on two indexes when there is a fine code. Whichever of
    them fails, the index holds exactly what it held before, and the error is raised."""
    v = for_index(_vecs(400, dim=32), 32)
    kept = list(range(101, 301))

    def built():
        vs = CompactVectorStore(32, bits=bits, rescore=8)
        _bound(vs, kept, v[100:300])
        return vs

    vs = built()
    before, found = vs.to_bytes(), [vs.search(q, 5) for q in v[:300:30]]
    upserts = {"new ids": [301, 302], "ids it holds": [150, 151], "ids older than the newest": [5, 6],
               "all of these": [350, 150, 50]}
    failed = set()
    for what, ids in upserts.items():
        for call in ("add", "remove_ids", "permute_entries"):
            for nth in (1, 2):
                with monkeypatch.context() as m:
                    made = _fail_the(m, call, nth)
                    try:
                        vs.upsert(ids, v[np.asarray(ids) - 1])
                    except MemoryError:
                        failed.add((what, call, nth))
                if (what, call, nth) not in failed:
                    vs = built()  # this upsert makes that call less often: it went through
                    continue
                assert len(made) == nth and vs.ids() == set(kept) and vs.to_bytes() == before
                assert [index.ntotal for index in vs._indexes] == [200] * len(vs._indexes)
                assert [vs.search(q, 5) for q in v[:300:30]] == found
    calls = {  # what each of these upserts asks of FAISS, once for each of its indexes
        "new ids": {"add"}, "ids it holds": {"remove_ids", "add", "permute_entries"},
        "ids older than the newest": {"add", "permute_entries"}, "all of these": {"remove_ids", "add", "permute_entries"},
    }
    every = {(what, call, nth) for what in calls for call in calls[what] for nth in range(1, len(vs._indexes) + 1)}
    assert failed == every
    for ids in upserts.values():  # and when nothing fails, the index is the one built once from the same vectors
        vs.upsert(ids, v[np.asarray(ids) - 1])
    final = sorted(set(kept) | {i for ids in upserts.values() for i in ids})
    once = CompactVectorStore(32, bits=bits, rescore=8)
    once.upsert(final, v[np.asarray(final) - 1])
    assert vs._ids.tolist() == final and vs.to_bytes() == once.to_bytes()


def test_the_store_adds_the_vectors_again_after_an_upsert_that_failed(tmp_path, monkeypatch):
    """The rows are committed before the index takes them. When the index fails to, the write
    raises, the index is as it was, and the next search brings it up to the rows by vector id."""
    s = _open(tmp_path / "idx", "compact")
    _seed(s, 60)
    with monkeypatch.context() as m:
        _fail_the(m, "add", 2)  # the fine index, after the coarse one took the codes
        with pytest.raises(MemoryError):
            _seed(s, 5, seed=7, prefix="g")
    assert s.counts()["vectors"]["code"] == 65 and len(s._types["code"].store) == 60
    assert _same_as_brute_force(s) and _in_sync(s) and len(s._types["code"].store) == 65
    _seed(s, 5, seed=8, prefix="h")
    assert _same_as_brute_force(s) and _in_sync(s)
    s.close()


def test_search_needs_the_stored_vectors():
    vs = CompactVectorStore(8)
    vs.upsert([1], for_index(_vecs(1, dim=8), 8))
    with pytest.raises(RuntimeError, match="bind"):
        vs.search(_vecs(1, dim=8)[0], 1)


def test_a_faiss_the_codes_were_not_checked_against_is_refused_with_a_sentence(monkeypatch, tmp_path):
    monkeypatch.setattr(faiss, "__version__", "1.14.0")
    for build in (lambda: CompactVectorStore(8), lambda: CompactVectorStore.bytes_per_vector(8),
                  lambda: vector_backend_class("compact"), lambda: Store(tmp_path / "idx", vector_backend="compact")):
        with pytest.raises(RuntimeError, match='vector_backend = "compact" needs FAISS 1.15.1 or newer'):
            build()
    assert vector_backend_class("faiss") is FaissVectorStore


# ---------------------------------------------------------------- 20,000 vectors through the store


def test_twenty_thousand_clustered_vectors_keep_the_exact_top_ten(tmp_path):
    docs, queries = _clustered(200, 100, 128, 1.0)
    store = Store(tmp_path / "idx", vector_backend="faiss")
    with store.transaction():
        store.ensure_vec_type("code", EMBEDDER)
    store.put_vectors("code", EMBEDDER, [VectorRow(i + 1, 0, 1, 0, 1, f"h{i}") for i in range(len(docs))], docs)
    rng = np.random.default_rng(3)
    filters = [None] * 40 + [
        rng.choice(np.arange(1, len(docs) + 1), int(share * len(docs)), replace=False).tolist()
        for share in (0.01, 0.1, 0.5, 1.0) for _ in range(15)
    ]
    exact = [store.vector_search("code", q, 10, allowed) for q, allowed in zip(queries, filters)]
    store.use_vector_backend("compact", COMPACT)  # the same rows, the other index: nothing is embedded
    assert isinstance(store._type_index("code").store, CompactVectorStore)
    overlap = []
    for q, allowed, want in zip(queries, filters, exact):
        got = store.vector_search("code", q, 10, allowed)
        assert len(got) == 10 and (allowed is None or {h.chunk_id for h in got} <= set(allowed))
        scores = {h.chunk_id: h.score for h in want}
        assert all(h.score == pytest.approx(scores[h.chunk_id], abs=1e-5) for h in got if h.chunk_id in scores)
        overlap.append(len({h.chunk_id for h in got} & {h.chunk_id for h in want}) / 10)
    assert np.mean(overlap[:40]) >= 0.99 and np.mean(overlap[40:]) >= 0.99
    ti = store._type_index("code")
    assert ti.table.nbytes == 32 * len(docs)  # the bookkeeping: 32 bytes per vector
    # saved: 8 bytes of id and two codes per vector (128 numbers: 24 bytes at 1 bit and 84 at 4, against 256 at 2 bytes each)
    assert ti.store.code_bytes == 24 + 84 and len(ti.store.to_bytes()) < len(docs) * 117
    store.close()


# ---------------------------------------------------------------- the config and the service


def test_config_reads_the_compact_table():
    cfg = config_from_dict({"vector_backend": "compact", "compact": {"bits": 2, "dim": 256, "rescore": 500}})
    assert (cfg.compact.bits, cfg.compact.dim, cfg.compact.rescore) == (2, 256, 500)
    assert cfg.vector_options() == {"bits": 2, "dim": 256, "rescore": 500}
    default = config_from_dict({"vector_backend": "compact"})
    assert default.vector_options() == {"bits": 4, "dim": 0, "rescore": 200}
    assert Config(vector_backend="faiss").vector_options() == {}
    assert Config(vector_backend="auto").vector_options() == {"bits": 4, "dim": 0, "rescore": 200}  # for when it picks compact
    assert config_from_dict({"vector_backend": "faiss", "compact": {"dim": 64}}).vector_options() == {}


@pytest.mark.parametrize("table, message", [
    ({"bits": 0}, "bits must be 1 to 8"), ({"bits": 9}, "bits must be 1 to 8"),
    ({"dim": -1}, f"dim must be 0 to {COMPACT_MAX_DIM}"),
    ({"dim": COMPACT_MAX_DIM + 1}, f"dim must be 0 to {COMPACT_MAX_DIM}"),
    ({"rescore": 0}, "rescore must be 1 or more"), ({"rescore": 2.5}, "whole numbers"),
    ({"bits": True}, "whole numbers"),
    ({"rescor": 100}, "unknown \\[compact\\] settings"),
])
def test_bad_compact_settings_are_refused_when_the_config_is_read(table, message):
    with pytest.raises(ValueError, match=message):
        config_from_dict({"vector_backend": "compact", "compact": table})


def test_switching_to_compact_and_changing_its_options_re_embeds_nothing(sample_repo, tmp_path, fake_config, recorder):
    def index(backend, **compact):
        cfg = config_from_dict({"vector_backend": backend, "compact": compact, "vectors": {
            "code": {"model": "fake:64"}, "usage": {"model": "fake:64"}}})
        store = Store(tmp_path / "index", vector_backend=backend, vector_options=cfg.vector_options())
        stats = Indexer(sample_repo, store, cfg, embedder_factory=lambda m, c: recorder).update()
        return store, stats

    def scores(store):
        return [round(h.score, 5) for h in store.vector_search("code", recorder.embed_queries(["session"])[0], 20)]

    store, first = index("faiss")
    want, n = scores(store), len(recorder.documents)
    assert sum(first.model_embedded.values()) > 0
    store.close()
    names = set()
    for options in ({}, {"dim": 32}, {"dim": 32, "rescore": 50}, {"bits": 2, "dim": 32, "rescore": 50}):
        store, stats = index("compact", **options)
        assert stats.queued == 0 and sum(stats.embedded.values()) == 0 and len(recorder.documents) == n
        assert scores(store) == want  # a small index: every vector is scored exactly
        backend = store._type_index("code").store
        assert isinstance(backend, CompactVectorStore)
        made_with = {"bits": backend.bits, "dim": options.get("dim", 0), "rescore": backend.rescore}
        assert made_with == {"bits": 4, "dim": 0, "rescore": 200, **options}
        assert backend.code_dim == options.get("dim", 64)
        store.load_vectors()  # what a server does at start: every type's index is built with the new options
        store.save_vectors()
        note = json.loads((tmp_path / "index" / "vec_code.json").read_text())
        assert note["backend"] == "compact" and note["options"] == made_with
        names = {p.name for p in (tmp_path / "index").glob("vec_*")}
        store.close()
    # the FAISS files are gone
    assert names == {"vec_code.rabitq", "vec_code.json", "vec_usage.rabitq", "vec_usage.json"}


def test_a_saved_file_made_with_other_options_is_rebuilt_and_one_with_the_same_is_read(tmp_path, monkeypatch):
    s = _open(tmp_path / "idx", "compact", dim=8)
    _seed(s, 30)
    s.save_vectors()
    s.close()
    rebuilds = []
    rebuild = Store._rebuild
    monkeypatch.setattr(Store, "_rebuild", lambda self, *a: rebuilds.append(a) or rebuild(self, *a))
    for options, rebuilt in (({"dim": 8}, 0), ({"dim": 4}, 1), ({"dim": 8, "rescore": 50}, 2), ({"bits": 2}, 3)):
        s = _open(tmp_path / "idx", "compact", **options)
        backend = s._type_index("code").store
        assert len(rebuilds) == rebuilt and _same_as_brute_force(s)
        made_with = (options.get("bits", 4), options.get("dim", 16), options.get("rescore", 200))
        assert (backend.bits, backend.code_dim, backend.rescore) == made_with
        s.close()  # not saved: the file on disk is still the first one
    s = Store(tmp_path / "idx", vector_backend="faiss")  # and the exact backend does not read a compact file
    assert isinstance(s._type_index("code").store, FaissVectorStore) and len(rebuilds) == 4
    s.close()


def test_the_service_follows_the_compact_settings_in_the_config_file(sample_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    svc = CodememService(sample_repo, index_dir=tmp_path / "idx")
    try:
        svc.update()
        found = [r.qualname for r in svc.search("revoke session", k=5, signals=["code"]).results]
        (sample_repo / ".codemem.toml").write_text('vector_backend = "compact"\n[compact]\ndim = 32\n')
        svc._reload_config()
        assert svc.store.vector_backend == "compact"
        assert svc.store.vector_options == {"bits": 4, "dim": 32, "rescore": 200}
        assert [r.qualname for r in svc.search("revoke session", k=5, signals=["code"]).results] == found
        first = svc.store._type_index("code").store
        assert isinstance(first, CompactVectorStore) and first.code_dim == 32
        (sample_repo / ".codemem.toml").write_text('vector_backend = "compact"\n[compact]\ndim = 32\nrescore = 64\n')
        svc._reload_config()
        second = svc.store._type_index("code").store
        assert second is not first and second.rescore == 64  # rebuilt from the rows, with the new options
        assert sum(svc.update().model_embedded.values()) == 0
        (sample_repo / ".codemem.toml").write_text('vector_backend = "compact"\n[compact]\nbits = 99\n')
        svc._reload_config()  # a config that is refused: the current one stays
        assert svc.config.compact.rescore == 64 and svc.store._type_index("code").store is second
    finally:
        svc.close()
