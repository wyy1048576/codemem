"""What a branch switch costs. One index follows its checkout from commit A to commit B and back
(gitrepo.py: a changed, an added, a moved and a deleted file). Coming back to a commit seen before
must cost no model call, work queued for the branch that was left must not be done, and a search
right after a switch embeds first what its own keywords rank on top.

The model is a fake one that records every text it is asked to embed.
"""

import threading
import time

import pytest
from conftest import RecordingEmbedder
from gitrepo import ONLY_ON_A, ONLY_ON_B, TO_A, TO_B, UNCHANGED, add_worktree, git, needs_git, two_commits

from codemem.indexer import Indexer, IndexStats
from codemem.service import CodememService
from codemem.store import Store, diff_snapshots

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


class ModelByThread(RecordingEmbedder):
    """Also records which thread asked: a search embeds in its own thread, the writer in its."""

    def __init__(self):
        super().__init__()
        self.asked: list[tuple[str, str]] = []  # (thread name, text)

    def embed_documents(self, texts):
        self.asked.extend((threading.current_thread().name, text) for text in texts)
        return super().embed_documents(texts)

    def by_this_thread(self):
        return [text for thread, text in self.asked if thread == threading.current_thread().name]


@pytest.fixture
def switched(repo, tmp_path, monkeypatch):
    """A running service without file events, current on A, whose checkout was just switched to
    B: the next search finds the switch itself, and the 11 chunks it queues."""
    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    monkeypatch.setattr("codemem.service.POLL_EVERY", 3600.0)  # no full check on a timer during the test
    model = ModelByThread()
    service = CodememService(repo, index_dir=tmp_path / "idx", embedder_factory=lambda m, c: model)
    try:
        assert service.update() is not None
        service.start(watch=False, prewarm=False)
        assert service.catch_up(budget=30).complete  # the start's own full check is done
        git(repo, "checkout", "-q", "feature")
        del model.asked[:]
        yield service, model
    finally:
        service.close()


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
