"""An embedder frees its model when asked, unless a call is using it or it was used too recently,
and loads it again at its next use (docs/architecture.md §3.5). The local embedder runs over a
stub of sentence-transformers, and time is a clock the tests move: no test loads a model or waits."""

import sys
import threading
import types
from importlib.machinery import ModuleSpec

import numpy as np
import pytest

from codemem.config import Config, config_from_dict
from codemem.embedder import Embedder, FakeEmbedder, OpenAIEmbedder, PluginEmbedder, SentenceTransformerEmbedder


class Clock:
    """Time that moves only when a test says so."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def pass_minutes(self, minutes):
        self.now += 60 * minutes


class GatedModel(FakeEmbedder):
    """The fake model, with a load that waits while the gate is closed, as a slow reload would."""

    def __init__(self, clock):
        super().__init__(64, clock)
        self.gate, self.loading = threading.Event(), threading.Event()
        self.gate.set()

    def load(self):
        self.loading.set()
        assert self.gate.wait(10)
        super().load()


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
    """Stands in for sentence_transformers.SentenceTransformer: no weights, and gates that hold a
    load or a call open."""

    prompts = {"nl2code_query": "", "nl2code_document": ""}
    max_seq_length = 512

    def __init__(self, name, device=None):
        cls = type(self)
        cls.loading.set()
        assert cls.load_gate.wait(10)
        cls.instances += 1

    def encode(self, texts, **kwargs):
        cls = type(self)
        cls.encoding.set()
        assert cls.encode_gate.wait(10)
        return np.ones((len(texts), 8), dtype=np.float32)


@pytest.fixture
def local_model(monkeypatch):
    """The real local embedder over a stub of sentence-transformers, and the stub's class."""
    pytest.importorskip("torch")  # the embedder resolves its device and empties allocator caches through it

    class Stub(_StubTransformer):
        instances = 0
        loading, load_gate, encoding, encode_gate = (threading.Event() for _ in range(4))

    Stub.load_gate.set()
    Stub.encode_gate.set()
    module = types.SimpleNamespace(SentenceTransformer=Stub, __spec__=ModuleSpec("sentence_transformers", None))
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    return SentenceTransformerEmbedder("stub-model", device="cpu"), Stub


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


def test_embedders_without_a_model_have_nothing_to_unload(monkeypatch):
    class Plain(_UnloadablePlugin):
        unload = Embedder.unload  # a plugin that does not define the hook

    emb = _plugin(monkeypatch, Plain)
    emb.embed_documents(["a"])
    assert not emb.unload() and emb.ready
    api = OpenAIEmbedder(config_from_dict({"embedding": {
        "provider": "openai", "model": "m", "base_url": "http://localhost:1/v1",
    }}).embedding)
    api.touch()
    assert api.ready and not api.unload()
