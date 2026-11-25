"""`vector_backend = "auto"`, the default: the exact search index while it fits a memory budget,
the compact one when it does not (docs/architecture.md §5).

The tests' indexes are small, so the budget is set in bytes here: an exact index of 16 numbers
takes 96 bytes a vector (FaissVectorStore.bytes_per_vector).
"""

import json
import logging

import faiss
import numpy as np
import pytest

import codemem.config as config_module
from codemem.config import Config, config_from_dict, physical_memory, vector_memory_budget
from codemem.embedder import l2_normalize
from codemem.render import format_status
from codemem.schema import Chunk, text_hash
from codemem.service import CodememService
from codemem.store import CompactVectorStore, FaissVectorStore, Store, VectorRow, prepare

EMBEDDER = "fake|doc"
COMPACT = {"bits": 4, "dim": 0, "rescore": 200}
PER_VECTOR = 96  # the exact index, at 16 numbers


def _vecs(n, dim=16, seed=0):
    return l2_normalize(np.random.default_rng(seed).normal(size=(n, dim)))


def _seed(store, n, vec_type="code", prefix="f", seed=0):
    """n chunks with one vector each."""
    with store.transaction():
        ids = []
        for i in range(n):
            name, code = f"{prefix}{i:04d}", f"def {prefix}{i:04d}():\n    return 1"
            ids.append(store.upsert_chunk(Chunk(
                key=f"pkg/{prefix}.py::{name}", path=f"pkg/{prefix}.py", qualname=name, name=name, kind="function",
                start_line=1, end_line=2, signature=f"def {name}():", docstring="", code=code,
                content_hash=text_hash(code))))
        store.ensure_vec_type(vec_type, EMBEDDER)
    store.put_vectors(vec_type, EMBEDDER, [VectorRow(c, 0, 1, 0, 1, f"h{c}") for c in ids], _vecs(n, seed=seed))
    return ids


def _auto(path, **kwargs):
    return Store(path, vector_backend="auto", vector_options=COMPACT, **kwargs)


def _budget(monkeypatch, n_bytes):
    monkeypatch.setattr("codemem.store.vector_memory_budget", lambda setting_mb=0: (n_bytes, "a test's budget"))


def _kinds(store):
    return {vec_type: type(store._type_index(vec_type).store) for vec_type in store.vec_types()}


def _exact_results(store, vec_type="code"):
    """Every search returns what a pass over the stored rows returns."""
    dim = store.vector_dim(vec_type)
    rows = store.conn.execute("SELECT chunk_id, data FROM vectors WHERE vec_type = ?", (vec_type,)).fetchall()
    stored = prepare(np.stack([np.frombuffer(r[1], dtype=np.float16) for r in rows]), dim)
    stored = stored.astype(np.float16).astype(np.float32)
    for seed in range(3):
        q = prepare(_vecs(1, seed=100 + seed), dim)[0]
        want = sorted(((float((v * q).sum()), -r[0]) for r, v in zip(rows, stored)), reverse=True)[:5]
        hits = store.vector_search(vec_type, q, 5)
        assert [h.chunk_id for h in hits] == [-c for _, c in want]
        assert [h.score for h in hits] == pytest.approx([s for s, _ in want], abs=1e-5)
    return True


def _saved(path):
    return sorted(p.name for p in path.glob("vec_*") if p.suffix != ".json")


# ---------------------------------------------------------------- the rule


