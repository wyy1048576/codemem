"""`codemem serve-embeddings` (embedserver.py): one model behind an OpenAI-style endpoint for several
codemem processes. Everything here uses the fake model; the real one is checked by
`scripts/check_served_vectors.py`."""

import base64
import http.client
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import tomllib

import httpx
import numpy as np
import pytest

from codemem import embedserver
from codemem.config import Config, VectorConfig, config_from_dict
from codemem.embedder import Embedder, FakeEmbedder, OpenAIEmbedder, SentenceTransformerEmbedder
from codemem.embedserver import EmbeddingServer, ModelQueue, local_embedder, served_space
from codemem.indexer import Indexer
from codemem.search import search
from codemem.store import Store

TEXTS = ["def revoke_session(session_id): ...", "def parse_csv(path): ...", "class SessionManager: ..."]


class Recording(FakeEmbedder):
    """The fake model, remembering every call that came through the server, and its thread."""

    def __init__(self, dim=64, delay=0.0):
        super().__init__(dim)
        self.batches: list[list[str]] = []
        self.threads: set[str] = set()
        self.delay = delay

    def embed_texts(self, texts):
        self.batches.append(list(texts))
        self.threads.add(threading.current_thread().name)
        time.sleep(self.delay)
        return super().embed_texts(texts)


class Prompted(FakeEmbedder):
    """A model that puts a prompt before a query and before a document, as the local model does.
    `document` is what it really puts before a document: the server must notice when that is not
    the prefix the model declares."""

    def __init__(self, document="passage: "):
        super().__init__(64)
        self.document = document

    @property
    def prefixes(self):
        return ("query: ", "passage: ")

    def embed_queries(self, texts):
        return self._embed(["query: " + t for t in texts])

    def embed_documents(self, texts):
        return self._embed([self.document + t for t in texts])


@pytest.fixture
def server():
    s = EmbeddingServer(FakeEmbedder(64), port=0).start()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _quick_retries(monkeypatch):
    monkeypatch.setattr(OpenAIEmbedder, "BACKOFF_S", 0.01)


def _client(server, **embedding) -> Config:
    """The config of a codemem that uses the server: the section the server prints, as it is."""
    raw = tomllib.loads(server.client_config())
    raw["embedding"].update(embedding)
    return config_from_dict(raw)


def _post(server, body, **kwargs):
    return httpx.post(f"{server.url}/embeddings", json=body, **kwargs)


def _error(response) -> str:
    return response.json()["error"]["message"]


# ---------------------------------------------------------------- the routes


def test_the_printed_section_is_a_working_client_config(server):
    cfg = _client(server)
    emb = cfg.embedding
    assert (emb.provider, emb.base_url, emb.model, emb.space) == ("openai", server.url, "fake:64", "fake")
    assert (emb.query_prefix, emb.document_prefix, emb.api_key_env) == ("", "", "")
    client, model = OpenAIEmbedder(emb), FakeEmbedder(64)
    assert client.key == "api:fake|fake:64|dims=full|doc=0" and client.dim == 64
    # Bit for bit: JSON carries a float32 exactly, and normalizing a normalized vector changes nothing.
    np.testing.assert_array_equal(client.embed_documents(TEXTS), model.embed_documents(TEXTS))
    np.testing.assert_array_equal(client.embed_queries(TEXTS), model.embed_queries(TEXTS))


def test_embeddings_in_the_openai_shape(server):
    one = _post(server, {"model": "fake:64", "input": TEXTS[0]})
    assert one.status_code == 200 and one.headers["content-type"] == "application/json"
    body = one.json()
    assert body["object"] == "list" and body["model"] == "fake:64"
    assert body["usage"] == {"prompt_tokens": 0, "total_tokens": 0}
    assert [(d["object"], d["index"], len(d["embedding"])) for d in body["data"]] == [("embedding", 0, 64)]

    many = _post(server, {"model": "fake:64", "input": TEXTS}).json()["data"]
    assert [d["index"] for d in many] == [0, 1, 2] and many[0]["embedding"] == body["data"][0]["embedding"]
    # The JSON carries each float32 exactly.
    want = FakeEmbedder(64).embed_texts(TEXTS)
    np.testing.assert_array_equal(np.asarray([d["embedding"] for d in many], dtype=np.float32), want)

    packed = _post(server, {"model": "fake:64", "input": TEXTS, "encoding_format": "base64"}).json()["data"]
    unpacked = np.stack([np.frombuffer(base64.b64decode(d["embedding"]), dtype="<f4") for d in packed])
    np.testing.assert_array_equal(unpacked, want)


