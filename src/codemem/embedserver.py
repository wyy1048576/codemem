"""`codemem serve-embeddings`: the local embedding model behind an OpenAI-style HTTP endpoint, so
that several codemem processes (one per git worktree, one per container) share one model in memory.

The endpoint embeds each text exactly as given. Its clients are codemem processes with
`[embedding] provider = "openai"`: they put the model's query or document prompt in front of the
text themselves (`query_prefix`, `document_prefix`), so the wire format stays the plain OpenAI one,
which has no field for "this text is a query". `EmbeddingServer.client_config()` is the `[embedding]`
section such a client needs; the command prints it at start. Its `space` names the model's settings
on this server, so an index built through one address is valid through any other (config.py).

Only the standard library serves HTTP here. Every model call happens in one thread (`ModelQueue`):
the local model guards its loading and its precision switch with a lock, but not `encode` itself.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import logging
import os
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

import numpy as np

from . import __version__
from .config import SERVE_HOST as DEFAULT_HOST
from .config import SERVE_KEY_ENV as KEY_ENV  # the environment variable that holds the shared key, when there is one
from .config import SERVE_PORT as DEFAULT_PORT
from .config import AssistConfig, Config
from .embedder import Embedder, FakeEmbedder, SentenceTransformerEmbedder, l2_normalize, make_embedder, release_idle

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 16 * 1024 * 1024  # a request body; codemem's own requests are about 0.2 MB
MAX_INPUTS = 2048  # texts in one request
IDLE_TIMEOUT_S = 60.0  # a connection that sends nothing for this long is closed
QUIET_CHECK_S = 1.0  # with no request for this long, the queue gives the model a quiet moment
# At start, a text embedded as "prefix + text" must agree at least this well (cosine) with the same
# text embedded in process as a query or a document. For jina-code-embeddings-0.5b in float16 on an
# Apple GPU the two are the same numbers; a text embedded alone and in a batch agree to 0.999998
# (scripts/check_served_vectors.py).
SAME_VECTOR = 0.9999
_PROBES = ("def revoke_session(session_id):\n    db.sessions.delete(session_id)", "disabled users stay logged in")
_ROUTES = {"/v1/embeddings": "POST", "/v1/models": "GET", "/health": "GET"}
_WILDCARD_HOSTS = ("", "0.0.0.0", "::")


@dataclass(frozen=True)
class Served:
    """What a client has to know about the model behind the endpoint."""

    model: str  # the name a request gives
    space: str  # names the vectors: the model's settings on this server
    dim: int
    query_prefix: str
    document_prefix: str


def served_space(embedder: Embedder) -> str:
    """A name for the vectors an embedder gives for a text as given. It holds what the model's name
    does not say and the local embedder key does: the weights version, the longest text, the
    precision and the device. Two servers with equal names serve interchangeable vectors."""
    if isinstance(embedder, FakeEmbedder):
        return "fake"
    if isinstance(embedder, SentenceTransformerEmbedder):  # "st": the sentence-transformers runtime
        parts = ["st", embedder.version, f"L{embedder.max_seq_length}", embedder.dtype, embedder.device]
        name = re.sub(r"[^\w.-]", "_", "-".join(p for p in parts if p))
        if len(name) <= 64:  # the longest `space` a config accepts; a long version label is hashed instead
            return name
    return "codemem-" + hashlib.sha256(embedder.key.encode("utf-8")).hexdigest()[:12]


def local_embedder(config: Config) -> Embedder:
    """The embedder this process serves: the config's local model, whatever `[embedding] provider`
    says, because the same config file may be the one that sends clients here. An assist of that
    config is the clients' too: a server is the model, and shares its work with nobody."""
    specs = {(s.model, s.embedder, s.version): s for s in (config.vectors[v] for v in config.enabled_vec_types())}
    if len(specs) != 1:
        raise ValueError(
            f"serve-embeddings serves one model, and the vector types name {len(specs)}: "
            f"{', '.join(sorted(s.model for s in specs.values())) or 'none is enabled'}"
        )
    alone = dataclasses.replace(config.embedding, provider="local", assist=AssistConfig())
    return make_embedder(next(iter(specs.values())), dataclasses.replace(config, embedding=alone))


