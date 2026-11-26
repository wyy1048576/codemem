"""What a branch switch costs. One index follows its checkout from commit A to commit B and back
(gitrepo.py: a changed, an added, a moved and a deleted file). Coming back to a commit seen before
must cost no model call, work queued for the branch that was left must not be done, and a search
right after a switch embeds first what its own keywords rank on top. `codemem search` on the
command line, which no server keeps current, brings the index to the checkout before it answers.

The model is a fake one that records every text it is asked to embed.
"""

import json
import threading
import time
from contextlib import contextmanager

import pytest
from conftest import RecordingEmbedder
from gitrepo import ONLY_ON_A, ONLY_ON_B, TO_A, TO_B, UNCHANGED, add_worktree, git, needs_git, two_commits

from codemem import service as service_module
from codemem.cli import main
from codemem.config import default_index_dir
from codemem.embedder import FakeEmbedder
from codemem.indexer import Indexer, IndexStats
from codemem.service import CodememService
from codemem.store import IndexLock, Store, diff_snapshots

pytestmark = needs_git
CHANGED_BOTH_WAYS = "auth/sessions.py::revoke_session"  # its body differs between A and B


@pytest.fixture
def repo(sample_repo):
    """The sample repo as a git repository on commit A; commit B is on the branch `feature`."""
    two_commits(sample_repo)
    return sample_repo.resolve()


class Index:
    """An index of `repo` and the model calls made for it."""

    def __init__(self, repo, folder, config, cache="global"):
        config.vector_cache = cache
        self.repo, self.model = repo, RecordingEmbedder()
        self.store = Store(folder)
        self.indexer = Indexer(repo, self.store, config, embedder_factory=lambda m, c: self.model)

    def switch(self, branch, *, vectors=True):
        """Check `branch` out and update the index: both stages, or (a switch away before the
        vectors were computed) the structure only. Returns the update's statistics and the texts
        the model was given."""
        git(self.repo, "checkout", "-q", branch)
        before = len(self.model.documents)
        if vectors:
            stats = self.indexer.update()
        else:
            stats = IndexStats()
            self.indexer.structure(stats)
        return stats, self.model.documents[before:]

    def ids(self, keys):
        return {key: chunk.chunk_id for key in keys if (chunk := self.store.get_chunk_by_key(key)) is not None}


@pytest.fixture
def index(repo, tmp_path, fake_config):
    idx = Index(repo, tmp_path / "idx", fake_config)
    idx.indexer.update()  # current on A
    yield idx
    idx.store.close()


def _files(stats):
    return {"files_changed": stats.files_changed, "files_deleted": stats.files_deleted}


def _total(counter):
    return sum(counter.values())


# --------------------------------------------------------------------------- one index, updated


def test_a_switch_touches_only_the_files_that_differ(index):
    """Stage A re-chunks the five files that differ. Chunks of other files keep their ids and
    vectors, and a chunk that only changed keeps its id."""
    stable = (*UNCHANGED, CHANGED_BOTH_WAYS)
    on_a = index.ids(stable)
    vectors = {key: index.store.vector_parts("code", [on_a[key]]) for key in UNCHANGED}
    assert set(index.ids(ONLY_ON_A)) == set(ONLY_ON_A) and not index.ids(ONLY_ON_B)

    to_b, _ = index.switch("feature")
    assert _files(to_b) == TO_B and to_b.files_scanned == 6
    assert (to_b.chunks_added, to_b.chunks_updated, to_b.chunks_deleted) == (6, 1, 6)
    assert set(index.ids(ONLY_ON_B)) == set(ONLY_ON_B) and not index.ids(ONLY_ON_A)
    assert index.ids(stable) == on_a
    assert index.indexer.verify() == []

    to_a, _ = index.switch("main")
    assert _files(to_a) == TO_A
    assert (to_a.chunks_added, to_a.chunks_updated, to_a.chunks_deleted) == (6, 1, 6)
    assert index.ids(stable) == on_a
    assert {key: index.store.vector_parts("code", [on_a[key]]) for key in UNCHANGED} == vectors  # the same rows


