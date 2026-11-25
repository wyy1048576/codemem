"""`cmeval proxy`: a recording proxy between Claude Code and the model API.

Claude Code sends its model requests to ANTHROPIC_BASE_URL. Point that at this proxy. The proxy sends each request on
to the API and streams the answer back as it arrives. For each request it appends one JSON line to a log: three
clocks, the shape of the request, and the token counts that the API reports in its answer. summarize() adds up the
log of one run, and cross_check() compares the sums with Claude Code's own `modelUsage` (track-a-evals.md section 5).

Rules (section 5.6):
- Change nothing. Headers and body go through as they are. Only the hop-by-hop headers and Host change, and the
  proxy asks the API for an uncompressed answer (accept-encoding: identity), so it can read the token counts.
- Never write a credential. The log keeps only whether Authorization and x-api-key were present.
- Do not hold back a streamed answer. Each piece goes to the client as soon as it arrives.
- One proxy for each run, on its own port and with its own log.

Bodies are not kept, because each request repeats the whole conversation. With bodies_dir, the proxy writes each
request body and answer body to <seq>.request and <seq>.response there, to debug a mismatch.

One log line has these fields. A field is left out when it has no value.

  seq                    number of the request, from 1, in the order the requests arrived
  start                  when the request arrived (UTC, ISO)
  method, path, query    path without the query string, for example "/v1/messages" and "beta=true"
  status                 status code that the client got (502: the API could not be reached)
  ms_headers             milliseconds from start until the API's status and headers arrived
  ms_first_byte          ... until the first byte of the answer body arrived
  ms_end                 ... until the last byte of the answer body went to the client
  request_bytes          size of the request body; response_bytes: size of the answer body
  model, stream, max_tokens, messages, tools, has_system, has_metadata
                         from the request JSON: messages and tools are counts, never the content
  has_authorization, has_x_api_key
                         whether the request had these headers (their values are never kept)
  request_headers        values of a short list of headers that are not secret (KEPT_REQUEST_HEADERS)
  response_model, message_id, stop_reason
                         from the answer (message_start and message_delta for a stream)
  usage                  the final usage block: message_start's usage, then each message_delta's usage on top
  usage_start, usage_delta
                         the raw usage blocks of message_start and the last message_delta (streams only)
  stream_complete        a stream ended with message_stop (streams only)
  counted_input_tokens   the answer of /v1/messages/count_tokens
  request_id             the answer's request-id header
  rate_limit_headers     the answer's anthropic-ratelimit-*, retry-after and x-should-retry headers
  error                  {"type", "message"} from an error answer, or from an error event inside a stream
  proxy_error            what went wrong in the proxy or on the way to the API
  client_closed          the client closed the connection before the answer ended
  parse_note             why the answer was passed on but not read
"""

from __future__ import annotations

import itertools
import json
import re
import signal
import threading
import time
import zlib
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

try:
    import httpx2 as httpx  # anthropic 2.x brings httpx2, a fork of httpx with the same API
except ImportError:  # pragma: no cover - an environment with httpx itself
    import httpx

DEFAULT_PORT = 8787
DEFAULT_UPSTREAM = "https://api.anthropic.com"
MESSAGES_PATH = "/v1/messages"
COUNT_TOKENS_PATH = "/v1/messages/count_tokens"
# read: the longest wait for the next piece of an answer. The API sends a ping event in a long stream.
TIMEOUT = httpx.Timeout(connect=30.0, read=600.0, write=60.0, pool=60.0)
STOP_WAIT = 10.0  # seconds that stop() waits for requests in progress
MAX_PARSED_BODY = 32 * 1024 * 1024  # a larger JSON answer is passed on but not read
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "proxy-connection", "te",
              "trailer", "trailers", "transfer-encoding", "upgrade"}
KEPT_REQUEST_HEADERS = ("anthropic-beta", "anthropic-version", "user-agent", "x-app", "x-stainless-retry-count",
                        "content-type", "content-encoding")
