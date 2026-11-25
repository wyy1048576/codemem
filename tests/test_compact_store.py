"""The compact search index (docs/architecture.md §5).

First the scenarios of the vector store on both backends, each held to a brute-force search over
the stored rows. Then what only the compact index does: candidates from codes and scores from
the rows, its saved file, and the checks in front of every FAISS call.
"""

import json
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
COMPACT = {"bits": 1, "dim": 0, "rescore": 200}
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


def test_a_damaged_file_is_rebuilt_from_the_rows(tmp_path, backend):
    s = _open(tmp_path / "idx", backend)
    _seed(s, 20)
    s.save_vectors()
    s.close()
    path = tmp_path / "idx" / json.loads((tmp_path / "idx" / "vec_code.json").read_text())["file"]
    for damaged in (b"garbage", path.read_bytes()[:-9], b""):
        path.write_bytes(damaged)
        s2 = _open(tmp_path / "idx", backend)
        assert _same_as_brute_force(s2) and _in_sync(s2)
        s2.close()


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
    scan = vs._scan
    vs._scan = lambda q, size, allowed: asked.append(size) or scan(q, size, allowed)
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
    for i in vs._scan(q, 8, None).tolist():  # every candidate of that search loses its row
        del rows[i]
    hits = vs.search(q, 2)
    assert len(hits) == 2 and not {i for i, _ in hits} & set(first) and all(i in rows for i, _ in hits)
    rows.clear()
    assert vs.search(q, 2) == []


def test_ties_at_the_candidate_cut_are_all_kept():
    """Copies of one vector have one code. A cut through them takes every copy, so at 1 bit the
    candidates do not depend on the order the codes are held in: the same vectors under other ids
    (as in another database) give the same candidates."""
    v = for_index(_vecs(300, dim=32), 32)
    v[100:160] = v[100]
    other_ids = np.random.default_rng(1).permutation(300) + 1  # vector j has id other_ids[j]: another order
    a, b = CompactVectorStore(32, rescore=8), CompactVectorStore(32, rescore=8)
    _bound(a, range(1, 301), v)
    _bound(b, other_ids.tolist(), v)
    vector_of = {int(i): j + 1 for j, i in enumerate(other_ids)}
    in_a = set(a._scan(v[100], 8, None).tolist())
    in_b = {vector_of[i] for i in b._scan(v[100], 8, None).tolist()}
    assert set(range(101, 161)) <= in_a and len(in_a) < 80 and in_a == in_b
    for q in for_index(_vecs(20, dim=32, seed=6), 32):
        assert set(a._scan(q, 8, None).tolist()) == {vector_of[i] for i in b._scan(q, 8, None).tolist()}
    assert [i for i, _ in a.search(v[100], 2)] == [101, 102]


def _codes(vs):
    table = faiss.vector_to_array(vs._index.codes).reshape(len(vs), -1)
    return {int(i): bytes(code) for i, code in zip(vs._ids, table)}


@pytest.mark.parametrize("bits", [1, 4])
def test_an_index_patched_step_by_step_is_the_index_rebuilt_from_the_rows(bits):
    """The same codes in the same order, whatever edits it went through: the same bytes when saved,
    and so the same candidates, also at more than 1 bit, where FAISS's scan depends on the order."""
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
        assert patched._scan(q, 16, None).tolist() == rebuilt._scan(q, 16, None).tolist()


@pytest.mark.parametrize("options", [{}, {"bits": 2}, {"bits": 4, "dim": 16}, {"dim": 24}])
def test_the_saved_file_holds_ids_and_codes_and_reads_back(options):
    v = for_index(_vecs(300, dim=40), 40)
    vs = CompactVectorStore(40, rescore=16, **options)
    rows = _bound(vs, range(1, 301), v)
    vs.remove(range(1, 20))
    data = vs.to_bytes()
    code_bytes = vs._index.code_size
    assert len(data) < len(vs) * (code_bytes + 8) + 600  # 8 bytes of id and one code per vector, and a small head
    back = CompactVectorStore.from_bytes(data, rescore=16, **options)
    back.bind(lambda wanted: (np.asarray(wanted, dtype=np.int64), np.stack([rows[int(i)] for i in wanted])))
    assert back.ids() == vs.ids() and (back.dim, back.code_dim, back.bits) == (vs.dim, vs.code_dim, vs.bits)
    assert back._index.thisown  # the object FAISS gave owns the index: nothing else points into it
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

    def saved(index, count, ids):
        body = np.asarray(ids, dtype="<i8").tobytes() + faiss.serialize_index(index).tobytes()
        head = {"dim": 16, "code_dim": 16, "bits": 1, "count": count, "rotation": CompactVectorStore(16)._rotation_id,
                "crc32": zlib.crc32(body)}
        return json.dumps(head).encode() + b"\n" + body

    v = np.ascontiguousarray(for_index(_vecs(6, dim=16), 16))
    right = faiss.IndexRaBitQ(16, faiss.METRIC_INNER_PRODUCT, 1)
    right.train(np.zeros((1, 16), dtype=np.float32))
    right.add(v)
    assert len(CompactVectorStore.from_bytes(saved(right, 6, range(6)))) == 6
    centred = faiss.IndexRaBitQ(16, faiss.METRIC_INNER_PRODUCT, 1)
    centred.train(v)  # a learned centre: its codes are not the ones this store makes
    centred.add(v)
    flat = faiss.IndexFlatIP(16)
    flat.add(v)
    l2 = faiss.IndexRaBitQ(16, faiss.METRIC_L2, 1)
    l2.train(np.zeros((1, 16), dtype=np.float32))
    l2.add(v)
    for index, count, ids in ((right, 5, range(5)), (right, 7, range(7)), (centred, 6, range(6)), (flat, 6, range(6)),
                              (l2, 6, range(6)), (right, 6, [0, 1, 2, 4, 3, 5]), (right, 6, [0, 1, 2, 2, 3, 4])):
        with pytest.raises(ValueError, match="not the one its first line describes|as many vector ids|not in order"):
            CompactVectorStore.from_bytes(saved(index, count, ids))