def test_dimensions_cut_the_vector_and_normalize_it_again(server):
    text = "revoke session token parse html document users login"
    full = FakeEmbedder(64).embed_texts([text])[0]
    short = np.asarray(
        _post(server, {"model": "fake:64", "input": [text], "dimensions": 32}).json()["data"][0]["embedding"],
        dtype=np.float32,
    )
    assert short.shape == (32,) and np.isclose(np.linalg.norm(short), 1.0)
    np.testing.assert_allclose(short, full[:32] / np.linalg.norm(full[:32]), rtol=0, atol=1e-7)
    assert OpenAIEmbedder(_client(server, dimensions=32).embedding).embed_documents([text]).shape == (1, 32)


def test_models_and_health(server):
    assert httpx.get(server.url.removesuffix("/v1") + "/health").json() == {"status": "ok"}
    models = httpx.get(f"{server.url}/models").json()
    assert models["object"] == "list" and len(models["data"]) == 1
    card = models["data"][0]
    assert (card["id"], card["object"], card["owned_by"]) == ("fake:64", "model", "codemem")
    assert card["codemem"] == {"space": "fake", "dimensions": 64, "query_prefix": "", "document_prefix": ""}


@pytest.mark.parametrize("body, status, message", [
    ({"model": "fake:64"}, 400, "`input` must be a string or a list of strings"),
    ({"model": "fake:64", "input": []}, 400, "not empty"),
    ({"model": "fake:64", "input": [1, 2]}, 400, "`input` must be"),
    ({"model": "another", "input": "x"}, 404, "serves the model 'fake:64', not 'another'"),
    ({"input": "x"}, 404, "not None"),
    ({"model": "fake:64", "input": "x", "dimensions": 65}, 400, "`dimensions` must be a whole number from 1 to 64"),
    ({"model": "fake:64", "input": "x", "dimensions": 0}, 400, "`dimensions`"),
    ({"model": "fake:64", "input": "x", "dimensions": True}, 400, "`dimensions`"),
    ({"model": "fake:64", "input": "x", "encoding_format": "int8"}, 400, "`encoding_format`"),
])
def test_a_bad_request_gets_an_error_that_says_what_is_wrong(server, body, status, message):
    r = _post(server, body)
    assert r.status_code == status and message in _error(r)
    assert r.json()["error"]["type"] == "invalid_request_error"


def test_bad_json_an_unknown_route_and_a_wrong_method(server):
    root = server.url.removesuffix("/v1")
    with httpx.Client() as client:  # one connection: an error must leave it usable, or close it
        r = client.post(f"{server.url}/embeddings", content=b"{not json", headers={"Content-Type": "application/json"})
        assert r.status_code == 400 and _error(r) == "the request body is not JSON"
        r = client.post(f"{server.url}/embeddings", content=b"[1, 2]")
        assert r.status_code == 400 and "must be a JSON object" in _error(r)
        r = client.post(f"{server.url}/rerank", json={"query": "x"})
        assert r.status_code == 404 and "unknown route /v1/rerank" in _error(r) and "POST /v1/embeddings" in _error(r)
        assert client.get(f"{root}/").status_code == 404
        r = client.get(f"{server.url}/embeddings")
        assert r.status_code == 405 and r.headers["allow"] == "POST"
        r = client.post(f"{root}/health", json={})
        assert r.status_code == 405 and r.headers["allow"] == "GET"
        assert client.post(f"{server.url}/embeddings", json={"model": "fake:64", "input": "x"}).status_code == 200


def test_a_request_that_is_too_large_is_refused_unread(server, monkeypatch):
    monkeypatch.setattr(embedserver, "MAX_BODY_BYTES", 300)
    monkeypatch.setattr(embedserver, "MAX_INPUTS", 3)
    r = _post(server, {"model": "fake:64", "input": "x" * 400})
    assert r.status_code == 413 and "the limit is 300" in _error(r)
    assert r.headers["connection"] == "close"  # the body was not read, so nothing can follow it
    r = _post(server, {"model": "fake:64", "input": ["a", "b", "c", "d"]})
    assert r.status_code == 413 and "has 4 texts; the limit is 3" in _error(r)
    assert _post(server, {"model": "fake:64", "input": ["a", "b", "c"]}).status_code == 200

    conn = http.client.HTTPConnection(*server.httpd.server_address[:2], timeout=10)
    conn.putrequest("POST", "/v1/embeddings")  # no Content-Length
    conn.endheaders()
    assert conn.getresponse().status == 411
    conn.close()