def describe(embedder: Embedder) -> Served:
    """Load the model and check that a client's prefixed text gives what the embedder itself gives
    for a query and for a document. A model whose prompt is more than a prefix (a system message, or
    tokens left out of the pooling) fails here, not silently in every index built through the server."""
    probes = list(_PROBES)
    try:
        query_prefix, document_prefix = embedder.prefixes
        for kind, prefix, direct in (
            ("query", query_prefix, embedder.embed_queries(probes)),
            ("document", document_prefix, embedder.embed_documents(probes)),
        ):
            served = embedder.embed_texts([prefix + p for p in probes])
            agreement = float(np.min(np.sum(direct * served, axis=1)))
            if agreement < SAME_VECTOR:
                raise ValueError(
                    f"{embedder.model_name} cannot be served: a {kind} embedded as its prefix plus the text "
                    f"differs from the same {kind} embedded in process (cosine {agreement:.4f})"
                )
    except NotImplementedError as e:  # a plugin embedder without `embed_texts` or `prefixes`
        raise ValueError(f"{embedder.model_name} cannot be served: {e}") from e
    return Served(embedder.model_name, served_space(embedder), embedder.dim, query_prefix, document_prefix)


class _Job:
    """One request's texts. They may go to the model in several batches; `done` is set when every
    vector is back, or a batch failed."""

    def __init__(self, texts: list[str]):
        self.texts = texts
        self.taken = 0  # texts handed to the model so far
        self.filled = 0
        self.vecs: np.ndarray | None = None
        self.error: Exception | None = None
        self.done = threading.Event()

    @property
    def left(self) -> int:
        return len(self.texts) - self.taken


class QueueClosed(RuntimeError):
    """The server is stopping: nothing more is embedded."""


class ModelQueue:
    """Gives one model to many request threads. One thread makes every model call, a batch of at
    most `batch_size` texts at a time. Between batches the request with the fewest texts left goes
    first, so a search's single query waits for one batch of another client's build, not for the
    build. Texts of several requests can share a batch. While no request waits, the same thread
    gives back what the model's calls needed besides it, and frees the model after `idle_minutes`
    without a request (0 keeps it); the next request then loads it again."""

    def __init__(self, embedder: Embedder, batch_size: int, idle_minutes: float = 0.0):
        self._embedder = embedder
        self._batch_size = max(1, batch_size)
        self._idle_minutes = idle_minutes
        self._cond = threading.Condition()
        self._waiting: list[_Job] = []
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="codemem-embed", daemon=True)
        self._thread.start()

    def embed(self, texts: list[str]) -> np.ndarray:
        job = _Job(texts)
        with self._cond:
            if self._closed:
                raise QueueClosed("the embedding server is stopping")
            self._waiting.append(job)
            self._cond.notify()
        job.done.wait()
        if job.error is not None:
            raise job.error
        assert job.vecs is not None
        return job.vecs

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify()
        self._thread.join(timeout=60)

    def _take(self) -> list[tuple[_Job, int, int]] | None:
        """The next batch as (job, first text, count) parts; None when the queue is closed, and
        an empty batch when no request came for `QUIET_CHECK_S`."""
        with self._cond:
            while not self._waiting and not self._closed:
                if not self._cond.wait(timeout=QUIET_CHECK_S) and not self._waiting and not self._closed:
                    return []
            if self._closed:
                for job in self._waiting:
                    job.error = QueueClosed("the embedding server is stopping")
                    job.done.set()
                self._waiting = []
                return None
            batch, room = [], self._batch_size
            for job in sorted(self._waiting, key=lambda j: j.left):  # stable: the first to arrive wins a tie
                count = min(room, job.left)
                batch.append((job, job.taken, count))
                job.taken += count
                room -= count
                if not room:
                    break
            self._waiting = [j for j in self._waiting if j.left]
            return batch

    def _run(self) -> None:
        while (batch := self._take()) is not None:
            if not batch:  # no request: only this thread calls the model, so none is running
                release_idle(self._embedder, self._idle_minutes)
                continue
            texts = [t for job, start, count in batch for t in job.texts[start : start + count]]
            try:
                vecs = self._embedder.embed_texts(texts)
                if len(vecs) != len(texts) or not np.isfinite(vecs).all():
                    raise ValueError(f"the model gave {len(vecs)} vectors for {len(texts)} texts, or one is not finite")
            except Exception as e:  # the requests in this batch fail; the server goes on
                log.exception("embedding a batch of %d texts failed", len(texts))
                with self._cond:
                    failed = {id(job) for job, *_ in batch}
                    self._waiting = [j for j in self._waiting if id(j) not in failed]
                for job, *_ in batch:
                    job.error = e
                    job.done.set()
                continue
            offset = 0
            for job, start, count in batch:
                if job.vecs is None:
                    job.vecs = np.empty((len(job.texts), vecs.shape[1]), dtype=np.float32)
                job.vecs[start : start + count] = vecs[offset : offset + count]
                offset += count
                job.filled += count
                if job.filled == len(job.texts):
                    job.done.set()


