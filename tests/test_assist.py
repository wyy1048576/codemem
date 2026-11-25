"""An assist endpoint (`[embedding.assist]`, assist.py): a second source that embeds part of a
build's texts beside the local model. Fake models throughout. Where the two must give the same
numbers the endpoint is a real `codemem serve-embeddings`; where it must misbehave it is a small
stub that can be told how."""

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest

from codemem import assist
from codemem.assist import AssistedEmbedder, probe_texts
from codemem.config import AssistConfig, Config, config_from_dict
from codemem.embedder import FakeEmbedder, make_embedder, release_idle
from codemem.embedserver import EmbeddingServer, local_embedder
from codemem.indexer import Indexer
from codemem.render import format_status
from codemem.search import search
from codemem.service import CodememService
from codemem.store import Store, diff_snapshots

PROBE = len(probe_texts(1024))  # texts in one check


def code_texts(n: int) -> list[str]:
    """`n` short code texts, longest first, as the indexer hands them to a model call."""
    texts = [f"def handler_{i}(request):\n    return process(request, {i})" + "  # more" * (i % 11) for i in range(n)]
    return sorted(texts, key=len, reverse=True)


class Slow(FakeEmbedder):
    """The fake model at a set time per text, standing in for a local model on weak hardware."""

    def __init__(self, per_text: float = 0.002, dim: int = 64, clock=time.monotonic):
        super().__init__(dim, clock)
        self.per_text = per_text
        self.threads: set[str] = set()

    def _embed(self, texts):
        self.threads.add(threading.current_thread().name)
        time.sleep(self.per_text * len(texts))
        return super()._embed(texts)


class Stub:
    """An OpenAI-style endpoint that answers with the fake model's vectors and can be told to
    differ from it: `fail` holds status codes to answer with first, `delay` seconds are slept per
    request, `scale` stretches each vector, `prompt` is put before each text on its side, `limit`
    cuts each text after that many words, `salt` makes it another model."""

    def __init__(self, dim: int = 64, **knobs):
        self.dim, self.requests = dim, []
        self.fail: list[int] = []
        self.retry_after: str | None = None
        self.delay, self.scale, self.prompt, self.limit, self.salt = 0.0, 1.0, "", None, ""
        self.__dict__.update(knobs)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"auth": self.headers.get("Authorization"), **body})
                time.sleep(outer.delay)
                if outer.fail:
                    status, out = outer.fail.pop(0), b'{"error": {"message": "not now"}}'
                else:
                    texts = [outer.prompt + t + outer.salt for t in body["input"]]
                    if outer.limit is not None:
                        texts = [" ".join(t.split()[: outer.limit]) for t in texts]
                    vecs = outer.scale * FakeEmbedder(outer.dim).embed_texts(texts)
                    data = [{"index": i, "embedding": v} for i, v in enumerate(vecs.tolist())]
                    status, out = 200, json.dumps({"data": data, "model": body["model"]}).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(out)))
                if status != 200 and outer.retry_after is not None:
                    self.send_header("Retry-After", outer.retry_after)
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def work(self) -> list[dict]:
        """The requests that carried a build's texts: every one but the checks."""
        return [r for r in self.requests if len(r["input"]) != PROBE or "handler_" in r["input"][0]]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.close()


@pytest.fixture
def served():
    s = EmbeddingServer(FakeEmbedder(64), port=0).start()
    yield s
    s.close()


def assisted(url: str, local: FakeEmbedder | None = None, *, batch_size: int = 16, clock=time.monotonic,
             **settings) -> AssistedEmbedder:
    cfg = AssistConfig(base_url=url, model="fake:64", **settings)
    return AssistedEmbedder(local or Slow(), cfg, batch_size=batch_size, clock=clock)


