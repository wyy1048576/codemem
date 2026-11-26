"""The gate (codemem_gate.py): codemem's MCP server warm before the agent, and the bridge to it. A stand-in
server answers the MCP handshake, index_status and search_code over stdio, and logs what it got."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from cmeval import codemem_gate as gate

GATE = Path(gate.__file__)

SERVER = r'''
import json, os, sys

mode = os.environ.get("FAKE_MODE", "")
if mode == "crash":
    sys.exit(4)
log = open(os.environ["FAKE_LOG"], "a")
print(json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {"data": "hello"}}), flush=True)
status = searches = 0
for line in sys.stdin:
    msg = json.loads(line)
    log.write(json.dumps({"method": msg.get("method"), "id": msg.get("id"), "params": msg.get("params"),
                          "home": os.environ.get("CODEMEM_HOME"), "other": os.environ.get("CODEMEM_OTHER")}) + "\n")
    log.flush()
    if "id" not in msg:
        continue
    if msg["method"] == "initialize":
        result = {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                  "serverInfo": {"name": "codemem", "version": "fake"}}
    elif msg["params"]["name"] == "index_status":
        status += 1
        state = "ready" if status > 1 and mode != "never" else "indexing"
        text = f"state: {state}\nsearch index: exact (faiss)\n\n" + json.dumps({"state": state})
        result = {"content": [{"type": "text", "text": text}]}
    else:
        searches += 1
        text = "1. a.py:1-2  f  [id 1]"
        if searches == 1:
            text += ("\n\nNote: codemem is still loading its embedding model or its search index (the first "
                     "searches after it starts); these results come from keyword matching only.")
        result = {"content": [{"type": "text", "text": text}]}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
    if searches == 2 and msg["method"] == "tools/call" and msg["params"]["name"] == "search_code":
        # a message after the warm-up, before the agent connects: the gate drops it
        print(json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {"data": "late"}}),
              flush=True)
'''


@pytest.fixture
def place(tmp_path, monkeypatch):
    """The gate's folder (short: a Unix socket path has a limit of about 100 characters), its config, and the
    stand-in server."""
    folder = Path(tempfile.mkdtemp(prefix="cmg-", dir="/tmp"))
    server = tmp_path / "server.py"
    server.write_text(SERVER)
    log = tmp_path / "server-calls.log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("CODEMEM_OTHER", "from the caller")  # must not reach codemem
    config = {"argv": [sys.executable, str(server)], "env": {"CODEMEM_HOME": "/home/agent/.codemem"},
              "cwd": str(tmp_path), "socket": str(folder / "codemem.sock"), "ready_file": str(folder / "warm.json"),
              "log": str(folder / "server.log"), "timeout_s": 20, "call_timeout_s": 10, "poll_s": 0.05,
              "accept_timeout_s": 20}
    path = folder / "cmgate.json"
    path.write_text(json.dumps(config))
    yield {"folder": folder, "config": config, "path": path, "log": log}
    shutil.rmtree(folder, ignore_errors=True)


def _start(place, env=None):
    return subprocess.Popen([sys.executable, str(GATE), "serve", str(place["path"])], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env={**os.environ, **(env or {})})


def _wait_file(path: Path, proc, seconds=20) -> dict:
    deadline = time.monotonic() + seconds
    while not path.exists():
        assert proc.poll() is None or path.exists(), proc.stderr.read().decode()
        assert time.monotonic() < deadline
        time.sleep(0.02)
    return json.loads(path.read_text())


def _ask(proc, rid, method, params):
    proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n").encode())
    proc.stdin.flush()
    while True:
        message = json.loads(proc.stdout.readline())
        if message.get("id") == rid:
            return message


def test_the_gate_warms_codemem_and_relays_one_connection(place):
    daemon = _start(place)
    warm = _wait_file(Path(place["config"]["ready_file"]), daemon)
    assert warm["ok"] and warm["warmup_searches"] == 2 and warm["status"] == {"state": "ready"}
    assert warm["status_text"] == "state: ready\nsearch index: exact (faiss)"
    assert warm["server"] == {"name": "codemem", "version": "fake"} and warm["seconds"] >= warm["ready_s"]

    bridge = subprocess.Popen([sys.executable, str(GATE), "connect", place["config"]["socket"]],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    init = _ask(bridge, 1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "agent"}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    bridge.stdin.write(b'{"jsonrpc": "2.0", "method": "notifications/initialized"}\n')
    answer = _ask(bridge, 2, "tools/call", {"name": "search_code", "arguments": {"query": "q"}})
    text = answer["result"]["content"][0]["text"]
    assert gate.note_kinds(text) == [] and text.startswith("1. a.py")
    bridge.stdin.close()
    assert bridge.wait(timeout=20) == 0
    assert daemon.wait(timeout=20) == 0  # the connection ended: the gate stops codemem and ends

    calls = [json.loads(line) for line in place["log"].read_text().splitlines()]
    inits = [c["params"]["clientInfo"]["name"] for c in calls if c["method"] == "initialize"]
    assert inits == ["cmeval-gate", "agent"]
    # the agent's request ids reach the server as the agent sent them
    assert [c["id"] for c in calls if c["method"] == "tools/call"][-1] == 2
    assert {c["home"] for c in calls} == {"/home/agent/.codemem"} and {c["other"] for c in calls} == {None}
    err = daemon.stderr.read().decode()
    assert "warm after" in err and "dropped 1 lines" in err  # the server's message before the connection
    assert "server ended with exit code 0" in err


def test_a_server_that_is_never_ready(place):
    place["path"].write_text(json.dumps({**place["config"], "timeout_s": 0.3}))
    daemon = _start(place, {"FAKE_MODE": "never"})
    assert daemon.wait(timeout=20) == 1
    warm = json.loads(Path(place["config"]["ready_file"]).read_text())
    assert warm["ok"] is False and warm["error"].startswith("the index was not ready after 0 s (state indexing)")
    assert not Path(place["config"]["socket"]).exists()


def test_a_server_that_stops(place):
    daemon = _start(place, {"FAKE_MODE": "crash"})
    assert daemon.wait(timeout=20) == 1
    warm = json.loads(Path(place["config"]["ready_file"]).read_text())
    assert not warm["ok"] and "stopped (exit code 4)" in warm["error"]


def test_connect_without_a_gate(tmp_path):
    proc = subprocess.run([sys.executable, str(GATE), "connect", "/tmp/no-such-cmgate.sock"], capture_output=True,
                          text=True, stdin=subprocess.DEVNULL, timeout=20)
    assert proc.returncode == 1 and "cannot reach the codemem server" in proc.stderr
    assert subprocess.run([sys.executable, str(GATE)], capture_output=True, timeout=20).returncode == 2


def test_notes_of_both_forms():
    new = ("1. a.py:1-2  f  [id 1]\n\nNote: codemem is still loading its embedding model or its search index (the "
           "first searches after it starts); these results come from keyword matching only.")
    old = json.dumps({"result": "1. a.py:1-2  f  [id 1]\n\nNote: the embedding model is still loading (the first "
                                "search after codemem starts); these results come from keyword matching only."})
    for text in (new, old):
        notes = gate.notes_of(text)
        assert notes["loading"] and notes["keywords_only"] and gate.note_kinds(text) == ["loading"]
    building = "Note: the codemem index is still being built (40% done); results may be incomplete."
    assert gate.note_kinds(building) == ["indexing"] and not gate.notes_of(building)["keywords_only"]
    assert gate.full_search(gate.notes_of("1. a.py:1-2  f  [id 1]"))
    assert gate.unwrap('{"result": "x"}') == "x" and gate.unwrap('{"result": "x", "y": 1}') == '{"result": "x", "y": 1}'