def test_coming_back_to_a_branch_makes_no_model_call(index):
    on_a = index.store.snapshot()
    to_b, texts_for_b = index.switch("feature")
    assert _total(to_b.model_embedded) == len(texts_for_b) > 0  # the first visit: B's own texts
    assert _total(to_b.cache_hits) == 0

    to_a, texts_for_a = index.switch("main")
    assert texts_for_a == [] and _total(to_a.model_embedded) == 0
    assert _total(to_a.embedded) == _total(to_a.cache_hits) > 0  # every vector A needs again: from the cache
    assert index.store.dirty_count() == 0
    assert diff_snapshots(index.store.snapshot(), on_a) == []
    assert index.indexer.verify() == []

    again, texts = index.switch("feature")  # and B is a branch seen before now
    assert texts == [] and _total(again.model_embedded) == 0
    assert index.indexer.verify() == []


def test_a_quick_double_switch_embeds_nothing(index):
    """A -> B -> A before any vector was computed for B. B's texts are never embedded, and A's
    vectors are in the index still or in the cache."""
    on_a = index.store.snapshot()
    to_b, texts = index.switch("feature", vectors=False)
    assert texts == [] and to_b.queued == index.store.dirty_count() > 0

    to_a, texts = index.switch("main")
    assert texts == []
    assert _total(to_a.model_embedded) == 0 and index.store.dirty_count() == 0
    # Chunks that only changed kept A's vectors while B's were pending: fewer rows to write again.
    assert 0 < _total(to_a.embedded) == _total(to_a.cache_hits)
    assert diff_snapshots(index.store.snapshot(), on_a) == []
    assert index.indexer.verify() == []


def test_a_quick_double_switch_leaves_no_work_queued_for_the_other_branch(index):
    """After A -> B -> A without stage B, the queue holds chunks of A only, and draining it stores
    no vector for a text of B."""
    embedded_on_a = len(index.model.documents)
    index.switch("feature", vectors=False)
    queued_on_b = set(index.store.dirty_batch(1000))
    b_only = set(index.ids(ONLY_ON_B).values())
    assert b_only <= queued_on_b

    git(index.repo, "checkout", "-q", "main")
    index.indexer.structure(IndexStats())
    queued = set(index.store.dirty_batch(1000))
    assert queued and not (queued & b_only) and queued <= index.store.chunk_ids()
    assert index.indexer.embed_pending(IndexStats())
    assert len(index.model.documents) == embedded_on_a
    assert index.indexer.verify() == []


# --------------------------------------------------------------------------- without the vector cache


def test_without_the_cache_coming_back_embeds_again_what_the_switch_removed(repo, tmp_path, fake_config):
    """What the vector cache is worth. Of A's 33 vectors, 12 belong to texts that differ on B.
    With the cache off, coming back embeds all 12 again if B's vectors were computed, and 8 if they
    were not: the 4 others still sat in the index, under chunks that exist on both commits."""
    def round_trip(cache, vectors_on_b):
        idx = Index(repo, tmp_path / f"idx-{cache}-{vectors_on_b}", fake_config, cache)
        try:
            built = idx.indexer.update()
            idx.switch("feature", vectors=vectors_on_b)
            to_a, texts = idx.switch("main")
            assert idx.store.dirty_count() == 0
            return built, to_a, texts
        finally:
            idx.store.close()

    built, to_a, texts = round_trip("off", vectors_on_b=True)
    assert _total(built.model_embedded) == 33
    assert to_a.model_embedded == {"code": 7, "usage": 5} and len(texts) == 12
    assert _total(to_a.reused) == 0  # nothing of it is left in the index

    _, to_a, texts = round_trip("off", vectors_on_b=False)
    assert to_a.model_embedded == {"code": 6, "usage": 2} and len(texts) == 8
    removed = ("auth/users.py", "api/routes.py")  # only on A: the switch to B deleted their chunks, vectors included
    assert all(any(path in text.splitlines()[0] for path in removed) for text in texts)

    _, to_a, texts = round_trip("global", vectors_on_b=True)  # the same round trip with the cache on
    assert texts == [] and to_a.cache_hits == {"code": 7, "usage": 5}


