"""An assist endpoint (`[embedding.assist]`, assist.py): a second source that embeds part of a
build's texts beside the local model. Fake models throughout. Where the two must give the same
numbers the endpoint is a real `codemem serve-embeddings`; where it must misbehave it is a small
stub that can be told how."""

import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import tomllib
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.machinery import ModuleSpec

import numpy as np
import pytest

from codemem import assist
from codemem.assist import AssistedEmbedder, probe_texts
from codemem.cli import main
from codemem.config import AssistConfig, Config, config_from_dict
from codemem.embedder import (
    DOCUMENT_PROMPT, QUERY_PROMPT, Embedder, FakeEmbedder, SentenceTransformerEmbedder, make_embedder, release_idle,
)
from codemem.embedserver import EmbeddingServer, local_embedder
from codemem.indexer import Indexer
from codemem.render import assist_line, format_status
from codemem.search import search
from codemem.service import CodememService
from codemem.store import Store, diff_snapshots

PROBE = len(probe_texts(FakeEmbedder(64), 1024))  # texts in one check


def tokens(text: str) -> list[str]:
    """What stands in for a model's tokens here: a run of letters, digits and underscores, or one
    other character."""
    return re.findall(r"\w+|[^\w\s]", text)


def read(text: str, limit: int | None) -> str:
    """What a model that reads `limit` tokens reads of a text: all of it, or its first `limit` tokens."""
    kept = tokens(text)
    return text if limit is None or len(kept) <= limit else " ".join(kept[:limit])


def long_text(i: int, lines: int = 80) -> str:
    """A text of ten tokens a line whose end is about other things than its start."""
    return "\n".join(f"row_{i}_{j} = load(table_{j}, key={i})" for j in range(lines))


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


class Reader(Slow):
    """A local model that reads `limit` tokens of a text, and says which texts that cuts."""

    def __init__(self, limit: int, per_text: float = 0.002):
        super().__init__(per_text)
        self.limit = limit

    def cut(self, texts):
        return [len(tokens(t)) > self.limit for t in texts]

    def _embed(self, texts):
        return super()._embed([read(t, self.limit) for t in texts])


class _Tokenizer:
    """Stands in for a model's tokenizer: `tokens` of a text between two tokens of its own. Like
    the real ones, it keeps whether it cuts as a setting that each call sets."""

    def __init__(self):
        self.cuts, self.calls = True, []

    def num_special_tokens_to_add(self) -> int:
        return 2

    def __call__(self, texts, truncation=True, padding=True, max_length=None, verbose=True):
        self.cuts = bool(truncation)
        self.calls.append(list(texts))
        ids = [[0, *range(1, len(tokens(t)) + 1), 0] for t in texts]
        return {"input_ids": [row[:max_length] if truncation and max_length else row for row in ids]}


class _Model:
    """Stands in for sentence_transformers.SentenceTransformer: it reads the prompt and the text
    as one string, `max_seq_length` tokens of it with the tokenizer's two, and gives the fake
    model's vector for what it read."""

    prompts = {QUERY_PROMPT: "Find code:\n", DOCUMENT_PROMPT: "Code:\n"}
    max_seq_length = 32768
    per_text = 0.0  # seconds a text takes

    def __init__(self, name, device=None):
        self.tokenizer = _Tokenizer()

    def to(self, target):
        return self

    def get_sentence_embedding_dimension(self) -> int:
        return 64

    def encode(self, texts, prompt_name=None, prompt="", **kwargs):
        before = self.prompts[prompt_name] if prompt_name else prompt
        time.sleep(self.per_text * len(texts))
        return FakeEmbedder(64).embed_texts([read(before + t, self.max_seq_length - 2) for t in texts])


@pytest.fixture
def reading_model(monkeypatch):
    """The stand-in model in place of sentence-transformers, for the real local embedder to load."""
    pytest.importorskip("torch")  # the embedder resolves its device and converts the weights through it
    module = types.SimpleNamespace(SentenceTransformer=_Model, __spec__=ModuleSpec("sentence_transformers", None))
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    return _Model


WORDS = [a + b for a in "bdfgklmnprst" for b in ("alo", "ime", "onu", "ura")]  # 48 words, a token each


def words(n: int, start: int = 0) -> str:
    """A text of `n` tokens; another `start` gives another text."""
    return " ".join(WORDS[(start + j) % len(WORDS)] for j in range(n))


