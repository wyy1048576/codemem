"""Loading a search index, and who waits for it (docs/architecture.md §5).

A rebuild reads and codes every stored vector: seconds to half a minute on a large index. It runs
outside the vector lock, so writes, status calls and keyword answers go on meanwhile; one thread
loads a vector type, and the others that need it wait for that thread. Here a gate holds every
rebuild for as long as a test needs it to take.
"""

import json
import threading
import time

import anyio
import numpy as np
import pytest

from codemem.embedder import l2_normalize
from codemem.indexer import Indexer
from codemem.schema import Chunk, text_hash
from codemem.service import CodememService
from codemem.store import CompactVectorStore, FaissVectorStore, Store, VectorRow

EMBEDDER = "fake|doc"
COMPACT = {"bits": 4, "dim": 0, "rescore": 200}


def _vecs(n, dim=16, seed=0):
    return l2_normalize(np.random.default_rng(seed).normal(size=(n, dim)))


def _seed(store, n, prefix="f", seed=0):
    with store.transaction():
        ids = []
        for i in range(n):
            name, code = f"{prefix}{i:04d}", f"def {prefix}{i:04d}():\n    return 1"
            ids.append(store.upsert_chunk(Chunk(
                key=f"pkg/{prefix}.py::{name}", path=f"pkg/{prefix}.py", qualname=name, name=name, kind="function",
                start_line=1, end_line=2, signature=f"def {name}():", docstring="", code=code,
                content_hash=text_hash(code))))
        store.ensure_vec_type("code", EMBEDDER)
    store.put_vectors("code", EMBEDDER, [VectorRow(c, 0, 1, 0, 1, f"h{c}") for c in ids], _vecs(n, seed=seed))
    return ids


def _in_sync(store):
    ti = store._type_index("code")
    rows = {vid for vid, _ in store.vector_rows("code").values()}
    return ti.store.ids() == rows and set(ti.table["vector"].tolist()) == rows


class Gate:
    """Holds every rebuild from the rows until it is opened, and counts them."""

    def __init__(self, monkeypatch):
        self.started, self.opened, self.rebuilds = threading.Event(), threading.Event(), 0
        rebuild = Store._rebuild

        def held(store, *args):
            self.rebuilds += 1
            self.started.set()
            assert self.opened.wait(30), "the test never opened the gate"
            return rebuild(store, *args)

        monkeypatch.setattr(Store, "_rebuild", held)

    def open(self):
        self.opened.set()


def _in_thread(fn):
    """Run fn in a thread; the returned function joins it and gives its result, or raises its error."""
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001
            box["error"] = e

    thread = threading.Thread(target=run)
    thread.start()

    def result(timeout=30):
        thread.join(timeout)
        assert not thread.is_alive(), "the thread is still waiting"
        if "error" in box:
            raise box["error"]
        return box["value"]

    return result


@pytest.fixture
def unsaved(tmp_path):
    """An index of 40 vectors whose search index was never saved: the next open rebuilds it."""
    store = Store(tmp_path / "idx", vector_backend="faiss")
    ids = _seed(store, 40)
    store.close()
    store = Store(tmp_path / "idx", vector_backend="faiss")
    yield store, ids
    store.close()


# ---------------------------------------------------------------- the store


def test_writes_and_status_do_not_wait_for_an_index_that_is_loading(unsaved, monkeypatch):
    store, ids = unsaved
    gate = Gate(monkeypatch)
    loading = _in_thread(lambda: store._type_index("code"))
    assert gate.started.wait(10)
    t = time.monotonic()
    assert not store.vectors_loaded()
    assert store.search_index_status()["types"]["code"]["vectors"] == 40
    new = _seed(store, 3, prefix="late", seed=5)  # commits while the index loads
    gone = store.vector_rows("code")[(ids[0], 0)][0]
    store.delete_vectors("code", [gone])
    assert time.monotonic() - t < 5 and gate.rebuilds == 1 and not gate.opened.is_set()
    assert store.counts()["vectors"]["code"] == 42
    gate.open()
    ti = loading()
    # what was written meanwhile is in the index it installed: applied at the end, by vector id
    assert len(ti.store) == 42 and _in_sync(store) and store.vectors_loaded()
    hits = store.vector_search("code", _vecs(3, seed=5)[1], 1)
    assert [h.chunk_id for h in hits] == [new[1]]
    assert gate.rebuilds == 1


