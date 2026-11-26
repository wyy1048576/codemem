"""The OpenAI-compatible embedder, against a fake local server (no network), plus a smoke test
against Nebius that runs only with `NEBIUS_API_KEY` set: `uv run pytest -m api`."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest

from codemem.config import DEFAULT_MODEL, Config, config_from_dict
from codemem.embedder import FakeEmbedder, OpenAIEmbedder, SentenceTransformerEmbedder
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
    gives an index for each). `fail` holds status codes to answer with first (429, 503, ...).
    With `honours_dimensions = False` it answers with full vectors whatever length is asked for."""

    def __init__(self, dim: int = 8):
        self.dim, self.requests, self.fail, self.honours_dimensions = dim, [], [], True
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
                dim = (outer.honours_dimensions and body.get("dimensions")) or outer.dim
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


def test_a_provider_that_ignores_dimensions_still_gives_vectors_of_that_length(server, sample_repo, tmp_path):
    """`dimensions` is sent, and what comes back is checked: full vectors are cut to their first
    numbers and normalized again, so the stored vectors are what the key says they are."""
    text = "def revoke_session(session_id): pass"
    honoured = OpenAIEmbedder(_config(server, dimensions=6).embedding).embed_documents([text])
    full = OpenAIEmbedder(_config(server).embedding).embed_documents([text])
    server.honours_dimensions = False
    cut = OpenAIEmbedder(_config(server, dimensions=6).embedding).embed_documents([text])
    assert cut.shape == (1, 6) and np.isclose(np.linalg.norm(cut[0]), 1.0)
    np.testing.assert_allclose(cut[0], full[0, :6] / np.linalg.norm(full[0, :6]), rtol=0, atol=1e-6)
    assert not np.allclose(cut, honoured, atol=1e-3)  # this fake API's short vectors are not a cut of its long ones

    store = Store(tmp_path / "idx")
    try:
        Indexer(sample_repo, store, _config(server, dimensions=6)).update()
        assert store.vector_dim("code") == 6 and store.get_meta("vec.code.embedder").endswith("|dims=6|doc=0")
    finally:
        store.close()


def test_fewer_numbers_than_dimensions_asks_for_is_an_error(server):
    server.honours_dimensions = False  # full vectors of 8 numbers
    with pytest.raises(RuntimeError, match="returned vectors of 8 numbers for test-embed, fewer than .* dimensions = 12"):
        OpenAIEmbedder(_config(server, dimensions=12).embedding).embed_documents(["x"])


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
    ({"space": "two words"}, "space must be"),
    ({"space": "a|b"}, "space must be"),  # `|` separates the parts of a key
    ({"space": "x" * 65}, "space must be"),
])
def test_bad_embedding_settings_are_refused(embedding, message):
    with pytest.raises(ValueError, match=message):
        config_from_dict({"embedding": embedding})


def _api(**embedding):
    return config_from_dict({"embedding": {"provider": "openai", "model": "m", "base_url": "http://a.example/v1",
                                           **embedding}})


def test_without_a_space_every_key_and_setting_is_the_string_it_was():
    """Pinned as literals: an index or a cached vector made before `space` existed keeps its name."""
    nebius = _api(model="Qwen/Qwen3-Embedding-8B", base_url="https://api.studio.nebius.com/v1", dimensions=1024)
    assert OpenAIEmbedder(nebius.embedding).key == "api:api.studio.nebius.com|Qwen/Qwen3-Embedding-8B|dims=1024|doc=0"
    assert nebius.index_settings()["embedding"] == {
        "provider": "openai", "model": "Qwen/Qwen3-Embedding-8B", "base_url": "https://api.studio.nebius.com/v1",
        "dimensions": 1024, "document_prefix": "",
    }
    on_a_port = _api(base_url="http://127.0.0.1:8765/v1", document_prefix="Doc: ")
    assert OpenAIEmbedder(on_a_port.embedding).key == "api:127.0.0.1:8765|m|dims=full|doc=9c41604f"
    assert FakeEmbedder(64).key == "fake:64|doc"
    assert SentenceTransformerEmbedder(DEFAULT_MODEL, device="cpu").key == (
        "jinaai/jina-code-embeddings-0.5b|doc|L1024|float32|cpu"
    )
    folder = SentenceTransformerEmbedder("/models/enc", device="cpu", dtype="float16", version="3fa2b1c9d0e1")
    assert folder.key == "/models/enc#3fa2b1c9d0e1|doc|L1024|float16|cpu"
    assert "embedding" not in Config().index_settings()
    assert Config().index_settings()["vectors"] == {"code": {"model": DEFAULT_MODEL}, "usage": {"model": DEFAULT_MODEL}}