KEPT_ANSWER_HEADERS = ("retry-after", "x-should-retry")
TOKEN_CLASSES = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
# The same classes in Claude Code's modelUsage (camelCase).
AGENT_CLASSES = {"input_tokens": "inputTokens", "output_tokens": "outputTokens",
                 "cache_creation_input_tokens": "cacheCreationInputTokens",
                 "cache_read_input_tokens": "cacheReadInputTokens"}
FIELDS = ("seq", "start", "method", "path", "query", "status", "ms_headers", "ms_first_byte", "ms_end",
          "request_bytes", "response_bytes", "model", "stream", "max_tokens", "messages", "tools", "has_system",
          "has_metadata", "has_authorization", "has_x_api_key", "request_headers", "response_model", "message_id",
          "stop_reason", "usage", "usage_start", "usage_delta", "stream_complete", "counted_input_tokens",
          "request_id", "rate_limit_headers", "error", "proxy_error", "client_closed", "parse_note")

_LINE_END = re.compile(rb"\r\n|\r|\n")


class SSEParser:
    """Server-sent events from a byte stream that arrives in pieces of any size.

    feed() takes the next piece and returns the events that it completes, as (event, data) pairs. A piece can end
    anywhere, also inside a line end or a UTF-8 character. Lines end in LF, CRLF, or CR. An event with no `event:`
    field is a "message" event. Comments and the fields id and retry are ignored. An event with no blank line after
    it at the end of the stream is not complete, so it is never returned.
    """

    def __init__(self) -> None:
        self._rest = b""  # the start of a line whose end has not arrived
        self._after_cr = False  # the last piece ended in CR, so an LF at the start of the next one is the same line end
        self._event = ""
        self._data: list[str] = []

    def feed(self, piece: bytes) -> list[tuple[str, str]]:
        if not piece:
            return []
        if self._after_cr and piece.startswith(b"\n"):
            piece = piece[1:]
        buffer = self._rest + piece
        self._after_cr = buffer.endswith(b"\r")
        lines = _LINE_END.split(buffer)
        self._rest = lines.pop()
        events: list[tuple[str, str]] = []
        for line in lines:  # a whole line, so a UTF-8 character cannot be cut
            self._line(line.decode("utf-8", "replace"), events)
        return events

    def _line(self, line: str, events: list[tuple[str, str]]) -> None:
        if not line:
            if self._data:
                events.append((self._event or "message", "\n".join(self._data)))
            self._event, self._data = "", []
            return
        if line.startswith(":"):
            return
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            self._event = value
        elif field == "data":
            self._data.append(value)


def merge_usage(*blocks: dict | None) -> dict:
    """The usage blocks one on top of the other: a later field replaces an earlier one. A null field replaces nothing."""
    merged: dict = {}
    for block in blocks:
        if isinstance(block, dict):
            merged.update({k: v for k, v in block.items() if v is not None})
    return merged


def _error_fields(error) -> dict | None:
    if not isinstance(error, dict):
        return None
    return {"type": error.get("type"), "message": error.get("message")}


