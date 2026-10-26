"""Embedder and vector-backend plugins named in config, and the weights version of a model folder
(docs/architecture.md §3.5 and §5)."""

import json
import os
import sys
import textwrap

import numpy as np
import pytest

from codemem.config import DEFAULT_MODEL, Config, VectorConfig, config_from_dict, model_folder_hash, model_version
from codemem.embedder import FakeEmbedder, PluginEmbedder, SentenceTransformerEmbedder, make_embedder
from codemem.indexer import Indexer
from codemem.search import search
from codemem.service import CodememService
from codemem.store import FaissVectorStore, Store, vector_backend_class

PLUGIN_MODULE = "cm_test_plugins"
EMBEDDER = f"{PLUGIN_MODULE}:WrappedFake"
BACKEND = f"{PLUGIN_MODULE}:NumpyVectorStore"
UNSAVED = f"{PLUGIN_MODULE}:UnsavedVectorStore"

PLUGIN_SOURCE = textwrap.dedent(
    '''
    import io

    import numpy as np

    from codemem.embedder import Embedder, FakeEmbedder
    from codemem.store import VectorStore


    class WrappedFake(Embedder):
        """The fake model's vectors, three times too long: codemem normalizes them."""

        instances = []

        def __init__(self, model, config):
            self.model_name = model
            self.inner = FakeEmbedder(32)
            WrappedFake.instances.append(self)

        @property
        def dim(self):
            return 32

        def embed_documents(self, texts):
            return 3.0 * self.inner.embed_documents(texts)

        def embed_queries(self, texts):
            return 3.0 * self.inner.embed_queries(texts)


    class NotAnEmbedder:
        def __init__(self, model, config):
            pass


    class NumpyVectorStore(VectorStore):
        """Brute force in numpy, saved as one .npz: a backend that is not FAISS."""

        suffix = ".npvec"
        loads = 0

        def __init__(self, dim):
            self.dim = dim
            self.vecs = {}

        def upsert(self, ids, vecs):
            for i, v in zip(ids, np.asarray(vecs, dtype=np.float32)):
                self.vecs[int(i)] = v

        def remove(self, ids):
            for i in ids:
                self.vecs.pop(int(i), None)

        def search(self, query, k, allowed_ids=None):
            allowed = None if allowed_ids is None else set(allowed_ids)
            ids = [i for i in self.vecs if allowed is None or i in allowed]
            if not ids or k <= 0:
                return []
            scores = np.stack([self.vecs[i] for i in ids]) @ np.asarray(query, dtype=np.float32)
            order = sorted(range(len(ids)), key=lambda j: (-scores[j], ids[j]))[:k]
            return [(ids[j], float(scores[j])) for j in order]

        def ids(self):
            return set(self.vecs)

        def __len__(self):
            return len(self.vecs)

        def to_bytes(self):
            ids = sorted(self.vecs)
            mat = np.stack([self.vecs[i] for i in ids]) if ids else np.zeros((0, self.dim), np.float32)
            buf = io.BytesIO()
            np.savez(buf, ids=np.array(ids, dtype=np.int64), vecs=mat)
            return buf.getvalue()

        @classmethod
        def from_bytes(cls, data):
            NumpyVectorStore.loads += 1
            saved = np.load(io.BytesIO(data))
            vs = cls(saved["vecs"].shape[1])
            vs.upsert(saved["ids"].tolist(), saved["vecs"])
            return vs


    class UnsavedVectorStore(NumpyVectorStore):
        """Never saved: rebuilt from the stored vectors at each start."""

        suffix = ".unsaved"

        def to_bytes(self):
            return None
    '''
)


@pytest.fixture
def plugins(tmp_path, monkeypatch):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / f"{PLUGIN_MODULE}.py").write_text(PLUGIN_SOURCE, encoding="utf-8", newline="\n")
    monkeypatch.syspath_prepend(str(plugin_dir))
    monkeypatch.delitem(sys.modules, PLUGIN_MODULE, raising=False)
    import cm_test_plugins

    yield cm_test_plugins
    sys.modules.pop(PLUGIN_MODULE, None)


@pytest.fixture
def model_dir(tmp_path):
    d = tmp_path / "my-model"
    d.mkdir()
    (d / "config.json").write_text('{"hidden": 8}', encoding="utf-8")
    (d / "weights.bin").write_bytes(b"\x01" * 100)
    return d


