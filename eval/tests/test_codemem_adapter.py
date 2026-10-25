import pytest

pytest.importorskip("codemem", reason="needs the codemem extra: uv sync --extra codemem")

from cmeval.adapters import codemem as adapter  # noqa: E402
from cmeval.adapters.codemem import CodememRetriever  # noqa: E402
from cmeval.retriever import RetrieverError, check_hits  # noqa: E402

FAKE = {"vectors": {"code": {"model": "fake"}, "usage": {"model": "fake"}}}  # no model download

SESSIONS = '''\
class SessionManager:
    def revoke_session(self, user):
        """End every session of a user."""
        for s in self.sessions(user):
            s.close()


def disable_user(user):
    SessionManager().revoke_session(user)
'''
TEST = '''\
from auth.sessions import disable_user


def test_disabled_user_loses_sessions():
    disable_user("bob")
'''


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "auth").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "auth" / "sessions.py").write_text(SESSIONS)
    (root / "tests" / "test_sessions.py").write_text(TEST)
    return root


@pytest.fixture(autouse=True)
def no_shared_leftovers():
    yield
    for entry in list(adapter._SHARED.values()):
        entry["service"].close()
    adapter._SHARED.clear()


def test_build_and_search(repo, tmp_path):
    cm = CodememRetriever(config=FAKE)
    report = cm.build(repo, tmp_path / "idx")
    assert report.items >= 3 and report.items_reembedded > 0 and report.bytes_on_disk > 0
    hits = cm.search("revoke session of a disabled user", k=5)
    assert check_hits(hits, "line", 5) == hits
    by_symbol = {h.symbol: h for h in hits}
    assert "SessionManager.revoke_session" in by_symbol
    revoke = by_symbol["SessionManager.revoke_session"]
    assert (revoke.path, revoke.start_line, revoke.end_line) == ("auth/sessions.py", 2, 5)
    assert hits[0].text.startswith("1. ") and hits[1].text.startswith("2. ")  # MCP card, real rank number
    assert "[id " in hits[0].text and "bm25=" not in hits[0].text  # no debug ranks in what the agent sees
    assert set(hits[0].extra["signals"]) == {"bm25", "code", "usage"}
    assert revoke.extra["language"] == "python" and revoke.extra["kind"] == "method"


def test_signals_select_what_is_searched(repo, tmp_path):
    cm = CodememRetriever(signals=["bm25"], config=FAKE)
    cm.build(repo, tmp_path / "idx")
    hits = cm.search("revoke session", k=5)
    assert hits and all(set(h.extra["ranks"]) <= {"bm25"} for h in hits)
    assert hits[0].extra["signals"] == ["bm25"]


def test_index_key_depends_on_index_time_settings_only():
    base = CodememRetriever(config=FAKE).index_key()
    assert CodememRetriever(signals=["bm25"], config=FAKE).index_key() == base
    assert CodememRetriever(config={**FAKE, "rrf": {"weights": {"bm25": 2.0}}, "bm25": {"weights": [1, 1, 1]}}).index_key() == base
    assert CodememRetriever(config={**FAKE, "embedding_dim": 32}).index_key() != base
    assert CodememRetriever(config={"vectors": {"code": {"model": "fake:16"}, "usage": {"model": "fake"}}}).index_key() != base


def test_v2_index_time_settings_change_the_key_and_search_time_ones_do_not():
    base = CodememRetriever(config=FAKE).index_key()
    assert CodememRetriever(config={**FAKE, "code_header": False}).index_key() != base
    assert CodememRetriever(config={**FAKE, "languages": ["python"]}).index_key() != base
    assert CodememRetriever(config={**FAKE, "kinds": ["function", "method"], "test_weight": 0.5}).index_key() == base


def test_systems_with_one_key_share_one_service(repo, tmp_path):
    a = CodememRetriever(name="a", signals=["bm25"], config=FAKE)
    b = CodememRetriever(name="b", signals=["bm25", "code"], config=FAKE)
    idx = tmp_path / "idx"
    a.build(repo, idx)
    assert b.update(repo, idx).items_reembedded == 0  # same service: nothing to do
    assert len(adapter._SHARED) == 1

    # a indexes a change; b must see it (a separate service would search stale vectors).
    (repo / "auth" / "tokens.py").write_text("def purge_expired_tokens():\n    pass\n")
    assert a.update(repo, idx).items_reembedded > 0
    assert "purge_expired_tokens" in [h.symbol for h in b.search("purge expired tokens", k=5)]

    a.close()
    assert b.search("purge expired tokens", k=5)  # b still works after a closed
    b.close()
    assert adapter._SHARED == {}