class AnswerReader:
    """Reads the token counts and other facts from an answer body while it passes.

    feed() takes each raw piece of the body. facts() gives the fields for the log line when the body has ended.
    A stream (text/event-stream) is read event by event. Any other answer is read as JSON at the end.
    """

    def __init__(self, content_type: str = "", content_encoding: str = "") -> None:
        self.stream = "text/event-stream" in content_type.lower()
        self._parser = SSEParser()
        self._body = bytearray()
        self._note: str | None = None
        encoding = content_encoding.strip().lower()
        # The proxy asks for identity, so a compressed answer is not expected. gzip and deflate are still read.
        self._inflate = zlib.decompressobj(wbits=47) if encoding in ("gzip", "x-gzip", "deflate") else None
        if encoding not in ("", "identity", "gzip", "x-gzip", "deflate"):
            self._note = f"content-encoding {encoding} is not read"
        self._facts: dict = {}
        self._start_usage: dict | None = None
        self._deltas: list[dict] = []
        self._complete = False

    def feed(self, piece: bytes) -> None:
        if self._note:
            return
        if self._inflate is not None:
            try:
                piece = self._inflate.decompress(piece)
            except zlib.error as exc:
                self._note = f"cannot decompress: {exc}"
                return
        if self.stream:
            for _, data in self._parser.feed(piece):
                self._event(data)
        elif len(self._body) + len(piece) > MAX_PARSED_BODY:
            self._note = f"body larger than {MAX_PARSED_BODY} bytes is not read"
            self._body = bytearray()
        else:
            self._body += piece

    def _event(self, data: str) -> None:
        try:
            payload = json.loads(data)
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        kind = payload.get("type")
        if kind == "message_start":
            message = payload.get("message") or {}
            self._facts["response_model"] = message.get("model")
            self._facts["message_id"] = message.get("id")
            self._start_usage = message.get("usage")
        elif kind == "message_delta":
            if isinstance(payload.get("usage"), dict):
                self._deltas.append(payload["usage"])
            stop = (payload.get("delta") or {}).get("stop_reason")
            if stop is not None:
                self._facts["stop_reason"] = stop
        elif kind == "message_stop":
            self._complete = True
        elif kind == "error":
            self._facts["error"] = _error_fields(payload.get("error"))

    def facts(self) -> dict:
        facts = dict(self._facts)
        if self._note:
            facts["parse_note"] = self._note
        elif self.stream:
            if self._start_usage is not None or self._deltas:
                facts["usage"] = merge_usage(self._start_usage, *self._deltas)
            facts["usage_start"] = self._start_usage
            facts["usage_delta"] = self._deltas[-1] if self._deltas else None
            facts["stream_complete"] = self._complete
        elif self._body:
            try:
                body = json.loads(bytes(self._body))
            except ValueError:
                body = None
            if isinstance(body, dict):
                facts["response_model"] = body.get("model")
                facts["message_id"] = body.get("id")
                facts["stop_reason"] = body.get("stop_reason")
                facts["usage"] = body.get("usage")
                if body.get("type") == "error":
                    facts["error"] = _error_fields(body.get("error"))
                if "usage" not in body and isinstance(body.get("input_tokens"), int):
                    facts["counted_input_tokens"] = body["input_tokens"]
        return {k: v for k, v in facts.items() if v is not None}


def _connection_names(items: Iterable[tuple[str, str]]) -> set[str]:
    """Hop-by-hop headers, and the headers that a Connection header names."""
    names = set(HOP_BY_HOP)
    for name, value in items:
        if name.lower() == "connection":
            names.update(part.strip().lower() for part in value.split(","))
    return names


