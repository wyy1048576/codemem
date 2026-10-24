import shutil

import pytest

from codemem.config import VectorConfig
from codemem.indexer import Indexer
from codemem.schema import Chunk
from codemem.search import _pick_top, name_hits, query_names, rrf, search
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


def _chunk(chunk_id, path, line):
    return Chunk(key=f"{path}::f{line}", path=path, qualname=f"f{line}", name=f"f{line}", kind="function",
                 start_line=line, end_line=line + 1, signature="", docstring="", code="", content_hash="",
                 chunk_id=chunk_id)


def test_ties_are_ordered_by_location_not_by_id():
    chunks = {5: _chunk(5, "a.py", 1), 3: _chunk(3, "c.py", 1), 1: _chunk(1, "b.py", 9), 4: _chunk(4, "b.py", 2)}
    fused = [(5, 0.9), (1, 0.5), (3, 0.5), (4, 0.5), (2, 0.4)]  # rrf() order: ties by id; id 2 has no row
    top = _pick_top(fused, 4, lambda ids: {i: chunks[i] for i in ids if i in chunks})
    assert [(c.location, score) for c, score in top] == [
        ("a.py:1-2", 0.9), ("b.py:2-3", 0.5), ("b.py:9-10", 0.5), ("c.py:1-2", 0.5),
    ]


def test_a_tie_at_the_cut_is_kept_whole():
    # 13 results tie for rank 2. The cut at k + 10 = 12 falls inside the group, and the result
    # that comes first by location has the highest id, so it is last in rrf() order.
    chunks = {0: _chunk(0, "top.py", 1), **{i: _chunk(i, f"f{20 - i:02}.py", 1) for i in range(1, 14)}}
    fused = [(0, 0.9)] + [(i, 0.5) for i in range(1, 14)]
    top = _pick_top(fused, 2, lambda ids: {i: chunks[i] for i in ids})
    assert [c.path for c, _ in top] == ["top.py", "f07.py"]  # id 13


def test_same_code_gives_the_same_order_with_other_chunk_ids(sample_repo, tmp_path, fake_config, recorder):
    factory = lambda m, c: recorder  # noqa: E731
    first = Store(tmp_path / "first")
    Indexer(sample_repo, first, fake_config, embedder_factory=factory).update()
    # Same code, other ids: index without api/routes.py, then add it back with an update.
    routes, away = sample_repo / "api" / "routes.py", tmp_path / "routes.py"
    shutil.move(routes, away)
    second = Store(tmp_path / "second")
    Indexer(sample_repo, second, fake_config, embedder_factory=factory).update()
    shutil.move(away, routes)
    Indexer(sample_repo, second, fake_config, embedder_factory=factory).update()

    tie_with_other_id_order = False
    for query in ("disabled users stay logged in", "session", "get user by id", "table rows", "logout"):
        a, b = (search(s, query, fake_config, k=50, embedder_factory=factory).results for s in (first, second))
        assert [(r.location, r.score) for r in a] == [(r.location, r.score) for r in b]
        id_b = {r.key: r.chunk_id for r in b}
        for x, y in zip(a, a[1:]):
            if x.score == y.score and (x.chunk_id < y.chunk_id) != (id_b[x.key] < id_b[y.key]):
                tie_with_other_id_order = True
    assert tie_with_other_id_order  # the test really has ties that ids would order differently
    first.close()
    second.close()


def test_copies_of_the_same_code_are_ordered_by_location_in_each_signal(tmp_path, fake_config, recorder):
    from codemem.tokenize import fts_match_query

    repo = tmp_path / "repo"
    repo.mkdir()
    store = Store(tmp_path / "index")
    factory = lambda m, c: recorder  # noqa: E731
    same = "def same_thing():\n    return 1\n"
    # z.py goes in first, so it has the lowest id and comes first in insertion order.
    (repo / "z.py").write_text(same)
    Indexer(repo, store, fake_config, embedder_factory=factory).update()
    for name in "abcd":
        (repo / f"{name}.py").write_text(same)
    Indexer(repo, store, fake_config, embedder_factory=factory).update()
    paths = lambda ids: [store.get_chunk(i).path for i in ids]  # noqa: E731
    query = recorder.embed_queries(["same thing"])[0]
    for n in (1, 2, 4):  # the 5 equal scores cross every cut
        assert paths(i for i, _ in store.vector_search("code", query, n)) == ["a.py", "b.py", "c.py", "d.py"][:n]
        assert paths(store.bm25_search(fts_match_query("same_thing"), n, fake_config.bm25_weights)) == ["a.py", "b.py", "c.py", "d.py"][:n]
    store.close()


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
    assert resp.signals == ["bm25", "name", "code", "usage"]
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


