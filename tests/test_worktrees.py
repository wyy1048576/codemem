"""A new git worktree's index starts from a copy of another checkout's, and the index of a removed
worktree is deleted (worktrees.py). Every repository and worktree here is made under `tmp_path`."""

import json
import os
import shutil
import sqlite3
import time

import pytest
from gitrepo import ONLY_ON_A, ONLY_ON_B, TO_B, add_worktree, commit, git, needs_git, two_commits

from codemem.cli import main
from codemem.config import default_index_dir
from codemem.indexer import Indexer
from codemem.service import CodememService
from codemem.store import IndexLock, Store, diff_snapshots
from codemem.worktrees import (
    DB, RECORD, checkouts, copy_index, copy_source, git_common_dir, is_linked_worktree, removable_indexes,
)

pytestmark = needs_git


@pytest.fixture(autouse=True)
def fake_env(monkeypatch):
    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")


@pytest.fixture
def repo(sample_repo):
    """The sample repo as a git repository on commit A; commit B is on the branch `feature`."""
    two_commits(sample_repo)
    return sample_repo.resolve()


def _indexed(checkout, **kwargs):
    """Build (or update) the default index of a checkout, as `codemem index` does."""
    service = CodememService(checkout, **kwargs)
    try:
        stats = service.update()
        assert stats is not None, service.last_error
        return stats
    finally:
        service.close()


@pytest.fixture
def main_index(repo):
    _indexed(repo)
    return default_index_dir(repo)


def _settings(checkout):
    service = CodememService(checkout, index_dir=checkout.parent / "unused-index")
    try:
        return service.config.index_settings()
    finally:
        service.close()


# --------------------------------------------------------------------------- git


def test_checkouts_of_a_repository_are_found_from_any_of_them(repo, tmp_path):
    tree = add_worktree(repo, tmp_path / "trees" / "one", "feature")
    assert git_common_dir(repo) == git_common_dir(tree) == repo / ".git"
    assert not is_linked_worktree(repo) and is_linked_worktree(tree)
    assert checkouts(repo / ".git") == [repo, tree]
    plain = tmp_path / "plain"
    plain.mkdir()
    assert git_common_dir(plain) is None and not is_linked_worktree(plain)


def test_a_submodule_is_not_a_linked_worktree(repo):
    (repo / ".git" / "modules" / "lib").mkdir(parents=True)
    (repo / "lib").mkdir()
    (repo / "lib" / ".git").write_text("gitdir: ../.git/modules/lib\n")
    assert not is_linked_worktree(repo / "lib")
    assert git_common_dir(repo / "lib") == repo / ".git" / "modules" / "lib"
    assert checkouts(repo / ".git" / "modules" / "lib") == []


def test_a_bare_repository_has_linked_worktrees_only(repo, tmp_path):
    bare = tmp_path / "bare.git"
    git(tmp_path, "clone", "-q", "--bare", str(repo), str(bare))
    one = add_worktree(bare, tmp_path / "trees" / "one", "main")
    two = add_worktree(bare, tmp_path / "trees" / "two", "feature")
    assert git_common_dir(one) == bare.resolve()
    assert checkouts(bare.resolve()) == [one, two]
    _indexed(one)
    assert copy_source(two, _settings(two)) == default_index_dir(one)


# --------------------------------------------------------------------------- starting from a copy


def test_a_new_worktree_starts_from_a_copy_and_ends_equal_to_a_fresh_build(repo, main_index, tmp_path, recorder):
    """The worktree is on another commit than the main checkout: files changed, added, moved and
    deleted. Its index starts as a copy, and one update makes it equal to a fresh build."""
    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    service = CodememService(tree, embedder_factory=lambda m, c: recorder)
    try:
        assert service.copied_from == main_index and service.index_dir == default_index_dir(tree)
        copied = service.store.counts()
        assert copied["chunks"] > 0 and copied["vectors"]["code"] > 0
        assert not service.has_index()  # not this checkout's index until a full check has compared it
        stats = service.update()
        assert service.has_index() and service.state == "ready"
        assert {"files_changed": stats.files_changed, "files_deleted": stats.files_deleted} == TO_B
        # Only the texts that differ went to the model: the rest came with the copy.
        embedded = sum(stats.embedded.values())
        assert 0 < embedded < sum(service.store.counts()["vectors"].values())
        assert len(recorder.documents) == sum(stats.model_embedded.values()) > 0
        for key in ONLY_ON_B:
            assert service.store.get_chunk_by_key(key) is not None
        for key in ONLY_ON_A:
            assert service.store.get_chunk_by_key(key) is None
        assert service.indexer.verify() == []
    finally:
        service.close()