def upstream_headers(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The client's headers as they go to the API, in the same order, repeated headers kept.

    Dropped: hop-by-hop headers, Host and Content-Length (the HTTP library sets them again for the API and the body),
    and Accept-Encoding, which becomes identity: an uncompressed answer is the simplest one to read on the way.
    """
    drop = _connection_names(items) | {"host", "content-length", "accept-encoding"}
    return [(name, value) for name, value in items if name.lower() not in drop] + [("accept-encoding", "identity")]


def _decoded(body: bytes, encoding: str) -> bytes | None:
    encoding = encoding.strip().lower()
    if encoding in ("", "identity"):
        return body
    if encoding in ("gzip", "x-gzip", "deflate"):
        try:
            return zlib.decompress(body, wbits=47)
        except zlib.error:
            return None
    return None


def request_facts(body: bytes, headers) -> dict:
    """Fields for the log line from the request: its shape, never its content and never a credential."""
    facts: dict = {
        "has_authorization": "authorization" in headers,
        "has_x_api_key": "x-api-key" in headers,
        "request_headers": {name: headers[name] for name in KEPT_REQUEST_HEADERS if name in headers} or None,
    }
    raw = _decoded(body, headers.get("content-encoding") or "") if body else None
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        data = None
    if isinstance(data, dict):
        facts["model"] = data.get("model")
        facts["stream"] = data.get("stream")
        facts["max_tokens"] = data.get("max_tokens")
        facts["messages"] = len(data["messages"]) if isinstance(data.get("messages"), list) else None
        facts["tools"] = len(data["tools"]) if isinstance(data.get("tools"), list) else None
        facts["has_system"] = "system" in data
        facts["has_metadata"] = "metadata" in data
    return {k: v for k, v in facts.items() if v is not None}


def _ms(since: float) -> float:
    return round((time.perf_counter() - since) * 1000, 1)


def _read_chunked(rfile) -> bytes:
    """A request body sent with Transfer-Encoding: chunked."""
    body = bytearray()
    while True:
        size = int(rfile.readline().split(b";", 1)[0].strip(), 16)
        if size == 0:
            while rfile.readline() not in (b"\r\n", b"\n", b""):  # trailer lines, then a blank line
                pass
            return bytes(body)
        chunk = rfile.read(size)
        if len(chunk) != size:
            raise ValueError("the body ended early")
        body += chunk
        rfile.readline()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive connections, and chunked answers
    disable_nagle_algorithm = True  # send each small piece of a stream at once
    server: _Server

    def _forward(self) -> None:
        proxy = self.server.proxy
        seq = proxy._begin()
        if seq is None:
            self.close_connection = True
            self._send_error(503, "the recording proxy is stopping")
            return
        record: dict = {"seq": seq, "start": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}
        try:
            self._exchange(proxy, record, time.perf_counter())
        finally:
            proxy._end(record)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _forward  # noqa: N815 - http.server names

    def _exchange(self, proxy: RecordingProxy, record: dict, t0: float) -> None:
        target = urlsplit(self.path)  # also takes the absolute form "http://host/path"
        record.update(method=self.command, path=target.path or "/", query=target.query or None)
        try:
            body = self._read_body()
        except (ValueError, OSError) as exc:
            self.close_connection = True
            record.update(status=400, proxy_error=f"cannot read the request body: {exc}")
            self._send_error(400, record["proxy_error"])
            return
        record["request_bytes"] = len(body)
        url = proxy.upstream + record["path"] + (f"?{target.query}" if target.query else "")
        request = httpx.Request(self.command, url, headers=upstream_headers(list(self.headers.items())), content=body,
                                extensions={"timeout": TIMEOUT.as_dict()})
        try:
            response = proxy._transport.handle_request(request)
        except httpx.HTTPError as exc:
            record.update(status=502, proxy_error=f"{type(exc).__name__}: {exc}")
            self._send_error(502, f"the recording proxy cannot reach {proxy.upstream}: {record['proxy_error']}")
        else:
            record["ms_headers"] = _ms(t0)
            try:
                self._relay(proxy, response, record, t0)
            finally:
                response.close()
        # The request is read for the log only after the answer, so that reading it adds no delay.
        record.update(request_facts(body, self.headers))
        if proxy.bodies_dir is not None:
            (proxy.bodies_dir / f"{record['seq']:06d}.request").write_bytes(body)

    def _relay(self, proxy: RecordingProxy, response, record: dict, t0: float) -> None:
        """Send the API's status and headers to the client at once, then each piece of the body as it arrives."""
        status = response.status_code
        headers = response.headers.multi_items()
        record["status"] = status
        record["request_id"] = response.headers.get("request-id")
        kept = {name.lower(): value for name, value in headers
                if name.lower().startswith("anthropic-ratelimit-") or name.lower() in KEPT_ANSWER_HEADERS}
        record["rate_limit_headers"] = kept or None

        no_body = self.command == "HEAD" or status in (204, 304) or status < 200
        # With a Content-Length from the API the raw bytes go through as they are. Without one the proxy sends the
        # body in chunks, one chunk for each piece that arrives.
        chunked = not no_body and "content-length" not in response.headers
        reason = response.extensions.get("reason_phrase", b"").decode("ascii", "replace") or None
        self.send_response_only(status, reason)
        drop = _connection_names(headers)
        for name, value in headers:
            if name.lower() not in drop:
                self.send_header(name, value)
        if chunked:
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()  # the status and headers go out now, before the body

        reader = AnswerReader(response.headers.get("content-type", ""), response.headers.get("content-encoding", ""))
        body_file = open(proxy.bodies_dir / f"{record['seq']:06d}.response", "wb") if proxy.bodies_dir else None
        size = 0
        try:
            for piece in response.iter_raw():  # raw bytes as they come off the socket, not decoded
                if not piece or no_body:
                    continue
                if size == 0:
                    record["ms_first_byte"] = _ms(t0)
                size += len(piece)
                if not self._write(b"%x\r\n%s\r\n" % (len(piece), piece) if chunked else piece):
                    record["client_closed"] = True
                    break
                reader.feed(piece)  # after the write, so that reading adds no delay
                if body_file:
                    body_file.write(piece)
            else:
                if chunked and not self._write(b"0\r\n\r\n"):
                    record["client_closed"] = True
        except httpx.HTTPError as exc:
            # The status has gone out, so the client can only see a body that ends early.
            self.close_connection = True
            record["proxy_error"] = f"{type(exc).__name__} while reading the answer: {exc}"
        finally:
            if body_file:
                body_file.close()
        record["ms_end"] = _ms(t0)
        record["response_bytes"] = size
        record.update(reader.facts())

    def _write(self, data: bytes) -> bool:
        """Send data to the client. False when the client has gone."""
        try:
            self.wfile.write(data)  # wfile has no buffer: each write goes to the socket
            return True
        except OSError:  # for example BrokenPipeError or ConnectionResetError
            self.close_connection = True
            return False

    def _read_body(self) -> bytes:
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            return _read_chunked(self.rfile)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length > 0 else b""
        if len(body) != length:
            raise ValueError("the body ended early")
        return body

    def _send_error(self, code: int, message: str) -> None:
        body = json.dumps({"type": "error", "error": {"type": "proxy_error", "message": message}}).encode("utf-8")
        self.send_response_only(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - the log file is the record, not the terminal
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True  # an idle keep-alive connection must not keep the program alive
    request_queue_size = 64

    def __init__(self, address: tuple[str, int], proxy: RecordingProxy) -> None:
        self.proxy = proxy
        super().__init__(address, _Handler)


class RecordingProxy:
    """A recording proxy on host:port (port 0: any free port) that forwards to upstream.

        with RecordingProxy(log_path) as proxy:
            ...  # run the agent with ANTHROPIC_BASE_URL=proxy.url
        summary = summarize(log_path)

    The log is opened for appending. Sequence numbers go on from the lines that are already in it. progress, when
    given, gets one short line for each request.
    """

    def __init__(self, log_path: str | Path, host: str = "127.0.0.1", port: int = 0, upstream: str = DEFAULT_UPSTREAM,
                 bodies_dir: str | Path | None = None, progress: Callable[[str], None] | None = None) -> None:
        self.log_path = Path(log_path)
        self.host = host
        self.upstream = upstream.rstrip("/")
        self.bodies_dir = Path(bodies_dir) if bodies_dir else None
        self._port = port
        self._progress = progress
        self._lock = threading.Lock()  # guards the log, the sequence, and the count of requests in progress
        self._idle = threading.Condition(self._lock)
        self._active = 0
        self._stopping = False
        self._seq = itertools.count(1)
        self._log = None
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._transport = None

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else self._port

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> RecordingProxy:
        self._server = _Server((self.host, self._port), self)  # first, so that a port in use fails before any file
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.bodies_dir:
            self.bodies_dir.mkdir(parents=True, exist_ok=True)
        lines = 0
        if self.log_path.exists():
            with open(self.log_path, "rb") as f:
                lines = sum(1 for line in f if line.strip())
        self._seq = itertools.count(lines + 1)
        self._log = open(self.log_path, "a", encoding="utf-8")
        # Environment proxy settings are not read: the requests go straight to upstream.
        self._transport = httpx.HTTPTransport(retries=0, trust_env=False,
                                              limits=httpx.Limits(max_connections=100, keepalive_expiry=30.0))
        # A short poll interval: stop() waits up to one interval for the server loop to see it.
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05},
                                        name="cmeval-proxy", daemon=True)
        self._thread.start()
        return self

    def stop(self, wait: float = STOP_WAIT) -> None:
        """Stop taking requests, wait up to `wait` seconds for the ones in progress, then close the log."""
        if self._server is None:
            return
        with self._lock:
            self._stopping = True
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
        with self._lock:
            self._idle.wait_for(lambda: self._active == 0, timeout=wait)
            self._log.close()
            self._log = None
        self._transport.close()
        self._port = self._server.server_address[1]
        self._server = None

    def __enter__(self) -> RecordingProxy:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def _begin(self) -> int | None:
        with self._lock:
            if self._stopping:
                return None
            self._active += 1
            return next(self._seq)

    def _end(self, record: dict) -> None:
        line = {k: record[k] for k in FIELDS if record.get(k) is not None}
        line.update({k: v for k, v in record.items() if k not in line and v is not None})
        text = json.dumps(line, ensure_ascii=False) + "\n"
        with self._lock:
            if self._log is not None:  # a request that outlived stop() is not written
                self._log.write(text)
                self._log.flush()
            self._active -= 1
            self._idle.notify_all()
        if self._progress:
            self._progress(progress_line(line))