# ---- name signal


def test_query_names_spots_identifiers_dotted_names_and_word_runs():
    # Word runs are candidates too; they only matter if a function has that name.
    assert query_names("why does merge_setting() drop None?") == ["why_does", "merge_setting", "drop_none"]
    assert query_names("getUserById and HTTPAdapter") == ["getUserById", "HTTPAdapter"]
    assert query_names("requests.sessions.Session.send fails") == [
        "requests.sessions.Session.send", "sessions.Session.send", "Session.send",
    ]
    assert query_names("get user by id") == ["get_user_by_id", "get_user_by", "get_user", "user_by_id", "user_by", "by_id"]
    assert query_names("proxy") == [] and query_names("") == []  # one plain word is not a name
    assert "_private" in query_names("_private helper")


@pytest.fixture
def uncalled(sample_repo, tmp_path, fake_config, recorder):
    """The fixture repo plus a function nobody calls and a name defined 6 times."""
    (sample_repo / "auth" / "audit.py").write_text(
        'def record_audit_event(evt):\n    """Write one audit row for a session change."""\n    return evt\n',
        encoding="utf-8", newline="\n",
    )
    for i in range(6):
        (sample_repo / f"helpers_{i}.py").write_text("def common_helper(x):\n    return x\n", encoding="utf-8", newline="\n")
    store = Store(tmp_path / "index")
    factory = lambda m, c: recorder  # noqa: E731
    Indexer(sample_repo, store, fake_config, embedder_factory=factory).update()
    yield store, fake_config, factory
    store.close()


def test_function_without_callers_wins_its_exact_name(uncalled):
    store, cfg, factory = uncalled
    for query in ("record_audit_event", "record audit event", "where is record_audit_event called"):
        resp = search(store, query, cfg, k=5, debug=True, embedder_factory=factory)
        top = resp.results[0]
        assert top.qualname == "record_audit_event" and top.ranks["name"] == 1, query
        assert "usage" not in top.ranks  # no callers, so no usage vector: the case RRF used to lose
    assert all(r.ranks.get("name") is None for r in resp.results[1:])


def test_dotted_name_matches_the_method_even_if_its_name_is_a_plain_word(uncalled):
    store, cfg, factory = uncalled
    resp = search(store, "Table.find", cfg, k=3, debug=True, embedder_factory=factory)
    assert (resp.results[0].qualname, resp.results[0].ranks["name"]) == ("Table.find", 1)
    assert name_hits(store, "find", cfg) == []  # the bare plain word pins nothing


def test_names_defined_too_often_are_not_pinned(uncalled):
    store, cfg, _ = uncalled
    assert len(store.definitions_named(["common_helper"])) == 6 > cfg.max_defs_per_name
    assert name_hits(store, "common_helper", cfg) == []
    cfg.max_defs_per_name = 6
    hits = name_hits(store, "common_helper", cfg)
    assert [store.get_chunk(i).path for i in hits] == [f"helpers_{i}.py" for i in range(6)]  # by location


def test_name_signal_respects_path_prefix(uncalled):
    store, cfg, factory = uncalled
    resp = search(store, "record_audit_event", cfg, k=5, path_prefix="api/", embedder_factory=factory)
    assert "record_audit_event" not in _quals(resp)


def test_without_the_name_signal_ranking_is_unchanged(uncalled):
    """Eval systems that list their signals keep their numbers. Weight 0 is the same as no signal."""
    store, cfg, factory = uncalled
    query = "record audit event for a session"
    without = search(store, query, cfg, k=10, signals=["bm25", "code", "usage"], embedder_factory=factory)
    cfg.rrf_weights = {"name": 0.0}
    zero = search(store, query, cfg, k=10, embedder_factory=factory)
    assert [(r.chunk_id, r.score) for r in without.results] == [(r.chunk_id, r.score) for r in zero.results]
    assert "name" not in without.signals


def test_signal_selection_and_validation(index):
    store, cfg, factory = index
    assert search(store, "session", cfg, signals=["code"], embedder_factory=factory).signals == ["code"]
    # A configured vector type with no stored vectors is silently skipped.
    cfg.vectors["other"] = VectorConfig(model="fake:64", enabled=False)
    assert search(store, "x", cfg, signals=["bm25", "other"], embedder_factory=factory).signals == ["bm25"]
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
