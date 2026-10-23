from pathlib import Path

from cmeval import paths


def test_cmeval_home_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CMEVAL_HOME", str(tmp_path / "x"))
    assert paths.cmeval_home() == tmp_path / "x"
    assert paths.repos_dir() == tmp_path / "x" / "repos"
    assert paths.worktrees_dir() == tmp_path / "x" / "worktrees"
    assert paths.indexes_dir() == tmp_path / "x" / "indexes"
    assert paths.runs_dir() == tmp_path / "x" / "runs"
    assert paths.token_cache_dir() == tmp_path / "x" / "token-cache"


def test_cmeval_home_default(monkeypatch):
    monkeypatch.delenv("CMEVAL_HOME", raising=False)
    assert paths.cmeval_home() == Path.home() / ".cmeval"


def test_helpers_do_not_create_directories(tmp_path, monkeypatch):
    monkeypatch.setenv("CMEVAL_HOME", str(tmp_path / "x"))
    paths.repos_dir()
    assert not (tmp_path / "x").exists()