class Stub:
    """An OpenAI-style endpoint that answers with the fake model's vectors and can be told to
    differ from it: `fail` holds status codes to answer with first, `delay` seconds are slept per
    request, `scale` stretches each vector, `prompt` is put before each text on its side, `limit`
    cuts each text after that many tokens, `salt` makes it another model."""

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
                    status, out = outer.fail.pop(0), b'{"error": {\n  "message": "not now"}}'
                else:
                    texts = [read(outer.prompt + t + outer.salt, outer.limit) for t in body["input"]]
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
        """The requests that carried a build's texts: every one but the checks, which end with
        the probe's long text."""
        return [r for r in self.requests if "session_0 = open_session(" not in r["input"][-1]]

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


@pytest.mark.parametrize("knobs, limit, reason", [
    ({"limit": 200}, None, "another one for a long text"),
    ({"limit": 200}, 1024, "another one for a text as long as the local model reads"),
    ({"prompt": "passage: "}, None, "another model, another prompt before the text, or another precision"),
    ({"salt": " v2"}, None, "gives other vectors than the local model for the same texts"),
    ({"dim": 32}, None, "returns vectors of 32 numbers for fake:64 and the local model's have 64"),
    ({"scale": 0.0}, None, "a vector for fake:64 that cannot be scaled to length 1"),
    ({"scale": float("nan")}, None, "a vector for fake:64 that cannot be scaled to length 1"),
])
def test_an_endpoint_that_differs_gets_no_text_and_says_why(knobs, limit, reason, caplog):
    """An endpoint that cuts a text earlier than the local model (which reads every text whole, or
    1024 tokens of it), a prompt of the provider's own, another model behind the name, vectors
    that cannot be scaled: each fails the check, and the build goes on alone."""
    stub = Stub(**knobs)
    texts = code_texts(60)
    try:
        emb = assisted(stub.url, Reader(limit) if limit else Slow())
        with caplog.at_level(logging.WARNING, logger="codemem"):
            got = emb.embed_documents(texts)
            emb.embed_documents(texts)
        np.testing.assert_array_equal(got, FakeEmbedder(64).embed_documents(texts))
        status = emb.status()
        assert status["state"] == "refused" and reason in status["reason"]
        assert ("it probably cuts a text earlier than the local model does" in status["reason"]) == ("limit" in knobs)
        assert emb.shared["endpoint"] == 0 and stub.work == [] and len(stub.requests) == 1  # the one check
        said = [r.getMessage() for r in caplog.records if "assist endpoint is not used" in r.getMessage()]
        assert len(said) == 1 and reason in said[0]
        assert "\n" not in status["reason"]
    finally:
        stub.close()


@pytest.mark.parametrize("knobs, limit", [
    ({"scale": 3.0}, None),  # vectors that are not normalized
    ({}, 300),  # an endpoint that reads further than the local model
    ({"limit": 300}, 300),  # one that cuts where the local model does
])
def test_an_endpoint_whose_vectors_only_need_scaling_or_that_reads_as_far_shares(knobs, limit, caplog):
    """Its vectors are scaled to length 1 before they are compared and before they are stored. And
    however far it reads, it is never handed a text the local model cuts, so it is compared on
    texts the local model reads whole."""
    stub = Stub(**knobs)
    long = [long_text(i) for i in range(6)]  # 800 tokens each
    texts = long + code_texts(60)
    try:
        emb = assisted(stub.url, Reader(limit) if limit else Slow())
        with caplog.at_level(logging.DEBUG, logger="codemem.assist"):
            got = emb.embed_documents(texts)
        said = [r.getMessage() for r in caplog.records if r.getMessage().startswith("an embedding call of 66 texts")]
        assert len(said) == 1 and re.fullmatch(
            rf".* s: the local model embedded {emb.shared['local']} \({6 if limit else 0} are longer than it reads\), "
            rf"127\.0\.0\.1:\d+ embedded {emb.shared['endpoint']}", said[0],
        )
        alone = (Reader(limit, 0) if limit else FakeEmbedder(64)).embed_documents(texts)
        if "scale" in knobs:
            np.testing.assert_allclose(got, alone, atol=1e-6)
            np.testing.assert_allclose(np.linalg.norm(got, axis=1), 1.0, atol=1e-6)
        else:
            np.testing.assert_array_equal(got, alone)
        assert emb.status()["state"] == "sharing" and emb.shared["endpoint"] > 0
        sent = [t for r in stub.work for t in r["input"]]
        assert sent and len(stub.requests) == len(stub.work) + 1
        if limit:
            assert emb.shared["cut"] == 6 and not any(len(tokens(t)) > limit for t in sent)
            assert "(6 of those are longer than the local model reads and stay with it)" in assist_line(emb.status())
            assert not np.allclose(got[:6], FakeEmbedder(64).embed_documents(long), atol=1e-3)  # read whole, they differ
        else:
            assert emb.shared["cut"] == 0
    finally:
        stub.close()