def progress_line(record: dict) -> str:
    """One short line about a request, for the terminal."""
    parts = [f"#{record.get('seq')}", str(record.get("method")), str(record.get("path")), str(record.get("status"))]
    if record.get("ms_end") is not None:
        parts.append(f"{record['ms_end'] / 1000:.1f}s")
    usage = record.get("usage") or {}
    for key, label in (("input_tokens", "in"), ("cache_creation_input_tokens", "cache_write"),
                       ("cache_read_input_tokens", "cache_read"), ("output_tokens", "out")):
        if key in usage:
            parts.append(f"{label}={usage[key]}")
    for key in ("error", "proxy_error"):
        if record.get(key):
            parts.append(f"{key}={json.dumps(record[key])}")
    return " ".join(parts)


def _interrupt(signum, frame) -> None:
    raise KeyboardInterrupt


def serve(log_path: str | Path, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT, upstream: str = DEFAULT_UPSTREAM,
          bodies_dir: str | Path | None = None, progress: Callable[[str], None] = lambda message: None) -> dict:
    """Run a proxy until Ctrl-C or SIGTERM. Returns the summary of the log.

    A job that a script starts in the background ignores Ctrl-C (SIGINT), so SIGTERM also stops the proxy cleanly.
    """
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _interrupt)
    with RecordingProxy(log_path, host=host, port=port, upstream=upstream, bodies_dir=bodies_dir,
                        progress=progress) as proxy:
        progress(f"proxy at {proxy.url} to {proxy.upstream}; log {log_path}; Ctrl-C to stop")
        progress(f"point the agent at it with ANTHROPIC_BASE_URL={proxy.url}")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    return summarize(log_path)