def test_auto_is_exact_while_the_exact_indexes_fit_together_and_compact_when_they_do_not(tmp_path, monkeypatch):
    path = tmp_path / "idx"
    store = _auto(path)
    _seed(store, 100)
    _seed(store, 50, vec_type="usage", prefix="u", seed=1)
    store.close()
    need = 150 * PER_VECTOR  # both vector types count
    for budget, kind, name in ((need, FaissVectorStore, "faiss"), (need - 1, CompactVectorStore, "compact"),
                               (100 * PER_VECTOR, CompactVectorStore, "compact")):  # one type alone would fit: both are compact
        _budget(monkeypatch, budget)
        store = _auto(path)
        assert _kinds(store) == {"code": kind, "usage": kind}
        assert _exact_results(store) and _exact_results(store, "usage")
        status = store.search_index_status()
        assert (status["setting"], status["index"]) == ("auto", name)
        assert status["exact_mb"] == round(need / 1e6, 1) and status["budget_mb"] == round(budget / 1e6, 1)
        assert ("within the budget" in status["why"]) == (name == "faiss") and "a test's budget" in status["why"]
        assert {t: v["vectors"] for t, v in status["types"].items()} == {"code": 100, "usage": 50}
        store.close()


def test_auto_uses_the_compact_options_when_it_picks_the_compact_index(tmp_path, monkeypatch):
    _budget(monkeypatch, 1)
    store = Store(tmp_path / "idx", vector_backend="auto", vector_options={"bits": 2, "dim": 8, "rescore": 50})
    _seed(store, 60)
    backend = store._type_index("code").store
    assert isinstance(backend, CompactVectorStore) and (backend.bits, backend.code_dim, backend.rescore) == (2, 8, 50)
    store.save_vectors()
    note = json.loads((tmp_path / "idx" / "vec_code.json").read_text())
    assert note["backend"] == "compact" and note["options"] == {"bits": 2, "dim": 8, "rescore": 50}
    store.close()


def test_a_named_backend_is_used_whatever_the_budget(tmp_path, monkeypatch):
    for budget, name, kind in ((1, "faiss", FaissVectorStore), (10**12, "compact", CompactVectorStore)):
        _budget(monkeypatch, budget)
        store = Store(tmp_path / name, vector_backend=name)
        _seed(store, 30)
        assert _kinds(store) == {"code": kind}
        status = store.search_index_status()
        assert status["index"] == status["setting"] == name and status["why"] == f'vector_backend = "{name}"'
        assert "budget_mb" not in status and "next" not in status
        store.close()


def test_when_the_pick_differs_from_the_saved_index_it_is_rebuilt_from_the_rows(tmp_path, monkeypatch):
    """As for any change of backend: nothing is embedded, and the next save replaces the file."""
    path = tmp_path / "idx"
    _budget(monkeypatch, 10**9)
    store = _auto(path)
    _seed(store, 80)
    store.save_vectors()
    store.close()
    assert _saved(path) == ["vec_code.faiss"]
    rebuilds = []
    rebuild = Store._rebuild
    monkeypatch.setattr(Store, "_rebuild", lambda self, *a: rebuilds.append(a) or rebuild(self, *a))
    store = _auto(path)
    assert _kinds(store) == {"code": FaissVectorStore} and not rebuilds  # the pick is the saved one: the file is read
    store.close()
    _budget(monkeypatch, 80 * PER_VECTOR - 1)
    store = _auto(path)
    assert _kinds(store) == {"code": CompactVectorStore} and len(rebuilds) == 1 and _exact_results(store)
    store.save_vectors()
    store.close()
    assert _saved(path) == ["vec_code.rabitq"]
    store = _auto(path)
    assert _kinds(store) == {"code": CompactVectorStore} and len(rebuilds) == 1  # and that file is read
    store.close()


def test_a_compact_index_goes_back_to_exact_only_well_under_the_budget(tmp_path, monkeypatch):
    """An index near the budget does not change its search index at every start."""
    path = tmp_path / "idx"
    need = 100 * PER_VECTOR

    def opened(budget):
        _budget(monkeypatch, budget)
        store = _auto(path)
        kind, why = _kinds(store).get("code"), store.search_index_status()["why"]
        store.save_vectors()
        store.close()
        return kind, why

    _budget(monkeypatch, 10**9)
    store = _auto(path)
    _seed(store, 100)
    store.save_vectors()
    store.close()
    assert opened(need)[0] is FaissVectorStore  # it fits, exactly
    assert opened(need - 1)[0] is CompactVectorStore  # one byte over
    kind, why = opened(need + 1000)  # under the budget again, but not by much: it stays compact
    assert kind is CompactVectorStore and "goes back to exact under 80% of the budget" in why
    assert opened(int(need / 0.8) - 1)[0] is CompactVectorStore
    assert opened(int(need / 0.8) + 1)[0] is FaissVectorStore  # under 80% of the budget: exact again
    assert opened(need)[0] is FaissVectorStore  # and an exact index stays exact up to the whole budget
    assert _saved(path) == ["vec_code.faiss"]