def test_a_space_stands_for_the_address_in_the_key_and_in_the_settings():
    host = _api(base_url="http://127.0.0.1:8791/v1", space="st-L1024-float16-mps")
    container = _api(base_url="http://host.docker.internal:9000/v1", space="st-L1024-float16-mps")
    assert OpenAIEmbedder(host.embedding).key == "api:st-L1024-float16-mps|m|dims=full|doc=0"
    assert OpenAIEmbedder(container.embedding).key == OpenAIEmbedder(host.embedding).key
    assert host.index_settings() == container.index_settings()
    assert host.index_settings()["embedding"] == {
        "provider": "openai", "model": "m", "space": "st-L1024-float16-mps", "dimensions": None, "document_prefix": "",
    }


@pytest.mark.parametrize("change", [
    {"space": "another"}, {"model": "m2"}, {"dimensions": 256}, {"document_prefix": "Doc: "},
])
def test_what_shapes_a_stored_vector_stays_in_the_identity_beside_the_space(change):
    base, other = _api(space="shared"), _api(**{"space": "shared", **change})
    assert OpenAIEmbedder(other.embedding).key != OpenAIEmbedder(base.embedding).key
    assert other.index_settings() != base.index_settings()


def test_what_never_shapes_a_stored_vector_is_in_neither():
    base = _api(space="shared")
    other = _api(space="shared", query_prefix="Q: ", api_key_env="SOME_KEY", batch_size=8, max_concurrency=1,
                 timeout_s=5.0)
    assert OpenAIEmbedder(other.embedding).key == OpenAIEmbedder(base.embedding).key
    assert other.index_settings() == base.index_settings()


def test_an_index_follows_its_space_to_another_address(server, sample_repo, tmp_path):
    """Built through one address and opened through another, an index with a `space` embeds nothing
    again; a new index of the same code takes its vectors from the shared cache."""
    other = _Server()
    store = Store(tmp_path / "idx")
    try:
        built = Indexer(sample_repo, store, _config(server, space="shared")).update()
        assert sum(built.model_embedded.values()) > 0
        moved = _config(other, space="shared")
        again = Indexer(sample_repo, store, moved).update()
        assert sum(again.embedded.values()) == 0 and other.requests == []
        assert search(store, "revoke session", moved, k=3).results
        assert [r["input"] for r in other.requests] == [["revoke session"]]  # the query alone used the new address

        fresh = Store(tmp_path / "idx-worktree")
        try:
            stats = Indexer(sample_repo, fresh, moved).update()
            assert stats.cache_hits == built.embedded and sum(stats.model_embedded.values()) == 0
            assert len(other.requests) == 1
        finally:
            fresh.close()
    finally:
        store.close()
        other.httpd.shutdown()


def test_without_a_space_another_address_is_another_embedder(server, sample_repo, tmp_path):
    other = _Server()
    store = Store(tmp_path / "idx")
    try:
        built = Indexer(sample_repo, store, _config(server)).update()
        again = Indexer(sample_repo, store, _config(other)).update()
        assert again.model_embedded == built.model_embedded and sum(again.model_embedded.values()) > 0
    finally:
        store.close()
        other.httpd.shutdown()


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