def test_a_call_of_texts_the_local_model_cuts_is_not_shared_at_all(stub):
    emb = assisted(stub.url, Reader(300))
    texts = [long_text(i) for i in range(40)]
    np.testing.assert_array_equal(emb.embed_documents(texts), Reader(300, 0).embed_documents(texts))
    assert emb.status()["state"] == "sharing" and stub.work == [] and emb.shared == {"local": 0, "endpoint": 0, "cut": 0}


@pytest.mark.parametrize("prompt, most", [("Code:\n", 28), ("", 30), ("Candidate code snippet:\n", 26)])
def test_the_local_model_says_a_text_is_cut_exactly_when_it_cuts_it(reading_model, monkeypatch, prompt, most):
    """At 32 tokens, of which the tokenizer's own are 2 and the prompt's 2, 0 or 4: a text that
    fills the rest to the token is read whole, and one token more is cut."""
    monkeypatch.setattr(reading_model, "prompts", {QUERY_PROMPT: "", DOCUMENT_PROMPT: prompt})
    emb = SentenceTransformerEmbedder("stub-model", device="cpu", max_seq_length=32)
    texts = [words(n) for n in (most - 1, most, most + 1, most + 2)]
    assert emb.cut(texts) == [False, False, True, True]
    read_whole = FakeEmbedder(64).embed_texts([prompt + t for t in texts])  # by a source that reads every text whole
    same = [np.array_equal(mine, whole) for mine, whole in zip(emb.embed_documents(texts), read_whole)]
    assert same == [True, True, False, False]  # the model cuts exactly the texts it says it cuts
    model = emb.model
    assert model.tokenizer.calls == [] and model.tokenizer.cuts  # counted on a copy: the model's own still cuts
    assert emb.unload() and emb.cut(texts) == [False, False, True, True]  # and again after the model was dropped


def test_a_short_plain_text_is_known_to_be_read_whole_without_tokenizing_it(reading_model):
    """At 1024 tokens, less the tokenizer's 2, the 6 characters of the prompt and 8 to spare: a
    plain ASCII text of 1008 characters cannot be more tokens than the model reads."""
    emb = SentenceTransformerEmbedder("stub-model", device="cpu", max_seq_length=1024)
    assert emb.cut(["(" * 1008, "x" * 1008, ""]) == [False, False, False] and emb._counter.calls == []
    assert emb.cut(["(" * 1009, "é"]) == [False, False]
    assert emb._counter.calls == [["Code:\n" + "(" * 1009, "Code:\né"]]  # longer, or not plain ASCII: counted
    assert emb.cut(["(" * 1020, "(" * 1021]) == [False, True]  # with the prompt's 2 and the tokenizer's 2: 1024 and 1025
    assert emb.cut([]) == []