# ---------------------------------------------------------------- the checks in front of FAISS


@pytest.mark.parametrize("args, kwargs", [
    ((0,), {}), ((-8,), {}), ((8.0,), {}), ((True,), {}),
    ((8,), {"bits": 0}), ((8,), {"bits": 9}), ((8,), {"bits": 1.0}),
    ((8,), {"dim": -1}), ((8,), {"dim": COMPACT_MAX_DIM + 1}),
    ((8,), {"rescore": 0}), ((8,), {"rescore": "200"}),
])
def test_options_faiss_cannot_take_are_refused_with_a_sentence(args, kwargs):
    with pytest.raises(ValueError, match="whole numbers|need an index dim of 1 or more"):
        CompactVectorStore(*args, **kwargs)


@pytest.mark.parametrize("dim, code_dim, expect", [(8, 0, 8), (8, 4, 4), (8, 64, 8), (5, 0, 5), (65, 33, 33)])
def test_the_code_covers_the_first_numbers_of_any_length(dim, code_dim, expect):
    vs = CompactVectorStore(dim, dim=code_dim, rescore=4)
    v = for_index(_vecs(60, dim=dim), dim)
    _bound(vs, range(1, 61), v)
    assert vs.code_dim == vs._index.d == expect and vs._index.code_size == -(-expect // 8) + 8
    hits = vs.search(v[7], 3)
    assert len(hits) == 3 and hits[0][1] == pytest.approx(max(float(s) for s in v @ v[7]), abs=1e-6)


def test_an_index_wider_than_the_longest_code_is_coded_on_its_first_numbers(monkeypatch):
    monkeypatch.setattr("codemem.store.COMPACT_MAX_DIM", 16)
    vs = CompactVectorStore(40)
    assert (vs.dim, vs.code_dim, vs._index.d) == (40, 16, 16)
    with pytest.raises(ValueError, match="dim 0 to 16"):
        CompactVectorStore(40, dim=17)


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
    assert len(vs) == 40 and vs._index.ntotal == 40
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


def test_search_needs_the_stored_vectors():
    vs = CompactVectorStore(8)
    vs.upsert([1], for_index(_vecs(1, dim=8), 8))
    with pytest.raises(RuntimeError, match="bind"):
        vs.search(_vecs(1, dim=8)[0], 1)


def test_a_faiss_the_codes_were_not_checked_against_is_refused_with_a_sentence(monkeypatch, tmp_path):
    monkeypatch.setattr(faiss, "__version__", "1.14.0")
    for build in (lambda: CompactVectorStore(8), lambda: vector_backend_class("compact"),
                  lambda: Store(tmp_path / "idx", vector_backend="compact")):
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
    assert len(ti.store.to_bytes()) < len(docs) * 34  # 16 bytes of bits, 8 of RaBitQ's numbers, 8 of id
    store.close()


# ---------------------------------------------------------------- the config and the service


def test_config_reads_the_compact_table():
    cfg = config_from_dict({"vector_backend": "compact", "compact": {"bits": 2, "dim": 256, "rescore": 500}})
    assert (cfg.compact.bits, cfg.compact.dim, cfg.compact.rescore) == (2, 256, 500)
    assert cfg.vector_options() == {"bits": 2, "dim": 256, "rescore": 500}
    default = config_from_dict({"vector_backend": "compact"})
    assert default.vector_options() == {"bits": 1, "dim": 0, "rescore": 200}
    assert Config(vector_backend="faiss").vector_options() == {}
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


def test_compact_settings_are_index_settings_only_for_the_compact_backend():
    plain = Config(vector_backend="faiss").index_settings()
    assert "compact" not in plain and "vector_backend" not in plain
    unused = config_from_dict({"vector_backend": "faiss", "compact": {"dim": 256}})
    assert unused.index_settings() == plain  # options of a backend that is not in use change nothing
    a = config_from_dict({"vector_backend": "compact"}).index_settings()
    b = config_from_dict({"vector_backend": "compact", "compact": {"dim": 256}}).index_settings()
    assert a["vector_backend"] == "compact" and a["compact"] == {"bits": 1, "dim": 0, "rescore": 200}
    assert b["compact"]["dim"] == 256
    rest = lambda settings: {k: v for k, v in settings.items() if k not in ("compact", "vector_backend")}  # noqa: E731
    assert rest(a) == rest(b) == plain and b["vector_backend"] == "compact"


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
        assert made_with == {"bits": 1, "dim": 0, "rescore": 200, **options}
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
        made_with = (options.get("bits", 1), options.get("dim", 16), options.get("rescore", 200))
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
        assert svc.store.vector_options == {"bits": 1, "dim": 32, "rescore": 200}
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
