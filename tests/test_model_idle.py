"""The embedding model leaves memory when idle and comes back at its next use
(docs/architecture.md §3.5): first the embedders' part, then the service's. The local embedder
runs over a stub of sentence-transformers and the service on the fake model, and time is a clock
the tests move, so no test loads a model or waits for an idle time. Most service tests run the
writer's steps themselves (`_step`), one at a time, instead of starting its thread."""

import sys
import threading
import time
import types
from importlib.machinery import ModuleSpec

import anyio
import numpy as np
import pytest

from codemem import embedserver
from codemem.config import Config, config_from_dict
from codemem.embedder import (
    TRIM_AFTER_IDLE, Embedder, FakeEmbedder, OpenAIEmbedder, PluginEmbedder, SentenceTransformerEmbedder,
)
from codemem.embedserver import ModelQueue
from codemem.render import format_status
from codemem.service import CodememService

IDLE_MINUTES = 5
EVERY_SIGNAL = ["bm25", "code", "usage"]


class Clock:
    """Time that moves only when a test says so."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def pass_minutes(self, minutes):
        self.now += 60 * minutes

    def pass_seconds(self, seconds):
        self.now += seconds


class GatedModel(FakeEmbedder):
    """The fake model, with a load that waits while the gate is closed, as a slow reload would."""

    def __init__(self, clock):
        super().__init__(64, clock)
        self.gate, self.loading, self.unloaded = threading.Event(), threading.Event(), threading.Event()
        self.gate.set()
        self.document_calls = 0  # started, whether or not they have the model yet

    def embed_documents(self, texts):
        self.document_calls += 1
        return super().embed_documents(texts)

    def load(self):
        self.loading.set()
        assert self.gate.wait(10)
        super().load()

    def unload(self, idle_seconds=0.0):
        freed = super().unload(idle_seconds)
        if freed:
            self.unloaded.set()
        return freed


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def model(clock):
    return GatedModel(clock)


# ---------------------------------------------------------------- the fake model


def test_the_fake_model_leaves_after_its_idle_time_and_loads_again(model, clock):
    model.embed_documents(["revoke session"])
    clock.pass_minutes(4.9)
    assert not model.unload(idle_seconds=300) and model.ready
    clock.pass_minutes(0.2)
    assert model.unload(idle_seconds=300) and not model.ready
    assert not model.unload()  # nothing left to free
    model.embed_queries(["revoke session"])
    assert model.ready and model.loads == 1


def test_touching_a_model_counts_as_a_use(model, clock):
    clock.pass_minutes(6)
    model.touch()
    assert not model.unload(idle_seconds=300)
    clock.pass_minutes(6)
    assert model.unload(idle_seconds=300)


def test_working_memory_is_given_back_once_after_a_burst_of_calls(model, clock):
    for _ in range(3):
        model.embed_documents(["revoke session"])
    assert not model.trim(idle_seconds=5)  # a moment after a call: the burst may not be over
    clock.pass_seconds(6)
    assert model.trim(idle_seconds=5) and model.trims == 1 and model.ready
    clock.pass_minutes(10)
    assert not model.trim(idle_seconds=5) and model.trims == 1  # no call since: nothing to give back
    model.embed_queries(["revoke session"])
    clock.pass_seconds(6)
    assert model.trim(idle_seconds=5) and model.trims == 2
    model.embed_queries(["revoke session"])
    assert model.unload() and not model.trim()  # what the calls needed went with the model


def test_calls_that_arrive_together_wait_for_one_load(model):
    assert model.unload()
    model.gate.clear()
    barrier = threading.Barrier(8)

    def embed():
        barrier.wait(10)
        model.embed_documents(["revoke session"])

    threads = [threading.Thread(target=embed) for _ in range(8)]
    for t in threads:
        t.start()
    assert model.loading.wait(10)
    assert not model.unload()  # calls are waiting for it
    model.gate.set()
    for t in threads:
        t.join(10)
    assert model.loads == 1 and len(model.calls) == 8


# ---------------------------------------------------------------- the local model


class _StubTransformer:
    """Stands in for sentence_transformers.SentenceTransformer: no weights, gates that hold a
    load or a call open, and a record of where it was built and moved."""

    prompts = {"nl2code_query": "", "nl2code_document": ""}
    max_seq_length = 512

    def __init__(self, name, device=None):
        cls = type(self)
        cls.loading.set()
        assert cls.load_gate.wait(10)
        cls.instances += 1
        cls.built_on.append(device)

    def to(self, target):
        type(self).moves.append(target)
        return self

    def encode(self, texts, **kwargs):
        cls = type(self)
        cls.encoding.set()
        assert cls.encode_gate.wait(10)
        return np.ones((len(texts), 8), dtype=np.float32)


@pytest.fixture
def transformer(monkeypatch):
    """A stub class in place of sentence-transformers, for the real local embedder to load."""
    pytest.importorskip("torch")  # the embedder resolves its device and empties allocator caches through it

    class Stub(_StubTransformer):
        instances = 0
        built_on, moves = [], []
        loading, load_gate, encoding, encode_gate = (threading.Event() for _ in range(4))

    Stub.load_gate.set()
    Stub.encode_gate.set()
    module = types.SimpleNamespace(SentenceTransformer=Stub, __spec__=ModuleSpec("sentence_transformers", None))
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    return Stub


@pytest.fixture
def local_model(transformer):
    """The real local embedder over the stub, and the stub's class."""
    return SentenceTransformerEmbedder("stub-model", device="cpu"), transformer