# --------------------------------------------------------------------------- the service and the watcher


class GatedModel(RecordingEmbedder):
    """A model that can be held in the middle of a call: `entered` is set when a call starts, and
    the call returns once `gate` is set."""

    def __init__(self):
        super().__init__()
        self.gate, self.entered = threading.Event(), threading.Event()
        self.gate.set()
        self.started = 0  # document calls begun

    def embed_documents(self, texts):
        self.documents.extend(texts)
        self.started += 1
        self.entered.set()
        assert self.gate.wait(60), "the test never released the model"
        return self._embed(texts)


def _wait_for(pred, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _commits(repo):
    return git(repo, "rev-parse", "main"), git(repo, "rev-parse", "feature")


def _follows(service, commit, present, absent):
    """The service's index is current on `commit`: its structure, and every vector."""
    store = service.store
    return (
        store.get_meta("indexed_commit") == commit
        and all(store.get_chunk_by_key(key) is not None for key in present)
        and all(store.get_chunk_by_key(key) is None for key in absent)
        and store.dirty_count() == 0
    )


@pytest.fixture
def served(repo, tmp_path, monkeypatch, request):
    """A running service (writer and watcher) with a recording model, for the main checkout or for
    a linked worktree of it, current on commit A. Yields (service, model, checkout, a, b)."""
    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    a, b = _commits(repo)
    checkout = repo
    if getattr(request, "param", "main checkout") == "linked worktree":
        checkout = add_worktree(repo, tmp_path / "trees" / "linked", "--detach", a)
    model = GatedModel()
    service = CodememService(checkout, index_dir=tmp_path / "idx", embedder_factory=lambda m, c: model)
    reconciles = []
    notify = service.notify
    service.notify = lambda paths, reconcile=False: (reconciles.append(reconcile), notify(paths, reconcile))[1]
    service.reconciles = reconciles
    try:
        assert service.update() is not None
        service.start(prewarm=False)
        time.sleep(0.3)  # the watcher is listening
        yield service, model, checkout, a, b
    finally:
        model.gate.set()
        service.close()


@pytest.mark.parametrize("served", ["main checkout", "linked worktree"], indirect=True)
def test_the_watcher_follows_a_switch_and_coming_back_makes_no_model_call(served):
    service, model, checkout, a, b = served
    del service.reconciles[:]
    git(checkout, "checkout", "-q", "--detach", b)
    assert _wait_for(lambda: _follows(service, b, ONLY_ON_B, ONLY_ON_A)), service.status(check_staleness=False)
    if service.status(check_staleness=False)["watching"]:
        assert _wait_for(lambda: any(service.reconciles))  # the change of HEAD asked for a full check
        assert _wait_for(lambda: _follows(service, b, ONLY_ON_B, ONLY_ON_A))
    assert service.indexer.verify() == []
    embedded_for_b = len(model.documents)
    assert embedded_for_b > 33

    git(checkout, "checkout", "-q", "--detach", a)
    assert _wait_for(lambda: _follows(service, a, ONLY_ON_A, ONLY_ON_B)), service.status(check_staleness=False)
    assert len(model.documents) == embedded_for_b  # the second visit to A: no model call
    assert _wait_for(lambda: service.search("revoke session", k=5).freshness.complete)
    assert service.indexer.verify() == []


def test_a_switch_back_during_a_model_call_ends_the_work_for_the_branch_left(served):
    """A -> B, and back to A while the model is busy with B's first texts. That call is the last
    one made for B: the writer stops before its next call, applies the switch, and A's vectors
    come from the index and the cache."""
    service, model, checkout, a, b = served
    if not service.status(check_staleness=False)["watching"]:
        pytest.skip("needs file events")
    model.entered.clear()
    model.gate.clear()
    calls_on_a = model.started
    git(checkout, "checkout", "-q", "--detach", b)
    assert model.entered.wait(30)  # stage A ran for B; stage B is inside its first model call
    assert service.store.dirty_count() > 0

    git(checkout, "checkout", "-q", "--detach", a)
    assert _wait_for(lambda: service._reconcile or service._dirty)  # the watcher has handed the switch over
    in_flight = len(model.documents)
    model.gate.set()

    assert _wait_for(lambda: _follows(service, a, ONLY_ON_A, ONLY_ON_B)), service.status(check_staleness=False)
    assert model.started == calls_on_a + 1 and model.documents[in_flight:] == []
    assert service.indexer.verify() == []


# --------------------------------------------------------------------------- a search right after a switch


class _ByThread:
    """Notes which thread asked for each text: a search embeds in its own thread, the writer and
    the model's loader in theirs."""

    def note(self, texts):
        if not hasattr(self, "asked"):
            self.asked: list[tuple[str, str]] = []  # (thread name, text)
        self.asked.extend((threading.current_thread().name, text) for text in texts)

    def by_this_thread(self):
        return [text for thread, text in getattr(self, "asked", []) if thread == threading.current_thread().name]


class ModelByThread(_ByThread, RecordingEmbedder):
    def embed_documents(self, texts):
        self.note(texts)
        return super().embed_documents(texts)


class Clock:
    """Time that moves only when a test says so."""

    now = 1000.0

    def __call__(self):
        return self.now


class ModelThatCanLeave(_ByThread, FakeEmbedder):
    """The fake model as one that is freed when idle: on a clock the test moves, and with a load
    the test can hold (`gate`). Before each document call of the test's own thread it tries to
    free itself, as the writer's quiet step may at that very moment (`freed_under_the_search`)."""

    IDLE_SECONDS = 300.0

    def __init__(self, clock):
        super().__init__(64, clock)
        self.gate = threading.Event()
        self.gate.set()
        self.loaded_by: list[str] = []  # thread names
        self.freed_under_the_search: list[bool] = []

    def load(self):
        assert self.gate.wait(30), "the test never let the model load"
        self.loaded_by.append(threading.current_thread().name)
        super().load()

    def embed_documents(self, texts):
        self.note(texts)
        if threading.current_thread() is threading.main_thread():
            self.freed_under_the_search.append(self.unload(self.IDLE_SECONDS))
        return super().embed_documents(texts)


@contextmanager
def _running_after_a_switch(repo, index_dir, monkeypatch, model, **service_options):
    """A running service without file events, current on A, whose checkout was just switched to
    B: the next search finds the switch itself, and the 11 chunks it queues."""
    monkeypatch.setattr("codemem.service.POLL_EVERY", 3600.0)  # no full check on a timer during the test
    service = CodememService(repo, index_dir=index_dir, embedder_factory=lambda m, c: model, **service_options)
    try:
        assert service.update() is not None
        service.start(watch=False, prewarm=False)
        assert service.catch_up(budget=30).complete  # the start's own full check is done
        git(repo, "checkout", "-q", "feature")
        del model.asked[:]  # from here on, the lists hold what the test's own searches cause
        if isinstance(model, ModelThatCanLeave):
            del model.freed_under_the_search[:]
        yield service
    finally:
        if isinstance(model, ModelThatCanLeave):
            model.gate.set()
        if service._prewarm is not None:
            service._prewarm.join(10)  # a load a search or the writer started
        service.close()


@pytest.fixture
def switched(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    model = ModelByThread()
    with _running_after_a_switch(repo, tmp_path / "idx", monkeypatch, model) as service:
        yield service, model


@pytest.fixture
def switched_with_a_model_that_can_leave(repo, tmp_path, monkeypatch, fake_config):
    """The same, with a model that can be freed and loaded again, and a long queue: more than 5
    queued chunks are too many to wait for."""
    monkeypatch.setattr("codemem.service.CATCHUP_MAX_CHUNKS", 5)
    clock = Clock()
    model = ModelThatCanLeave(clock)
    with _running_after_a_switch(repo, tmp_path / "idx", monkeypatch, model, config=fake_config) as service:
        yield service, model, clock


def _first_lines(texts):
    return [text.splitlines()[0] for text in texts]


def test_a_search_embeds_its_keyword_results_first_however_long_the_queue(switched, monkeypatch):
    """After a switch the queue can be minutes long, and a search does not wait for it. But a
    pending chunk has no current vector, so the merge would rank it by its keywords alone: the
    search embeds the pending chunks among its own keyword results, and only those."""
    service, model = switched
    monkeypatch.setattr("codemem.service.CATCHUP_MAX_CHUNKS", 5)  # the 11 chunks of this switch are a long queue
    resp = service.search("record audit event", k=3, debug=True)
    mine = model.by_this_thread()
    assert mine and all("auth/audit.py" in line for line in _first_lines(mine))
    assert any("def record_audit_event" in text for text in mine)
    top = resp.results[0]
    assert top.qualname == "record_audit_event" and {"bm25", "code"} <= set(top.ranks)
    assert resp.freshness.indexing and resp.freshness.pending_chunks > 5  # the rest is reported, not waited for
    assert _wait_for(lambda: service.store.dirty_count() == 0)  # and embedded by the writer
    assert service.indexer.verify() == []


def test_a_keyword_only_search_embeds_nothing_of_a_long_queue(switched, monkeypatch):
    service, model = switched
    monkeypatch.setattr("codemem.service.CATCHUP_MAX_CHUNKS", 5)
    resp = service.search("record audit event", k=3, signals=["bm25"])
    assert model.by_this_thread() == [] and resp.results[0].qualname == "record_audit_event"
    assert resp.freshness.indexing


def test_a_search_embeds_its_keyword_results_before_the_rest_of_a_short_queue(switched):
    service, model = switched
    resp = service.search("record audit event", k=3)
    mine = model.by_this_thread()
    audit = sum("auth/audit.py" in line for line in _first_lines(mine))
    assert 0 < audit < len(mine)  # the whole queue fits in the search's time
    assert all("auth/audit.py" in line for line in _first_lines(mine[:audit]))  # its own results went first
    assert resp.freshness.complete and service.indexer.verify() == []


# --------------------------------------------------------------------------- ... while the model is not in memory


def test_a_search_with_a_budget_does_not_load_the_model_for_its_keyword_results(
        switched_with_a_model_that_can_leave, monkeypatch):
    """The model was freed for being idle, and loading it again takes longer than a search may
    wait. The MCP server's search waits for the load within its budget, in the loader's thread,
    and then answers from keywords: its keyword results are embedded under the same rule as the
    rest of the queue, not in a model call of its own that would wait out the load."""
    service, model, _ = switched_with_a_model_that_can_leave
    monkeypatch.setattr(service_module, "IDLE_RELOAD_WAIT", 0.05)  # the load outlasts the longer wait too
    assert model.unload() and not model.ready
    model.gate.clear()
    service.catch_up(budget=30, embed=False)  # the switch is applied: 11 chunks are queued
    service.config.catchup_budget_ms = 1000  # of which the search spends most on waiting for the model
    resp = service.search("record audit event", k=3, wait_for_models=False)
    assert model.by_this_thread() == []  # no model call in the search's own thread
    assert resp.models_loading and resp.signals == ["bm25"] and resp.results[0].qualname == "record_audit_event"
    assert resp.freshness.indexing and resp.freshness.pending_chunks == 11
    assert not model.ready and {thread for thread, _ in model.asked} == {"codemem-prewarm"}
    model.gate.set()  # the load ends, and the writer embeds the queue
    assert _wait_for(lambda: service.store.dirty_count() == 0)
    assert model.loaded_by == ["codemem-prewarm"] and service.indexer.verify() == []


def test_a_search_counts_as_a_use_of_the_model_before_it_embeds_its_keyword_results(switched_with_a_model_that_can_leave):
    """A model nobody has used for longer than its idle time can be freed at any moment. The
    search counts as a use before it checks that the model is in memory, so the model cannot
    leave between that check and the search's own embedding."""
    service, model, clock = switched_with_a_model_that_can_leave
    clock.now += 3600
    resp = service.search("record audit event", k=3, wait_for_models=False, debug=True)
    assert model.by_this_thread() and model.freed_under_the_search
    assert not any(model.freed_under_the_search) and model.loaded_by == []
    assert resp.results[0].qualname == "record_audit_event" and "code" in resp.results[0].ranks


def test_a_search_that_may_wait_for_the_model_loads_it_for_its_keyword_results(switched_with_a_model_that_can_leave):
    """Without a budget for the model (the CLI's and the eval's kind of search), the search loads
    a freed model where it first needs it: for its own keyword results."""
    service, model, _ = switched_with_a_model_that_can_leave
    assert model.unload() and not model.ready
    resp = service.search("record audit event", k=3, debug=True)
    mine = model.by_this_thread()
    assert model.loaded_by == ["MainThread"] and mine
    assert all("auth/audit.py" in line for line in _first_lines(mine))
    assert resp.results[0].qualname == "record_audit_event" and "code" in resp.results[0].ranks
    assert resp.freshness.indexing and not resp.models_loading


# --------------------------------------------------------------------------- `codemem search` on the command line


@pytest.fixture
def cli_repo(repo, monkeypatch, capsys):
    """The checkout with the command line's own index of it, current on A. No server runs."""
    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    return repo


def _cli_search(capsys, repo, query, *options):
    """`codemem search --json`: its exit status, its results and what it wrote to stderr."""
    status = main(["search", query, "--repo", str(repo), "--json", *options])
    out, err = capsys.readouterr()
    return status, json.loads(out)["results"] if status == 0 else [], err


def _queued(repo):
    store = Store(default_index_dir(repo))
    try:
        return store.dirty_count()
    finally:
        store.close()


def test_the_command_lines_search_follows_a_switch(cli_repo, capsys):
    """Fixed bug: `codemem search` never looked at the checkout. After `git switch` it answered
    from the branch that was left, with nothing on stderr, while `codemem status` knew."""
    git(cli_repo, "switch", "-q", "feature")
    status, results, err = _cli_search(capsys, cli_repo, "record audit event")
    assert status == 0 and results[0]["key"] == "auth/audit.py::record_audit_event"  # exists only on B
    assert "the index is behind this checkout (3 files changed, 2 deleted, git HEAD moved); updating it first" in err
    assert "note:" not in err  # 11 chunks: every vector is in before the answer

    status, results, err = _cli_search(capsys, cli_repo, "logout")  # exists only on A
    assert status == 0 and "api/routes.py::logout" not in [r["key"] for r in results]
    assert err == ""  # the index is this checkout's now: nothing to update, nothing to say
    service = CodememService(cli_repo)
    try:
        assert service.store.get_meta("indexed_commit") == git(cli_repo, "rev-parse", "feature")
        assert service.store.dirty_count() == 0 and service.indexer.verify() == []
        assert service.status()["stale"] == {
            "changed_files": 0, "deleted_files": 0, "head": git(cli_repo, "rev-parse", "HEAD"), "head_moved": False,
        }
    finally:
        service.close()


def test_the_command_lines_search_keeps_stdout_for_the_results(cli_repo, capsys):
    git(cli_repo, "switch", "-q", "feature")
    assert main(["search", "record audit event", "--repo", str(cli_repo), "-k", "3"]) == 0
    out, err = capsys.readouterr()
    assert out.startswith("1. auth/audit.py:4-5  record_audit_event") and "behind this checkout" not in out
    assert "updating it first" in err


def test_the_command_lines_search_follows_edits_no_server_saw(cli_repo, capsys):
    """Not only a switch: any file that differs from the index, with git's HEAD where it was."""
    (cli_repo / "auth" / "quota.py").write_text("def enforce_login_quota(user):\n    return user\n")
    (cli_repo / "api" / "routes.py").unlink()
    status, results, err = _cli_search(capsys, cli_repo, "enforce login quota")
    assert status == 0 and results[0]["key"] == "auth/quota.py::enforce_login_quota"
    assert "the index is behind this checkout (1 file changed, 1 deleted); updating it first" in err
    assert "api/routes.py::logout" not in [r["key"] for r in _cli_search(capsys, cli_repo, "logout")[1]]


def test_after_a_large_switch_the_command_lines_search_names_what_is_left(cli_repo, capsys, monkeypatch):
    """More chunks need vectors than a search waits for. The structure is the checkout's all the
    same; the search embeds the chunks its own keywords rank on top, and says what is left and
    which command embeds it."""
    monkeypatch.setattr("codemem.service.CATCHUP_MAX_CHUNKS", 5)  # the 11 chunks of this switch are a large change
    git(cli_repo, "switch", "-q", "feature")
    status, results, err = _cli_search(capsys, cli_repo, "record audit event", "--debug")
    assert status == 0 and results[0]["key"] == "auth/audit.py::record_audit_event"
    assert {"bm25", "code"} <= set(results[0]["ranks"])  # ranked by its new vector too
    left = _queued(cli_repo)
    assert 0 < left < 11
    assert f"note: {left} code chunks in " in err and "are not embedded yet" in err
    assert "Run `codemem index` to embed them." in err

    status, _, err = _cli_search(capsys, cli_repo, "record audit event")  # the next search is not silent about them
    assert status == 0 and f"the index is behind this checkout ({left} chunks to embed); updating it first" in err
    assert main(["index", str(cli_repo)]) == 0
    capsys.readouterr()
    assert _queued(cli_repo) == 0 and _cli_search(capsys, cli_repo, "record audit event")[2] == ""


def test_the_command_lines_search_embeds_the_rest_of_a_change_for_a_limited_time(cli_repo, capsys, monkeypatch):
    """A change of fewer chunks than a large one is embedded whole before the answer, but not for
    longer than a caller with a time limit of its own would wait (an agent's shell tool). When the
    time is up, the search has its own keyword results' vectors, answers, and names what is left."""
    monkeypatch.setattr("codemem.service.FOLLOW_EMBED_SECONDS", 0.0)  # no time for the rest
    git(cli_repo, "switch", "-q", "feature")
    status, results, err = _cli_search(capsys, cli_repo, "record audit event", "--debug")
    assert status == 0 and results[0]["key"] == "auth/audit.py::record_audit_event"
    assert {"bm25", "code"} <= set(results[0]["ranks"])  # its own results were embedded first, and are not counted
    left = _queued(cli_repo)
    assert 0 < left < 11
    assert f"note: {left} code chunks in " in err and "Run `codemem index` to embed them." in err

    monkeypatch.setattr("codemem.service.FOLLOW_EMBED_SECONDS", 20.0)
    status, _, err = _cli_search(capsys, cli_repo, "record audit event")  # with time, the next search embeds the rest
    assert status == 0 and f"({left} chunks to embed); updating it first" in err and "note:" not in err
    assert _queued(cli_repo) == 0


def test_a_keyword_search_on_the_command_line_follows_a_switch_and_embeds_nothing(cli_repo, capsys):
    """`--signals bm25` needs no vector: it brings the structure to the checkout and loads no
    model for the rest, which the next search by meaning embeds."""
    git(cli_repo, "switch", "-q", "feature")
    status, results, err = _cli_search(capsys, cli_repo, "record audit event", "--signals", "bm25")
    assert status == 0 and results[0]["key"] == "auth/audit.py::record_audit_event"
    assert "(3 files changed, 2 deleted, git HEAD moved); updating it first" in err and "note:" not in err
    assert _queued(cli_repo) == 11
    assert _cli_search(capsys, cli_repo, "record audit event", "--signals", "bm25")[2] == ""  # nothing a keyword search lacks

    status, _, err = _cli_search(capsys, cli_repo, "record audit event")
    assert status == 0 and "the index is behind this checkout (11 chunks to embed); updating it first" in err
    assert "note:" not in err and _queued(cli_repo) == 0


def test_the_command_lines_search_says_so_when_it_cannot_update_the_index(cli_repo, capsys, monkeypatch):
    """Another codemem process holds the index's write lock for longer than the search waits. It
    then answers from the index as it is, and says that this is another state of the checkout."""
    git(cli_repo, "switch", "-q", "feature")
    monkeypatch.setattr(IndexLock.acquire, "__defaults__", (0.2,))  # not the half minute a writer is waited for
    lock = IndexLock(default_index_dir(cli_repo))
    lock.acquire()
    try:
        status, results, err = _cli_search(capsys, cli_repo, "logout")
    finally:
        lock.release()
    assert status == 0 and "api/routes.py::logout" in [r["key"] for r in results]  # A's code still
    assert "note: the index is behind this checkout (3 files changed, 2 deleted, git HEAD moved) and could not be " in err
    assert "another codemem process is writing to" in err and "Run `codemem index`, then search again." in err


def test_the_command_lines_search_never_rebuilds_an_index(cli_repo, capsys, monkeypatch):
    """An index built with other settings, or by another embedder, is rebuilt or embedded again by
    its next update: minutes to hours on a real repository, and the old vectors are dropped first.
    `codemem index` does that. A search answers from the index as it is and says why."""
    def stored():
        store = Store(default_index_dir(cli_repo))
        try:
            return store.counts()["vectors"], sorted(store.get_files()), store.get_meta("indexed_commit")
        finally:
            store.close()

    built = stored()
    git(cli_repo, "switch", "-q", "feature")
    (cli_repo / ".codemem.toml").write_text("max_block_lines = 7\n")  # the chunker would cut other blocks
    status, results, err = _cli_search(capsys, cli_repo, "logout", "--signals", "bm25")
    assert status == 0 and "api/routes.py::logout" in [r["key"] for r in results]  # A's code still
    assert "the index is behind this checkout (3 files changed, 2 deleted, git HEAD moved); updating it first" in err
    assert (
        "and could not be updated: the index was built with other settings than the config has now "
        "(max_block_lines), and only `codemem index` rebuilds it. These results are from the index as it is."
    ) in err
    assert stored() == built

    (cli_repo / ".codemem.toml").unlink()
    store = Store(default_index_dir(cli_repo))
    store.set_meta("vec.code.embedder", "fake:64|doc|float16|mps")  # as if built on another device
    store.close()
    status, _, err = _cli_search(capsys, cli_repo, "logout", "--signals", "bm25")
    assert status == 0 and "the index holds the vectors of another embedder (fake:64|doc|float16|mps, now fake:64|doc)" in err
    assert stored() == built  # no vector was dropped

    assert main(["index", str(cli_repo)]) == 0  # the command that does embed it again
    assert stored()[2] == git(cli_repo, "rev-parse", "feature")


def test_a_keyword_search_answers_where_the_index_cannot_be_updated_for_want_of_a_model(cli_repo, capsys, monkeypatch):
    """An environment built without PyTorch, and a config that names the local model: no update
    can run there. A search by keywords needs no model, so it still answers, from the index as
    it is, and says so."""
    git(cli_repo, "switch", "-q", "feature")
    monkeypatch.delenv("CODEMEM_MODEL")
    monkeypatch.setattr("codemem.embedder.find_spec", lambda name: None)
    monkeypatch.setattr("codemem.embedder._CACHE", {})
    status, results, err = _cli_search(capsys, cli_repo, "logout", "--signals", "bm25")
    assert status == 0 and "api/routes.py::logout" in [r["key"] for r in results]
    assert "and could not be updated: The local embedding model cannot run because PyTorch" in err
    assert "These results are from the index as it is." in err and "Traceback" not in err