def test_other_settings_on_the_same_folder_are_refused(repo, tmp_path):
    CodememRetriever(config=FAKE).build(repo, tmp_path / "idx")
    other = CodememRetriever(config={**FAKE, "embedding_dim": 32})
    with pytest.raises(RetrieverError, match="other index-time settings"):
        other.build(repo, tmp_path / "idx")


def test_update_re_embeds_only_what_changed(repo, tmp_path):
    cm = CodememRetriever(config=FAKE)
    first = cm.build(repo, tmp_path / "idx").items_reembedded
    assert cm.update(repo, tmp_path / "idx").items_reembedded == 0
    (repo / "tests" / "test_sessions.py").write_text(TEST.replace('"bob"', '"alice"'))
    changed = cm.update(repo, tmp_path / "idx").items_reembedded
    assert 0 < changed < first


def test_failed_indexing_is_an_error_not_a_silent_success(repo, tmp_path):
    broken = CodememRetriever(config={"vectors": {"code": {"model": "fake:not-a-number"}, "usage": {"enabled": False}}})
    with pytest.raises(RetrieverError, match="codemem indexing failed"):
        broken.build(repo, tmp_path / "idx")


def test_search_before_build_and_describe():
    cm = CodememRetriever(config=FAKE)
    with pytest.raises(RetrieverError, match="search before build"):
        cm.search("x", 5)
    info = cm.describe()
    assert info["adapter"] == "codemem" and info["codemem_version"]
    assert info["device"] in {"cpu", "mps", "cuda", "xpu"}
    assert info["config"]["vectors"]["code"]["model"] == "fake"
    assert info["index_key"] == cm.index_key()


# ---- review fixes


def test_unusable_signals_are_refused_when_the_system_is_made():
    with pytest.raises(RetrieverError, match="not usable"):
        CodememRetriever(signals=["bm25", "cod"], config=FAKE)  # typo
    with pytest.raises(RetrieverError, match="not usable"):
        CodememRetriever(signals=["bm25", "usage"], config={**FAKE, "vectors": {**FAKE["vectors"], "usage": {"enabled": False}}})


def test_a_signal_without_vectors_is_an_error_not_a_quiet_fallback(tmp_path):
    root = tmp_path / "lonely"
    root.mkdir()
    (root / "solo.py").write_text("def nobody_calls_me():\n    pass\n")  # no callers, so no usage vectors
    cm = CodememRetriever(signals=["bm25", "code", "usage"], config=FAKE)
    cm.build(root, tmp_path / "idx")
    with pytest.raises(RetrieverError, match=r"no vectors for signals \['usage'\]"):
        cm.search("nobody calls me", k=5)


def test_files_that_fail_to_index_are_counted(repo, tmp_path, monkeypatch):
    import codemem.indexer

    real = codemem.indexer.chunk_source

    def flaky(source, rel, *args, **kwargs):
        if rel.endswith("test_sessions.py"):
            raise ValueError("cannot parse")
        return real(source, rel, *args, **kwargs)

    monkeypatch.setattr(codemem.indexer, "chunk_source", flaky)
    report = CodememRetriever(config=FAKE).build(repo, tmp_path / "idx")
    assert report.extra["files_failed"] == 1 and "test_sessions.py" in report.extra["errors"][0]


def test_snapshot_without_git_inside_another_git_tree(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path / "outer")], check=True)
    inner = tmp_path / "outer" / "snapshots" / "app"
    inner.mkdir(parents=True)
    (inner / "app.py").write_text("def revoke_session():\n    pass\n")
    cm = CodememRetriever(config=FAKE)
    cm.build(inner, tmp_path / "idx")
    assert [h.path for h in cm.search("revoke session", 5)][0] == "app.py"  # relative to inner, not outer


def test_refused_build_does_not_attach_to_the_other_index(repo, tmp_path):
    other_repo = tmp_path / "other"
    other_repo.mkdir()
    (other_repo / "x.py").write_text("def x():\n    pass\n")
    a = CodememRetriever(name="a", config=FAKE)
    a.build(repo, tmp_path / "idx")
    b = CodememRetriever(name="b", config=FAKE)
    with pytest.raises(RetrieverError, match="indexes"):
        b.build(other_repo, tmp_path / "idx")
    with pytest.raises(RetrieverError, match="search before build"):
        b.search("revoke session", 5)
    a.close()
    assert adapter._SHARED == {}  # b never became a user
