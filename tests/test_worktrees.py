"""A new git worktree's index starts from a copy of another checkout's, and the index of a removed
worktree is deleted (worktrees.py). Every repository and worktree here is made under `tmp_path`."""

import json
import os
import shutil
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import anyio
import pytest
from gitrepo import ONLY_ON_A, ONLY_ON_B, TO_B, UNCHANGED, add_worktree, commit, git, needs_git, two_commits

from codemem.cli import main
from codemem.config import Config, default_index_dir, load_config
from codemem.indexer import IgnoreRules, Indexer, walk_source_files
from codemem.render import format_status
from codemem.search import search
from codemem.service import CodememService
from codemem.store import IndexLock, Store, diff_snapshots
from codemem.worktrees import (
    DB, RECORD, _is_gone, checkouts, copy_index, copy_source, git_common_dir, is_linked_worktree, is_worktree_of,
    removable_indexes,
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


def test_a_copy_does_not_keep_its_source_databases_identity(main_index, tmp_path):
    with closing(sqlite3.connect(main_index / DB, isolation_level=None)) as source:
        source.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('database_id', '\"the-source\"')")
    assert copy_index(main_index, tmp_path / "copy")
    with closing(sqlite3.connect(tmp_path / "copy" / DB)) as copy:
        assert copy.execute("SELECT value FROM meta WHERE key = 'database_id'").fetchone() is None
        assert copy.execute("SELECT COUNT(*) FROM meta").fetchone()[0] > 0  # the rest of the meta rows came along


def test_a_copy_never_replaces_an_index(main_index, tmp_path):
    existing = tmp_path / "existing"
    own = Store(existing)
    own.set_meta("mine", True)
    own.close()
    assert not copy_index(main_index, existing)
    own = Store(existing)
    assert own.get_meta("mine") is True and own.counts()["chunks"] == 0
    own.close()

    for suffix in ("-wal", "-shm", "-journal"):  # an index deleted by hand, one of SQLite's side files left behind
        leftover = tmp_path / f"leftover{suffix}"
        leftover.mkdir()
        (leftover / f"{DB}{suffix}").write_bytes(b"old")
        assert not copy_index(main_index, leftover)
        assert not (leftover / DB).exists() and (leftover / f"{DB}{suffix}").read_bytes() == b"old"

    assert not copy_index(tmp_path / "no-such-index", tmp_path / "new")

    interrupted = tmp_path / "interrupted"  # an earlier copy that stopped half way
    interrupted.mkdir()
    (interrupted / f"{DB}.copy-123").write_bytes(b"half")
    assert copy_index(main_index, interrupted)
    assert sorted(p.name for p in interrupted.iterdir()) == [DB, "write.lock"]


def test_a_copy_clears_the_saved_search_indexes_a_deleted_index_left(repo, main_index, tmp_path):
    """Fixed bug: the store matches a saved search index to the vector rows by id. Files left by
    an index that was deleted by hand would be taken for the copy's, which has another index's ids."""
    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    index = default_index_dir(tree)
    own = Store(index)  # an index of its own, built from nothing: its vector ids are not the main index's
    Indexer(tree, own, load_config(tree)).update()
    own.close()
    assert list(index.glob("vec_*"))
    for name in (DB, f"{DB}-wal", f"{DB}-shm"):
        (index / name).unlink(missing_ok=True)
    service = CodememService(tree)
    fresh = Store(tmp_path / "fresh")
    try:
        assert service.copied_from == main_index and not list(index.glob("vec_*"))
        service.update()
        Indexer(tree, fresh, service.config).update()
        for query in ("expire sessions", "record audit event", "disable user"):
            by_meaning = [
                [r.key for r in search(store, query, service.config, k=5, signals=["code", "usage"]).results]
                for store in (service.store, fresh)
            ]
            assert by_meaning[0] == by_meaning[1]
    finally:
        fresh.close()
        service.close()


def test_two_starts_at_once_make_one_copy(main_index, tmp_path):
    """Two codemem processes started in the same new worktree: one copies, the other waits for it
    and then finds the index there."""
    start = threading.Barrier(4)

    def one_start(_):
        start.wait(10)
        return copy_index(main_index, tmp_path / "copy")

    with ThreadPoolExecutor(4) as pool:
        made = list(pool.map(one_start, range(4)))
    assert sorted(made) == [False, False, False, True]
    copy, source = Store(tmp_path / "copy"), Store(main_index)
    assert copy.counts() == source.counts() and copy.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert sorted(p.name for p in (tmp_path / "copy").iterdir() if not p.name.startswith(DB + "-")) == [DB, "write.lock"]
    copy.close()
    source.close()


def test_a_copy_does_not_count_as_an_index_until_it_is_checked(repo, main_index, tmp_path, capsys):
    """`codemem search` follows the checkout only with an index that is the checkout's own. A copy
    that no full check has compared with the files is not: the command asks for `codemem index`."""
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


@pytest.fixture
def held_check(main_index, monkeypatch):
    """Every full check waits until the test sets the event: the time in which a new worktree's
    index is still the copy of the main checkout's (commit A)."""
    gate = threading.Event()
    structure = Indexer.structure

    def held(self, *args, **kwargs):
        assert gate.wait(30), "the test never let the full check run"
        return structure(self, *args, **kwargs)

    monkeypatch.setattr(Indexer, "structure", held)
    yield gate
    gate.set()


def _keys(resp):
    return [r.key for r in resp.results]


def test_a_search_waits_for_the_first_check_of_a_copied_index(repo, tmp_path, held_check):
    """Fixed bug: until its first full check had run, a new worktree's server answered from the
    copy, which is the other checkout's code, with the note of an index that is being built. A
    search and `get_chunk` now wait for that check, as they wait for stage A of a save."""
    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    service = CodememService(tree)
    try:
        assert service.copy_unchecked()
        service.start(watch=False, prewarm=False)
        threading.Timer(0.5, held_check.set).start()  # the check takes half a second: well within a search's 4 s
        started = time.monotonic()
        resp = service.search("logout", k=10, wait_for_models=False)
        assert time.monotonic() - started >= 0.4 and "api/routes.py::logout" not in _keys(resp)  # exists only on A
        assert not resp.freshness.unchecked_copy and service.has_index() and not service.copy_unchecked()
        assert "auth/audit.py::record_audit_event" in _keys(service.search("record audit event", k=5))  # only on B
        assert service.get_chunk(ONLY_ON_A[0]) is None
        assert "unchecked_copy" not in service.get_chunk(ONLY_ON_B[0])
    finally:
        service.close()


def test_get_chunk_waits_for_the_first_check_of_a_copied_index(repo, tmp_path, held_check):
    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    service = CodememService(tree)
    try:
        service.start(watch=False, prewarm=False)
        threading.Timer(0.5, held_check.set).start()
        assert service.get_chunk(ONLY_ON_A[0]) is None  # the copy has it: this checkout does not
        assert service.get_chunk(ONLY_ON_B[0])["qualname"] == "record_audit_event"
    finally:
        service.close()


def test_an_answer_from_a_copy_that_is_not_checked_in_time_says_so(repo, tmp_path, held_check):
    """The first check of a worktree far from its source, or of a large repository, can take
    longer than a search waits. The answer then comes from the copy, and says so."""
    from mcp import Client

    from codemem import prompts
    from codemem.server import build_server

    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    (tree / ".codemem.toml").write_text("catchup_budget_ms = 300\n")
    service = CodememService(tree)
    notice = prompts.copy_notice()
    assert "started as a copy of another checkout's index" in notice and "can be the other checkout's code" in notice
    try:
        service.start(watch=False, prewarm=False)
        resp = service.search("logout", k=10, wait_for_models=False)
        assert "api/routes.py::logout" in _keys(resp)  # the other checkout's code ...
        assert resp.freshness.unchecked_copy and not resp.freshness.complete  # ... and the answer knows it
        assert service.get_chunk(ONLY_ON_A[0])["unchecked_copy"] is True
        assert service.get_chunk(ONLY_ON_B[0]) is None
        server = build_server(service)

        async def before():
            async with Client(server) as client:
                found = (await client.call_tool("search_code", {"query": "logout"})).content[0].text
                assert found.startswith(notice) and "logout" in found and "still being built" not in found
                shown = (await client.call_tool("get_chunk", {"ref": ONLY_ON_A[0]})).content[0].text
                assert shown.startswith(notice) and "def logout" in shown
                missing = (await client.call_tool("get_chunk", {"ref": ONLY_ON_B[0]})).content[0].text
                assert missing.startswith("No indexed function matches") and missing.endswith(notice)

        anyio.run(before)
        held_check.set()
        assert _wait_for(lambda: service.state == "ready" and service.store.dirty_count() == 0), service.last_error

        async def after():
            async with Client(server) as client:
                found = (await client.call_tool("search_code", {"query": "record audit event"})).content[0].text
                assert "record_audit_event" in found and "copy of another checkout" not in found
                gone = (await client.call_tool("get_chunk", {"ref": ONLY_ON_A[0]})).content[0].text
                assert gone.startswith("No indexed function matches") and "copy of another checkout" not in gone
                shown = (await client.call_tool("get_chunk", {"ref": UNCHANGED[0]})).content[0].text
                assert shown.startswith("auth/db.py:")

        anyio.run(after)
        assert service.search("logout", k=10).freshness.complete and service.indexer.verify() == []
    finally:
        service.close()


def test_a_copy_that_nothing_checks_says_what_it_is(repo, main_index, tmp_path):
    """A service nobody started has no writer that would make the first check. What it answers
    with is marked all the same."""
    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    service = CodememService(tree)
    try:
        resp = service.search("logout", k=10)
        assert "api/routes.py::logout" in _keys(resp) and resp.freshness.unchecked_copy
        assert service.get_chunk(ONLY_ON_A[0])["unchecked_copy"] is True
        service.update()
        assert not service.search("logout", k=10).freshness.unchecked_copy
    finally:
        service.close()


def test_an_index_of_its_own_checkout_is_not_asked_whether_it_is_a_copy(repo, main_index, monkeypatch):
    """The normal case pays nothing: a service whose index is its checkout's answers from its
    state, without a query to the store."""
    service = CodememService(repo)
    try:
        def fail(*args, **kwargs):
            raise AssertionError("an index that is the checkout's own was asked for its rows")

        monkeypatch.setattr(service.store, "chunk_total", fail)
        monkeypatch.setattr(service, "has_index", fail)
        assert service.state == "ready" and not service.copy_unchecked()
        assert "unchecked_copy" not in service.get_chunk(UNCHANGED[0])
        assert service.search("revoke session", k=3).freshness.complete
    finally:
        service.close()


def test_the_mcp_server_started_in_a_new_worktree_serves_it_from_the_copy(repo, main_index, tmp_path, isolated_home, fake_config):
    """Real `codemem mcp` over stdio, launched in the worktree's folder as an agent host does."""
    import sys

    from mcp import Client, StdioServerParameters

    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    # A chunk of a file that is the same on both commits keeps the main index's id in a copy; a
    # build of the worktree from nothing numbers it differently.
    main, fresh = Store(main_index), Store(tmp_path / "fresh")
    Indexer(tree, fresh, fake_config).update()
    copied_id = main.get_chunk_by_key(UNCHANGED[0]).chunk_id
    assert fresh.get_chunk_by_key(UNCHANGED[0]).chunk_id != copied_id
    main.close()
    fresh.close()

    env = {**os.environ, "CODEMEM_MODEL": "fake:64", "CODEMEM_HOME": str(isolated_home)}
    params = StdioServerParameters(command=sys.executable, args=["-m", "codemem.cli", "mcp"], env=env, cwd=str(tree))

    async def run():
        with anyio.fail_after(60):
            async with Client(params) as client:
                for _ in range(200):
                    status = (await client.call_tool("index_status", {})).content[0].text
                    if "state: ready" in status and "pending:" not in status:
                        break
                    await anyio.sleep(0.1)
                assert "state: ready" in status and f"repo: {tree}" in status
                assert f"index: {default_index_dir(tree)}" in status
                assert f"[id {copied_id}]" in (await client.call_tool("get_chunk", {"ref": UNCHANGED[0]})).content[0].text
                found = (await client.call_tool("search_code", {"query": "expire sessions"})).content[0].text
                assert "expire_sessions" in found  # only on the worktree's commit
                gone = (await client.call_tool("get_chunk", {"ref": ONLY_ON_A[0]})).content[0].text
                assert "No indexed function matches" in gone

    anyio.run(run)
    assert (default_index_dir(tree) / RECORD).is_file()


def test_an_index_folder_the_caller_chose_is_left_alone(repo, main_index, tmp_path):
    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    service = CodememService(tree, index_dir=tmp_path / "chosen")
    try:
        assert service.copied_from is None and service.store.counts()["chunks"] == 0
        assert not (tmp_path / "chosen" / RECORD).exists()
    finally:
        service.close()


def test_a_failed_copy_or_clean_up_never_stops_a_start(repo, main_index, tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("disk full")

    tree = add_worktree(repo, tmp_path / "trees" / "feature", "feature")
    monkeypatch.setattr("codemem.worktrees.removable_indexes", fail)
    service = CodememService(tree)
    assert service.copied_from == main_index  # the clean-up failed: the copy is made all the same
    service.close()
    shutil.rmtree(default_index_dir(tree))
    monkeypatch.setattr("codemem.worktrees.copy_index", fail)
    service = CodememService(tree)
    try:
        assert service.copied_from is None  # the copy failed: the index is built from nothing
        assert service.update().files_changed == 6
        assert service.indexer.verify() == []
    finally:
        service.close()
    shutil.rmtree(default_index_dir(tree))
    monkeypatch.setattr(Config, "index_settings", fail)  # a model folder that cannot be read, say
    service = CodememService(tree)
    assert service.copied_from is None and (default_index_dir(tree) / RECORD).is_file()
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


# --------------------------------------------------------------------------- a worktree inside another checkout

INSIDE = ".claude/worktrees/agent-1"  # where agent hosts put a worktree: inside the main checkout


def _files_and_chunks(checkout):
    store = Store(default_index_dir(checkout))
    try:
        counts = store.counts()
        return counts["files"], counts["chunks"]
    finally:
        store.close()


def test_a_worktree_inside_a_checkout_is_left_out_of_that_checkouts_index(repo, main_index):
    """Fixed bug: the main checkout's scan read a worktree placed inside it, so its index held
    every function twice. The worktree is another checkout: the scan counts it and leaves it out."""
    before = _files_and_chunks(repo)
    inner = add_worktree(repo, repo / INSIDE, "feature")
    service = CodememService(repo)
    try:
        stats = service.update()
        assert (stats.files_changed, stats.files_deleted) == (0, 0) and _files_and_chunks(repo) == before
        assert not any(path.startswith(".claude/") for path in service.store.get_files())
        found = [r.key for r in service.search("revoke session", k=10).results]
        assert found.count("auth/sessions.py::revoke_session") == 1 and not any(".claude/" in key for key in found)
        info = service.status()
        assert info["coverage"]["worktrees"] == {"count": 1, "examples": [INSIDE]}
        assert f"not indexed here (git worktrees, each a checkout with its own index): 1 folder ({INSIDE})" in format_status(info)
        assert service.indexer.verify() == []
    finally:
        service.close()

    # The worktree's own index is the one that holds its files, as for a worktree anywhere else.
    service = CodememService(inner)
    try:
        assert service.copied_from == main_index and service.index_dir == default_index_dir(inner) != main_index
        stats = service.update()
        assert {"files_changed": stats.files_changed, "files_deleted": stats.files_deleted} == TO_B
        assert all(service.store.get_chunk_by_key(key) is not None for key in ONLY_ON_B)
        assert service.status()["coverage"]["worktrees"] == {"count": 0, "examples": []}
        assert service.indexer.verify() == []
    finally:
        service.close()


def test_an_index_that_read_a_worktree_inside_its_checkout_drops_those_files(repo, monkeypatch):
    """An index built before the scan knew the rule holds the worktree's files. The next full
    check drops them."""
    add_worktree(repo, repo / INSIDE, "--detach", "main")
    with monkeypatch.context() as as_before:
        as_before.setattr(IgnoreRules, "other_checkout", lambda self, folder: False)
        assert _indexed(repo).files_changed == 12  # every file twice
    service = CodememService(repo)
    try:
        stats = service.update()
        assert (stats.files_changed, stats.files_deleted) == (0, 6) and service.store.counts()["files"] == 6
        assert service.indexer.verify() == []
    finally:
        service.close()


def test_a_worktree_inside_a_worktree_is_left_out_too(repo, tmp_path, fake_config):
    """The rule asks for the repository's shared git folder, which a linked worktree names in its
    own git folder: it holds for a checkout that is itself a linked worktree."""
    outer = add_worktree(repo, tmp_path / "trees" / "outer", "feature")
    add_worktree(repo, outer / INSIDE, "--detach", "main")
    files = walk_source_files(outer, fake_config)
    assert "auth/audit.py" in files and not any(path.startswith(".claude/") for path in files)
    # A folder that is no checkout of the repository reads what is in it, as before.
    assert f"outer/{INSIDE}/auth/sessions.py" in walk_source_files(tmp_path / "trees", fake_config)


def test_a_submodule_and_other_repositories_inside_a_checkout_are_read_as_before(repo, tmp_path, fake_config):
    """Only another checkout of the same repository is left out. A submodule has a `.git` file
    too; a nested repository has a `.git` folder; a worktree of another repository has a `.git`
    file that names that repository. All three stay in the index."""
    code = "def helper():\n    return 1\n"
    (repo / ".git" / "modules" / "lib").mkdir(parents=True)  # a submodule, as `git submodule add` lays it out
    (repo / "lib").mkdir()
    (repo / "lib" / ".git").write_text("gitdir: ../.git/modules/lib\n")
    (repo / "lib" / "lib.py").write_text(code)
    nested = repo / "tools" / "nested"  # a repository of its own
    nested.mkdir(parents=True)
    (nested / "nested.py").write_text(code)
    git(nested, "init", "-q", "-b", "main")
    commit(nested, "nested")
    other = tmp_path / "other"  # another repository, with a worktree placed inside this checkout
    other.mkdir()
    (other / "other.py").write_text(code)
    git(other, "init", "-q", "-b", "main")
    commit(other, "other")
    foreign = add_worktree(other, repo / "third_party" / "other", "--detach", "main")
    common = repo / ".git"
    assert not any(is_worktree_of(folder, common) for folder in (repo / "lib", nested, foreign, repo, repo / "auth"))
    assert is_worktree_of(foreign, other / ".git")

    inner = add_worktree(repo, repo / INSIDE, "--detach", "main")
    assert is_worktree_of(inner, common) and not is_worktree_of(inner, other / ".git")
    files = walk_source_files(repo, fake_config)
    assert {"lib/lib.py", "tools/nested/nested.py", "third_party/other/other.py"} <= set(files)
    assert not any(path.startswith(".claude/") for path in files)


def test_another_spelling_of_the_checkouts_folder_finds_the_worktree_inside_it(repo, fake_config):
    """On a disk that ignores case, codemem can be started in `SAMPLE_REPO` while git wrote
    `sample_repo` into the worktree's `.git` file. It is the same repository all the same."""
    add_worktree(repo, repo / INSIDE, "--detach", "main")
    spelled = repo.with_name(repo.name.upper())
    if not spelled.exists():
        pytest.skip("this disk tells upper case from lower case")
    files = walk_source_files(spelled, fake_config)
    assert "auth/sessions.py" in files and not any(path.startswith(".claude/") for path in files)


def test_changed_paths_inside_a_worktree_are_not_this_checkouts(repo, main_index):
    """What the watcher reports is checked by the same rule as the scan: a path in a worktree
    inside the checkout changes nothing, whether it comes as a file or as a folder."""
    inner = add_worktree(repo, repo / INSIDE, "feature")
    (inner / "auth" / "extra.py").write_text("def extra():\n    return 1\n")
    store = Store(main_index)
    try:
        indexer = Indexer(repo, store, load_config(repo))
        stats = indexer.update(paths=[INSIDE, f"{INSIDE}/auth/extra.py", f"{INSIDE}/auth", ".claude"])
        assert (stats.files_changed, stats.files_deleted, stats.queued) == (0, 0, 0) and store.counts()["files"] == 6
        assert not indexer.allows(f"{INSIDE}/auth/extra.py") and indexer.allows("auth/sessions.py")
        assert indexer.verify() == []
    finally:
        store.close()


def test_the_watcher_ignores_saves_in_a_worktree_inside_the_checkout(repo, main_index):
    """Saves in the inner worktree are its own index's. For the outer checkout they would be a
    wake-up of its writer at every save, and a full check at every change of the inner
    `.gitignore` or `.codemem.toml`."""
    inner = add_worktree(repo, repo / INSIDE, "feature")
    service = CodememService(repo)
    calls = []
    try:
        service.update()
        service.notify = lambda paths, reconcile=False: calls.append((paths, reconcile))
        service.start_watcher()
        time.sleep(0.3)
        (inner / "auth" / "extra.py").write_text("def extra():\n    return 1\n")
        (inner / "auth" / "sessions.py").unlink()
        (inner / "pkg").mkdir()
        (inner / "pkg" / "new.py").write_text("def new():\n    return 2\n")
        (inner / ".gitignore").write_text("scratch/\n")
        (inner / ".codemem.toml").write_text("debounce_ms = 300\n")
        time.sleep(1.5)
        assert calls == []
        (repo / "auth" / "extra.py").write_text("def extra():\n    return 1\n")
        assert _wait_for(lambda: calls)
        assert calls[0] == ({"auth/extra.py"}, False)
    finally:
        service.close()


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


def test_a_folder_taken_over_by_another_checkout_is_no_longer_a_worktrees_index(repo, main_index, tmp_path):
    """Fixed bug: a worktree is removed, and its folder becomes a clone, a checkout of its own. The
    index folder is the same (it is named after the path), so the worktree's record must go: or
    the clone's index would be deleted the day its folder is missing."""
    tree = add_worktree(repo, tmp_path / "trees" / "reused", "feature")
    _indexed(tree)
    index = default_index_dir(tree)
    git(repo, "worktree", "remove", "--force", str(tree))
    git(tmp_path, "clone", "-q", str(repo), str(tree))
    _indexed(tree)
    assert (index / DB).is_file() and not (index / RECORD).exists()
    shutil.rmtree(tree)
    _start(repo)
    assert (index / DB).is_file()


def test_another_spelling_of_a_worktrees_folder_is_the_same_worktree(repo, main_index, tmp_path):
    """Fixed bug: on a disk that ignores case, git can list `Trees/Away` while codemem was started
    in `trees/away`. The missing worktree is still listed, whatever the spelling."""
    tree = add_worktree(repo, tmp_path / "Trees" / "Away", "feature")
    spelled = tmp_path / "trees" / "away"
    if not spelled.exists():
        pytest.skip("this disk tells upper case from lower case")
    _indexed(spelled)
    index = default_index_dir(spelled)
    assert index != default_index_dir(tree) and "away" in json.loads((index / RECORD).read_text())["worktree"]
    shutil.rmtree(tree)
    _start(repo)
    assert (index / DB).is_file()
    git(repo, "worktree", "prune")
    _start(repo)
    assert not index.exists()


def test_nothing_is_deleted_when_it_cannot_be_known_that_a_worktree_is_gone(repo, main_index, tmp_path):
    tree = add_worktree(repo, tmp_path / "trees" / "gone", "feature")
    _indexed(tree)
    index = default_index_dir(tree)
    git(repo, "worktree", "remove", "--force", str(tree))
    unreadable = repo / ".git" / "worktrees" / "unreadable"  # an entry that names no folder
    unreadable.mkdir(parents=True)
    assert removable_indexes(repo) == []
    _start(repo)
    assert (index / DB).is_file()
    unreadable.rmdir()
    assert removable_indexes(repo) == [index]

    if os.name == "nt" or os.geteuid() == 0:
        return  # no way here to make a folder that cannot be looked into
    tree.parent.chmod(0)  # nor when nobody can tell whether the worktree's folder exists
    try:
        assert not _is_gone(tree) and removable_indexes(repo) == []
    finally:
        tree.parent.chmod(0o755)
    assert _is_gone(tree) and removable_indexes(repo) == [index]


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