def test_threads_that_need_an_index_wait_for_the_one_that_loads_it(unsaved, monkeypatch):
    store, ids = unsaved
    gate = Gate(monkeypatch)
    q = _vecs(40)[7]
    searches = [_in_thread(lambda: store.vector_search("code", q, 3)) for _ in range(4)]
    assert gate.started.wait(10)
    time.sleep(0.2)  # the other three have asked by now, and wait
    gate.open()
    results = [search() for search in searches]
    assert gate.rebuilds == 1 and all(r == results[0] for r in results) and results[0][0].chunk_id == ids[7]


def test_an_index_that_was_loading_for_another_backend_is_not_installed(unsaved, monkeypatch):
    store, _ = unsaved
    gate = Gate(monkeypatch)
    loading = _in_thread(lambda: store._type_index("code"))
    assert gate.started.wait(10)
    store.use_vector_backend("compact", COMPACT)  # the config changed while the exact index was loading
    gate.open()
    ti = loading()
    assert isinstance(ti.store, CompactVectorStore) and gate.rebuilds == 2 and _in_sync(store)


def test_a_load_that_fails_reaches_everyone_who_waited_for_it(unsaved, monkeypatch):
    store, _ = unsaved
    started, release = threading.Event(), threading.Event()

    def broken(self, *args):
        started.set()
        release.wait(30)
        raise RuntimeError("no index today")

    monkeypatch.setattr(Store, "_rebuild", broken)
    waiting = [_in_thread(lambda: store._type_index("code")) for _ in range(3)]
    assert started.wait(10)
    release.set()
    for result in waiting:
        with pytest.raises(RuntimeError, match="no index today"):
            result()
    assert not store._loading and not store.vectors_loaded()


def test_a_write_to_an_index_that_is_not_in_memory_leaves_it_for_its_first_use(tmp_path, monkeypatch):
    path = tmp_path / "idx"
    store = Store(path, vector_backend="faiss")
    with store.transaction():
        store.ensure_vec_type("code", EMBEDDER)
    assert store._types == {}
    ids = _seed(store, 20)  # a type's first vectors start its index, and later batches add to it
    first = store._types["code"]
    more = _seed(store, 5, prefix="g", seed=1)
    assert store._types["code"] is first and len(first.store) == 25
    store.save_vectors()
    store.close()

    loads = []
    for name in ("_load_saved", "_rebuild"):
        monkeypatch.setattr(Store, name, lambda self, *a, name=name, real=getattr(Store, name): loads.append(name) or real(self, *a))
    store = Store(path, vector_backend="faiss")
    late = _seed(store, 4, prefix="late", seed=2)  # the index of the earlier vectors is not loaded for this
    assert store._types == {} and loads == [] and not store.vectors_loaded()
    hit = store.vector_search("code", _vecs(4, seed=2)[3], 1)[0]  # its first use: the file, and the rows it lacks
    assert hit.chunk_id == late[3] and loads == ["_load_saved"] and _in_sync(store)
    assert len(store._types["code"].store) == 29 and len(ids) + len(more) == 25
    store.close()


def test_load_eta_follows_the_pace_of_the_rebuild(unsaved):
    store, _ = unsaved
    assert store.load_eta() is None
    store._progress["code"] = (time.monotonic() - 2.0, 1000, 3000)  # 1,000 of 3,000 vectors in 2 s
    assert store.load_eta() == pytest.approx(4.0, abs=0.2)
    store._progress["code"] = (time.monotonic() - 2.0, 0, 3000)  # it has only begun: no pace yet
    assert store.load_eta() is None
    store._progress.clear()


# ---------------------------------------------------------------- an update that saves