def test_a_copy_is_checked_by_content_not_by_file_dates(repo, main_index, tmp_path):
    """Every file is read again after a copy: equal dates must not hide different content."""
    tree = add_worktree(repo, tmp_path / "trees" / "same", "-b", "same")
    source = Store(main_index)
    dates = {path: row.mtime for path, row in source.get_files().items()}
    source.close()
    target = tree / "auth" / "sessions.py"
    text = target.read_text()
    target.write_text(text.replace("token_hex(16)", "token_hex(32)"))  # same size, other content
    stat = (repo / "auth" / "sessions.py").stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # and the date the copied row had
    assert target.stat().st_size == stat.st_size and target.stat().st_mtime == dates["auth/sessions.py"]
    service = CodememService(tree)
    try:
        stats = service.update()
        assert stats.files_changed == 1 and stats.chunks_updated == 1
        assert "token_hex(32)" in service.store.get_chunk_by_key("auth/sessions.py::new_token").code
        assert service.indexer.verify() == []
    finally:
        service.close()


def test_a_copy_is_one_consistent_snapshot_while_the_source_is_written(main_index, tmp_path):
    writer = sqlite3.connect(main_index / DB, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")  # another process is in the middle of an update
    writer.execute("DELETE FROM chunks")
    writer.execute("INSERT INTO meta(key, value) VALUES('half_done', '1')")
    try:
        assert copy_index(main_index, tmp_path / "copy")
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    copy, source = Store(tmp_path / "copy"), Store(main_index)
    assert copy.get_meta("half_done") is None and copy.counts() == source.counts()
    a, b = copy.snapshot(), source.snapshot()
    assert a["chunks"] == b["chunks"] and a["vectors"] == b["vectors"] and a["fts"] == b["fts"]
    assert all(row.mtime == 0 for row in copy.get_files().values())
    assert copy.get_meta("indexed_at") is None and copy.get_meta("indexed_commit") == source.get_meta("indexed_commit")
    assert sorted(p.name for p in (tmp_path / "copy").iterdir() if not p.name.startswith(DB + "-")) == [DB, "write.lock"]
    copy.close()
    source.close()


def test_a_copy_never_replaces_an_index(main_index, tmp_path):
    existing = tmp_path / "existing"
    own = Store(existing)
    own.set_meta("mine", True)
    own.close()
    assert not copy_index(main_index, existing)
    own = Store(existing)
    assert own.get_meta("mine") is True and own.counts()["chunks"] == 0
    own.close()

    leftover = tmp_path / "leftover"  # an index deleted by hand, its write-ahead log left behind
    leftover.mkdir()
    (leftover / f"{DB}-wal").write_bytes(b"old")
    assert not copy_index(main_index, leftover)
    assert not (leftover / DB).exists() and (leftover / f"{DB}-wal").read_bytes() == b"old"

    assert not copy_index(tmp_path / "no-such-index", tmp_path / "new")

    interrupted = tmp_path / "interrupted"  # an earlier copy that stopped half way
    interrupted.mkdir()
    (interrupted / f"{DB}.copy-123").write_bytes(b"half")
    assert copy_index(main_index, interrupted)
    assert sorted(p.name for p in interrupted.iterdir()) == [DB, "write.lock"]


def test_a_copy_does_not_count_as_an_index_until_it_is_checked(repo, main_index, tmp_path, capsys):
    """`codemem search` never updates an index, so it must not answer from another checkout's code."""
    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    assert main(["search", "expire sessions", "--repo", str(tree)]) == 2
    assert "run `codemem index` first" in capsys.readouterr().err
    assert (default_index_dir(tree) / DB).is_file()  # the copy is there for that first `codemem index`

    assert main(["index", str(tree)]) == 0
    assert f"({TO_B['files_changed']} changed, {TO_B['files_deleted']} deleted)" in capsys.readouterr().out
    assert main(["search", "expire sessions", "--repo", str(tree)]) == 0
    assert "expire_sessions" in capsys.readouterr().out


def test_codemem_index_in_a_new_worktree_says_what_it_starts_from(repo, main_index, tmp_path, capsys):
    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    assert main(["index", str(tree), "--verify"]) == 0
    captured = capsys.readouterr()
    assert f"starting from a copy of {main_index}" in captured.err
    assert f"({TO_B['files_changed']} changed, {TO_B['files_deleted']} deleted)" in captured.out
    assert "the index equals a fresh build" in captured.out


def test_a_server_started_in_a_new_worktree_copies_then_checks(repo, main_index, tmp_path):
    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    service = CodememService(tree)
    try:
        assert service.copied_from == main_index and service.state == "empty"
        service.start(watch=False, prewarm=False)
        assert _wait_for(lambda: service.state == "ready" and service.store.dirty_count() == 0), service.last_error
        resp = service.search("expire sessions", k=5)
        assert "expire_sessions" in [r.qualname for r in resp.results] and resp.freshness.complete
        assert service.indexer.verify() == []
    finally:
        service.close()


def test_an_index_folder_the_caller_chose_is_left_alone(repo, main_index, tmp_path):
    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    service = CodememService(tree, index_dir=tmp_path / "chosen")
    try:
        assert service.copied_from is None and service.store.counts()["chunks"] == 0
        assert not (tmp_path / "chosen" / RECORD).exists()
    finally:
        service.close()


def test_the_main_checkout_copies_from_a_worktree_too(repo, tmp_path):
    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    _indexed(tree)
    service = CodememService(repo)
    try:
        assert service.copied_from == default_index_dir(tree)
        service.update()
        assert service.indexer.verify() == []
    finally:
        service.close()


def test_which_index_a_new_worktree_copies(repo, main_index, tmp_path):
    """Same commit first, then the main checkout, then the most recently updated."""
    a, b = git(repo, "rev-parse", "main"), git(repo, "rev-parse", "feature")
    feature = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    _indexed(feature)
    feature_index = default_index_dir(feature)

    at_a = add_worktree(repo, tmp_path / "trees" / "at-a", "--detach", a)
    at_b = add_worktree(repo, tmp_path / "trees" / "at-b", "--detach", b)
    settings = _settings(at_a)
    assert copy_source(at_a, settings) == main_index  # built at A, and the main checkout
    assert copy_source(at_b, settings) == feature_index  # built at B: only uncommitted edits can differ
    assert copy_source(feature, settings) == main_index  # never its own index

    (at_a / "auth" / "extra.py").write_text("def extra():\n    return 1\n")
    c = commit(at_a, "C")  # a commit no index was built at
    assert c not in (a, b)
    assert copy_source(at_a, settings) == main_index  # the main checkout comes first

    shutil.rmtree(main_index)
    assert copy_source(at_a, settings) == feature_index  # the only one left
    _indexed(at_b)
    assert copy_source(at_a, settings) == default_index_dir(at_b)  # the most recently updated


def test_an_index_with_other_settings_or_another_format_is_not_copied(repo, main_index, tmp_path):
    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    settings = _settings(tree)
    assert copy_source(tree, settings) == main_index
    assert copy_source(tree, {**settings, "max_block_lines": 7}) is None  # the first update would rebuild it

    conn = sqlite3.connect(main_index / DB)
    conn.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")  # written by a newer codemem
    conn.commit()
    conn.close()
    assert copy_source(tree, settings) is None
    service = CodememService(tree)  # so the worktree builds its own index, and can open it
    try:
        assert service.copied_from is None
        assert service.update().files_changed > TO_B["files_changed"]
        assert service.indexer.verify() == []
    finally:
        service.close()


def test_an_index_that_was_never_checked_is_not_copied(repo, main_index, tmp_path):
    """A copy that no full check has compared with its files says nothing certain about any commit."""
    first = add_worktree(repo, tmp_path / "trees" / "first", "feature")
    service = CodememService(first)  # copies, and stops before its first update
    assert service.copied_from == main_index
    service.close()
    shutil.rmtree(main_index)
    second = add_worktree(repo, tmp_path / "trees" / "second", "--detach", "feature")
    assert copy_source(second, _settings(second)) is None


# --------------------------------------------------------------------------- clean-up


def _start(checkout):
    """What any codemem start does for a checkout's default index folder."""
    CodememService(checkout).close()


def test_the_index_of_a_removed_worktree_is_deleted(repo, main_index, tmp_path):
    kept = add_worktree(repo, tmp_path / "trees" / "kept", "feature")
    gone = add_worktree(repo, tmp_path / "trees" / "gone", "-b", "gone")
    for tree in (kept, gone):
        _indexed(tree)
    kept_index, gone_index = default_index_dir(kept), default_index_dir(gone)
    assert json.loads((gone_index / RECORD).read_text()) == {"worktree": str(gone), "repository": str(repo / ".git")}
    assert not (main_index / RECORD).exists()  # the main checkout is no worktree: never recorded, never deleted
    _start(repo)
    assert gone_index.is_dir()  # the worktree exists

    git(repo, "worktree", "remove", "--force", str(gone))
    assert removable_indexes(kept) == [gone_index]  # seen from any checkout of the repository
    _start(repo)
    assert not gone_index.exists()
    assert (kept_index / DB).is_file() and (main_index / DB).is_file()


def test_a_missing_worktree_keeps_its_index_while_git_still_lists_it(repo, main_index, tmp_path):
    """A folder can be missing for a while (a drive that is not mounted). git still lists the
    worktree then, and the index stays until git forgets it."""
    tree = add_worktree(repo, tmp_path / "trees" / "away", "feature")
    _indexed(tree)
    index = default_index_dir(tree)
    shutil.rmtree(tree)
    _start(repo)
    assert (index / DB).is_file()
    git(repo, "worktree", "prune")
    _start(repo)
    assert not index.exists()


def test_clean_up_refuses_everything_it_cannot_prove_is_a_removed_worktrees_index(repo, main_index, tmp_path, isolated_home):
    tree = add_worktree(repo, tmp_path / "trees" / "gone", "feature")
    _indexed(tree)
    index = default_index_dir(tree)
    indexes = isolated_home / "indexes"
    record = (index / RECORD).read_text()

    # Another repository's worktree, recorded and gone: not this repository's to delete.
    other = tmp_path / "other"
    shutil.copytree(repo, other, ignore=shutil.ignore_patterns(".git"))
    two_commits(other)
    other_tree = add_worktree(other, tmp_path / "trees" / "other-gone", "feature")
    _indexed(other_tree)
    other_index = default_index_dir(other_tree)
    git(other, "worktree", "remove", "--force", str(other_tree))

    git(repo, "worktree", "remove", "--force", str(tree))
    assert removable_indexes(repo) == [index]

    # A copy of the folder under another name: not the folder codemem made for that worktree.
    renamed = indexes / "a-backup"
    shutil.copytree(index, renamed)
    # A folder with no record, and records that cannot be read or name nothing.
    unrecorded = indexes / "unrecorded"
    shutil.copytree(index, unrecorded)
    (unrecorded / RECORD).unlink()
    for name, text in (("broken", "{not json"), ("empty", "{}"), ("wrong-types", '{"worktree": 1, "repository": []}')):
        shutil.copytree(index, indexes / name)
        (indexes / name / RECORD).write_text(text)
    # A link in the index folder to a folder elsewhere that holds the same record.
    elsewhere = tmp_path / "elsewhere" / index.name
    shutil.copytree(index, elsewhere)
    shutil.move(str(index), str(tmp_path / "moved-away"))
    index.symlink_to(elsewhere, target_is_directory=True)
    assert removable_indexes(repo) == []
    _start(repo)
    for folder in (renamed, unrecorded, indexes / "broken", indexes / "empty", indexes / "wrong-types", elsewhere,
                   other_index, main_index):
        assert (folder / DB).is_file(), folder

    # The real folder again, with a file codemem did not write and one being written right now.
    index.unlink()
    shutil.move(str(tmp_path / "moved-away"), str(index))
    assert (index / RECORD).read_text() == record and removable_indexes(repo) == [index]
    lock = IndexLock(index)
    lock.acquire()
    try:
        _start(repo)
        assert (index / DB).is_file()  # a codemem process is writing it: left for a later start
    finally:
        lock.release()
    for name in ("notes.txt", f"{DB}.bak"):
        (index / name).write_text("mine")
    (index / "vec_folder").mkdir()
    _start(repo)
    assert sorted(p.name for p in index.iterdir()) == [f"{DB}.bak", "notes.txt", "vec_folder"]  # codemem's own files went
    _start(repo)  # and what is left has no record: it is never looked at again
    assert removable_indexes(repo) == [] and len(list(index.iterdir())) == 3


def test_a_worktree_made_again_in_the_same_folder_keeps_the_folders_index(repo, main_index, tmp_path):
    tree = add_worktree(repo, tmp_path / "trees" / "again", "-b", "first")
    _indexed(tree)
    git(repo, "worktree", "remove", "--force", str(tree))
    add_worktree(repo, tmp_path / "trees" / "again", "feature")
    service = CodememService(tree)
    try:
        assert service.copied_from is None  # the folder's index is there: one update brings it to the new commit
        stats = service.update()
        assert {"files_changed": stats.files_changed, "files_deleted": stats.files_deleted} == TO_B
        assert service.indexer.verify() == []
    finally:
        service.close()


def test_a_copied_index_equals_a_fresh_build_when_the_source_had_work_queued(repo, tmp_path, fake_config):
    """The source's queue comes along: chunks it had not embedded yet are embedded in the copy."""
    from codemem.indexer import IndexStats

    source = Store(tmp_path / "source")
    Indexer(repo, source, fake_config).structure(IndexStats())  # stage A only: every chunk is queued
    assert source.dirty_count() > 0 and source.counts()["vectors"] == {}
    source.close()
    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    assert copy_index(tmp_path / "source", tmp_path / "copy")
    copy, fresh = Store(tmp_path / "copy"), Store(tmp_path / "fresh")
    Indexer(tree, copy, fake_config).update()
    Indexer(tree, fresh, fake_config).update()
    assert diff_snapshots(copy.snapshot(), fresh.snapshot()) == []
    copy.close()
    fresh.close()


def _wait_for(pred, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return False