def test_the_local_model_loads_at_its_first_use_and_again_after_an_unload(local_model):
    emb, stub = local_model
    assert not emb.ready and not emb.unload()  # nothing to free yet
    assert emb.embed_documents(["a", "b"]).shape == (2, 8)
    assert emb.ready and stub.instances == 1
    assert not emb.unload(idle_seconds=3600)  # used a moment ago
    assert emb.ready
    assert emb.unload() and not emb.ready
    emb.embed_queries(["a"])
    assert emb.ready and stub.instances == 2


def test_the_model_runs_in_the_precision_its_key_names_on_every_device(transformer, monkeypatch):
    """The file's precision is not the key's: the weights are always converted. For the Apple GPU
    that happens on the CPU first, because converting there leaves the file's blocks in the GPU's
    allocator while the model lives."""
    import torch

    from codemem import embedder

    def load(device, dtype):
        monkeypatch.setattr(embedder, "resolve_device", lambda preference: device)
        del transformer.built_on[:], transformer.moves[:]
        emb = SentenceTransformerEmbedder("stub-model", device=device, dtype=dtype)
        emb.embed_documents(["a"])
        return emb.key.split("|")[-2:], transformer.built_on, transformer.moves

    assert load("cpu", "auto") == (["float32", "cpu"], ["cpu"], [torch.float32, "cpu"])
    assert load("mps", "auto") == (["float16", "mps"], ["cpu"], [torch.float16, "mps"])
    assert load("mps", "float32") == (["float32", "mps"], ["cpu"], [torch.float32, "mps"])
    assert load("cuda", "auto") == (["float16", "cuda"], ["cuda"], [torch.float16, "cuda"])
    assert load("cpu", "bfloat16") == (["bfloat16", "cpu"], ["cpu"], [torch.bfloat16, "cpu"])


def test_the_local_model_is_loaded_once_by_calls_that_arrive_together(local_model):
    emb, stub = local_model
    stub.load_gate.clear()
    barrier = threading.Barrier(6)

    def embed():
        barrier.wait(10)
        emb.embed_documents(["a"])

    threads = [threading.Thread(target=embed) for _ in range(6)]
    for t in threads:
        t.start()
    assert stub.loading.wait(10)
    assert not emb.unload()  # a load is under way: the model is wanted
    stub.load_gate.set()
    for t in threads:
        t.join(10)
    assert stub.instances == 1