def _retrain(path):
    """Same size, new bytes, later mtime: what saving a new checkpoint over the old one looks like."""
    weights = path / "weights.bin"
    weights.write_bytes(b"\x02" * 100)
    st = weights.stat()
    os.utime(weights, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


# ---------------------------------------------------------------- config


def test_config_parses_embedder_version_and_backend():
    cfg = config_from_dict(
        {"vector_backend": "pkg.mod:Store", "vectors": {"code": {"embedder": "pkg.emb:Mine", "version": "run-3"}}}
    )
    assert cfg.vector_backend == "pkg.mod:Store"
    assert cfg.vectors["code"].embedder == "pkg.emb:Mine" and cfg.vectors["code"].version == "run-3"
    assert cfg.vectors["code"].model == DEFAULT_MODEL
    assert cfg.vectors["usage"].embedder is None and cfg.vectors["usage"].version is None
    assert Config().vector_backend == "faiss"


@pytest.mark.parametrize("raw, message", [
    ({"vectors": {"code": {"embedder": "no_colon"}}}, "embedder must be 'module:Class'"),
    ({"vector_backend": "lancedb"}, "vector_backend must be faiss"),
    ({"vectors": {"code": {"modle": "x"}}}, "unknown \\[vectors.code\\] settings"),
    ({"vectors": {"summary": {"enabled": True}}}, "have no text builder"),  # a type without a text builder
])
def test_bad_settings_are_refused(raw, message):
    with pytest.raises(ValueError, match=message):
        config_from_dict(raw)


def test_defaults_keep_their_ids_so_existing_indexes_stay_valid():
    """No summary slot, and no version, plugin or backend in any id unless one is set: indexes,
    cached vectors and the eval's index keys from before stay valid."""
    cfg = Config()
    assert set(cfg.vectors) == {"code", "usage"}
    assert config_from_dict({"vectors": {"summary": {"enabled": False}}}).enabled_vec_types() == ["code", "usage"]
    assert cfg.model_id("code") == DEFAULT_MODEL
    assert Config(embedding_dim=256).model_id("code") == f"{DEFAULT_MODEL}@256"
    assert "vector_backend" not in cfg.index_settings()
    assert SentenceTransformerEmbedder(DEFAULT_MODEL, device="cpu").key == f"{DEFAULT_MODEL}|doc|L1024|float32|cpu"


def test_model_id_includes_version_and_plugin():
    cfg = Config(embedding_dim=256)
    cfg.vectors["code"] = VectorConfig(model="org/model", embedder="pkg.emb:Mine", version="run-3")
    assert cfg.model_id("code") == "org/model@256#run-3+pkg.emb:Mine"


# ---------------------------------------------------------------- weights version


def test_folder_hash_follows_content_not_location(tmp_path, model_dir, isolated_home):
    h = model_folder_hash(model_dir)
    assert len(h) == 12 and model_folder_hash(model_dir) == h
    assert (isolated_home / "model_hashes.json").is_file()

    copy = tmp_path / "copy"
    copy.mkdir()
    for f in model_dir.iterdir():
        (copy / f.name).write_bytes(f.read_bytes())
    assert model_folder_hash(copy) == h  # the same weights on another path or machine

    (model_dir / ".cache").mkdir()
    (model_dir / ".cache" / "lock").write_text("x")
    assert model_folder_hash(model_dir) == h  # dot folders are tool metadata

    _retrain(model_dir)
    assert model_folder_hash(model_dir) != h


def test_model_version_sources(model_dir):
    assert model_version(VectorConfig(model=str(model_dir))) == model_folder_hash(model_dir)
    assert model_version(VectorConfig(model=str(model_dir), version="run-7")) == "run-7"
    assert model_version(VectorConfig(model="org/hub-model")) is None
    assert model_version(VectorConfig(model="fake:64")) is None


def test_a_local_model_folder_names_its_weights(model_dir):
    """New weights saved over a model folder give the built-in embedder a new key, and a new
    instance (so the new weights are what gets loaded), without loading the model to find out."""
    spec = VectorConfig(model=str(model_dir))
    emb = make_embedder(spec, Config(device="cpu"))
    assert isinstance(emb, SentenceTransformerEmbedder) and not emb.ready
    assert emb.key == f"{model_dir}#{model_folder_hash(model_dir)}|doc|L1024|float32|cpu"
    _retrain(model_dir)
    again = make_embedder(spec, Config(device="cpu"))
    assert again is not emb and again.key != emb.key
    assert make_embedder(spec, Config(device="cpu")) is again


def test_retrained_weights_re_embed_and_never_come_from_the_vector_cache(plugins, sample_repo, tmp_path,
                                                                         fake_config, model_dir):
    """The shared vector cache is keyed by the embedder's key, so vectors of the old weights are
    never reused: not in a new index, and not in the index that had them."""
    fake_config.vectors["code"] = VectorConfig(model=str(model_dir), embedder=EMBEDDER)
    store = Store(tmp_path / "index")
    indexer = Indexer(sample_repo, store, fake_config)
    n = indexer.update().model_embedded["code"]
    key = store.get_meta("vec.code.embedder")
    assert n > 0 and key.startswith(f"{model_dir}#{model_folder_hash(model_dir)}|plugin={EMBEDDER}|")
    assert sum(indexer.update().model_embedded.values()) == 0  # nothing changed
    loaded = len(plugins.WrappedFake.instances)

    _retrain(model_dir)
    fresh = Store(tmp_path / "fresh")
    assert Indexer(sample_repo, fresh, fake_config).update().model_embedded["code"] == n  # the cache had only the old ones
    fresh.close()
    assert len(plugins.WrappedFake.instances) == loaded + 1  # the new weights were loaded, not the cached model

    stats = indexer.update()  # the first index catches up, from the vectors the new model just made
    assert stats.embedded["code"] == n and stats.model_embedded == {"code": 0, "usage": 0}
    assert store.get_meta("vec.code.embedder") != key
    store.close()


# ---------------------------------------------------------------- embedder plugin


def test_make_embedder_loads_a_plugin_and_normalizes_it(plugins, model_dir):
    emb = make_embedder(VectorConfig(model=str(model_dir), embedder=EMBEDDER), Config())
    assert isinstance(emb, PluginEmbedder) and isinstance(emb.inner, plugins.WrappedFake)
    assert emb.inner.model_name == str(model_dir) and emb.dim == 32
    vecs = emb.embed_queries(["revoke session"])
    assert vecs.shape == (1, 32) and np.isclose(np.linalg.norm(vecs[0]), 1.0)  # the plugin's are 3x longer


def test_make_embedder_refuses_a_class_that_is_not_an_embedder(plugins, model_dir):
    with pytest.raises(TypeError, match="Embedder"):
        make_embedder(VectorConfig(model=str(model_dir), embedder=f"{PLUGIN_MODULE}:NotAnEmbedder"), Config())


def test_the_fake_model_wins_over_a_plugin_and_model_names_still_work(plugins):
    assert isinstance(make_embedder(VectorConfig(model="fake:16", embedder=EMBEDDER), Config()), FakeEmbedder)
    assert make_embedder("fake:16", Config()).dim == 16


def test_searches_embed_the_query_with_the_plugin(plugins, sample_repo, tmp_path, fake_config, model_dir):
    fake_config.vectors["code"] = VectorConfig(model=str(model_dir), embedder=EMBEDDER)
    store = Store(tmp_path / "index")
    Indexer(sample_repo, store, fake_config).update()
    resp = search(store, "revoke session", fake_config, k=5, signals=["code"])
    assert resp.signals == ["code"] and "revoke_session" in [r.qualname for r in resp.results]
    assert f"embed_query:{model_dir}+{EMBEDDER}" in resp.timings
    store.close()


# ---------------------------------------------------------------- vector backend


def test_backend_class_resolution(plugins):
    assert vector_backend_class("faiss") is FaissVectorStore
    assert vector_backend_class(BACKEND) is plugins.NumpyVectorStore
    with pytest.raises(TypeError, match="VectorStore"):
        vector_backend_class("codemem.store:Store")


def _index(path, sample_repo, cfg, recorder, backend="faiss"):
    cfg.vector_backend = backend
    store = Store(path, vector_backend=backend)
    stats = Indexer(sample_repo, store, cfg, embedder_factory=lambda m, c: recorder).update()
    return store, stats


def _scores(store, recorder, query="session"):
    q = recorder.embed_queries([query])[0]
    return [round(h.score, 5) for h in store.vector_search("code", q, 20)]


def test_a_plugin_backend_saves_reloads_and_scores_like_faiss(plugins, sample_repo, tmp_path, fake_config, recorder):
    faiss_store, _ = _index(tmp_path / "faiss", sample_repo, fake_config, recorder)
    store, _ = _index(tmp_path / "np", sample_repo, fake_config, recorder, BACKEND)
    n = store.counts()["vectors"]["code"]
    found = [
        [r.qualname for r in search(s, "disabled users stay logged in", fake_config, k=10,
                                    embedder_factory=lambda m, c: recorder).results]
        for s in (store, faiss_store)
    ]
    assert found[0] == found[1] and len(found[0]) == 10  # the same results as FAISS
    store.save_vectors()
    store.close()
    assert (tmp_path / "np" / "vec_code.npvec").is_file() and not list((tmp_path / "np").glob("*.faiss"))
    assert json.loads((tmp_path / "np" / "vec_code.json").read_text())["backend"] == BACKEND

    reopened = Store(tmp_path / "np", vector_backend=BACKEND)
    ti = reopened._type_index("code")
    assert isinstance(ti.store, plugins.NumpyVectorStore) and len(ti.store) == n
    assert plugins.NumpyVectorStore.loads == 1  # read back from its file, not rebuilt
    assert _scores(reopened, recorder) == _scores(faiss_store, recorder)  # same scores, any backend
    reopened.close()
    faiss_store.close()


def test_switching_backend_re_embeds_nothing_and_drops_the_old_file(plugins, sample_repo, tmp_path, fake_config,
                                                                    recorder):
    """Vectors live in SQLite: a new backend only builds its search index from them. It still is an
    index setting, so the eval gives systems with another backend their own index."""
    store, _ = _index(tmp_path / "index", sample_repo, fake_config, recorder)
    want = _scores(store, recorder)
    store.close()
    assert (tmp_path / "index" / "vec_code.faiss").is_file()

    store, stats = _index(tmp_path / "index", sample_repo, fake_config, recorder, BACKEND)
    assert "vector_backend" in fake_config.index_settings()
    assert stats.queued == 0 and sum(stats.model_embedded.values()) == 0 and stats.files_changed == 0
    assert _scores(store, recorder) == want
    assert isinstance(store._type_index("code").store, plugins.NumpyVectorStore)
    store.load_vectors()  # what a server does at start: every type's index is built with the new backend
    store.save_vectors()
    assert {p.name for p in (tmp_path / "index").glob("vec_*")} == {
        "vec_code.npvec", "vec_code.json", "vec_usage.npvec", "vec_usage.json",
    }  # the FAISS files are removed once replaced
    store.close()


def test_a_backend_that_is_not_saved_is_rebuilt_from_the_stored_vectors(plugins, sample_repo, tmp_path,
                                                                        fake_config, recorder):
    store, _ = _index(tmp_path / "index", sample_repo, fake_config, recorder, UNSAVED)
    n = store.counts()["vectors"]["code"]
    store.load_vectors()
    store.save_vectors()
    store.close()
    assert not list((tmp_path / "index").glob("vec_*"))  # no file and no note

    reopened = Store(tmp_path / "index", vector_backend=UNSAVED)
    assert len(reopened._type_index("code").store) == n and _scores(reopened, recorder)
    reopened.close()


def test_saved_indexes_from_before_backends_load_as_faiss(sample_repo, tmp_path, fake_config, recorder, monkeypatch):
    store, _ = _index(tmp_path / "index", sample_repo, fake_config, recorder)
    want = _scores(store, recorder)
    store.close()
    for note_path in (tmp_path / "index").glob("vec_*.json"):  # notes written before backends were pluggable
        note = json.loads(note_path.read_text())
        del note["backend"], note["file"]
        note_path.write_text(json.dumps(note))

    def no_rebuild(*args):
        raise AssertionError("the saved FAISS file should have been used")

    monkeypatch.setattr(Store, "_rebuild", no_rebuild)
    store = Store(tmp_path / "index")
    assert _scores(store, recorder) == want
    store.close()


def test_the_service_switches_backend_when_the_config_file_changes(plugins, sample_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    svc = CodememService(sample_repo, index_dir=tmp_path / "idx")
    try:
        svc.update()
        (sample_repo / ".codemem.toml").write_text(f'vector_backend = "{BACKEND}"\n')
        svc._reload_config()
        assert svc.store.vector_backend == svc.config.vector_backend == BACKEND
        assert "revoke_session" in [r.qualname for r in svc.search("revoke session", k=5, signals=["code"]).results]
        assert isinstance(svc.store._type_index("code").store, plugins.NumpyVectorStore)
        assert sum(svc.update().model_embedded.values()) == 0

        (sample_repo / ".codemem.toml").write_text('vector_backend = "no_such_module:Store"\n')
        svc._reload_config()  # a backend that does not load: keep the current config
        assert svc.store.vector_backend == svc.config.vector_backend == BACKEND
    finally:
        svc.close()