def test_a_text_at_the_local_limit_may_go_to_the_endpoint_and_one_token_more_stays_local(reading_model, stub, monkeypatch):
    """The real local embedder over the stand-in model, at 32 tokens, and an endpoint that reads
    every text whole: texts of exactly 32 tokens with the prompt and the tokenizer's own are
    shared, texts of 33 are not, and the vectors are the local model's."""
    monkeypatch.setattr(reading_model, "per_text", 0.003)

    def local():
        return SentenceTransformerEmbedder("stub-model", device="cpu", batch_size=4, max_seq_length=32)

    at, over = [words(28, k) for k in range(30)], [words(29, k) for k in range(10)]
    texts = over + at
    emb = AssistedEmbedder(local(), AssistConfig(base_url=stub.url, model="fake:64"), batch_size=4, max_seq_length=32)
    got = emb.embed_documents(texts)
    np.testing.assert_array_equal(got, local().embed_documents(texts))
    assert emb.status()["state"] == "sharing" and emb.shared["endpoint"] > 0 and emb.shared["cut"] == 10
    sent = {t for r in stub.work for t in r["input"]}
    assert sent and sent <= {"Code:\n" + t for t in at}  # with the local model's prompt, and none of the longer ones
    read_whole = FakeEmbedder(64).embed_texts(["Code:\n" + t for t in texts])
    same = [np.array_equal(mine, whole) for mine, whole in zip(got, read_whole)]
    assert same == [False] * 10 + [True] * 30  # the endpoint would have given other vectors for the ten
    check = [r for r in stub.requests if r not in stub.work]
    assert len(check) == 1 and len(tokens(check[0]["input"][-1])) == 30  # the probe's last text: 32 with the tokenizer's 2
    assert all(len(tokens(t)) <= 30 for t in check[0]["input"])


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

    probes = probe_texts(Reader(1024), 1024)
    found = assist.difference(local, at(0.999996), probes, "host", "m")
    assert found["reason"] is None and found["agreement"] == pytest.approx(0.999996, abs=2e-6)
    found = assist.difference(local, at(0.99978), probes, "host", "m")
    assert found["agreement"] == pytest.approx(0.99978, abs=2e-6) and "another precision" in found["reason"]
    assert 0.99978 < assist.SAME_VECTORS < 0.999996

    found = assist.difference(local, 27.5 * at(0.999996), probes, "host", "m")  # the same vectors, not normalized
    assert found["reason"] is None and found["agreement"] == pytest.approx(0.999996, abs=2e-6)
    assert [row["probe"] for row in found["probes"]] == [label for label, _ in probes]
    for row, (_, text) in zip(found["probes"], probes):
        assert row["characters"] == len(text) and row["cosine"] == pytest.approx(0.999996, abs=2e-6)
        assert row["local_length"] == pytest.approx(1.0, abs=1e-6) and row["endpoint_length"] == pytest.approx(27.5, abs=1e-4)

    last = local.copy()
    last[-1] = at(0.9)[-1]  # only the text at the local model's limit differs
    found = assist.difference(local, last, probes, "host", "m")
    assert found["agreement"] == pytest.approx(0.9, abs=1e-5)
    assert "another one for a text as long as the local model reads (cosine 0.90000, 0.99995 needed)" in found["reason"]
    for broken in (0.0, np.nan, np.inf):
        bad = local.copy()
        bad[2, 5 if broken else slice(None)] = broken
        found = assist.difference(local, bad, probes, "host", "m")
        assert found["agreement"] is None and "cannot be scaled to length 1" in found["reason"]
        assert found["probes"][2]["endpoint_length"] == (0.0 if broken == 0.0 else None)


def test_the_last_probe_text_ends_at_the_local_models_limit():
    """Every probe text is one the local model reads whole, and the last is filled to its limit to
    the token: the longest text an endpoint is ever handed."""
    for limit in (40, 256, 1024, 8192):
        probes = probe_texts(Reader(limit), limit)
        label, text = probes[-1]
        assert label == "a text as long as the local model reads" and len(tokens(text)) == limit
        assert not any(Reader(limit).cut([text for _, text in probes]))
    assert [label for label, _ in probe_texts(Reader(40), 40)] == [  # without the two it would cut
        "a function", "a usage text", "plain words", "other alphabets", "a text as long as the local model reads",
    ]
    label, text = probe_texts(FakeEmbedder(64), 1024)[-1]  # a model that reads every text whole
    lines = text.split("\n")
    assert label == "a long text" and len(text.split()) == 7 * len(lines) > 1024  # a token is a word at most
    does = [re.fullmatch(r"\w+ = (\w+)\(.*", line).group(1) for line in lines]
    assert len(set(does)) == len(lines) == 256  # no two lines do the same thing to the same thing


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


