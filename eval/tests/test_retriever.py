import pytest

from cmeval.adapters.fake import FakeRetriever
from cmeval.retriever import Hit, IndexReport, Retriever, RetrieverError, check_hits, stable_hash


def test_fake_retriever_implements_the_interface():
    assert isinstance(FakeRetriever(), Retriever)


def test_hit_round_trip():
    hit = Hit("auth/sessions.py", 30, 45, "SessionManager.revoke_session", 0.5, "def revoke_session(...)", {"ranks": {"bm25": 1}})
    assert Hit.from_dict(hit.to_dict()) == hit
    assert IndexReport(1.5, 10, 3).to_dict() == {"seconds": 1.5, "bytes_on_disk": 10, "items": 3, "items_reembedded": None, "extra": {}}


def test_stable_hash_ignores_key_order():
    assert stable_hash({"a": 1, "b": [1, 2]}) == stable_hash({"b": [1, 2], "a": 1})
    assert stable_hash({"a": 1}) != stable_hash({"a": 2})
    assert len(stable_hash({})) == 16


def test_check_hits_accepts_good_hits():
    line_hits = [Hit("a.py", 1, 10), Hit("b/c.py", 5, 5)]
    assert check_hits(line_hits, "line", k=5) == line_hits
    file_hits = [Hit("a.py"), Hit("b/c.py")]
    assert check_hits(file_hits, "file", k=2) == file_hits


@pytest.mark.parametrize(
    "hits, granularity, k, message",
    [
        ([Hit("a.py")], "line", 5, "without line numbers"),
        ([Hit("a.py", 3, None)], "line", 5, "without line numbers"),
        ([Hit("a.py", 9, 3)], "line", 5, "needs 1 <= start <= end"),
        ([Hit("a.py", 0, 3)], "line", 5, "needs 1 <= start <= end"),
        ([Hit("a.py", 1, 3)], "file", 5, "file-level system returned line numbers"),
        ([Hit("/abs/a.py")], "file", 5, "not a repo-relative path"),
        ([Hit("a\\b.py")], "file", 5, "not a repo-relative path"),
        ([Hit("a.py"), Hit("b.py")], "file", 1, "more than k=1"),
        ([{"path": "a.py"}], "file", 5, "not a Hit"),
        ([], "chunk", 5, "granularity 'chunk'"),
    ],
)
def test_check_hits_rejects_contract_breaks(hits, granularity, k, message):
    with pytest.raises(RetrieverError, match=message):
        check_hits(hits, granularity, k, system="x")


def test_fake_retriever_indexes_and_ranks(tmp_path):
    repo = tmp_path / "repo"
    (repo / "auth").mkdir(parents=True)
    (repo / "auth" / "sessions.py").write_text("def revoke_session():\n    session = 1\n    return session\n")
    (repo / "auth" / "users.py").write_text("def disable_user():\n    session = 0\n")
    (repo / "README.md").write_text("session session session\n")  # wrong suffix: not indexed
    (repo / ".git").mkdir()
    (repo / ".git" / "hook.py").write_text("session\n")  # inside .git: not indexed
    fake = FakeRetriever()
    report = fake.build(repo, tmp_path / "idx")
    assert report.items == 2 and (tmp_path / "idx" / "fake-index.json").exists()
    hits = fake.search("revoke the session", k=10)
    assert [h.path for h in hits] == ["auth/sessions.py", "auth/users.py"]
    assert (hits[0].start_line, hits[0].end_line) == (1, 3)
    assert check_hits(hits, fake.granularity, 10) == hits
    assert fake.calls == ["build", "search"]


def test_fake_retriever_file_granularity_and_script(tmp_path):
    (tmp_path / "a.py").write_text("alpha\n")
    fake = FakeRetriever(granularity="file", script={"q": [{"path": "x.py", "text": "scripted"}]})
    fake.build(tmp_path, tmp_path / "idx")
    assert fake.search("alpha", 5) == [Hit("a.py", score=1.0, text="alpha")]
    assert fake.search("q", 5) == [Hit("x.py", text="scripted")]


def test_fake_retriever_needs_a_build_first():
    with pytest.raises(RetrieverError, match="search before build"):
        FakeRetriever().search("anything", 5)