def test_auto_picks_when_an_index_is_loaded_and_keeps_to_it_while_the_store_is_open(tmp_path, monkeypatch):
    path = tmp_path / "idx"
    _budget(monkeypatch, 100 * PER_VECTOR)
    store = _auto(path)
    _seed(store, 100)
    first = store._type_index("code").store
    assert isinstance(first, FaissVectorStore) and "next" not in store.search_index_status()
    _seed(store, 60, prefix="g", seed=2)  # the index grows past the budget while the store is open
    assert store._type_index("code").store is first and len(first) == 160 and _exact_results(store)
    status = store.search_index_status()
    assert status["index"] == "faiss" and status["next"]["index"] == "compact"
    assert "over the budget" in status["next"]["why"]
    store.save_vectors()
    store.close()
    assert _saved(path) == ["vec_code.faiss"]
    store = _auto(path)  # the next start
    assert _kinds(store) == {"code": CompactVectorStore} and _exact_results(store)
    assert "next" not in store.search_index_status()
    store.close()


def test_an_empty_index_starts_exact(tmp_path, monkeypatch):
    _budget(monkeypatch, 5 * PER_VECTOR)
    store = _auto(tmp_path / "idx")
    assert store.search_index_status()["index"] == "faiss" and store.search_index_status()["types"] == {}
    _seed(store, 40)  # built while the store is open: exact until the next start
    assert _kinds(store) == {"code": FaissVectorStore}
    store.close()


