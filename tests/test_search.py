import pytest

from codemem.indexer import Indexer
from codemem.search import rrf, search
from codemem.store import Store

QUERY = "disabled users stay logged in"


def test_rrf_math():
    fused = dict(rrf({"a": [1, 2, 3], "b": [3, 1]}, k=60))
    assert fused[1] == pytest.approx(1 / 61 + 1 / 62)
    assert fused[3] == pytest.approx(1 / 63 + 1 / 61)
    assert fused[2] == pytest.approx(1 / 62)
    assert [d for d, _ in rrf({"a": [1, 2, 3], "b": [3, 1]}, k=60)] == [1, 3, 2]


def test_rrf_weights_and_ties():
    assert rrf({"a": [1], "b": [2]}, k=0) == [(1, 1.0), (2, 1.0)]  # ties broken by id
    fused = rrf({"a": [1], "b": [2]}, k=0, weights={"b": 2.0})
    assert fused == [(2, 2.0), (1, 1.0)]
    assert rrf({}, k=60) == []


@pytest.fixture
def index(sample_repo, tmp_path, fake_config, recorder):
    store = Store(tmp_path / "index")
    factory = lambda m, c: recorder  # noqa: E731
    Indexer(sample_repo, store, fake_config, embedder_factory=factory).update()
    yield store, fake_config, factory
    store.close()


def _quals(resp):
    return [r.qualname for r in resp.results]


def test_end_to_end_nl_query_found_via_usage(index):
    """FakeEmbedder is bag-of-words, so its code vectors are noise for an NL query and
    disable_user (also "tested by test_disabled_...") competes fairly. Here we check the
    usage signal carries the hit; test_model.py checks fused top-3 with real jina."""
    store, cfg, factory = index
    usage_only = search(store, QUERY, cfg, k=3, signals=["usage"], embedder_factory=factory)
    assert "revoke_session" in _quals(usage_only)
    resp = search(store, QUERY, cfg, k=10, debug=True, embedder_factory=factory)
    assert resp.signals == ["bm25", "code", "usage"]
    assert "revoke_session" in _quals(resp)
    card = next(r for r in resp.results if r.qualname == "revoke_session")
    assert card.ranks.get("usage") is not None and "bm25" not in card.ranks
    assert card.location == "auth/sessions.py:19-20"
    assert card.signature == "def revoke_session(session_id):"
    # The query shares no words with revoke_session's code, so BM25 alone can't find it.
    bm25_only = search(store, QUERY, cfg, k=50, signals=["bm25"], embedder_factory=factory)
    assert "revoke_session" not in _quals(bm25_only)


def test_exact_identifier_query_ranks_first(index):
    store, cfg, factory = index
    resp = search(store, "get_user_by_id", cfg, k=5, embedder_factory=factory)
    assert resp.results[0].qualname == "get_user_by_id"


def test_signal_selection_and_validation(index):
    store, cfg, factory = index
    assert search(store, "session", cfg, signals=["code"], embedder_factory=factory).signals == ["code"]
    # summary is configured but has no stored vectors: silently skipped
    assert search(store, "x", cfg, signals=["bm25", "summary"], embedder_factory=factory).signals == ["bm25"]
    with pytest.raises(ValueError):
        search(store, "x", cfg, signals=["nope"], embedder_factory=factory)


def test_path_prefix_filter(index):
    store, cfg, factory = index
    resp = search(store, "session", cfg, k=20, path_prefix="api/", embedder_factory=factory)
    assert resp.results and all(r.path.startswith("api/") for r in resp.results)
    assert search(store, "session", cfg, path_prefix="nowhere/", embedder_factory=factory).results == []


def test_query_embedded_once_per_distinct_model(index):
    store, cfg, _ = index
    calls = []

    class Counting:
        def embed_queries(self, texts):
            calls.append(texts)
            from codemem.embedder import FakeEmbedder

            return FakeEmbedder(64).embed_queries(texts)

    search(store, "logout", cfg, embedder_factory=lambda m, c: Counting())
    assert len(calls) == 1  # code and usage share fake:64


def test_cards_are_json_ready_and_capped(index):
    store, cfg, factory = index
    cfg.preview_lines = 2
    resp = search(store, "table rows", cfg, k=2, embedder_factory=factory)
    d = resp.to_dict()
    assert len(d["results"]) == 2 and "ranks" not in d["results"][0]
    assert {"location", "qualname", "signature", "doc", "preview", "score"} <= set(d["results"][0])
    assert all(len(r.preview.splitlines()) <= 3 for r in resp.results)
    assert d["timings"]["total"] >= 0


def test_weird_query_does_not_break(index):
    store, cfg, factory = index
    for q in ['"', "AND OR NOT", "*", "-", "!!!", "", "NEAR(a b)"]:
        search(store, q, cfg, embedder_factory=factory)