class _HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128  # connections that may wait to be accepted, as while the model loads

    def __init__(self, address: tuple[str, int], app: EmbeddingServer):
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        self.app = app
        super().__init__(address, _Handler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        if isinstance(sys.exception(), ConnectionError):  # the client went away: not this server's error
            log.debug("connection from %s dropped", client_address[0])
        else:
            log.exception("request from %s failed", client_address[0])


class EmbeddingServer:
    """An embedder behind `POST /v1/embeddings`, `GET /v1/models` and `GET /health`. It takes the
    port first (so a port in use fails at once), then loads the model. `key`, when given, must come
    as `Authorization: Bearer <key>` with every request but the health check; it is never logged."""

    def __init__(
        self, embedder: Embedder, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, key: str | None = None,
        batch_size: int = 16, idle_minutes: float = 0.0,
    ):
        self._key = (key or "").strip() or None
        self.started = int(time.time())
        self.httpd = _HTTPServer((host, port), self)
        try:
            self.served = describe(embedder)
        except BaseException:
            self.httpd.server_close()
            raise
        self.queue = ModelQueue(embedder, batch_size, idle_minutes)
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        """The `base_url` for a client on this machine."""
        host, port = self.httpd.server_address[:2]
        host = "127.0.0.1" if host in _WILDCARD_HOSTS else f"[{host}]" if ":" in host else host
        return f"http://{host}:{port}/v1"

    @property
    def has_key(self) -> bool:
        return self._key is not None

    def authorized(self, header: str | None) -> bool:
        if self._key is None:
            return True
        scheme, _, given = (header or "").partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(given.strip().encode(), self._key.encode())

    def client_config(self) -> str:
        """The `[embedding]` section of a codemem that embeds through this server."""
        s = self.served
        lines = [
            "[embedding]",
            'provider = "openai"',
            f"base_url = {_toml(self.url)}",
            f"model = {_toml(s.model)}",
            f"space = {_toml(s.space)}",
            f"query_prefix = {_toml(s.query_prefix)}",
            f"document_prefix = {_toml(s.document_prefix)}",
        ]
        if self.has_key:
            lines.append(f"api_key_env = {_toml(KEY_ENV)}")
        return "\n".join(lines) + "\n"

    def assist_config(self) -> str:
        """The `[embedding.assist]` section of a codemem that runs the same model itself and lets
        this server embed a share of each build. The prefix is that codemem's own model's."""
        lines = ["[embedding.assist]", f"base_url = {_toml(self.url)}", f"model = {_toml(self.served.model)}"]
        if self.has_key:
            lines.append(f"api_key_env = {_toml(KEY_ENV)}")
        return "\n".join(lines) + "\n"

    def serve_forever(self) -> None:
        self.httpd.serve_forever()

    def start(self) -> EmbeddingServer:
        """Serve in a background thread (tests, and programs that embed the server)."""
        self._thread = threading.Thread(target=self.serve_forever, name="codemem-embed-http", daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        if self._thread is not None:
            self.httpd.shutdown()
            self._thread.join(timeout=10)
        self.httpd.server_close()
        self.queue.close()


def _toml(text: str) -> str:
    """A TOML basic string. JSON's escapes are TOML's, except that TOML also wants DEL escaped."""
    return json.dumps(text, ensure_ascii=False).replace("\x7f", "\\u007f")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive: a client's requests share a connection
    timeout = IDLE_TIMEOUT_S
    server: _HTTPServer

    def version_string(self) -> str:
        return f"codemem/{__version__}"

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def log_message(self, format: str, *args: Any) -> None:  # the request line and status only: no header, no body
        log.debug("%s %s", self.address_string(), format % args)

    def _route(self, method: str) -> None:
        app = self.server.app
        self._body_unread = method == "POST"  # until the body is read, an answer has to close the connection
        path = urlsplit(self.path).path.rstrip("/") or "/"
        if path not in _ROUTES:
            routes = ", ".join(f"{m} {p}" for p, m in _ROUTES.items())
            return self._error(404, f"unknown route {path}: this server has {routes}")
        if method != _ROUTES[path]:
            return self._error(405, f"{path} takes {_ROUTES[path]}, not {method}", headers={"Allow": _ROUTES[path]})
        if path == "/health":
            return self._json(200, {"status": "ok"})
        if not app.authorized(self.headers.get("Authorization")):
            return self._error(
                401, f"missing or wrong key: this server wants `Authorization: Bearer <the value of {KEY_ENV}>`",
                "invalid_api_key", headers={"WWW-Authenticate": "Bearer"},
            )
        if path == "/v1/models":
            return self._json(200, {"object": "list", "data": [self._model_card()]})
        self._embeddings()

    def _model_card(self) -> dict[str, Any]:
        app = self.server.app
        s = app.served
        return {
            "id": s.model, "object": "model", "created": app.started, "owned_by": "codemem",
            # What a codemem client sets beside `model` (the same as the `[embedding]` section printed at start).
            "codemem": {
                "space": s.space, "dimensions": s.dim, "query_prefix": s.query_prefix,
                "document_prefix": s.document_prefix,
            },
        }

    def _embeddings(self) -> None:
        app = self.server.app
        s = app.served
        length = self.headers.get("Content-Length") or ""
        if not length.isdigit():
            return self._error(411, "the request needs a Content-Length")
        if int(length) > MAX_BODY_BYTES:
            return self._error(413, f"the request body is {length} bytes; the limit is {MAX_BODY_BYTES}")
        raw = self.rfile.read(int(length))
        self._body_unread = False
        try:
            body = json.loads(raw)
        except ValueError:
            return self._error(400, "the request body is not JSON")
        if not isinstance(body, dict):
            return self._error(400, "the request body must be a JSON object")
        texts = body.get("input")
        if isinstance(texts, str):
            texts = [texts]
        if not isinstance(texts, list) or not texts or not all(isinstance(t, str) for t in texts):
            return self._error(400, "`input` must be a string or a list of strings, and not empty")
        if len(texts) > MAX_INPUTS:
            return self._error(413, f"`input` has {len(texts)} texts; the limit is {MAX_INPUTS} in one request")
        if body.get("model") != s.model:
            return self._error(404, f"this server serves the model {s.model!r}, not {body.get('model')!r}",
                               "model_not_found")
        dims = body.get("dimensions")
        if dims is not None and (type(dims) is not int or not 1 <= dims <= s.dim):
            return self._error(400, f"`dimensions` must be a whole number from 1 to {s.dim}")
        encoding = body.get("encoding_format") or "float"
        if encoding not in ("float", "base64"):
            return self._error(400, "`encoding_format` must be float or base64")
        try:
            vecs = app.queue.embed(texts)
        except QueueClosed as e:
            return self._error(503, str(e))
        except Exception as e:
            return self._error(500, f"the model failed: {type(e).__name__}: {e}")
        if dims is not None and dims < s.dim:
            vecs = l2_normalize(vecs[:, :dims])
        if encoding == "base64":  # OpenAI's compact form: the float32 values, little-endian
            rows: list[Any] = [base64.b64encode(v.astype("<f4").tobytes()).decode("ascii") for v in vecs]
        else:
            rows = vecs.tolist()
        self._json(200, {
            "object": "list",
            "data": [{"object": "embedding", "index": i, "embedding": row} for i, row in enumerate(rows)],
            "model": s.model,
            "usage": {"prompt_tokens": 0, "total_tokens": 0},  # the server does not count tokens
        })

    def _error(
        self, status: int, message: str, code: str | None = None, headers: dict[str, str] | None = None
    ) -> None:
        """An error in OpenAI's shape; a client shows `message`."""
        kind = "server_error" if status >= 500 else "invalid_request_error"
        self._json(status, {"error": {"message": message, "type": kind, "param": None, "code": code}}, headers)

    def _json(self, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        if self._body_unread:  # the request's body is still on the wire: no other request can follow it
            self.close_connection = True
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)


def serve(config: Config, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> EmbeddingServer:
    """A server for the config's local model, ready to `serve_forever()`. The shared key, if any,
    is read from the environment variable `CODEMEM_SERVE_KEY`. The model stays in memory unless
    the config's `model_idle_minutes` says how long it may sit idle."""
    return EmbeddingServer(
        local_embedder(config), host=host, port=port, key=os.environ.get(KEY_ENV), batch_size=config.batch_size,
        idle_minutes=config.model_idle_minutes,
    )
