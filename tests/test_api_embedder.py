"""The OpenAI-compatible embedder, against a fake local server (no network), plus a smoke test
against Nebius that runs only with `NEBIUS_API_KEY` set: `uv run pytest -m api`."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest

from codemem.config import config_from_dict
from codemem.embedder import OpenAIEmbedder
from codemem.indexer import Indexer
from codemem.search import search
from codemem.store import Store


def _vec(text: str, dim: int) -> list[float]:
    v = np.full(dim, 0.01)
    for word in text.lower().split():
        v[sum(word.encode()) % dim] += 1.0
    return v.tolist()


class _Server:
    """A fake `/v1/embeddings`: vectors from each input's words, returned out of order (the API
    gives an index for each). `fail` holds status codes to answer with first (429, 503, ...)."""

    def __init__(self, dim: int = 8):
        self.dim, self.requests, self.fail = dim, [], []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), **body})
                if outer.fail:
                    self.send_response(outer.fail.pop(0))
                    self.send_header("Retry-After", "0")
                    self.end_headers()
                    self.wfile.write(b'{"error": {"message": "slow down"}}')
                    return
                dim = body.get("dimensions") or outer.dim
                data = [{"index": i, "embedding": _vec(t, dim)} for i, t in enumerate(body["input"])]
                out = json.dumps({"data": data[::-1], "model": body["model"]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def server():
    s = _Server()
    yield s
    s.httpd.shutdown()


@pytest.fixture(autouse=True)
def _quick_retries(monkeypatch):
    monkeypatch.setattr(OpenAIEmbedder, "BACKOFF_S", 0.01)
    monkeypatch.setenv("CODEMEM_TEST_KEY", "secret")


def _config(server, **embedding):
    return config_from_dict({"embedding": {
        "provider": "openai", "model": "test-embed", "base_url": server.url, "api_key_env": "CODEMEM_TEST_KEY",
        "batch_size": 4, **embedding,
    }})


def test_an_index_built_through_the_api_searches_like_any_other(server, sample_repo, tmp_path):
    cfg = _config(server, dimensions=6, query_prefix="Query: ", document_prefix="Doc: ")
    store = Store(tmp_path / "idx")
    try:
        Indexer(sample_repo, store, cfg).update()
        assert store.get_meta("vec.code.embedder").startswith(
            f"api:127.0.0.1:{server.httpd.server_port}|test-embed|dims=6|doc="
        )
        assert store.vector_dim("code") == 6 and store.vector_dim("usage") == 6
        docs = [r for r in server.requests if r["input"][0].startswith("Doc: ")]
        assert docs and all(len(r["input"]) <= 4 for r in docs)  # batch_size
        assert all(r["auth"] == "Bearer secret" and r["model"] == "test-embed" and r["dimensions"] == 6
                   for r in server.requests)
        assert all(r["path"] == "/v1/embeddings" for r in server.requests)
        resp = search(store, "revoke session", cfg, k=3)
        assert resp.results
        assert any(r["input"] == ["Query: revoke session"] for r in server.requests)  # the query prefix
    finally:
        store.close()


def test_rate_limits_and_server_errors_are_retried(server):
    server.fail = [429, 503]
    vecs = OpenAIEmbedder(_config(server).embedding).embed_documents(["def f(): pass"])
    assert vecs.shape == (1, 8) and len(server.requests) == 3
    assert np.isclose(np.linalg.norm(vecs[0]), 1.0)  # normalized


def test_other_errors_fail_at_once_with_the_providers_message(server):
    server.fail = [400]
    with pytest.raises(RuntimeError, match="HTTP 400.*slow down"):
        OpenAIEmbedder(_config(server).embedding).embed_documents(["x"])
    assert len(server.requests) == 1


def test_a_missing_key_names_its_variable_and_sends_nothing(server, monkeypatch):
    monkeypatch.delenv("CODEMEM_TEST_KEY")
    with pytest.raises(RuntimeError, match="CODEMEM_TEST_KEY"):
        OpenAIEmbedder(_config(server).embedding).embed_documents(["x"])
    assert server.requests == []


def test_vectors_keep_the_input_order_across_concurrent_requests(server):
    emb = OpenAIEmbedder(_config(server, api_key_env="", batch_size=2, max_concurrency=3).embedding)
    texts = [f"word{i} shared" for i in range(9)]
    together = emb.embed_documents(texts)
    assert len(server.requests) == 5 and all(r["auth"] is None for r in server.requests)  # no key: none sent
    assert np.allclose(together, np.vstack([emb.embed_documents([t]) for t in texts]))


def test_a_repeated_query_costs_no_request(server):
    emb = OpenAIEmbedder(_config(server).embedding)
    emb.embed_queries(["where is the login"])
    emb.embed_queries(["where is the login"])
    assert len(server.requests) == 1


def test_another_api_model_re_embeds_and_keeps_the_chunks(server, sample_repo, tmp_path):
    store = Store(tmp_path / "idx")
    try:
        Indexer(sample_repo, store, _config(server, dimensions=6)).update()
        ids = {c.key: c.chunk_id for c in store.chunks_for_paths(["auth/sessions.py"])}
        stats = Indexer(sample_repo, store, _config(server, dimensions=4)).update()
        assert store.vector_dim("code") == 4 and sum(stats.model_embedded.values()) > 0
        assert {c.key: c.chunk_id for c in store.chunks_for_paths(["auth/sessions.py"])} == ids  # not rebuilt
    finally:
        store.close()


def test_the_local_model_keeps_its_settings_and_the_api_keeps_only_what_shapes_vectors(server):
    assert "embedding" not in config_from_dict({}).index_settings()  # local indexes are not rebuilt
    api = _config(server, query_prefix="Q: ", max_concurrency=8).index_settings()["embedding"]
    assert set(api) == {"provider", "model", "base_url", "dimensions", "document_prefix"}


@pytest.mark.parametrize("embedding, message", [
    ({"provider": "cohere"}, "provider must be local|openai"),
    ({"provider": "openai", "model": "m"}, "needs model and base_url"),
    ({"provider": "local", "modle": "m"}, "unknown \\[embedding\\] settings"),
])
def test_bad_embedding_settings_are_refused(embedding, message):
    with pytest.raises(ValueError, match=message):
        config_from_dict({"embedding": embedding})


@pytest.mark.api
@pytest.mark.skipif(not os.environ.get("NEBIUS_API_KEY"), reason="set NEBIUS_API_KEY to call Nebius")
def test_nebius_smoke():
    """Model and URL from NEBIUS_EMBED_MODEL / NEBIUS_BASE_URL if set (check your console)."""
    cfg = config_from_dict({"embedding": {
        "provider": "openai",
        "model": os.environ.get("NEBIUS_EMBED_MODEL", "Qwen/Qwen3-Embedding-8B"),
        "base_url": os.environ.get("NEBIUS_BASE_URL", "https://api.studio.nebius.com/v1"),
        "api_key_env": "NEBIUS_API_KEY",
        "dimensions": 1024,
        "query_prefix": "Instruct: Given a code search request, retrieve the relevant code\nQuery: ",
    }})
    emb = OpenAIEmbedder(cfg.embedding)
    q = emb.embed_queries(["remove a user's login session"])[0]
    docs = emb.embed_documents([
        "def revoke_session(session_id):\n    db.sessions.delete(session_id)",
        "def parse_csv(path):\n    return list(csv.reader(open(path)))",
    ])
    assert docs.shape == (2, 1024) and q @ docs[0] > q @ docs[1]
