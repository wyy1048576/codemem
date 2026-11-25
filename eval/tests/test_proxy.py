import http.client
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cmeval import cli, proxy
from cmeval.cli import main
from cmeval.proxy import AnswerReader, RecordingProxy, SSEParser, cross_check, merge_usage, summarize

SECRET = "FAKE-LOGIN-VALUE-7f3a9c"
API_KEY = "FAKE-KEY-VALUE-51bd"
MODEL = "claude-opus-4-5-20251101"


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


START = sse("message_start", {"type": "message_start", "message": {
    "id": "msg_01", "type": "message", "role": "assistant", "model": MODEL, "content": [], "stop_reason": None,
    "usage": {"input_tokens": 3, "cache_creation_input_tokens": 1200, "cache_read_input_tokens": 40000,
              "cache_creation": {"ephemeral_5m_input_tokens": 1200, "ephemeral_1h_input_tokens": 0},
              "output_tokens": 1}}})
REST = [
    sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
    b"event: ping\ndata: {\"type\": \"ping\"}\n\n",
    sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}}),
    sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
    sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                          "usage": {"input_tokens": 3, "cache_creation_input_tokens": 1200,
                                    "cache_read_input_tokens": 40000, "output_tokens": 57}}),
    sse("message_stop", {"type": "message_stop"}),
]
JSON_ANSWER = {"id": "msg_02", "type": "message", "model": MODEL, "stop_reason": "end_turn",
               "content": [{"type": "text", "text": "Hi"}],
               "usage": {"input_tokens": 10, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 500,
                         "output_tokens": 7}}
LIMIT_ANSWER = {"type": "error", "error": {"type": "rate_limit_error", "message": "usage limit reached"}}


class FakeAPI:
    """A local stand-in for the model API. The header x-fake-answer chooses the answer."""

    def __init__(self):
        self.seen = []  # (method, path, headers, body) of each request
        self.release = threading.Event()  # the stream test sets it when its client has the first event
        self.stream_done = threading.Event()  # set after the last event is sent
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                fake.seen.append((self.command, self.path, self.headers, body))
                answer = self.headers.get("x-fake-answer", "json")
                if answer == "sse":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.send_header("request-id", "req_sse")
                    self.end_headers()
                    self._chunk(START)
                    fake.release.wait(5)
                    for piece in REST:
                        self._chunk(piece)
                    self.wfile.write(b"0\r\n\r\n")
                    fake.stream_done.set()
                elif answer == "429":
                    self._json(429, LIMIT_ANSWER, {"retry-after": "120", "anthropic-ratelimit-unified-status": "rejected",
                                                   "request-id": "req_429"})
                elif self.path.startswith("/v1/messages/count_tokens"):
                    self._json(200, {"input_tokens": 321}, {})
                else:
                    self._json(200, JSON_ANSWER, {"request-id": "req_json"})

            def _chunk(self, data):
                self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))

            def _json(self, code, payload, headers):
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"