def test_a_local_embedder_that_cannot_say_which_texts_it_cuts_gets_no_help(stub):
    """A plugin embedder need not define `cut`; no text could then be handed on safely."""

    class Silent(Slow):
        def cut(self, texts):
            return Embedder.cut(self, texts)

    texts = code_texts(40)
    emb = assisted(stub.url, Silent())
    np.testing.assert_array_equal(emb.embed_documents(texts), FakeEmbedder(64).embed_documents(texts))
    status = emb.status()
    assert status["state"] == "refused" and stub.requests == []
    assert status["reason"] == (
        "Silent does not say which texts it reads only in part, so an endpoint cannot share its work"
    )

    class Late(Slow):  # one whose count fails after the check passed
        fails = False

        def cut(self, texts):
            if self.fails:
                raise NotImplementedError("the tokens of late could not be counted (ValueError: no tokenizer)")
            return super().cut(texts)

    emb = assisted(stub.url, Late())
    emb.embed_documents(texts)
    assert emb.status()["state"] == "sharing" and emb.shared["endpoint"] > 0
    emb.inner.fails, asked = True, len(stub.requests)
    np.testing.assert_array_equal(emb.embed_documents(texts), FakeEmbedder(64).embed_documents(texts))
    assert emb.status()["state"] == "refused" and len(stub.requests) == asked
    assert "the tokens of late could not be counted (ValueError: no tokenizer), so an endpoint" in emb.status()["reason"]


def test_the_local_half_of_a_check_is_kept_between_processes(stub, isolated_home):
    """The probe texts and the local model's vectors for them belong to its key: a later process
    asks the endpoint only."""
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

    kept = sorted((isolated_home / "assist").glob("probe-*.npz"))
    assert len(kept) == 2 and not list((isolated_home / "assist").glob("*.tmp"))
    for file in kept:
        file.write_bytes(b"not a file of ours")
    again = assisted(stub.url)  # what cannot be read is made again
    again.embed_documents(code_texts(40))
    assert PROBE in again.inner.calls and again.status()["state"] == "sharing"


def test_the_local_models_prefix_is_asked_for_once_and_only_when_the_config_names_none(stub):
    class Prompted(Slow):
        asked = 0

        @property
        def prefixes(self):
            type(self).asked += 1
            return ("query: ", "passage: ")

        def embed_documents(self, texts):
            return self._embed(["passage: " + t for t in texts])

    stub.prompt = "passage: "  # a provider that puts the prompt in front itself
    named = assisted(stub.url, Prompted(), document_prefix="")
    named.embed_documents(code_texts(40))
    assert named.status()["state"] == "sharing" and Prompted.asked == 0
    stub.prompt, before = "", len(stub.requests)
    first = assisted(stub.url, Prompted())  # the probe is remembered, the prefix is not yet
    first.embed_documents(code_texts(40))
    assert first.status()["state"] == "sharing" and Prompted.asked == 1 and PROBE not in first.inner.calls
    later = assisted(stub.url, Prompted())
    later.embed_documents(code_texts(40))
    assert later.status()["state"] == "sharing" and Prompted.asked == 1
    assert all(t.startswith("passage: ") for r in stub.requests[before:] for t in r["input"])


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
    assert "\n" not in status["reason"] and "not now" in status["reason"]  # one line, with the provider's words
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
    fresh.endpoint.checking()
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