def _indexed(path, repo, cfg, recorder, **store_kwargs):
    store = Store(path, **store_kwargs)
    stats = Indexer(repo, store, cfg, embedder_factory=lambda m, c: recorder).update()
    return store, stats


def _files(path):
    return sorted(p.name for p in path.glob("vec_*"))


def test_an_update_that_saves_leaves_the_files_the_next_start_reads(sample_repo, tmp_path, fake_config, recorder, monkeypatch):
    path = tmp_path / "index"
    fake_config.vector_backend = "faiss"
    store, first = _indexed(path, sample_repo, fake_config, recorder, vector_backend="faiss")
    assert sum(first.embedded.values()) > 0 and _files(path) == ["vec_code.faiss", "vec_code.json", "vec_usage.faiss", "vec_usage.json"]
    store.close()

    store, stats = _indexed(path, sample_repo, fake_config, recorder, vector_backend="faiss")
    assert store._types == {} and sum(stats.embedded.values()) == 0  # nothing changed, the files are current: nothing is loaded
    store.close()

    # An index from before a saved index named its database: its files are rebuilt in the update,
    # and the start after it reads them.
    for note_path in path.glob("vec_*.json"):
        note = json.loads(note_path.read_text())
        del note["database"]
        note_path.write_text(json.dumps(note))
    store, stats = _indexed(path, sample_repo, fake_config, recorder, vector_backend="faiss")
    assert set(store._types) == {"code", "usage"} and sum(stats.embedded.values()) == 0
    assert all("database" in json.loads(p.read_text()) for p in path.glob("vec_*.json"))
    store.close()

    # Another backend: the update writes its files and removes the others.
    fake_config.vector_backend = "compact"
    store, stats = _indexed(path, sample_repo, fake_config, recorder, vector_backend="compact", vector_options=COMPACT)
    assert sum(stats.embedded.values()) == 0
    assert _files(path) == ["vec_code.json", "vec_code.rabitq", "vec_usage.json", "vec_usage.rabitq"]
    store.close()
    monkeypatch.setattr(Store, "_rebuild", lambda self, *a: pytest.fail("the saved files should have been read"))
    store = Store(path, vector_backend="compact", vector_options=COMPACT)
    store.load_vectors()
    assert isinstance(store._type_index("code").store, CompactVectorStore)
    store.close()


def test_an_update_that_saves_applies_the_auto_rule_again(sample_repo, tmp_path, fake_config, recorder, monkeypatch):
    """An index that outgrew the budget while it was built is compact, in memory and on disk, when
    the update that built it ends: the eval and the CLI see the saving in the run that builds."""
    path = tmp_path / "index"
    budget = {"bytes": 10**9}
    monkeypatch.setattr("codemem.store.vector_memory_budget", lambda setting_mb=0: (budget["bytes"], "a test's budget"))
    fake_config.vector_backend = "auto"
    store, _ = _indexed(path, sample_repo, fake_config, recorder, vector_backend="auto", vector_options=COMPACT)
    assert isinstance(store._type_index("code").store, FaissVectorStore) and "vec_code.faiss" in _files(path)
    budget["bytes"] = 100  # as if the build had grown it past the budget
    stats = Indexer(sample_repo, store, fake_config, embedder_factory=lambda m, c: recorder).update()
    assert sum(stats.embedded.values()) == 0
    assert isinstance(store._type_index("code").store, CompactVectorStore) and store.search_index_status()["index"] == "compact"
    assert _files(path) == ["vec_code.json", "vec_code.rabitq", "vec_usage.json", "vec_usage.rabitq"]
    store.save_vectors()  # a save by itself (the service's, when the index is quiet) does not pick again
    budget["bytes"] = 10**9
    store.save_vectors()
    assert isinstance(store._type_index("code").store, CompactVectorStore)
    store.close()


# ---------------------------------------------------------------- the service