@pytest.fixture
def fake_api():
    fake = FakeAPI()
    thread = threading.Thread(target=fake.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield fake
    fake.release.set()
    fake.server.shutdown()
    fake.server.server_close()


@pytest.fixture
def running(tmp_path, fake_api):
    log = tmp_path / "proxy.jsonl"
    with RecordingProxy(log, upstream=fake_api.url) as p:
        yield p, log, fake_api


def records(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


def post(port, body, headers, path="/v1/messages?beta=true"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", path, body=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    return conn, conn.getresponse()


REQUEST = {"model": MODEL, "max_tokens": 32000, "stream": True, "system": [{"type": "text", "text": "secret prompt"}],
           "metadata": {"user_id": "u1"}, "messages": [{"role": "user", "content": "hello"}] * 3,
           "tools": [{"name": "Bash"}, {"name": "Read"}]}


def test_stream_passes_through_unbuffered_and_records_usage(tmp_path, fake_api):
    log = tmp_path / "proxy.jsonl"
    with RecordingProxy(log, upstream=fake_api.url) as p:
        conn, response = post(p.port, REQUEST, {"x-fake-answer": "sse"})
        assert response.status == 200 and response.getheader("Content-Type") == "text/event-stream"
        received = b""
        while not received.endswith(b"\n\n"):
            received += response.read1(65536)
        assert received == START
        # The client has the first event while the API still holds back the rest: nothing is buffered.
        assert not fake_api.stream_done.is_set()
        fake_api.release.set()
        received += response.read()
        conn.close()
    assert received == START + b"".join(REST)  # byte for byte
    [r] = records(log)
    assert r["status"] == 200 and r["path"] == "/v1/messages" and r["query"] == "beta=true"
    assert r["model"] == MODEL and r["stream"] is True and r["max_tokens"] == 32000
    assert r["messages"] == 3 and r["tools"] == 2 and r["has_system"] and r["has_metadata"]
    assert r["response_model"] == MODEL and r["message_id"] == "msg_01" and r["stop_reason"] == "end_turn"
    assert r["usage"] == {"input_tokens": 3, "cache_creation_input_tokens": 1200, "cache_read_input_tokens": 40000,
                          "cache_creation": {"ephemeral_5m_input_tokens": 1200, "ephemeral_1h_input_tokens": 0},
                          "output_tokens": 57}
    assert r["usage_start"]["output_tokens"] == 1 and r["usage_delta"]["output_tokens"] == 57
    assert r["stream_complete"] is True and r["request_id"] == "req_sse"
    assert 0 <= r["ms_headers"] <= r["ms_first_byte"] <= r["ms_end"]
    assert r["response_bytes"] == len(received)
    assert "secret prompt" not in log.read_text()  # bodies are not kept


def test_json_answer_and_count_tokens(running):
    p, log, _ = running
    body = {**REQUEST, "stream": False}
    conn, response = post(p.port, body, {})
    data = response.read()
    assert response.status == 200 and json.loads(data) == JSON_ANSWER
    assert response.getheader("Content-Length") == str(len(data))
    # The same connection again, for a count: keep-alive works.
    conn.request("POST", "/v1/messages/count_tokens?beta=true", body=b'{"model": "m", "messages": []}')
    assert json.loads(conn.getresponse().read()) == {"input_tokens": 321}
    conn.close()
    p.stop()
    first, second = records(log)
    assert first["seq"] == 1 and first["usage"] == JSON_ANSWER["usage"] and first["stream"] is False
    assert "stream_complete" not in first and first["request_id"] == "req_json"
    assert second["seq"] == 2 and second["path"] == "/v1/messages/count_tokens"
    assert second["counted_input_tokens"] == 321 and "usage" not in second


def test_error_answer(running):
    p, log, _ = running
    conn, response = post(p.port, REQUEST, {"x-fake-answer": "429"})
    assert response.status == 429 and response.getheader("retry-after") == "120"
    assert json.loads(response.read()) == LIMIT_ANSWER
    conn.close()
    p.stop()
    [r] = records(log)
    assert r["status"] == 429 and r["error"] == {"type": "rate_limit_error", "message": "usage limit reached"}
    assert r["rate_limit_headers"] == {"retry-after": "120", "anthropic-ratelimit-unified-status": "rejected"}
    summary = summarize(log)
    assert summary["errors"]["by_status"] == {"429": 1} and summary["errors"]["list"][0]["retry_after"] == "120"
    assert summary["messages"]["requests"] == 0


def test_headers_pass_through_and_secrets_stay_out_of_the_log(tmp_path, fake_api):
    log, bodies = tmp_path / "proxy.jsonl", tmp_path / "bodies"
    sent = {"Authorization": f"Bearer {SECRET}", "x-api-key": API_KEY, "anthropic-version": "2023-06-01",
            "anthropic-beta": "oauth-2025-04-20,claude-code-20250219", "User-Agent": "claude-cli/2.1.300 (external, cli)",
            "X-Custom": "kept", "Connection": "keep-alive, X-Hop", "X-Hop": "dropped", "Accept-Encoding": "gzip, br"}
    with RecordingProxy(log, upstream=fake_api.url, bodies_dir=bodies) as p:
        conn, response = post(p.port, {**REQUEST, "stream": False}, sent)
        response.read()
        conn.close()
    _, path, headers, body = fake_api.seen[0]
    assert path == "/v1/messages?beta=true" and json.loads(body)["model"] == MODEL
    for name in ("Authorization", "x-api-key", "anthropic-version", "anthropic-beta", "User-Agent", "X-Custom"):
        assert headers[name] == sent[name]
    assert headers["accept-encoding"] == "identity"
    assert headers["host"] == fake_api.url.removeprefix("http://")
    assert "X-Hop" not in headers and "Connection" not in headers
    text = log.read_text()
    assert SECRET not in text and API_KEY not in text
    [r] = records(log)
    assert r["has_authorization"] is True and r["has_x_api_key"] is True
    assert r["request_headers"]["anthropic-beta"] == sent["anthropic-beta"]
    # The bodies folder holds the bodies, but no headers.
    assert json.loads((bodies / "000001.request").read_bytes()) == {**REQUEST, "stream": False}
    assert json.loads((bodies / "000001.response").read_bytes()) == JSON_ANSWER
    assert not any(SECRET.encode() in f.read_bytes() for f in bodies.iterdir())


def test_upstream_down_gives_502(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed_port = s.getsockname()[1]
    log = tmp_path / "proxy.jsonl"
    with RecordingProxy(log, upstream=f"http://127.0.0.1:{closed_port}") as p:
        conn, response = post(p.port, REQUEST, {})
        assert response.status == 502 and json.loads(response.read())["error"]["type"] == "proxy_error"
        conn.close()
    [r] = records(log)
    assert r["status"] == 502 and "ConnectError" in r["proxy_error"]
    assert summarize(log)["errors"]["count"] == 1


def test_sequence_goes_on_in_an_existing_log(tmp_path, fake_api):
    log = tmp_path / "proxy.jsonl"
    for _ in range(2):
        with RecordingProxy(log, upstream=fake_api.url) as p:
            assert p.url == f"http://127.0.0.1:{p.port}" and p.port > 0
            conn, response = post(p.port, {**REQUEST, "stream": False}, {})
            response.read()
            conn.close()
    assert [r["seq"] for r in records(log)] == [1, 2]


STREAM = (b": a comment\r\n"
          b"event: message_start\r\ndata: {\"type\": \"message_start\"}\r\n\r\n"
          b"data: line one\ndata: line two \xc3\xa9\n\n"
          b"event: ping\rdata:no-space\r\r"
          b"event: empty\n\n"
          b"id: 7\nretry: 10\nevent: last\ndata: x\n\n"
          b"event: cut\ndata: never ends\n")
EVENTS = [("message_start", '{"type": "message_start"}'), ("message", "line one\nline two é"),
          ("ping", "no-space"), ("last", "x")]


def test_sse_parser_whole_stream():
    assert SSEParser().feed(STREAM) == EVENTS


def test_sse_parser_split_at_every_byte():
    for i in range(len(STREAM) + 1):
        parser = SSEParser()
        assert parser.feed(STREAM[:i]) + parser.feed(STREAM[i:]) == EVENTS, i
    parser = SSEParser()
    assert [e for i in range(len(STREAM)) for e in parser.feed(STREAM[i:i + 1])] == EVENTS


def test_answer_reader_stream_without_end():
    reader = AnswerReader("text/event-stream; charset=utf-8")
    reader.feed(START)
    facts = reader.facts()
    assert facts["stream_complete"] is False and facts["usage"]["output_tokens"] == 1 and "usage_delta" not in facts


def test_answer_reader_error_event_and_gzip():
    import gzip

    reader = AnswerReader("text/event-stream", "gzip")
    error = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
    data = gzip.compress(START + sse("error", error))
    for i in range(0, len(data), 7):
        reader.feed(data[i:i + 7])
    facts = reader.facts()
    assert facts["error"] == {"type": "overloaded_error", "message": "Overloaded"} and facts["usage"]["input_tokens"] == 3
    reader = AnswerReader("application/json", "br")
    reader.feed(b"\x00\x01")
    assert reader.facts() == {"parse_note": "content-encoding br is not read"}


def test_merge_usage_ignores_null():
    assert merge_usage({"a": 1, "b": 2}, None, {"b": 3, "a": None}) == {"a": 1, "b": 3}


def write_log(path, rows, extra_line=None):
    lines = [json.dumps(r) for r in rows] + ([extra_line] if extra_line else [])
    path.write_text("\n".join(lines) + "\n")


def usage(i, cw, cr, o):
    return {"input_tokens": i, "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr, "output_tokens": o}


LOG_ROWS = [
    {"seq": 1, "start": "2026-11-24T10:00:00.000+00:00", "path": "/v1/messages", "status": 200, "model": MODEL,
     "response_model": MODEL, "usage": usage(3, 1200, 40000, 57), "stream_complete": True},
    {"seq": 2, "start": "2026-11-24T10:00:05.000+00:00", "path": "/v1/messages", "status": 200,
     "model": "claude-haiku-4-5", "response_model": "claude-haiku-4-5-20251001", "usage": usage(100, 0, 0, 20)},
    {"seq": 3, "start": "2026-11-24T10:00:06.000+00:00", "path": "/v1/messages/count_tokens", "status": 200,
     "counted_input_tokens": 321},
    {"seq": 4, "start": "2026-11-24T10:00:07.000+00:00", "path": "/v1/messages", "status": 429,
     "error": {"type": "rate_limit_error", "message": "limit"}, "rate_limit_headers": {"retry-after": "60"}},
    {"seq": 5, "start": "2026-11-24T10:00:08.000+00:00", "path": "/v1/messages", "status": 200, "model": MODEL,
     "stream_complete": False},
    {"seq": 6, "start": "2026-11-24T10:00:09.000+00:00", "path": "/v1/messages", "status": 529,
     "error": {"type": "overloaded_error", "message": "Overloaded"}},
]


def test_summarize(tmp_path):
    log = tmp_path / "proxy.jsonl"
    write_log(log, LOG_ROWS, extra_line='{"seq": 7, "cut off')
    s = summarize(log)
    assert s["requests"] == 6 and s["bad_lines"] == 1
    assert s["by_path"] == {"/v1/messages": 5, "/v1/messages/count_tokens": 1}
    assert s["by_status"] == {"200": 4, "429": 1, "529": 1}
    m = s["messages"]
    assert (m["requests"], m["input_tokens"], m["cache_creation_input_tokens"], m["cache_read_input_tokens"],
            m["output_tokens"]) == (2, 103, 1200, 40000, 77)
    assert m["processed_tokens"] == 103 + 1200 + 40000 + 77 and m["peak_context_tokens"] == 41203
    assert m["by_model"]["claude-haiku-4-5-20251001"] == {"requests": 1, **usage(100, 0, 0, 20)}
    assert s["count_tokens"] == {"requests": 1, "counted_input_tokens": 321}
    assert s["missing_usage_seqs"] == [5] and s["incomplete_stream_seqs"] == [5] and s["proxy_complete"] is False
    assert s["errors"]["by_status"] == {"429": 1, "529": 1}
    assert [e["type"] for e in s["errors"]["list"]] == ["rate_limit_error", "overloaded_error"]
    assert s["first_request"] == "2026-11-24T10:00:00.000+00:00"
    assert s["last_request"] == "2026-11-24T10:00:09.000+00:00"
    assert s["seq_gaps"] == [] and s["duplicate_seqs"] == [] and s["unfinished"] == 0


def test_summarize_finds_a_gap_in_the_sequence(tmp_path):
    log = tmp_path / "proxy.jsonl"
    rows = [LOG_ROWS[0], {**LOG_ROWS[1], "seq": 4}, {**LOG_ROWS[1], "seq": 5}]
    write_log(log, rows)
    s = summarize(log)
    assert s["seq_gaps"] == [2, 3] and s["proxy_complete"] is False
    # Every line is JSON and every request has its usage: only the gap shows that lines are lost.
    assert s["bad_lines"] == 0 and s["missing_usage"] == 0 and s["incomplete_streams"] == 0
    write_log(log, [LOG_ROWS[0], LOG_ROWS[0], LOG_ROWS[1]])
    s = summarize(log)
    assert s["seq_gaps"] == [] and s["duplicate_seqs"] == [1] and s["proxy_complete"] is False
    write_log(log, LOG_ROWS[:2] + [{"seq": 3, "start": "2026-11-24T10:00:06.000+00:00", "path": "/v1/messages",
                                    "status": 200, "unfinished": True}])
    s = summarize(log)
    assert s["unfinished_seqs"] == [3] and s["proxy_complete"] is False


def test_stop_writes_a_line_for_a_request_that_is_still_open(tmp_path, fake_api):
    log = tmp_path / "proxy.jsonl"
    p = RecordingProxy(log, upstream=fake_api.url).start()
    conn, response = post(p.port, REQUEST, {"x-fake-answer": "sse"})
    assert response.status == 200  # the API holds back the rest of the stream until release
    p.stop(wait=0.2)
    fake_api.release.set()
    conn.close()
    [r] = records(log)
    assert r["seq"] == 1 and r["unfinished"] is True and r["status"] == 200 and "usage" not in r
    s = summarize(log)
    assert s["unfinished_seqs"] == [1] and s["proxy_complete"] is False


def test_summarize_empty_log(tmp_path):
    log = tmp_path / "proxy.jsonl"
    log.write_text("")
    s = summarize(log)
    assert s["requests"] == 0 and s["proxy_complete"] is True and s["first_request"] is None


def agent_usage(i, cw, cr, o):
    return {"inputTokens": i, "cacheCreationInputTokens": cw, "cacheReadInputTokens": cr, "outputTokens": o,
            "costUSD": 0.5, "contextWindow": 200000}


def test_cross_check_agrees_over_models_with_other_names(tmp_path):
    log = tmp_path / "proxy.jsonl"
    write_log(log, LOG_ROWS[:2])
    agent = {"claude-opus-4-5": agent_usage(3, 1200, 40100, 57), "claude-haiku-4-5": agent_usage(100, 0, 0, 20)}
    result = cross_check(summarize(log), agent)
    assert result["agree"] is True and result["reason"] == "ok"
    assert result["classes"]["cache_read_input_tokens"] == {"proxy": 40000, "agent": 40100,
                                                           "relative_difference": round(100 / 40100, 6), "agree": True}
    assert result["classes"]["cache_creation_input_tokens"]["agree"] is True
    assert set(result["models"]["proxy"]) == {MODEL, "claude-haiku-4-5-20251001"}
    assert result["models"]["agent"]["claude-haiku-4-5"]["output_tokens"] == 20


def test_cross_check_disagrees(tmp_path):
    log = tmp_path / "proxy.jsonl"
    write_log(log, LOG_ROWS[:2])
    agent = {MODEL: agent_usage(3, 1200, 40000, 57)}  # the haiku request is missing on the agent's side
    result = cross_check(summarize(log), agent)
    assert result["agree"] is False and result["reason"] == "token counts differ: input_tokens, output_tokens"
    assert result["classes"]["input_tokens"]["agree"] is False and result["classes"]["output_tokens"]["agree"] is False
    assert result["classes"]["cache_read_input_tokens"]["agree"] is True


def test_cross_check_zero_cases(tmp_path):
    log = tmp_path / "proxy.jsonl"
    write_log(log, [{**LOG_ROWS[0], "usage": usage(3, 0, 40000, 57)}])
    s = summarize(log)
    both_zero = cross_check(s, {MODEL: agent_usage(3, 0, 40000, 57)})
    assert both_zero["agree"] is True and both_zero["classes"]["cache_creation_input_tokens"]["relative_difference"] == 0
    one_zero = cross_check(s, {MODEL: agent_usage(3, 5, 40000, 57)})
    assert one_zero["agree"] is False and one_zero["classes"]["cache_creation_input_tokens"]["agree"] is False
    assert cross_check(s, {}, tolerance=2.0)["agree"] is False  # never agrees with an empty side, whatever the tolerance


def test_cross_check_never_agrees_on_nothing(tmp_path):
    log = tmp_path / "proxy.jsonl"
    log.write_text("")
    empty = summarize(log)
    for agent in ({}, {MODEL: agent_usage(0, 0, 0, 0)}):
        result = cross_check(empty, agent)
        assert result["agree"] is False and result["reason"] == "the proxy log has no /v1/messages request with usage"
    # A log with only errors and counts has no usage either.
    write_log(log, [{**LOG_ROWS[2], "seq": 1}, {**LOG_ROWS[3], "seq": 2}])
    assert cross_check(summarize(log), {})["reason"] == "the proxy log has no /v1/messages request with usage"
    # The proxy has usage, the agent's side is empty or has only zeros.
    write_log(log, LOG_ROWS[:1])
    s = summarize(log)
    for agent in ({}, {"x": {"costUSD": 1.0}}, {MODEL: agent_usage(0, 0, 0, 0)}):
        result = cross_check(s, agent)
        assert result["agree"] is False and result["reason"] == "the agent's modelUsage has no tokens"


def test_cross_check_does_not_agree_with_an_incomplete_proxy(tmp_path):
    log = tmp_path / "proxy.jsonl"
    # The numbers agree, but a request after the first one is lost (a gap in the sequence).
    write_log(log, [LOG_ROWS[0], {**LOG_ROWS[1], "seq": 3}])
    agent = {MODEL: agent_usage(3, 1200, 40000, 57), "claude-haiku-4-5": agent_usage(100, 0, 0, 20)}
    result = cross_check(summarize(log), agent)
    assert result["agree"] is False and result["reason"] == "the proxy log is not complete"
    assert all(c["agree"] for c in result["classes"].values())  # the numbers per class stay
    assert cross_check({**summarize(log), "seq_gaps": [], "proxy_complete": True}, agent)["agree"] is True


def test_cli_proxy_summary(tmp_path, capsys):
    log = tmp_path / "proxy.jsonl"
    write_log(log, LOG_ROWS[:2])
    assert main(["proxy-summary", str(log)]) == 0
    assert json.loads(capsys.readouterr().out)["messages"]["requests"] == 2
    assert main(["proxy-summary", str(tmp_path / "missing.jsonl")]) == 1


def test_cli_default_port_matches():
    assert cli.PROXY_PORT == proxy.DEFAULT_PORT