def test_a_failing_model_call_fails_its_requests_and_the_server_goes_on(monkeypatch):
    class Failing(FakeEmbedder):
        def embed_texts(self, texts):
            if any("boom" in t for t in texts):
                raise ValueError("no room on the device")
            return super().embed_texts(texts)

    s = EmbeddingServer(Failing(64), port=0).start()
    try:
        r = _post(s, {"model": "fake:64", "input": ["fine", "boom"]})
        assert r.status_code == 500 and _error(r) == "the model failed: ValueError: no room on the device"
        assert r.json()["error"]["type"] == "server_error"
        assert _post(s, {"model": "fake:64", "input": ["fine"]}).status_code == 200
        monkeypatch.setattr(OpenAIEmbedder, "RETRIES", 2)
        with pytest.raises(RuntimeError, match="HTTP 500.*no room on the device"):  # the client shows the reason
            OpenAIEmbedder(_client(s).embedding).embed_documents(["boom"])
    finally:
        s.close()


def test_a_model_that_gives_the_wrong_number_of_vectors_fails_the_request_not_the_server():
    class Short(FakeEmbedder):
        def embed_texts(self, texts):
            return super().embed_texts(texts)[: 2 if "short" in texts else None]

    s = EmbeddingServer(Short(64), port=0).start()
    try:
        r = _post(s, {"model": "fake:64", "input": ["a", "short", "c"]})
        assert r.status_code == 500 and "gave 2 vectors for 3 texts" in _error(r)
        assert _post(s, {"model": "fake:64", "input": ["a", "b", "c"]}).status_code == 200
    finally:
        s.close()


def test_a_server_that_is_down_fails_with_its_address(server, monkeypatch):
    cfg = _client(server)
    server.close()
    monkeypatch.setattr(OpenAIEmbedder, "RETRIES", 2)
    with pytest.raises(RuntimeError, match=f"embedding request to 127.0.0.1:{server.httpd.server_address[1]} failed"):
        OpenAIEmbedder(cfg.embedding).embed_queries(["revoke session"])


# ---------------------------------------------------------------- the key


def test_a_shared_key_is_asked_of_every_request_but_the_health_check(monkeypatch, caplog):
    key = "s3cret-value-7f1b"
    s = EmbeddingServer(FakeEmbedder(64), port=0, key=key).start()
    body = {"model": "fake:64", "input": "x"}
    try:
        with caplog.at_level(logging.DEBUG):
            assert httpx.get(s.url.removesuffix("/v1") + "/health").status_code == 200
            r = _post(s, body)
            assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
            assert r.json()["error"]["code"] == "invalid_api_key" and "CODEMEM_SERVE_KEY" in _error(r)
            assert _post(s, body, headers={"Authorization": "Bearer wrong"}).status_code == 401
            assert _post(s, body, headers={"Authorization": f"Basic {key}"}).status_code == 401
            assert httpx.get(f"{s.url}/models").status_code == 401
            assert _post(s, body, headers={"Authorization": f"Bearer {key}"}).status_code == 200
            assert httpx.get(f"{s.url}/models", headers={"Authorization": f"Bearer {key}"}).status_code == 200

            cfg = _client(s)  # the printed section names the variable, and a client reads the key from it
            assert cfg.embedding.api_key_env == "CODEMEM_SERVE_KEY"
            monkeypatch.setenv("CODEMEM_SERVE_KEY", key)
            assert OpenAIEmbedder(cfg.embedding).embed_documents(TEXTS).shape == (3, 64)
        assert key not in s.client_config() and key not in caplog.text
    finally:
        s.close()


def test_the_key_comes_from_the_environment(monkeypatch, fake_config):
    monkeypatch.setenv("CODEMEM_SERVE_KEY", "from-the-environment")
    s = embedserver.serve(fake_config, port=0)
    try:
        assert s.has_key and s.authorized("Bearer from-the-environment") and not s.authorized(None)
    finally:
        s.close()
    monkeypatch.delenv("CODEMEM_SERVE_KEY")
    s = embedserver.serve(fake_config, port=0)
    try:
        assert not s.has_key and s.authorized(None)
    finally:
        s.close()