def test_the_local_model_is_not_freed_under_a_running_call(local_model):
    emb, stub = local_model
    stub.encode_gate.clear()
    call = threading.Thread(target=lambda: emb.embed_documents(["a"]))
    call.start()
    assert stub.encoding.wait(10)
    assert not emb.unload() and emb.ready
    stub.encode_gate.set()
    call.join(10)
    assert emb.unload() and not emb.ready


def test_the_allocator_cache_is_emptied_once_after_a_burst_and_never_under_a_call(local_model, monkeypatch):
    from codemem import embedder

    emptied = []
    monkeypatch.setattr(embedder, "_empty_cache", lambda device: emptied.append(device) or True)
    emb, stub = local_model
    assert not emb.trim()  # no model, no call: nothing to give back
    stub.encode_gate.clear()
    call = threading.Thread(target=lambda: emb.embed_documents(["a"]))
    call.start()
    assert stub.encoding.wait(10)
    assert not emb.trim() and emptied == []  # a call is running
    stub.encode_gate.set()
    call.join(10)
    assert not emb.trim(idle_seconds=3600) and emptied == []  # the burst may not be over
    assert emb.trim() and emptied == ["cpu"] and emb.ready
    assert not emb.trim() and emptied == ["cpu"]  # once
    emb.embed_documents(["a"])
    assert emb.unload() and emptied == ["cpu", "cpu"]  # the unload empties it itself
    assert not emb.trim() and emptied == ["cpu", "cpu"]


# ---------------------------------------------------------------- plugins and the API


class _UnloadablePlugin(Embedder):
    """A plugin embedder that holds a model it can free."""

    def __init__(self, model, config):
        self.model_name, self.loaded, self.unloads = model, True, 0
        self.gate, self.embedding = threading.Event(), threading.Event()
        self.gate.set()

    @property
    def dim(self):
        return 4

    @property
    def ready(self):
        return self.loaded

    def unload(self, idle_seconds=0.0):
        freed, self.loaded = self.loaded, False
        self.unloads += freed
        return freed

    def embed_documents(self, texts):
        self.loaded = True
        self.embedding.set()
        assert self.gate.wait(10)
        return np.ones((len(texts), 4), dtype=np.float32)

    embed_queries = embed_documents


def _plugin(monkeypatch, cls):
    monkeypatch.setitem(sys.modules, "cm_idle_plugin", types.SimpleNamespace(Model=cls))
    return PluginEmbedder("cm_idle_plugin:Model", "my-model", Config(), None)


def test_a_plugin_embedder_is_asked_to_unload_only_while_no_call_runs(monkeypatch):
    emb = _plugin(monkeypatch, _UnloadablePlugin)
    emb.inner.gate.clear()
    call = threading.Thread(target=lambda: emb.embed_documents(["a"]))
    call.start()
    assert emb.inner.embedding.wait(10)
    assert not emb.unload() and emb.inner.unloads == 0  # a call is running
    emb.inner.gate.set()
    call.join(10)
    assert not emb.unload(idle_seconds=3600) and emb.ready  # used a moment ago
    assert emb.unload() and not emb.ready and emb.inner.unloads == 1
    emb.embed_queries(["a"])
    assert emb.ready


def test_a_plugin_embedder_is_asked_to_trim_once_after_a_burst(monkeypatch):
    class Trimmable(_UnloadablePlugin):
        trims = 0

        def trim(self, idle_seconds=0.0):
            self.trims += 1
            return True

    emb = _plugin(monkeypatch, Trimmable)
    assert not emb.trim() and emb.inner.trims == 0  # no call yet
    emb.embed_documents(["a"])
    assert not emb.trim(idle_seconds=3600) and emb.inner.trims == 0
    assert emb.trim() and not emb.trim() and emb.inner.trims == 1 and emb.ready