def read_log(log_path: str | Path) -> tuple[list[dict], int]:
    """The records of a log, and the number of lines that are not JSON (for example a line cut off by a kill)."""
    records, bad = [], 0
    for line in Path(log_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            bad += 1
    return records, bad


def _zero() -> dict:
    return {"requests": 0, **dict.fromkeys(TOKEN_CLASSES, 0)}


def summarize(log_path: str | Path) -> dict:
    """Totals over the log of one run.

    Tokens are summed over the /v1/messages requests with status 200 that have a usage block. Requests to
    count_tokens are counted apart and never added to the token sums. processed_tokens is the sum of the four
    classes (section 5.4); peak_context_tokens is the largest input of one request (fresh input, cache writes and
    cache reads). proxy_complete is true when every such request has a usage block, every stream ended with
    message_stop, and every line of the log is JSON.
    """
    records, bad = read_log(log_path)
    records.sort(key=lambda r: r.get("seq", 0))
    messages, by_model = _zero(), {}
    missing, incomplete, errors = [], [], []
    count_tokens = {"requests": 0, "counted_input_tokens": 0}
    peak = 0
    for r in records:
        path, status = r.get("path"), r.get("status")
        if path == COUNT_TOKENS_PATH:
            count_tokens["requests"] += 1
            count_tokens["counted_input_tokens"] += r.get("counted_input_tokens") or 0
        if status is None or status >= 400 or r.get("error") or r.get("proxy_error"):
            error = r.get("error") or {}
            errors.append({"seq": r.get("seq"), "start": r.get("start"), "path": path, "status": status,
                           "type": error.get("type"), "message": error.get("message"),
                           "retry_after": (r.get("rate_limit_headers") or {}).get("retry-after"),
                           "proxy_error": r.get("proxy_error")})
        if path != MESSAGES_PATH or status != 200:
            continue
        if r.get("stream_complete") is False:
            incomplete.append(r.get("seq"))
        usage = r.get("usage")
        if not usage:
            missing.append(r.get("seq"))
            continue
        model = r.get("response_model") or r.get("model") or "unknown"
        per_model = by_model.setdefault(model, _zero())
        for totals in (messages, per_model):
            totals["requests"] += 1
            for cls in TOKEN_CLASSES:
                totals[cls] += usage.get(cls) or 0
        peak = max(peak, sum(usage.get(cls) or 0 for cls in TOKEN_CLASSES if cls != "output_tokens"))
    starts = [r["start"] for r in records if r.get("start")]
    return {
        "log": str(log_path),
        "requests": len(records),
        "bad_lines": bad,
        "by_path": dict(Counter(str(r.get("path")) for r in records)),
        "by_status": dict(Counter(str(r.get("status")) for r in records)),
        "messages": {**messages, "processed_tokens": sum(messages[cls] for cls in TOKEN_CLASSES),
                     "peak_context_tokens": peak, "by_model": by_model},
        "missing_usage": len(missing),
        "missing_usage_seqs": missing,
        "incomplete_streams": len(incomplete),
        "incomplete_stream_seqs": incomplete,
        "proxy_complete": not missing and not incomplete and not bad,
        "count_tokens": count_tokens,
        "errors": {"count": len(errors), "by_status": dict(Counter(str(e["status"]) for e in errors)), "list": errors},
        "first_request": min(starts) if starts else None,
        "last_request": max(starts) if starts else None,
    }


def relative_difference(a: int, b: int) -> float:
    """|a - b| over the larger of the two. 0.0 when both are 0."""
    return abs(a - b) / max(a, b) if max(a, b) else 0.0


def cross_check(summary: dict, agent_model_usage: dict, tolerance: float = 0.01) -> dict:
    """Compare the proxy's token sums with the agent's own summary (section 5.3).

    agent_model_usage is the `modelUsage` object of Claude Code's final result event: model id -> {inputTokens,
    outputTokens, cacheReadInputTokens, cacheCreationInputTokens, ...}. The two sides can name a model in different
    forms (for example with or without a date), so the verdict compares totals over all models, class by class. A
    class agrees when its relative difference is at most tolerance; when both sides are 0; and never when only one
    side is 0. The per-model sums of both sides are in "models", for information.
    """
    agent = {model: {cls: int(usage.get(key) or 0) for cls, key in AGENT_CLASSES.items()}
             for model, usage in (agent_model_usage or {}).items() if isinstance(usage, dict)}
    proxy = {model: {cls: totals[cls] for cls in TOKEN_CLASSES}
             for model, totals in summary["messages"]["by_model"].items()}
    classes = {}
    for cls in TOKEN_CLASSES:
        p, a = summary["messages"][cls], sum(m[cls] for m in agent.values())
        diff = relative_difference(p, a)
        agree = p == a == 0 or (p > 0 and a > 0 and diff <= tolerance)
        classes[cls] = {"proxy": p, "agent": a, "relative_difference": round(diff, 6), "agree": agree}
    return {"agree": all(c["agree"] for c in classes.values()), "tolerance": tolerance, "classes": classes,
            "models": {"proxy": proxy, "agent": agent}}
