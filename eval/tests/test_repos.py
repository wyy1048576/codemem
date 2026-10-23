import pytest
from conftest import REMOTE_REPO as REPO

from cmeval import repos
from cmeval.repos import RepoError, checkout, ensure_commit, head, move_to, read_file, remove_worktree


def test_fixed_snapshot(remote):
    shas = remote.shas
    path = checkout(REPO, shas[0])
    assert path.name == f"acme__demo@{shas[0][:12]}"
    assert (path / "app.py").read_text() == "VERSION = 1\n"
    assert head(path) == shas[0]
    assert checkout(REPO, shas[0]) == path  # second call reuses it


def test_movable_worktree_steps_forward(remote):
    shas = remote.shas
    live = checkout(REPO, shas[0], name="run1")
    assert live.name == "acme__demo@live-run1"
    move_to(live, shas[2])
    assert head(live) == shas[2] and (live / "app.py").read_text() == "VERSION = 3\n"
    assert checkout(REPO, shas[1], name="run1") == live  # same worktree, moved back
    assert (live / "app.py").read_text() == "VERSION = 2\n"


def test_move_refuses_local_changes(remote):
    shas = remote.shas
    live = checkout(REPO, shas[0], name="run1")
    (live / "notes.txt").write_text("untracked counts too")
    with pytest.raises(RepoError, match="local changes"):
        move_to(live, shas[1])
    (live / "notes.txt").unlink()
    (live / "app.py").write_text("edited")
    with pytest.raises(RepoError, match="local changes"):
        move_to(live, shas[1])


def test_fixed_snapshot_cannot_move(remote):
    shas = remote.shas
    path = checkout(REPO, shas[0])
    with pytest.raises(RepoError, match="fixed snapshot"):
        move_to(path, shas[1])


def test_dirty_fixed_snapshot_is_rejected(remote):
    shas = remote.shas
    path = checkout(REPO, shas[0])
    (path / "app.py").write_text("edited")
    with pytest.raises(RepoError, match="not a clean checkout"):
        checkout(REPO, shas[0])


def test_new_remote_commit_is_fetched_on_demand(remote):
    new = remote.commit({"app.py": "VERSION = 4\n"})
    assert not repos.has_commit(REPO, new)
    ensure_commit(REPO, new)
    assert read_file(REPO, new, "app.py") == "VERSION = 4\n"


def test_read_file(remote):
    shas = remote.shas
    assert read_file(REPO, shas[1], "app.py") == "VERSION = 2\n"
    assert read_file(REPO, shas[1], "missing.py") is None
    crlf = remote.commit({"app.py": "a = 1\r\nb = 2\r\n"})
    assert read_file(REPO, crlf, "app.py") == "a = 1\r\nb = 2\r\n"  # line endings kept as committed


def test_bad_or_unknown_commit(remote):
    with pytest.raises(RepoError, match="not a full 40-character"):
        ensure_commit(REPO, "abc123")
    with pytest.raises(RepoError, match="not found"):
        ensure_commit(REPO, "0" * 40)


def test_remove_worktree(remote):
    shas = remote.shas
    path = checkout(REPO, shas[0])
    remove_worktree(path)
    assert not path.exists()
    assert str(path) not in remote.git("--git-dir", str(repos.clone_path(REPO)), "worktree", "list")
    assert checkout(REPO, shas[0]) == path  # can be created again