# ---------------------------------------------------------------- one model, many clients


def test_several_clients_at_once_each_get_their_own_vectors():
    model = Recording(delay=0.002)
    s = EmbeddingServer(model, port=0, batch_size=4).start()
    model.batches.clear()
    model.threads.clear()
    wrong: list[int] = []

    def client(i: int) -> None:
        texts = [f"client{i} word{j} shared" for j in range(1 + (i * 3) % 11)]
        got = OpenAIEmbedder(_client(s, batch_size=5, max_concurrency=3).embedding).embed_documents(texts)
        if not np.array_equal(got, FakeEmbedder(64).embed_texts(texts)):
            wrong.append(i)

    try:
        threads = [threading.Thread(target=client, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        assert not wrong and not any(t.is_alive() for t in threads)
        assert model.threads == {"codemem-embed"}  # one thread makes every model call
        assert max(len(b) for b in model.batches) <= 4
        assert sum(len(b) for b in model.batches) == sum(1 + (i * 3) % 11 for i in range(12))
    finally:
        s.close()


def test_the_request_with_the_fewest_texts_left_goes_first():
    """A search's query arrives while another client's build is in the model. It goes into the very
    next batch, beside texts of the build."""
    entered, release = threading.Event(), threading.Event()

    class Gated(Recording):
        def embed_texts(self, texts):
            out = super().embed_texts(texts)
            entered.set()
            release.wait(10)
            return out

    model = Gated(8)
    queue = ModelQueue(model, batch_size=4)
    build, got = [f"build text{i}" for i in range(10)], {}
    try:
        first = threading.Thread(target=lambda: got.update(build=queue.embed(build)))
        first.start()
        assert entered.wait(10)  # the build's first four texts are in the model
        second = threading.Thread(target=lambda: got.update(query=queue.embed(["the query"])))
        second.start()
        deadline = time.monotonic() + 10
        while len(queue._waiting) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        release.set()
        first.join(10)
        second.join(10)
        assert model.batches == [build[:4], ["the query", *build[4:7]], build[7:]]
        np.testing.assert_array_equal(got["build"], FakeEmbedder(8).embed_texts(build))
        np.testing.assert_array_equal(got["query"], FakeEmbedder(8).embed_texts(["the query"]))
    finally:
        release.set()
        queue.close()


def test_requests_waiting_when_the_server_stops_are_answered():
    entered, release = threading.Event(), threading.Event()

    class Gated(FakeEmbedder):
        def embed_texts(self, texts):
            entered.set()
            release.wait(10)
            return super().embed_texts(texts)

    queue = ModelQueue(Gated(8), batch_size=1)
    errors: list[Exception] = []

    def ask() -> None:
        try:
            queue.embed(["a", "b"])
        except Exception as e:
            errors.append(e)

    thread = threading.Thread(target=ask)
    thread.start()
    assert entered.wait(10)
    closer = threading.Thread(target=queue.close)
    closer.start()
    time.sleep(0.05)
    release.set()
    thread.join(10)
    closer.join(10)
    assert [type(e) for e in errors] == [embedserver.QueueClosed]
    with pytest.raises(embedserver.QueueClosed):
        queue.embed(["c"])


# ---------------------------------------------------------------- queries and documents


def test_a_models_prompts_reach_the_client_as_prefixes():
    """The wire format has no word for "this text is a query". The server embeds a text as given,
    and the client puts the model's prompt in front: both kinds come out as they do in process."""
    s = EmbeddingServer(Prompted(), port=0).start()
    try:
        cfg = _client(s)
        assert (cfg.embedding.query_prefix, cfg.embedding.document_prefix) == ("query: ", "passage: ")
        client, model = OpenAIEmbedder(cfg.embedding), Prompted()
        np.testing.assert_array_equal(client.embed_queries(TEXTS), model.embed_queries(TEXTS))
        np.testing.assert_array_equal(client.embed_documents(TEXTS), model.embed_documents(TEXTS))
        assert not np.allclose(model.embed_queries(TEXTS), model.embed_documents(TEXTS), atol=1e-3)
    finally:
        s.close()


def test_a_model_whose_prompt_is_more_than_a_prefix_is_not_served():
    with pytest.raises(ValueError, match="cannot be served: a document embedded as its prefix plus the text differs"):
        EmbeddingServer(Prompted(document="something else: "), port=0)

    class NoTextsAsGiven(Embedder):  # what a plugin embedder gives when it defines only the required methods
        model_name = "plain"
        dim = 8

        def embed_documents(self, texts):
            return np.ones((len(texts), 8), dtype=np.float32)

        embed_queries = embed_documents

    with pytest.raises(ValueError, match="plain cannot be served: NoTextsAsGiven does not say"):
        EmbeddingServer(NoTextsAsGiven(), port=0)


def test_the_space_names_the_models_settings_on_the_server():
    spaces = [
        served_space(FakeEmbedder(8)),
        served_space(SentenceTransformerEmbedder("org/model", device="cpu")),
        served_space(SentenceTransformerEmbedder(
            "/models/enc", device="cpu", dtype="float16", max_seq_length=512, version="3fa2b1c9d0e1",
        )),
        served_space(SentenceTransformerEmbedder("org/model", device="cpu", version="run 7|b")),
        served_space(SentenceTransformerEmbedder("org/model", device="cpu", version="a long label " * 6)),
    ]
    assert spaces[:4] == [
        "fake", "st-L1024-float32-cpu", "st-3fa2b1c9d0e1-L512-float16-cpu", "st-run_7_b-L1024-float32-cpu",
    ]
    assert spaces[4].startswith("codemem-") and len(spaces[4]) == 20
    for space in spaces:  # each is a name a config accepts
        assert config_from_dict({"embedding": {"space": space}}).embedding.space == space


def test_the_server_serves_the_local_model_whatever_the_provider_setting_says():
    """The config file that sends clients to the server may be the one the server itself reads."""
    cfg = config_from_dict({
        "vectors": {"code": {"model": "fake:16"}, "usage": {"model": "fake:16"}},
        "embedding": {"provider": "openai", "model": "fake:16", "base_url": "http://127.0.0.1:9/v1"},
    })
    model = local_embedder(cfg)
    assert isinstance(model, FakeEmbedder) and model.dim == 16
    cfg.vectors["usage"] = VectorConfig(model="fake:32")
    with pytest.raises(ValueError, match="serves one model, and the vector types name 2: fake:16, fake:32"):
        local_embedder(cfg)
    cfg.vectors["usage"] = VectorConfig(model="fake:32", enabled=False)
    assert local_embedder(cfg).dim == 16


# ---------------------------------------------------------------- an index through the server


def test_a_build_and_a_search_through_the_server_match_the_model_in_process(server, sample_repo, tmp_path,
                                                                            fake_config):
    cfg = _client(server)
    served, local = Store(tmp_path / "served"), Store(tmp_path / "local")
    try:
        stats = Indexer(sample_repo, served, cfg).update()
        direct = Indexer(sample_repo, local, fake_config).update()
        assert stats.model_embedded == direct.model_embedded and sum(stats.model_embedded.values()) > 0
        assert served.counts() == local.counts()
        assert served.get_meta("vec.code.embedder") == "api:fake|fake:64|dims=full|doc=0"
        for query in ("revoke session", "disabled users stay logged in", "parse a csv file", "logout"):
            through = search(served, query, cfg, k=8, debug=True)
            in_process = search(local, query, fake_config, k=8, debug=True)
            assert through.signals == ["bm25", "code", "usage"]
            assert [(r.key, r.ranks) for r in through.results] == [(r.key, r.ranks) for r in in_process.results]
    finally:
        served.close()
        local.close()


def test_an_index_built_through_one_server_is_searched_through_another(sample_repo, tmp_path):
    """Two servers of one model on two ports, as the host and a container see one server at two
    addresses. The `space` they print is equal, so the index embeds nothing again."""
    first, second = Recording(), Recording()
    a, b = EmbeddingServer(first, port=0).start(), EmbeddingServer(second, port=0).start()
    store = Store(tmp_path / "idx")
    try:
        on_host, in_container = _client(a), _client(b)
        assert on_host.embedding.base_url != in_container.embedding.base_url
        assert on_host.index_settings() == in_container.index_settings()
        built = Indexer(sample_repo, store, on_host).update()
        assert sum(built.model_embedded.values()) > 0
        second.batches.clear()

        again = Indexer(sample_repo, store, in_container).update()
        assert sum(again.embedded.values()) == 0 and second.batches == []
        assert "revoke_session" in [r.qualname for r in search(store, "revoke session", in_container, k=5).results]
        assert second.batches == [["revoke session"]]  # the query alone was embedded at the second address

        without = Indexer(sample_repo, store, _client(b, space="")).update()  # the address names the vectors again
        assert without.model_embedded == built.model_embedded
    finally:
        store.close()
        a.close()
        b.close()


# ---------------------------------------------------------------- the command


def _serve_env(isolated_home, model="fake:16"):
    return {**os.environ, "CODEMEM_MODEL": model, "CODEMEM_HOME": str(isolated_home), "PYTHONUNBUFFERED": "1"}


def test_the_command_prints_what_a_client_needs_and_serves(tmp_path, isolated_home):
    proc = subprocess.Popen(
        [sys.executable, "-m", "codemem", "serve-embeddings", "--port", "0"], cwd=tmp_path,
        env=_serve_env(isolated_home), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    watchdog = threading.Timer(60, proc.kill)
    watchdog.start()
    try:
        printed: list[str] = []
        for line in proc.stdout:
            if not line.strip() and printed:  # the empty line after the section
                break
            printed.append(line)
        assert proc.poll() is None, proc.stderr.read()
        assert printed[0].startswith("# codemem serve-embeddings: fake:16, 16 numbers per vector, at http://127.0.0.1:")
        cfg = config_from_dict(tomllib.loads("".join(printed)))  # comments and all, stdout is the client's TOML
        assert (cfg.embedding.model, cfg.embedding.space, cfg.embedding.api_key_env) == ("fake:16", "fake", "")
        vecs = OpenAIEmbedder(cfg.embedding).embed_documents(TEXTS)
        np.testing.assert_array_equal(vecs, FakeEmbedder(16).embed_documents(TEXTS))
    finally:
        watchdog.cancel()
        proc.terminate()
        proc.wait(10)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows lets a second listener take a port that is in use")
def test_the_command_says_so_when_the_port_is_taken(tmp_path, isolated_home):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        proc = subprocess.run(
            [sys.executable, "-m", "codemem", "serve-embeddings", "--port", str(taken.getsockname()[1])],
            cwd=tmp_path, env=_serve_env(isolated_home), capture_output=True, text=True, timeout=60,
        )
    assert proc.returncode == 2 and proc.stderr.startswith("error: ") and "Traceback" not in proc.stderr
    assert proc.stdout == ""


NO_PYTORCH = """
import sys

# What an environment built without PyTorch and sentence-transformers looks like: importing either
# fails, and importlib finds neither.
sys.modules["torch"] = None
sys.modules["sentence_transformers"] = None

from pathlib import Path

from codemem.cli import main
from codemem.embedder import FakeEmbedder
from codemem.embedserver import EmbeddingServer
from codemem.server import build_server
from codemem.service import CodememService

repo, index_dir = sys.argv[1:]
server = EmbeddingServer(FakeEmbedder(64), port=0).start()
Path(repo, ".codemem.toml").write_text(server.client_config())
assert main(["index", repo, "--index-dir", index_dir]) == 0
assert main(["search", "revoke session", "--repo", repo, "--index-dir", index_dir, "-k", "3"]) == 0
assert main(["status", repo, "--index-dir", index_dir]) == 0

service = CodememService(repo, index_dir=index_dir)  # what `codemem mcp` runs
service.start(watch=False)
service.prewarm()
build_server(service)
found = service.search("disabled users stay logged in", k=5, wait_for_models=False)
assert found.signals == ["bm25", "code", "usage"] and not found.models_loading, found.signals
service.close()
server.close()
assert sys.modules["torch"] is None and sys.modules["sentence_transformers"] is None
print("built and searched without PyTorch")
"""


def test_without_pytorch_a_codemem_builds_and_searches_through_the_server(sample_repo, tmp_path, isolated_home):
    """A client of a served model needs neither package: the CLI, the service behind the MCP server
    and its model warm-up all work with PyTorch and sentence-transformers unimportable."""
    proc = subprocess.run(
        [sys.executable, "-c", NO_PYTORCH, str(sample_repo), str(tmp_path / "idx")], cwd=tmp_path,
        env={**os.environ, "CODEMEM_HOME": str(isolated_home)}, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert proc.stdout.rstrip().endswith("built and searched without PyTorch")
    assert "1. auth/sessions.py:19-20  revoke_session" in proc.stdout
