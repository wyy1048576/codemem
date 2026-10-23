import subprocess

import pytest

from cmeval import repos
from cmeval.repos import RepoError, checkout, ensure_clone, ensure_commit, head, move_to, read_file, remove_worktree

REPO = "acme/demo"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def remote(tmp_path, monkeypatch):
    """A local git repo with 3 commits that stands in for GitHub. The user's git config is ignored."""
    config = tmp_path / "gitconfig"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{key}_NAME", "Test")
        monkeypatch.setenv(f"{key}_EMAIL", "test@example.com")
    root = tmp_path / "remote"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    shas = []
    for i in (1, 2, 3):
        (root / "app.py").write_text(f"VERSION = {i}\n")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", f"v{i}")
        shas.append(git(root, "rev-parse", "HEAD"))
    ensure_clone(REPO, url=str(root))
    return root, shas


def add_commit(root, text):
    (root / "app.py").write_text(text)
    git(root, "commit", "-q", "-am", "next")
    return git(root, "rev-parse", "HEAD")


def test_fixed_snapshot(remote):
    _, shas = remote
    path = checkout(REPO, shas[0])
    assert path.name == f"acme__demo@{shas[0][:12]}"
    assert (path / "app.py").read_text() == "VERSION = 1\n"
    assert head(path) == shas[0]
    assert checkout(REPO, shas[0]) == path  # second call reuses it


def test_movable_worktree_steps_forward(remote):
    _, shas = remote
    live = checkout(REPO, shas[0], name="run1")
    assert live.name == "acme__demo@live-run1"
    move_to(live, shas[2])
    assert head(live) == shas[2] and (live / "app.py").read_text() == "VERSION = 3\n"
    assert checkout(REPO, shas[1], name="run1") == live  # same worktree, moved back
    assert (live / "app.py").read_text() == "VERSION = 2\n"


def test_move_refuses_local_changes(remote):
    _, shas = remote
    live = checkout(REPO, shas[0], name="run1")
    (live / "notes.txt").write_text("untracked counts too")
    with pytest.raises(RepoError, match="local changes"):
        move_to(live, shas[1])
    (live / "notes.txt").unlink()
    (live / "app.py").write_text("edited")
    with pytest.raises(RepoError, match="local changes"):
        move_to(live, shas[1])


def test_fixed_snapshot_cannot_move(remote):
    _, shas = remote
    path = checkout(REPO, shas[0])
    with pytest.raises(RepoError, match="fixed snapshot"):
        move_to(path, shas[1])


def test_dirty_fixed_snapshot_is_rejected(remote):
    _, shas = remote
    path = checkout(REPO, shas[0])
    (path / "app.py").write_text("edited")
    with pytest.raises(RepoError, match="not a clean checkout"):
        checkout(REPO, shas[0])


def test_new_remote_commit_is_fetched_on_demand(remote):
    root, _ = remote
    new = add_commit(root, "VERSION = 4\n")
    assert not repos.has_commit(REPO, new)
    ensure_commit(REPO, new)
    assert read_file(REPO, new, "app.py") == "VERSION = 4\n"


def test_read_file(remote):
    root, shas = remote
    assert read_file(REPO, shas[1], "app.py") == "VERSION = 2\n"
    assert read_file(REPO, shas[1], "missing.py") is None
    crlf = add_commit(root, "a = 1\r\nb = 2\r\n")
    assert read_file(REPO, crlf, "app.py") == "a = 1\r\nb = 2\r\n"  # line endings kept as committed


def test_bad_or_unknown_commit(remote):
    with pytest.raises(RepoError, match="not a full 40-character"):
        ensure_commit(REPO, "abc123")
    with pytest.raises(RepoError, match="not found"):
        ensure_commit(REPO, "0" * 40)


def test_remove_worktree(remote):
    _, shas = remote
    path = checkout(REPO, shas[0])
    remove_worktree(path)
    assert not path.exists()
    assert str(path) not in git(repos.clone_path(REPO), "worktree", "list")
    assert checkout(REPO, shas[0]) == path  # can be created again
