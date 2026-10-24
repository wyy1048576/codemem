"""Custom embedders, model versions and vector backends named in config."""

import os
import sys
import textwrap

import numpy as np
import pytest

from codemem.config import DEFAULT_MODEL, Config, VectorConfig, config_from_dict, model_folder_hash, model_version
from codemem.embedder import FakeEmbedder, make_embedder
from codemem.indexer import Indexer
from codemem.search import search
from codemem.store import FaissVectorStore, Store, vector_backend_class

PLUGIN_MODULE = "cm_test_plugins"
EMBEDDER = f"{PLUGIN_MODULE}:WrappedFake"
BACKEND = f"{PLUGIN_MODULE}:NumpyVectorStore"

PLUGIN_SOURCE = textwrap.dedent(
    '''
    import numpy as np

    from codemem.embedder import Embedder, FakeEmbedder
    from codemem.store import VectorStore


    class WrappedFake(Embedder):
        instances = []

        def __init__(self, model, config):
            self.model_name = model
            self.inner = FakeEmbedder(32)
            self.documents = 0
            WrappedFake.instances.append(self)

        @property
        def dim(self):
            return 32

        def embed_documents(self, texts):
            self.documents += len(texts)
            return self.inner.embed_documents(texts)

        def embed_queries(self, texts):
            return self.inner.embed_queries(texts)


    class NotAnEmbedder:
        def __init__(self, model, config):
            pass


    class NumpyVectorStore(VectorStore):
        """Brute force in numpy, saved as a folder: a backend that is not FAISS."""

        suffix = ".npvec"

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

        def save(self, path):
            path.mkdir(exist_ok=True)
            ids = sorted(self.vecs)
            mat = np.stack([self.vecs[i] for i in ids]) if ids else np.zeros((0, self.dim), np.float32)
            np.save(path / "ids.npy", np.array(ids, dtype=np.int64))
            np.save(path / "vecs.npy", mat)

        @classmethod
        def load(cls, path):
            mat = np.load(path / "vecs.npy")
            vs = cls(mat.shape[1])
            vs.upsert(np.load(path / "ids.npy").tolist(), mat)
            return vs
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
    """Same size, new bytes, later mtime: what overwriting a checkpoint looks like."""
    weights = path / "weights.bin"
    weights.write_bytes(b"\x02" * 100)
    st = weights.stat()
    os.utime(weights, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


# ---- config


def test_config_parses_embedder_version_and_backend():
    cfg = config_from_dict(
        {"vector_backend": "pkg.mod:Store", "vectors": {"code": {"embedder": "pkg.emb:Mine", "version": "v3"}}}
    )
    assert cfg.vector_backend == "pkg.mod:Store"
    assert cfg.vectors["code"].embedder == "pkg.emb:Mine" and cfg.vectors["code"].version == "v3"
    assert cfg.vectors["code"].model == DEFAULT_MODEL
    assert cfg.vectors["usage"].embedder is None and cfg.vectors["usage"].version is None
    assert Config().vector_backend == "faiss"


def test_config_rejects_bad_plugin_names():
    with pytest.raises(ValueError, match="embedder"):
        config_from_dict({"vectors": {"code": {"embedder": "no_colon"}}})
    with pytest.raises(ValueError, match="vector_backend"):
        config_from_dict({"vector_backend": "lancedb"})


def test_model_id_unchanged_without_version_or_embedder():
    """Old indexes and cached eval indexes keep their key."""
    cfg = Config()
    assert cfg.model_id("code") == DEFAULT_MODEL
    cfg.embedding_dim = 256
    assert cfg.model_id("code") == f"{DEFAULT_MODEL}@256"


def test_model_id_includes_version_and_embedder():
    cfg = Config(embedding_dim=256)
    cfg.vectors["code"] = VectorConfig(model="org/model", embedder="pkg.emb:Mine", version="v3")
    assert cfg.model_id("code") == "org/model@256#v3+pkg.emb:Mine"


# ---- model folder hash


def test_folder_hash_follows_content_not_location(tmp_path, model_dir, isolated_home):
    h = model_folder_hash(model_dir)
    assert len(h) == 12 and model_folder_hash(model_dir) == h
    assert (isolated_home / "model_hashes.json").is_file()

    copy = tmp_path / "copy"
    copy.mkdir()
    for f in model_dir.iterdir():
        (copy / f.name).write_bytes(f.read_bytes())
    assert model_folder_hash(copy) == h  # same weights on another path or machine

    (model_dir / ".cache").mkdir()
    (model_dir / ".cache" / "lock").write_text("x")
    assert model_folder_hash(model_dir) == h  # dot folders are tool metadata

    _retrain(model_dir)
    assert model_folder_hash(model_dir) != h


def test_model_version_sources(model_dir):
    assert model_version(VectorConfig(model=str(model_dir))) == model_folder_hash(model_dir)
    assert model_version(VectorConfig(model=str(model_dir), version="v7")) == "v7"
    assert model_version(VectorConfig(model="org/hub-model")) is None
    assert model_version(VectorConfig(model="fake:64")) is None


# ---- embedder plugin


def test_make_embedder_loads_plugin(plugins, model_dir):
    emb = make_embedder(VectorConfig(model=str(model_dir), embedder=EMBEDDER), Config())
    assert isinstance(emb, plugins.WrappedFake) and emb.model_name == str(model_dir)
    assert emb.embed_queries(["x"]).shape == (1, 32)


def test_make_embedder_rejects_non_embedder(plugins, model_dir):
    with pytest.raises(TypeError, match="Embedder"):
        make_embedder(VectorConfig(model=str(model_dir), embedder=f"{PLUGIN_MODULE}:NotAnEmbedder"), Config())


def test_fake_model_wins_over_plugin_and_strings_still_work(plugins):
    assert isinstance(make_embedder(VectorConfig(model="fake:16", embedder=EMBEDDER), Config()), FakeEmbedder)
    assert make_embedder("fake:16", Config()).dim == 16


def test_retrained_weights_in_same_folder_rebuild(plugins, sample_repo, tmp_path, fake_config, model_dir):
    fake_config.vectors["code"] = VectorConfig(model=str(model_dir), embedder=EMBEDDER)
    store = Store(tmp_path / "index")
    indexer = Indexer(sample_repo, store, fake_config)
    stats = indexer.update()
    n = store.counts()["chunks"]
    assert stats.embedded["code"] == n
    first_id = store.get_meta("vec.code.model")
    assert first_id == f"{model_dir}#{model_folder_hash(model_dir)}+{EMBEDDER}"

    assert indexer.update().embedded["code"] == 0  # nothing changed

    loaded = len(plugins.WrappedFake.instances)
    _retrain(model_dir)
    stats = indexer.update()
    assert stats.embedded["code"] == n and stats.embedded["usage"] == 0
    assert store.get_meta("vec.code.model") != first_id
    assert len(plugins.WrappedFake.instances) == loaded + 1  # the new weights were loaded, not the cached model
    store.close()


# ---- vector backend


def test_backend_class_resolution(plugins):
    assert vector_backend_class("faiss") is FaissVectorStore
    assert vector_backend_class(BACKEND) is plugins.NumpyVectorStore
    with pytest.raises(TypeError, match="VectorStore"):
        vector_backend_class("codemem.store:Store")


def _index(path, sample_repo, cfg, recorder, backend="faiss"):
    store = Store(path, vector_backend=backend)
    stats = Indexer(sample_repo, store, cfg, embedder_factory=lambda m, c: recorder).update()
    return store, stats


def test_plugin_backend_indexes_saves_and_searches(plugins, sample_repo, tmp_path, fake_config, recorder):
    store, _ = _index(tmp_path / "np", sample_repo, fake_config, recorder, BACKEND)
    n = store.counts()["chunks"]
    assert (tmp_path / "np" / "vec_code.npvec").is_dir()
    assert not list((tmp_path / "np").glob("*.faiss"))
    assert store.get_meta("vector_backend") == BACKEND
    resp = search(store, "disabled users stay logged in", fake_config, k=10, embedder_factory=lambda m, c: recorder)
    assert "revoke_session" in [r.qualname for r in resp.results]
    store.close()

    reopened = Store(tmp_path / "np", vector_backend=BACKEND)
    assert isinstance(reopened.vectors("code"), plugins.NumpyVectorStore) and len(reopened.vectors("code")) == n

    faiss_store, _ = _index(tmp_path / "faiss", sample_repo, fake_config, recorder)
    q = recorder.embed_queries(["session"])[0]
    got = [s for _, s in reopened.vector_search("code", q, 20)]
    want = [s for _, s in faiss_store.vector_search("code", q, 20)]
    assert got == pytest.approx(want, abs=1e-5)  # same scores, any backend
    reopened.close()
    faiss_store.close()


def test_switching_backend_rebuilds_vectors(plugins, sample_repo, tmp_path, fake_config, recorder):
    store, _ = _index(tmp_path / "index", sample_repo, fake_config, recorder)
    n = store.counts()["chunks"]
    assert (tmp_path / "index" / "vec_code.faiss").is_file()
    store.close()

    store, stats = _index(tmp_path / "index", sample_repo, fake_config, recorder, BACKEND)
    assert stats.embedded["code"] == n and stats.files_changed == 0  # chunks kept, vectors redone
    assert not list((tmp_path / "index").glob("*.faiss"))
    assert len(store.vectors("code")) == n
    assert store.vectors("code").ids() == set(store.embedding_hashes("code"))
    store.close()


def test_index_from_before_the_setting_counts_as_faiss(sample_repo, tmp_path, fake_config, recorder):
    store, _ = _index(tmp_path / "index", sample_repo, fake_config, recorder)
    store.conn.execute("DELETE FROM meta WHERE key = 'vector_backend'")
    store.close()
    store, stats = _index(tmp_path / "index", sample_repo, fake_config, recorder)
    assert stats.embedded["code"] == 0
    store.close()