def _rebuilt_at_start(sample_repo, tmp_path, **config):
    """A service on an index whose search indexes have to be rebuilt when it starts."""
    lines = [f"{k} = {json.dumps(v)}" for k, v in config.items()]
    (sample_repo / ".codemem.toml").write_text("\n".join(lines) + "\n")
    built = CodememService(sample_repo, index_dir=tmp_path / "idx")
    built.update()
    built.close()
    for p in (tmp_path / "idx").glob("vec_*"):
        p.unlink()
    return CodememService(sample_repo, index_dir=tmp_path / "idx")


def test_an_mcp_search_answers_from_keywords_while_the_search_index_is_rebuilt(sample_repo, tmp_path, monkeypatch):
    from mcp import Client

    from codemem.server import build_server

    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    svc = _rebuilt_at_start(sample_repo, tmp_path, catchup_budget_ms=300)
    gate = Gate(monkeypatch)
    try:
        svc.start()  # with prewarm: the search indexes load in the background
        server = build_server(svc)

        async def run():
            async with Client(server) as client:
                assert gate.started.wait(10)
                t = time.monotonic()
                text = (await client.call_tool("search_code", {"query": "revoke session", "k": 3})).content[0].text
                assert time.monotonic() - t < 2.0  # within the 0.3 s limit, however long the rebuild takes
                assert "revoke_session" in text and "still loading" in text  # keyword results, and the note
                status = (await client.call_tool("index_status", {})).content[0].text
                assert "search index: " in status  # and status does not wait either
                chunk = (await client.call_tool("get_chunk", {"ref": "auth/sessions.py::revoke_session"})).content[0].text
                assert "revoke_session" in chunk
                assert time.monotonic() - t < 4.0 and not svc.store.vectors_loaded()
                gate.open()
                for _ in range(200):
                    if svc.store.vectors_loaded():
                        break
                    await anyio.sleep(0.05)
                text = (await client.call_tool("search_code", {"query": "revoke session", "k": 3})).content[0].text
                assert "revoke_session" in text and "still loading" not in text

        anyio.run(run)
        assert svc.search("revoke session", k=3, wait_for_models=False).signals == ["bm25", "code", "usage"]
    finally:
        gate.open()
        svc.close()


def test_a_search_that_waits_for_the_models_waits_for_the_search_index_too(sample_repo, tmp_path, monkeypatch):
    """The CLI and the eval: a search returns the vectors' results, whoever is loading the index."""
    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    svc = _rebuilt_at_start(sample_repo, tmp_path)
    gate = Gate(monkeypatch)
    try:
        prewarm = _in_thread(svc.prewarm)
        assert gate.started.wait(10)
        search = _in_thread(lambda: svc.search("revoke session", k=3))
        time.sleep(0.3)
        gate.open()
        resp = search()
        prewarm()
        assert resp.signals == ["bm25", "code", "usage"] and not resp.models_loading
        assert "revoke_session" in [r.qualname for r in resp.results] and gate.rebuilds == 2  # one for each vector type
    finally:
        gate.open()
        svc.close()


def test_a_search_does_not_wait_for_a_rebuild_that_will_not_end_in_time(sample_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    svc = _rebuilt_at_start(sample_repo, tmp_path, catchup_budget_ms=5000)
    gate = Gate(monkeypatch)
    try:
        prewarm = _in_thread(svc.prewarm)
        assert gate.started.wait(10)
        svc.store._progress["code"] = (time.monotonic() - 1.0, 100, 10_000)  # 99 s to go at this pace
        t = time.monotonic()
        resp = svc.search("revoke session", k=3, wait_for_models=False)
        assert time.monotonic() - t < 2.0 and resp.signals == ["bm25"] and resp.models_loading
        svc.store._progress["code"] = (time.monotonic() - 1.0, 9_900, 10_000)  # nearly there: worth the wait
        waited = _in_thread(lambda: svc.search("revoke session", k=3, wait_for_models=False))
        time.sleep(0.3)
        svc.store._progress.clear()
        gate.open()
        assert waited().signals == ["bm25", "code", "usage"]
        prewarm()
    finally:
        gate.open()
        svc.close()
