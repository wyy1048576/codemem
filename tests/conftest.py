import shutil
from pathlib import Path

import pytest

from codemem.config import Config, VectorConfig
from codemem.embedder import FakeEmbedder

# The sample repo contains its own test_*.py files; they are data, not tests.
collect_ignore_glob = ["fixtures/*"]

FIXTURES = Path(__file__).parent / "fixtures"


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


@pytest.fixture
def sample_repo(tmp_path):
    dst = tmp_path / "sample_repo"
    shutil.copytree(FIXTURES / "sample_repo", dst)
    return dst


@pytest.fixture
def fake_config():
    cfg = Config()
    cfg.vectors = {
        "code": VectorConfig(model="fake:64"),
        "usage": VectorConfig(model="fake:64"),
        "summary": VectorConfig(model="fake:64", enabled=False),
    }
    return cfg


@pytest.fixture
def recorder():
    return RecordingEmbedder()
