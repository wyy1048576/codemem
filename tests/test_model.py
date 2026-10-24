"""Real jina-code-embeddings tests. Downloads the model on first run.

Run with:  uv run pytest -m model
"""

import pytest

from codemem.config import DEFAULT_MODEL, Config
from codemem.embedder import DOCUMENT_PROMPT, QUERY_PROMPT, make_embedder
from codemem.indexer import Indexer
from codemem.search import search
from codemem.store import Store

pytestmark = pytest.mark.model

QUERY = "disabled users stay logged in"


@pytest.fixture(scope="module")
def config():
    return Config(device="cpu")


def test_model_ships_task_prompts(config):
    emb = make_embedder(DEFAULT_MODEL, config)
    prompts = emb.model.prompts
    assert QUERY_PROMPT in prompts and DOCUMENT_PROMPT in prompts, sorted(prompts)
    assert emb.dim == 896


def test_query_document_similarity_is_semantic(config):
    emb = make_embedder(DEFAULT_MODEL, config)
    q = emb.embed_queries(["remove a user's login session"])[0]
    docs = emb.embed_documents([
        "def revoke_session(session_id):\n    db.sessions.delete(session_id)",
        "def parse_csv(path):\n    return list(csv.reader(open(path)))",
    ])
    assert q @ docs[0] > q @ docs[1]


def test_nl_query_finds_revoke_session(sample_repo, tmp_path, config):
    """Observed with jina-0.5b on CPU (v2, Oct 24 2026): fused rank 3 with the default weights
    (7 without them: a test helper class, a test and two blocks rank above it), usage rank 2,
    code rank 10. disable_user ranks first, which is a fair answer on this tiny fixture."""
    store = Store(tmp_path / "idx")
    try:
        Indexer(sample_repo, store, config).update()
        resp = search(store, QUERY, config, k=5, debug=True)
        hits = {r.qualname: r for r in resp.results}
        assert "revoke_session" in hits, [(r.qualname, r.ranks) for r in resp.results]
        ranks = hits["revoke_session"].ranks
        # The usage signal is what surfaces it: it must rank it above the code signal.
        assert ranks["usage"] < ranks.get("code", 10**6), ranks
    finally:
        store.close()