def test_embedders_without_a_model_have_nothing_to_unload(monkeypatch):
    class Plain(_UnloadablePlugin):
        unload = Embedder.unload  # a plugin that does not define the hook

    emb = _plugin(monkeypatch, Plain)
    emb.embed_documents(["a"])
    assert not emb.unload() and not emb.trim() and emb.ready
    api = OpenAIEmbedder(config_from_dict({"embedding": {
        "provider": "openai", "model": "m", "base_url": "http://localhost:1/v1",
    }}).embedding)
    api.touch()
    assert api.ready and not api.unload() and not api.trim()


# ================================================================ the service


@pytest.fixture
def service(sample_repo, tmp_path, fake_config, model):
    """An index of the sample repo, built just now with `model`, which may leave after 5 idle minutes."""
    fake_config.model_idle_minutes = IDLE_MINUTES
    svc = CodememService(sample_repo, index_dir=tmp_path / "idx", config=fake_config, embedder_factory=lambda s, c: model)
    assert svc.update() is not None
    yield svc
    if svc._prewarm is not None:
        svc._prewarm.join(10)  # a load a search started: let it finish before the index closes
    svc.close()


def _idle_out(service, model, clock):
    clock.pass_minutes(IDLE_MINUTES + 1)
    service._step()
    assert not model.ready


def _add_function(repo, name):
    (repo / "auth" / f"{name}.py").write_text(f"def {name}(user):\n    return user\n")