def test_on_an_older_faiss_auto_is_the_exact_index_and_only_a_named_compact_is_refused(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(faiss, "__version__", "1.9.0")
    _budget(monkeypatch, 1)  # nothing fits
    with caplog.at_level(logging.INFO, logger="codemem.store"):
        store = _auto(tmp_path / "idx")
        _seed(store, 30)
        assert _kinds(store) == {"code": FaissVectorStore} and _exact_results(store)
        assert "this FAISS, 1.9.0, cannot make the compact index" in store.search_index_status()["why"]
        store.save_vectors()
        store.close()
    said = [r for r in caplog.records if "cannot make the compact index" in r.getMessage()]
    assert said and all(r.levelno == logging.INFO for r in said)  # in the log, and no louder
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    with pytest.raises(RuntimeError, match='vector_backend = "compact" needs FAISS 1.15.1 or newer'):
        Store(tmp_path / "named", vector_backend="compact")


# ---------------------------------------------------------------- the budget


def test_the_budget_is_the_setting_or_two_percent_of_the_machine_s_memory(monkeypatch):
    assert vector_memory_budget(300) == (300_000_000, "vector_memory_mb = 300")
    for memory, budget, said in (
        (17_179_869_184, 343_597_383, "2% of this machine's 17.2 GB"),  # 16 GB as macOS counts it
        (25_769_803_776, 515_396_075, "2% of this machine's 25.8 GB"),
        (4_000_000_000, 128_000_000, "128 MB (2% of this machine's 4.0 GB would be less)"),
        (None, 320_000_000, "2% of 16 GB (this machine's memory could not be read)"),
    ):
        monkeypatch.setattr(config_module, "physical_memory", lambda memory=memory: memory)
        assert vector_memory_budget() == vector_memory_budget(0) == (budget, said)


def test_the_machine_s_memory_is_read_and_a_container_s_limit_counts(tmp_path, monkeypatch):
    memory = physical_memory()
    assert isinstance(memory, int) and memory > 2**28  # it can be read here: macOS and Linux
    limit = tmp_path / "memory.max"
    monkeypatch.setattr(config_module, "_CGROUP_LIMITS", (str(limit),))
    limit.write_text("max\n")
    assert physical_memory() == memory
    limit.write_text(f"{memory // 4}\n")
    assert physical_memory() == memory // 4
    limit.write_text(f"{memory * 4}\n")  # a limit above what the machine has changes nothing
    assert physical_memory() == memory

    def no_such_call(name):
        raise ValueError(name)

    monkeypatch.setattr(config_module.os, "sysconf", no_such_call, raising=False)
    assert physical_memory() is None and vector_memory_budget()[0] == 320_000_000


def test_the_config_s_budget_reaches_the_store(tmp_path, sample_repo, monkeypatch):
    fake = {"code": {"model": "fake:64"}, "usage": {"model": "fake:64"}}
    cfg = config_from_dict({"vector_backend": "auto", "vector_memory_mb": 7, "vectors": fake})
    assert cfg.vector_memory_mb == 7 and Config().vector_memory_mb == 0
    svc = CodememService(sample_repo, index_dir=tmp_path / "idx", config=cfg)
    try:
        assert svc.store.vector_memory_mb == 7
        assert svc.update() is not None
        assert "vector_memory_mb = 7" in svc.store.search_index_status()["why"]
    finally:
        svc.close()


# ---------------------------------------------------------------- what the user sees


def test_status_says_which_search_index_is_in_use_why_and_its_memory(sample_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    (sample_repo / ".codemem.toml").write_text('vector_backend = "auto"\n')
    svc = CodememService(sample_repo, index_dir=tmp_path / "idx")
    try:
        svc.update()
        info = svc.status(check_staleness=False)
        index = info["search_index"]
        assert (index["setting"], index["index"]) == ("auto", "faiss")
        assert index["why"].startswith("auto: the exact index takes 0 MB, within the budget of ")
        counts = svc.store.counts()["vectors"]
        assert {t: v["vectors"] for t, v in index["types"].items()} == counts
        per = 2 * 64 + 64  # the exact index at 64 numbers
        assert all(v["index"] == "faiss" and v["memory_mb"] == round(counts[t] * per / 1e6, 1) for t, v in index["types"].items())
        text = format_status(info)
        assert "search index: exact (faiss)\n  auto: the exact index takes 0 MB, within the budget of " in text
        assert f"  code: {counts['code']} vectors, about 0 MB in memory" in text

        (sample_repo / ".codemem.toml").write_text('vector_backend = "auto"\nvector_memory_mb = 1\n')
        monkeypatch.setattr("codemem.store.vector_memory_budget", lambda setting_mb=0: (setting_mb * 1000, f"vector_memory_mb = {setting_mb}"))
        svc._reload_config()  # another budget: the indexes are picked again
        index = svc.status(check_staleness=False)["search_index"]
        assert index["index"] == "compact" and "over the budget of 0 MB (vector_memory_mb = 1)" in index["why"]
        assert all(v["index"] == "compact" for v in index["types"].values())
        assert isinstance(svc.store._type_index("code").store, CompactVectorStore)
        assert "revoke_session" in [r.qualname for r in svc.search("revoke session", k=5, signals=["code"]).results]
        assert "search index: compact\n  auto: the exact index would take " in format_status(svc.status(check_staleness=False))
    finally:
        svc.close()


def test_the_mcp_status_tool_carries_the_search_index(sample_repo, tmp_path, monkeypatch):
    from codemem.server import build_server

    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    svc = CodememService(sample_repo, index_dir=tmp_path / "idx")
    try:
        svc.update()
        server = build_server(svc)
        tool = next(t for t in server._tool_manager.list_tools() if t.name == "index_status")
        text = tool.fn()
        data = json.loads(text[text.rindex("\n\n") + 2:])
        assert data["search_index"]["index"] in ("faiss", "compact") and "types" in data["search_index"]
    finally:
        svc.close()
