import os
import shutil
from pathlib import Path

import pytest

from codemem.config import Config, VectorConfig
from codemem.embedder import FakeEmbedder
from codemem.store import Store

# The sample repo contains its own test_*.py files; they are data, not tests.
collect_ignore_glob = ["fixtures/*"]

FIXTURES = Path(__file__).parent / "fixtures"

# CODEMEM_TEST_VECTOR_BACKEND=compact runs the suite on that search index: every Store and Config
# that a test builds without naming a backend gets it.
VECTOR_BACKEND = os.environ.get("CODEMEM_TEST_VECTOR_BACKEND", "faiss")
# Tests of what the defaults are, or that name the FAISS file: they hold for the FAISS backend only.
FAISS_ONLY = {
    "test_config_parses_embedder_version_and_backend": "asserts that the default backend is faiss",
    "test_defaults_keep_their_ids_so_existing_indexes_stay_valid": "asserts the default index settings",
    "test_saved_indexes_from_before_backends_load_as_faiss": "a note without a backend is read as FAISS",
    "test_a_saved_index_is_reconciled_with_the_rows": "reads vec_code.faiss",
    "test_the_search_indexes_are_written_once_the_index_is_quiet": "reads vec_code.faiss",
    "test_cli_default_index_dir_under_codemem_home": "reads vec_code.faiss",
    "test_the_mcp_server_started_in_a_new_worktree_serves_it_from_the_copy":
        "starts codemem in a process of its own, which gets the default backend, not this run's",
}


class RecordingEmbedder(FakeEmbedder):
    """FakeEmbedder that remembers every document text it embedded."""

    def __init__(self, dim=64):
        super().__init__(dim)
        self.documents: list[str] = []

    def embed_documents(self, texts):
        self.documents.extend(texts)
        return super().embed_documents(texts)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never touch the real ~/.codemem from tests."""
    home = tmp_path / "codemem_home"
    monkeypatch.setenv("CODEMEM_HOME", str(home))
    for var in ("CODEMEM_MODEL", "CODEMEM_DEVICE", "CODEMEM_STEERING"):
        monkeypatch.delenv(var, raising=False)
    return home


def pytest_collection_modifyitems(items):
    if VECTOR_BACKEND == "faiss":
        return
    for item in items:
        if reason := FAISS_ONLY.get(item.originalname):
            item.add_marker(pytest.mark.skip(reason=f"FAISS backend only: {reason}"))


@pytest.fixture(autouse=True)
def default_vector_backend(monkeypatch):
    if VECTOR_BACKEND == "faiss":
        return
    monkeypatch.setitem(Store.__init__.__kwdefaults__, "vector_backend", VECTOR_BACKEND)
    init = Config.__init__

    def with_backend(self, *args, **kwargs):
        kwargs.setdefault("vector_backend", VECTOR_BACKEND)
        init(self, *args, **kwargs)

    monkeypatch.setattr(Config, "__init__", with_backend)


@pytest.fixture
def sample_repo(tmp_path):
    dst = tmp_path / "sample_repo"
    shutil.copytree(FIXTURES / "sample_repo", dst)
    return dst


@pytest.fixture
def fake_config():
    cfg = Config()
    cfg.vectors = {"code": VectorConfig(model="fake:64"), "usage": VectorConfig(model="fake:64")}
    return cfg


@pytest.fixture
def recorder():
    return RecordingEmbedder()