def test_the_check_alone_prints_each_probe_texts_numbers_and_the_verdict(stub, sample_repo, tmp_path, monkeypatch, capsys):
    """`codemem status --check-assist`: a provider is tried without a build."""
    from codemem import embedder as embedders

    def check(*more: str) -> tuple[int, str, str]:
        monkeypatch.setattr(embedders, "_CACHE", {})  # as a process of its own
        status = main(["status", str(sample_repo), "--index-dir", str(tmp_path / "idx"), "--check-assist", *more])
        return status, *capsys.readouterr()

    def local_calls() -> list[int]:
        return next(e for e in embedders._CACHE.values() if type(e) is FakeEmbedder).calls

    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    status, out, err = check()
    assert status == 2 and out == "" and "no assist endpoint to check" in err

    (sample_repo / ".codemem.toml").write_text(
        f'[embedding.assist]\nbase_url = "{stub.url}"\nmodel = "fake:64"\n', encoding="utf-8"
    )
    host = stub.url.removeprefix("http://").removesuffix("/v1")
    stub.scale = 2.5  # the same model's vectors, not normalized
    status, out, _ = check()
    assert status == 0 and local_calls() == [PROBE]
    lines = out.splitlines()
    assert lines[0] == f"assist: fake:64 at {host}, compared with the local fake:64"
    assert lines[1] == "  the local model's vectors for the probe texts: embedded now"
    assert lines[2].split() == ["probe", "text", "characters", "cosine", "local", "length", "endpoint", "length"]
    assert len(lines) == 3 + PROBE + 2
    assert re.fullmatch(r"  plain words +96  1\.000000      1\.000000         2\.500000", lines[7])
    assert re.fullmatch(r"  a long text +\d+  1\.000000      1\.000000         2\.500000", lines[9])
    assert lines[10] == (
        "  needed: a cosine of 0.99995 or more for every probe text, after the endpoint's vectors are scaled to length 1"
    )
    assert lines[11] == "assist: its vectors agree with the local model's (cosine 1.000000 at worst)"
    assert len(stub.requests) == 1 and stub.work == []  # the probe texts only: no code of the repository

    status, out, _ = check("--json")  # the local half is remembered: no model call
    report, = json.loads(out)
    assert status == 0 and local_calls() == [] and len(stub.requests) == 2
    assert report["state"] == "sharing" and report["reason"] is None and report["needed"] == 0.99995
    assert (report["host"], report["model"], report["local_model"]) == (host, "fake:64", "fake:64")
    assert report["local_vectors"] == "remembered" and report["agreement"] == pytest.approx(1.0, abs=1e-6)
    assert [row["probe"] for row in report["probes"]][-2:] == ["other alphabets", "a long text"]
    assert all(row["endpoint_length"] == pytest.approx(2.5, abs=1e-5) for row in report["probes"])
    later = CodememService(sample_repo, index_dir=tmp_path / "idx")  # and `codemem status` has the verdict
    try:
        assert "assist: its vectors agree with the local model's (cosine 1.000000 at worst) (as of " in format_status(
            later.status()
        )
    finally:
        later.close()

    stub.salt = " other weights"
    status, out, err = check()
    assert status == 1 and "the local model's vectors for the probe texts: remembered from an earlier check" in out
    assert err == ""  # the verdict is said once, on stdout
    assert re.search(r"  plain words +96  0\.\d{6}      1\.000000         2\.500000", out)
    assert out.splitlines()[-1].startswith(
        f"assist: not used: {host} gives other vectors than the local model for the same texts (cosine 0."
    )

    stub.fail = [503]
    status, out, _ = check()
    assert status == 1 and out.splitlines()[-1] == (
        f"assist: not used for now: embedding request to {host} failed: HTTP 503 " + '{"error": { "message": "not now"}}'
    )
    assert "characters" not in out  # nothing came back to compare


def test_a_server_prints_the_settings_of_a_codemem_it_assists_too(monkeypatch):
    server = EmbeddingServer(FakeEmbedder(64), port=0, key="s3cret").start()
    try:
        printed = server.assist_config()
        assert printed == (
            f'[embedding.assist]\nbase_url = "{server.url}"\nmodel = "fake:64"\napi_key_env = "CODEMEM_SERVE_KEY"\n'
        )
        monkeypatch.setenv("CODEMEM_SERVE_KEY", "s3cret")
        cfg = config_from_dict({"vectors": {"code": {"model": "fake:64"}}, **tomllib.loads(printed)})
        emb = AssistedEmbedder(Slow(), cfg.embedding.assist)
        texts = code_texts(60)
        np.testing.assert_array_equal(emb.embed_documents(texts), FakeEmbedder(64).embed_documents(texts))
        assert emb.status()["state"] == "sharing" and emb.shared["endpoint"] > 0
    finally:
        server.close()
    bare = EmbeddingServer(FakeEmbedder(64), port=0)
    try:
        assert "api_key_env" not in bare.assist_config()
    finally:
        bare.close()


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
        offered: list[str] = []  # after the client's section: the server as an assist, in comment lines
        for line in proc.stdout:
            if not line.strip():
                break
            offered.append(line)
        assert proc.poll() is None, proc.stderr.read()
        server = tomllib.loads("".join(printed))["embedding"]
        assert tomllib.loads("".join(offered)) == {}  # so all of stdout stays the first section's TOML
        said = "".join(offered[: offered.index("# [embedding.assist]\n")])
        assert "a codemem that runs no model of its own" in said and "that runs this model itself" in said
        section = tomllib.loads("".join(line.removeprefix("# ") for line in offered[len(said.splitlines()):]))
        assert section == {"embedding": {"assist": {"base_url": server["base_url"], "model": server["model"]}}}
        fake = {"code": {"model": "fake:64"}, "usage": {"model": "fake:64"}}
        on = config_from_dict({"batch_size": 4, "vectors": fake, "vector_cache": "off", **section})
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