def _wait_for(pred, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


# ---------------------------------------------------------------- when the model leaves


def test_the_model_leaves_memory_after_the_idle_time_and_not_before(service, model, clock):
    clock.pass_minutes(IDLE_MINUTES - 0.1)
    service._step()
    assert model.ready
    clock.pass_minutes(0.2)
    service._step()
    assert not model.ready and model.loads == 0


def test_a_search_and_an_update_each_restart_the_idle_time(service, model, clock, sample_repo):
    clock.pass_minutes(4)
    service.search("revoke session")  # embeds the query
    clock.pass_minutes(4)
    service._step()
    assert model.ready  # 8 minutes after the build, 4 after the search
    _add_function(sample_repo, "enforce_login_quota")
    assert service.update().model_embedded["code"] == 1
    clock.pass_minutes(4)
    service._step()
    assert model.ready  # 4 minutes after the update
    clock.pass_minutes(1.1)
    service._step()
    assert not model.ready


def test_zero_idle_minutes_keeps_the_model(service, model, clock):
    service.config.model_idle_minutes = 0
    clock.pass_minutes(100_000)
    service._step()
    assert model.ready


def test_the_idle_time_is_a_setting_that_no_index_depends_on():
    assert Config().model_idle_minutes == 0  # the model stays unless asked otherwise
    cfg = config_from_dict({"model_idle_minutes": 2.5})
    assert cfg.model_idle_minutes == 2.5 and cfg.index_settings() == Config().index_settings()
    for bad in (-1, "ten"):
        with pytest.raises(ValueError, match="model_idle_minutes"):
            config_from_dict({"model_idle_minutes": bad})


def test_the_writer_gives_working_memory_back_once_after_each_burst(service, model, clock):
    """With the model kept for ever, too: this needs no setting."""
    service.config.model_idle_minutes = 0
    service._step()
    assert model.trims == 0  # the build's calls are a moment old: the burst may not be over
    clock.pass_seconds(TRIM_AFTER_IDLE + 1)
    service._step()
    service._step()
    assert model.trims == 1 and model.ready
    service.search("revoke session")
    service._step()
    assert model.trims == 1
    clock.pass_seconds(TRIM_AFTER_IDLE + 1)
    service._step()
    assert model.trims == 2 and model.ready and model.loads == 0


def test_an_unload_takes_the_working_memory_with_it(service, model, clock):
    clock.pass_minutes(IDLE_MINUTES + 1)
    service._step()
    service._step()
    assert not model.ready and model.trims == 0


def test_two_vector_types_on_one_model_are_one_model_to_unload(service, model, clock):
    asked = []
    model.unload = lambda idle_seconds=0.0: asked.append(idle_seconds) or False
    clock.pass_minutes(IDLE_MINUTES + 1)
    service._step()
    assert asked == [IDLE_MINUTES * 60]  # once, although code and usage vectors both use it


def test_a_model_that_cannot_be_freed_does_not_stop_the_writer(service, model, clock):
    tries = []

    def broken():
        tries.append(clock())
        raise RuntimeError("the allocator said no")

    model._drop = broken
    clock.pass_minutes(IDLE_MINUTES + 1)
    service._step()  # logged, not raised
    service._step()
    assert len(tries) == 1 and model.ready  # it counted as a use: the next try is an idle time away
    del model._drop
    clock.pass_minutes(IDLE_MINUTES + 1)
    service._step()
    assert not model.ready


# ---------------------------------------------------------------- the next use loads it again


def test_a_search_after_an_unload_answers_from_keywords_while_the_model_loads(service, model, clock):
    service.config.catchup_budget_ms = 50
    _idle_out(service, model, clock)
    model.gate.clear()  # the reload takes longer than the search may wait
    resp = service.search("revoke session", k=3, wait_for_models=False)
    assert resp.models_loading and resp.signals == ["bm25"]
    assert "revoke_session" in [r.qualname for r in resp.results]
    model.gate.set()
    service._prewarm.join(10)
    resp = service.search("revoke session", k=3, wait_for_models=False)
    assert not resp.models_loading and resp.signals == EVERY_SIGNAL
    assert model.loads == 1


def test_a_search_after_an_unload_gets_full_results_when_the_model_loads_in_time(service, model, clock):
    _idle_out(service, model, clock)
    resp = service.search("revoke session", k=3, wait_for_models=False)  # the load is instant, the budget 4 s
    assert not resp.models_loading and resp.signals == EVERY_SIGNAL
    assert model.ready and model.loads == 1


def test_a_search_that_waits_for_the_model_loads_it_itself(service, model, clock):
    _idle_out(service, model, clock)
    resp = service.search("revoke session", k=3)  # the CLI and the eval
    assert not resp.models_loading and resp.signals == EVERY_SIGNAL
    assert model.ready and model.loads == 1


def test_a_repeated_query_after_an_unload_still_brings_the_model_back(sample_repo, tmp_path, local_model):
    """The local embedder keeps query vectors, so embedding the same query again loads nothing:
    bringing the model back must not depend on it."""
    emb, stub = local_model
    cfg = Config(device="cpu", vector_cache="off")
    svc = CodememService(sample_repo, index_dir=tmp_path / "idx", config=cfg, embedder_factory=lambda s, c: emb)
    try:
        svc.prewarm()
        assert emb.ready and emb.unload() and not emb.ready
        assert svc._models_ready(time.monotonic() + 10)
        assert stub.instances == 2
        svc._prewarm.join(10)
    finally:
        svc.close()


def test_an_update_after_an_unload_embeds_with_the_reloaded_model(service, model, clock, sample_repo):
    _idle_out(service, model, clock)
    _add_function(sample_repo, "enforce_login_quota")
    stats = service.update()
    assert stats.model_embedded == {"code": 1, "usage": 0} and stats.pending == 0
    assert model.ready and model.loads == 1
    resp = service.search("enforce login quota", k=1, signals=["code"])
    assert resp.results[0].qualname == "enforce_login_quota"


def test_the_writer_applies_saves_while_the_model_loads_again(service, model, clock, sample_repo):
    _idle_out(service, model, clock)
    model.gate.clear()
    _add_function(sample_repo, "first_edit")
    service.notify({"auth/first_edit.py"})
    assert service._step()  # stage A
    assert service.store.get_chunk_by_key("auth/first_edit.py::first_edit") is not None
    assert service._step()  # stage B has to wait: the load starts, in its own thread
    assert model.loading.wait(10) and not model.ready
    _add_function(sample_repo, "second_edit")
    service.notify({"auth/second_edit.py"})
    assert service._step()  # so the writer is free for the next save
    assert service.store.get_chunk_by_key("auth/second_edit.py::second_edit") is not None
    assert service.store.dirty_count() == 2
    model.gate.set()
    service._prewarm.join(10)
    assert service._step()  # stage B, now that the model is back
    assert service.store.dirty_count() == 0 and model.loads == 1


def test_with_the_writer_running_edits_stay_searchable_while_the_model_loads(service, model, clock, sample_repo):
    """The same through the writer's own thread, which also frees the model: an edit is in the
    keyword results while the model loads, later saves are applied meanwhile, and the vectors
    follow once it is back."""
    store = service.store
    service.config.catchup_budget_ms = 200
    service.start(watch=False, prewarm=False)
    clock.pass_minutes(IDLE_MINUTES + 1)
    service.notify(set())  # wakes the writer: its next quiet step frees the model
    assert model.unloaded.wait(10)
    model.gate.clear()
    before = model.document_calls
    _add_function(sample_repo, "first_edit")
    service.notify({"auth/first_edit.py"})
    assert _wait_for(lambda: store.get_chunk_by_key("auth/first_edit.py::first_edit") is not None)
    resp = service.search("first_edit", k=3, wait_for_models=False)
    assert resp.results[0].qualname == "first_edit"
    assert resp.models_loading and resp.signals == ["bm25"] and resp.freshness.pending_chunks == 1
    assert model.loading.is_set() and not model.ready
    assert model.document_calls == before + 1  # the loader's warm-up: neither the writer nor the search waits in a call
    _add_function(sample_repo, "second_edit")
    service.notify({"auth/second_edit.py"})
    assert _wait_for(lambda: store.get_chunk_by_key("auth/second_edit.py::second_edit") is not None)
    model.gate.set()
    assert _wait_for(lambda: store.dirty_count() == 0)
    service.config.catchup_budget_ms = 4000
    resp = service.search("first_edit", k=3, wait_for_models=False)
    assert not resp.models_loading and resp.freshness.complete and model.loads == 1


def test_a_failed_load_is_reported_and_tried_again(service, model, clock, sample_repo):
    _idle_out(service, model, clock)
    failures = []

    def failing_load():
        failures.append(1)
        raise OSError("no weights")

    model.load = failing_load
    _add_function(sample_repo, "first_edit")
    service.notify({"auth/first_edit.py"})
    assert service._step() and service._step()  # stage A, then a load that fails
    service._prewarm.join(10)
    assert service.status(check_staleness=False)["error"] == "OSError: no weights"
    assert service._load_retry_at > 0  # the failure set the time of the next try
    service._load_retry_at = time.monotonic() + 3600
    assert service._step() and len(failures) == 1  # not before then
    service._load_retry_at = 0.0
    del model.load
    assert service._step()  # tried again: this time the weights are there
    service._prewarm.join(10)
    service._step()
    assert service.store.dirty_count() == 0 and model.loads == 1


# ---------------------------------------------------------------- at the same moment


def test_two_threads_that_need_the_model_load_it_once(service, model, clock, sample_repo):
    _idle_out(service, model, clock)
    model.gate.clear()
    _add_function(sample_repo, "enforce_login_quota")
    threads = [
        threading.Thread(target=service.update),
        threading.Thread(target=lambda: service.search("revoke session", wait_for_models=False)),
    ]
    for t in threads:
        t.start()
    assert model.loading.wait(10)
    model.gate.set()
    for t in threads:
        t.join(10)
        assert not t.is_alive()
    if service._prewarm is not None:  # the search started the load, unless the update had finished it
        service._prewarm.join(10)
    assert model.ready and model.loads == 1 and service.store.dirty_count() == 0


def test_a_search_that_found_the_model_keeps_it_for_the_idle_time(service, model, clock):
    """An unload must not fall between a search's check for the model and its own embedding."""
    clock.pass_minutes(IDLE_MINUTES + 1)
    assert service._models_ready(0.0)  # what a search does first
    service._step()
    assert model.ready
    clock.pass_minutes(IDLE_MINUTES + 1)
    service._step()
    assert not model.ready


# ---------------------------------------------------------------- the embedding server


def test_the_embedding_server_gives_working_memory_back_and_keeps_its_model(model, clock, monkeypatch):
    monkeypatch.setattr(embedserver, "QUIET_CHECK_S", 0.01)
    queue = ModelQueue(model, batch_size=4)
    try:
        assert len(queue.embed(["revoke session", "parse csv"])) == 2
        clock.pass_minutes(1000)
        assert _wait_for(lambda: model.trims == 1)  # the queue's quiet moments run
        assert model.ready and not model.unloaded.is_set()
    finally:
        queue.close()


def test_the_embedding_server_frees_its_model_when_idle_minutes_are_set(model, clock, monkeypatch, fake_config):
    monkeypatch.setattr(embedserver, "QUIET_CHECK_S", 0.01)
    queue = ModelQueue(model, batch_size=4, idle_minutes=IDLE_MINUTES)
    try:
        queue.embed(["revoke session"])  # a request is a use of the model
        clock.pass_minutes(IDLE_MINUTES - 1)
        assert _wait_for(lambda: model.trims == 1) and model.ready  # quiet moments ran: not yet idle for long enough
        clock.pass_minutes(2)
        assert model.unloaded.wait(10) and not model.ready
        assert len(queue.embed(["revoke session"])) == 1  # the next request loads it again
        assert model.ready and model.loads == 1
    finally:
        queue.close()
    fake_config.model_idle_minutes = 7  # `codemem serve-embeddings` takes the time from the config
    server = embedserver.serve(fake_config, port=0)
    try:
        assert server.queue._idle_minutes == 7
    finally:
        server.close()


# ---------------------------------------------------------------- status


def test_status_says_whether_the_model_is_in_memory(service, model, clock, sample_repo, tmp_path):
    info = service.status(check_staleness=False)
    assert info["models_loaded"] is True and "embedding model: in memory" in format_status(info)
    _idle_out(service, model, clock)
    info = service.status(check_staleness=False)
    assert info["models_loaded"] is False
    assert "embedding model: not in this process's memory" in format_status(info)
    assert not model.ready and model.loads == 0  # asking does not load it

    fresh = CodememService(sample_repo, index_dir=tmp_path / "idx", config=service.config)
    try:  # a process that has not embedded anything holds no model, and status builds none
        assert fresh.status(check_staleness=False)["models_loaded"] is False and fresh._embedders == {}
        fresh.embedder_factory("fake:64", fresh.config)  # by name, as make_embedder allows
        assert fresh.status(check_staleness=False)["models_loaded"] is True
    finally:
        fresh.close()

    api = config_from_dict({"embedding": {"provider": "openai", "model": "m", "base_url": "http://localhost:1/v1"}})
    remote = CodememService(sample_repo, index_dir=tmp_path / "api-idx", config=api)
    try:
        info = remote.status(check_staleness=False)
        assert info["models_loaded"] is None and "embedding model" not in format_status(info)
    finally:
        remote.close()


def test_an_agent_sees_the_unloaded_model_in_index_status_and_in_the_search_note(service, model, clock):
    from mcp import Client

    from codemem.server import build_server

    service.config.catchup_budget_ms = 50
    _idle_out(service, model, clock)
    model.gate.clear()
    server = build_server(service)

    async def run():
        async with Client(server) as client:
            text = (await client.call_tool("index_status", {})).content[0].text
            assert "embedding model: not in this process's memory" in text and '"models_loaded": false' in text
            text = (await client.call_tool("search_code", {"query": "revoke session", "k": 3})).content[0].text
            assert "revoke_session" in text and "still loading" in text
            model.gate.set()
            service._prewarm.join(10)
            text = (await client.call_tool("search_code", {"query": "revoke session", "k": 3})).content[0].text
            assert "revoke_session" in text and "still loading" not in text
            text = (await client.call_tool("index_status", {})).content[0].text
            assert "embedding model: in memory" in text and '"models_loaded": true' in text

    anyio.run(run)
    assert model.loads == 1