def wait_for(pred, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return False


# ---------------------------------------------------------------- the split


@pytest.mark.parametrize("n", [17, 40, 200])
def test_a_shared_call_gives_the_local_models_vectors_in_order(served, n):
    """Bit for bit: the endpoint is a `serve-embeddings` server of the same deterministic model."""
    texts = code_texts(n)
    emb = assisted(served.url)
    np.testing.assert_array_equal(emb.embed_documents(texts), FakeEmbedder(64).embed_documents(texts))
    status = emb.status()
    assert status["state"] == "sharing" and status["agreement"] == 1.0
    assert emb.shared["local"] + emb.shared["endpoint"] == n and emb.shared["local"] >= 16
    assert emb.key == "fake:64|doc"  # the vectors are the local embedder's, whoever made them


def test_the_endpoint_takes_most_of_a_call_from_a_slow_local_model(served):
    texts = code_texts(200)
    emb = assisted(served.url, Slow(0.004))
    t = time.perf_counter()
    got = emb.embed_documents(texts)
    took = time.perf_counter() - t
    np.testing.assert_array_equal(got, FakeEmbedder(64).embed_documents(texts))
    assert emb.shared["endpoint"] > 100 and took < 0.6  # alone, the local model needs 0.8 s
    assert emb.inner.threads == {threading.current_thread().name}  # the local model stays in the caller's thread


def test_a_call_of_one_local_batch_and_every_query_stay_local(stub):
    emb = assisted(stub.url)
    np.testing.assert_array_equal(emb.embed_documents(code_texts(16)), FakeEmbedder(64).embed_documents(code_texts(16)))
    emb.embed_documents(["warmup"])
    emb.embed_queries(code_texts(40))
    emb.embed_texts(code_texts(40))
    assert stub.requests == [] and emb.status()["state"] == "unchecked"


def test_document_texts_carry_the_local_models_prefix_and_the_providers_own_fields(stub, monkeypatch):
    class Prompted(Slow):
        @property
        def prefixes(self):
            return ("query: ", "passage: ")

        def embed_documents(self, texts):
            return self._embed(["passage: " + t for t in texts])

    monkeypatch.setenv("ASSIST_TEST_KEY", "k-123")
    texts = code_texts(60)
    emb = assisted(stub.url, Prompted(), api_key_env="ASSIST_TEST_KEY", request={"task": "nl2code.passage"})
    np.testing.assert_array_equal(emb.embed_documents(texts), Prompted().embed_documents(texts))
    assert stub.work and all(r["input"][0].startswith("passage: def handler_") for r in stub.work)
    assert all(r["task"] == "nl2code.passage" and r["model"] == "fake:64" and r["auth"] == "Bearer k-123"
               for r in stub.requests)

    stub.prompt = "passage: "  # a provider that puts the prompt in front itself: the client then sends none
    own = assisted(stub.url, Prompted(), document_prefix="")
    np.testing.assert_array_equal(own.embed_documents(texts), Prompted().embed_documents(texts))
    assert own.shared["endpoint"] > 0


# ---------------------------------------------------------------- no mixing without proof


@pytest.mark.parametrize("knobs, local, reason", [
    ({"limit": 1024}, None, "cuts texts at another length than 1024 tokens"),
    ({}, "cut", "cuts texts at another length than 1024 tokens"),
    ({"prompt": "passage: "}, None, "another model, another prompt before the text, or another precision"),
    ({"scale": 3.0}, None, "returns vectors that are not normalized (length 3"),
    ({"salt": " v2"}, None, "gives other vectors than the local model for the same texts"),
    ({"dim": 32}, None, "returns vectors of 32 numbers for fake:64 and the local model's have 64"),
])
def test_an_endpoint_that_differs_gets_no_text_and_says_why(knobs, local, reason, caplog):
    """Another longest text (on either side), a prompt of the provider's own, vectors that are not
    normalized, another model behind the name: each fails the check, and the build goes on alone."""

    class Cut(Slow):  # a local model that reads 1024 words of a text, as the real one reads 1024 tokens
        def _embed(self, texts):
            return super()._embed([" ".join(t.split()[:1024]) for t in texts])

    stub = Stub(**knobs)
    texts = code_texts(60)
    try:
        emb = assisted(stub.url, Cut() if local else Slow())
        with caplog.at_level(logging.WARNING, logger="codemem"):
            got = emb.embed_documents(texts)
            emb.embed_documents(texts)
        np.testing.assert_array_equal(got, FakeEmbedder(64).embed_documents(texts))
        status = emb.status()
        assert status["state"] == "refused" and reason in status["reason"]
        assert emb.shared["endpoint"] == 0 and stub.work == [] and len(stub.requests) == 1  # the one check
        said = [r.getMessage() for r in caplog.records if "assist endpoint is not used" in r.getMessage()]
        assert len(said) == 1 and reason in said[0]
        assert "\n" not in status["reason"]
    finally:
        stub.close()


def test_what_the_same_model_gives_on_other_hardware_passes_and_what_changes_rankings_does_not():
    """The bar, at the numbers it was set from: 0.999996 is the same model on a CPU in float32 and
    a GPU in float16; 0.99978 is bfloat16 against float16, which changed 2 of 20 top-10 lists."""
    rng = np.random.default_rng(0)
    local = rng.standard_normal((7, 896)).astype(np.float32)
    local /= np.linalg.norm(local, axis=1, keepdims=True)

    def at(cosine: float) -> np.ndarray:
        other = rng.standard_normal(local.shape).astype(np.float32)
        other -= np.sum(other * local, axis=1, keepdims=True) * local
        other /= np.linalg.norm(other, axis=1, keepdims=True)
        return (cosine * local + np.sqrt(1 - cosine**2) * other).astype(np.float32)

    labels = [label for label, _ in probe_texts(1024)]
    agreement, reason = assist.difference(local, at(0.999996), labels, "host", "m", 1024)
    assert reason is None and agreement == pytest.approx(0.999996, abs=2e-6)
    agreement, reason = assist.difference(local, at(0.99978), labels, "host", "m", 1024)
    assert agreement == pytest.approx(0.99978, abs=2e-6) and "another precision" in reason
    assert 0.99978 < assist.SAME_VECTORS < 0.999996


def test_the_probe_holds_a_text_longer_than_the_model_reads():
    for limit in (256, 1024, 8192):
        (label, text), words = probe_texts(limit)[-1], None
        words = text.split()
        assert len(words) > limit and label == "a text longer than the model reads"  # a token is a word at most
        assert set(words[:50]) != set(words[-50:])  # its end is not its start again


def test_a_local_embedder_that_does_not_name_its_prefix_gets_no_help(stub):
    """A plugin embedder need not say what it puts before a document; the endpoint's texts could
    then not be given the same, so it is not used, unless the config names the prefix."""

    class Plain(Slow):
        @property
        def prefixes(self):
            raise NotImplementedError("Plain does not say what it puts before a query or a document")

    emb = assisted(stub.url, Plain())
    emb.embed_documents(code_texts(40))
    status = emb.status()
    assert status["state"] == "refused" and "Plain does not say what it puts before" in status["reason"]
    assert stub.requests == []
    named = assisted(stub.url, Plain(), document_prefix="")
    named.embed_documents(code_texts(40))
    assert named.status()["state"] == "sharing"


def test_the_local_half_of_a_check_is_kept_between_processes(stub):
    """The local model's probe vectors belong to its key: a later process asks the endpoint only."""
    first = assisted(stub.url)
    first.embed_documents(code_texts(40))
    assert PROBE in first.inner.calls and first.status()["state"] == "sharing"
    later = assisted(stub.url)  # as a new process: nothing in memory
    later.embed_documents(code_texts(40))
    assert PROBE not in later.inner.calls and later.status()["state"] == "sharing"
    checks = [r for r in stub.requests if r not in stub.work]
    assert len(checks) == 2 and all(len(r["input"]) == PROBE for r in checks)  # the endpoint is asked each time

    other_model = assisted(stub.url, Slow(dim=32))  # another key: its own probe vectors, and a refusal
    other_model.embed_documents(code_texts(40))
    assert PROBE in other_model.inner.calls and other_model.status()["state"] == "refused"


# ---------------------------------------------------------------- an endpoint that fails, is slow, or says "later"


def test_an_endpoint_that_fails_gives_its_texts_back_and_rests(stub, caplog):
    clock = [1000.0]
    texts = code_texts(120)
    emb = assisted(stub.url, clock=lambda: clock[0])
    emb.embed_documents(texts)
    assert emb.status()["state"] == "sharing" and emb.shared["endpoint"] > 0
    shared, asked = emb.shared["endpoint"], len(stub.requests)

    stub.fail = [503] * 50
    with caplog.at_level(logging.WARNING, logger="codemem"):
        got = emb.embed_documents(texts)
    np.testing.assert_array_equal(got, FakeEmbedder(64).embed_documents(texts))  # within the same call
    status = emb.status()
    assert status["state"] == "resting" and "HTTP 503" in status["reason"] and "tried again in 1 s" in status["reason"]
    said = [r for r in caplog.records if "not used for now" in r.getMessage()]
    assert len(said) == 1  # once, however many requests failed
    failed = len(stub.requests) - asked
    assert 1 <= failed <= 4

    emb.embed_documents(texts)  # resting: not asked at all
    assert len(stub.requests) == asked + failed and emb.shared["endpoint"] == shared

    stub.fail = []
    clock[0] += 1.5  # the rest is over: its vectors are compared again before it gets work
    emb.embed_documents(texts)
    assert wait_for(lambda: emb.status()["state"] == "sharing")
    emb.embed_documents(texts)
    assert emb.shared["endpoint"] > shared
    checks = [r for r in stub.requests if r not in stub.work]
    assert len(checks) == 2


def test_each_failure_in_a_row_doubles_the_rest(stub):
    clock = [0.0]
    emb = assisted(stub.url, clock=lambda: clock[0])
    emb.embed_documents(code_texts(60))
    rests = []
    for _ in range(3):
        stub.fail = [500] * 50
        clock[0] += 1000  # any rest is over
        emb.embed_documents(code_texts(60))  # a check, which fails
        assert wait_for(lambda: emb.status()["state"] == "resting")
        rests.append(emb.status()["reason"].rsplit("in ", 1)[1])
    assert rests == ["1 s", "2 s", "4 s"]


def test_a_rate_limit_rests_the_endpoint_for_as_long_as_it_asks_and_needs_no_new_check(stub):
    clock = [0.0]
    texts = code_texts(120)
    emb = assisted(stub.url, clock=lambda: clock[0])
    emb.embed_documents(texts)
    stub.fail, stub.retry_after = [429], "7"
    np.testing.assert_array_equal(emb.embed_documents(texts), FakeEmbedder(64).embed_documents(texts))
    status = emb.status()
    assert status["state"] == "resting" and "HTTP 429" in status["reason"] and "tried again in 7 s" in status["reason"]
    asked = len(stub.requests)
    clock[0] += 6
    emb.embed_documents(texts)
    assert len(stub.requests) == asked  # still resting
    clock[0] += 2
    shared = emb.shared["endpoint"]
    emb.embed_documents(texts)
    assert emb.shared["endpoint"] > shared and emb.status()["state"] == "sharing"
    assert len([r for r in stub.requests if r not in stub.work]) == 1  # the first check was the only one


def test_a_slow_endpoint_gets_little_and_a_hung_one_does_not_hold_the_call(stub):
    texts = code_texts(200)
    emb = assisted(stub.url, Slow(0.001), timeout_s=30)
    emb.embed_documents(texts)  # the check, and a first measure of both
    stub.delay = 0.4  # each request now takes far longer than the local model needs for all of it
    for _ in range(2):  # the measured speed follows
        t = time.perf_counter()
        got = emb.embed_documents(texts)
        took = time.perf_counter() - t
    np.testing.assert_array_equal(got, FakeEmbedder(64).embed_documents(texts))
    before = emb.shared["endpoint"]
    emb.embed_documents(texts)
    assert emb.shared["endpoint"] == before  # it is offered nothing more
    assert took < 0.35  # the local model alone needs 0.2 s; a request would take 0.4 s

    stub.delay = 5.0  # an endpoint that hangs
    fresh = assisted(stub.url, Slow(0.001), timeout_s=30)
    fresh.endpoint.speed.add(10**9, 1.0)  # believed fast, as after a good check
    fresh.endpoint.accept(1.0, 64, "")
    t = time.perf_counter()
    got = fresh.embed_documents(texts)
    assert time.perf_counter() - t < 2.0  # not 5 s: the local model took the late requests' texts back
    np.testing.assert_array_equal(got, FakeEmbedder(64).embed_documents(texts))


def test_a_check_that_gets_no_answer_holds_no_call_up(stub, monkeypatch):
    monkeypatch.setattr(assist, "FIRST_CHECK_WAIT_S", 0.05)
    stub.delay = 0.6
    texts = code_texts(60)
    emb = assisted(stub.url, Slow(0.001))
    t = time.perf_counter()
    got = emb.embed_documents(texts)
    assert time.perf_counter() - t < 0.5 and emb.status()["state"] == "checking"
    np.testing.assert_array_equal(got, FakeEmbedder(64).embed_documents(texts))
    stub.delay = 0.0
    assert wait_for(lambda: emb.status()["state"] == "sharing")
    emb.embed_documents(code_texts(200))
    assert emb.shared["endpoint"] > 0


def test_an_endpoint_that_cannot_be_reached_or_refuses_the_key(monkeypatch):
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    texts = code_texts(40)
    down = assisted(f"http://127.0.0.1:{port}/v1")
    np.testing.assert_array_equal(down.embed_documents(texts), FakeEmbedder(64).embed_documents(texts))
    assert wait_for(lambda: down.status()["state"] == "resting")
    assert f"embedding request to 127.0.0.1:{port} failed" in down.status()["reason"]

    monkeypatch.delenv("ASSIST_TEST_KEY", raising=False)
    no_key = assisted(f"http://127.0.0.1:{port}/v1", api_key_env="ASSIST_TEST_KEY")
    no_key.embed_documents(texts)
    assert wait_for(lambda: no_key.status()["state"] == "refused")
    assert "[embedding.assist] api_key_env is 'ASSIST_TEST_KEY'" in no_key.status()["reason"]


# ---------------------------------------------------------------- what callers rely on


def test_the_idle_unload_and_the_trim_still_work(stub):
    clock = [1000.0]
    local = Slow(0.002, clock=lambda: clock[0])
    emb = assisted(stub.url, local, clock=lambda: clock[0])
    entered, release = threading.Event(), threading.Event()
    plain_embed = local._embed

    def gated(texts):
        entered.set()
        release.wait(10)
        return plain_embed(texts)

    emb.embed_documents(code_texts(60))  # the check is done
    local._embed = gated
    call = threading.Thread(target=lambda: emb.embed_documents(code_texts(60)))
    call.start()
    assert entered.wait(10)
    clock[0] += 3600
    assert not emb.unload(60) and not emb.trim(5) and local.ready  # a shared call is running: one use, start to end
    release.set()
    call.join(10)
    local._embed = plain_embed

    assert not emb.unload(300) and emb.ready  # used a moment ago
    clock[0] += 6
    assert emb.trim(5) and local.trims == 1 and not emb.trim(5)
    clock[0] += 300
    release_idle(emb, 5)  # what the service's writer and the embedding server do in a quiet moment
    assert not emb.ready and not local.ready
    np.testing.assert_array_equal(emb.embed_documents(code_texts(60)), FakeEmbedder(64).embed_documents(code_texts(60)))
    assert local.loads == 1 and emb.ready


def test_without_an_assist_nothing_is_wrapped_and_nothing_is_sent(sample_repo, tmp_path, fake_config, monkeypatch):
    def no_network(self, *args, **kwargs):
        raise AssertionError("a connection was opened")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    assert not fake_config.embedding.assist.active and type(make_embedder("fake:64", fake_config)) is FakeEmbedder
    store = Store(tmp_path / "idx")
    try:
        stats = Indexer(sample_repo, store, fake_config).update()
        assert sum(stats.model_embedded.values()) > 0
        assert search(store, "revoke session", fake_config, k=3).results
    finally:
        store.close()


def test_a_build_with_the_assist_equals_a_build_without_it(served, sample_repo, tmp_path, fake_config):
    """The same repo built twice, once with the endpoint sharing the work: equal indexes, down to
    the bytes of every vector, under the local embedder's key."""
    shared = assisted(served.url, Slow(0.003), batch_size=4)
    with_assist, alone = Store(tmp_path / "with"), Store(tmp_path / "alone")
    fake_config.vector_cache = "off"
    try:
        Indexer(sample_repo, with_assist, fake_config, embedder_factory=lambda spec, cfg: shared).update()
        Indexer(sample_repo, alone, fake_config).update()
        assert shared.shared["endpoint"] > 0 and shared.shared["local"] > 0
        assert diff_snapshots(with_assist.snapshot(), alone.snapshot()) == []
        assert with_assist.get_meta("vec.code.embedder") == alone.get_meta("vec.code.embedder") == "fake:64|doc"

        def vectors(store):
            rows = store.conn.execute(
                "SELECT c.key, v.vec_type, v.part, v.data FROM vectors v JOIN chunks c USING (chunk_id)"
            )
            return {(r[0], r[1], r[2]): bytes(r[3]) for r in rows}

        assert vectors(with_assist) == vectors(alone) and len(vectors(alone)) == 33
        assert fake_config.index_settings() == Config(vectors=fake_config.vectors).index_settings()
    finally:
        with_assist.close()
        alone.close()


# ---------------------------------------------------------------- settings, status, two processes


def test_the_settings():
    cfg = config_from_dict({"embedding": {"assist": {
        "base_url": "http://gpu-box:8791/v1", "model": "jinaai/jina-code-embeddings-0.5b",
        "api_key_env": "CODEMEM_SERVE_KEY", "batch_size": 8, "max_concurrency": 2, "timeout_s": 5,
        "document_prefix": "", "request": {"task": "nl2code.passage"},
    }}})
    helper = cfg.embedding.assist
    assert helper.active and (helper.batch_size, helper.max_concurrency, helper.timeout_s) == (8, 2, 5)
    assert helper.document_prefix == "" and helper.request == {"task": "nl2code.passage"}
    assert cfg.index_settings() == Config().index_settings()  # who computes a vector is no part of an index
    assert not Config().embedding.assist.active
    assert not config_from_dict({"embedding": {"assist": {"base_url": ""}}}).embedding.assist.active  # switched off


@pytest.mark.parametrize("embedding, message", [
    ({"assist": {"base_url": "http://x/v1"}}, "needs model"),
    ({"assist": {"base_url": "http://x/v1", "model": "m", "space": "s"}}, "unknown \\[embedding.assist\\] settings"),
    ({"assist": {"base_url": "http://x/v1", "model": "m", "batch_size": 0}}, "must be 1 or more"),
    ({"assist": {"base_url": "http://x/v1", "model": "m", "request": {"input": ["x"]}}}, "model and input are not"),
    ({"provider": "openai", "model": "m", "base_url": "http://y/v1",
      "assist": {"base_url": "http://x/v1", "model": "m"}}, "needs \\[embedding\\] provider = \"local\""),
])
def test_bad_assist_settings_are_refused(embedding, message):
    with pytest.raises(ValueError, match=message):
        config_from_dict({"embedding": embedding})


def test_make_embedder_wraps_the_cached_local_embedder_and_a_server_serves_it_bare(stub):
    plain = config_from_dict({"vectors": {"code": {"model": "fake:64"}, "usage": {"model": "fake:64"}}})
    with_assist = config_from_dict({
        "vectors": {"code": {"model": "fake:64"}, "usage": {"model": "fake:64"}},
        "embedding": {"assist": {"base_url": stub.url, "model": "fake:64"}},
    })
    emb = make_embedder(with_assist.vectors["code"], with_assist)
    assert isinstance(emb, AssistedEmbedder) and emb is make_embedder("fake:64", with_assist)
    assert emb.inner is make_embedder("fake:64", plain) and emb.key == emb.inner.key
    assert local_embedder(with_assist) is emb.inner  # a server is the model: it shares with nobody
    api = config_from_dict({"embedding": {"provider": "openai", "model": "m", "base_url": stub.url}})
    assert type(make_embedder("anything", api)).__name__ == "OpenAIEmbedder"


def test_status_says_where_code_goes_and_what_the_endpoint_does(stub, sample_repo, tmp_path, monkeypatch):
    (sample_repo / ".codemem.toml").write_text(
        f'[embedding.assist]\nbase_url = "{stub.url}"\nmodel = "fake:64"\n', encoding="utf-8"
    )
    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    host = stub.url.removeprefix("http://").removesuffix("/v1")
    svc = CodememService(sample_repo, index_dir=tmp_path / "idx")
    try:
        text = format_status(svc.status())
        assert f"embeddings: local, with fake:64 at {host} for a share of a build's texts (code is sent there" in text
        assert "assist: not checked yet" in text
        assert svc.update() is not None
        info = svc.status()
        assert info["assist"]["state"] == "sharing" and info["assist"]["host"] == host
        assert "assist: its vectors agree with the local model's (cosine 1.000000 at worst)" in format_status(info)
    finally:
        svc.close()

    monkeypatch.setattr("codemem.embedder._CACHE", {})  # as `codemem status` in a process of its own
    later = CodememService(sample_repo, index_dir=tmp_path / "idx")
    try:
        assert "assist: its vectors agree with the local model's" in format_status(later.status())
        assert len(stub.requests) == len(stub.requests)  # reading the status asks the endpoint nothing
        asked = len(stub.requests)
        later.status()
        assert len(stub.requests) == asked
    finally:
        later.close()

    stub.salt = " other weights"  # the endpoint now serves another model under the name
    monkeypatch.setattr("codemem.embedder._CACHE", {})
    (sample_repo / "auth" / "more.py").write_text(
        "\n\n".join(f"def extra_{i}(x):\n    return x + {i}" for i in range(40)), encoding="utf-8"
    )
    changed = CodememService(sample_repo, index_dir=tmp_path / "idx")
    try:
        assert changed.update() is not None
        text = format_status(changed.status())
        assert "assist: not used: " in text and "gives other vectors than the local model" in text
    finally:
        changed.close()


def test_a_build_through_the_config_with_a_server_in_another_process(sample_repo, tmp_path, isolated_home):
    """`codemem serve-embeddings` in its own process as the endpoint, named in the repo's config:
    the index equals one built without it."""
    env = {**os.environ, "CODEMEM_MODEL": "fake:64", "CODEMEM_HOME": str(isolated_home), "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "codemem", "serve-embeddings", "--port", "0"], cwd=tmp_path, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    watchdog = threading.Timer(60, proc.kill)
    watchdog.start()
    try:
        printed: list[str] = []
        for line in proc.stdout:
            if not line.strip() and printed:
                break
            printed.append(line)
        assert proc.poll() is None, proc.stderr.read()
        server = tomllib.loads("".join(printed))["embedding"]
        fake = {"code": {"model": "fake:64"}, "usage": {"model": "fake:64"}}
        on = config_from_dict({"batch_size": 4, "vectors": fake, "vector_cache": "off", "embedding": {
            "assist": {"base_url": server["base_url"], "model": server["model"]},
        }})
        off = config_from_dict({"batch_size": 4, "vectors": fake, "vector_cache": "off"})
        with_assist, alone = Store(tmp_path / "with"), Store(tmp_path / "alone")
        try:
            Indexer(sample_repo, with_assist, on).update()
            Indexer(sample_repo, alone, off).update()
            assert diff_snapshots(with_assist.snapshot(), alone.snapshot()) == []
            emb = make_embedder("fake:64", on)
            assert emb.status()["state"] == "sharing" and emb.status()["agreement"] == 1.0
            hits = [r.qualname for r in search(with_assist, "revoke session", on, k=5).results]
            assert hits == [r.qualname for r in search(alone, "revoke session", off, k=5).results]
        finally:
            with_assist.close()
            alone.close()
    finally:
        watchdog.cancel()
        proc.terminate()
        proc.wait(10)
