"""codemem's MCP server, warm before the agent starts, and the notes that codemem puts on a search result.

The problem. Claude Code starts its MCP servers when it starts, and sends its first model request at once.
codemem loads its embedding model in the background when its server starts (about 7 s on the run machine). A
search_code call in that time waits for at most `catchup_budget_ms` (4 s, a setting of the config file only),
and is then answered from keywords alone, with a note. In the runs of codemem 041124e the agent's first search
came in turn 1 to 3, and in half of the runs it got the keyword answer.

The gate. In a run of a codemem setup, the container script starts this file before Claude Code, outside the
agent's clock:

  python cmgate.py serve CONFIG      start `codemem mcp` with the run's arguments and environment, do the MCP
                                     handshake, wait until index_status says ready and a search has no note
                                     (wait_ready), write the ready file, then listen on a Unix socket for one
                                     connection, and relay it to the server byte for byte
  python cmgate.py connect SOCKET    the MCP server that Claude Code starts (mcp.json): relay its stdin and
                                     stdout to the socket

So the agent talks to the same codemem process, with the same program, arguments and environment, but its
model and search index are in memory before the agent's first turn. codemem itself does not change. The
handshake of Claude Code goes to the server as a second `initialize`; the MCP library of codemem (mcp 2.3.0,
server/runner.py) answers it and takes the client's protocol version from it.

The file imports only the standard library: the runner copies it into the task's container, where codemem's
own Python runs it. e2e_replay uses the same client and the same wait on the host.
"""

from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---- the notes of codemem on a search_code result

# Each note, and a text that only it holds. The texts come from codemem's code (prompts.py, render.py and
# server.py). The loading note changed after 041124e; both forms are here, so that old runs count too.
NOTES = (
    ("loading", "Note: codemem is still loading its embedding model or its search index"),  # 09c4ef0 and later
    ("loading", "Note: the embedding model is still loading"),  # 041124e
    ("cannot_embed", "Note: codemem cannot embed right now ("),  # the model's load failed, or an endpoint is down
    ("indexing", "Note: the codemem index is still being built ("),
    ("not_fresh", "Search again in a few seconds, or use grep for those files."),  # edits not indexed yet
    ("unchecked_copy", "Note: codemem's index for this checkout started as a copy of another checkout's index"),
    ("not_available", "The codemem index is not available yet."),  # no results at all
)
NOTE_KINDS = ("loading", "cannot_embed", "indexing", "not_fresh", "unchecked_copy", "not_available")
# The notes of an answer from keywords alone: no result came from the vectors.
KEYWORDS_ONLY_KINDS = ("loading", "cannot_embed")


def unwrap(text: str) -> str:
    """The rendered text of a result. The MCP server of codemem 041124e answered {"result": "<text>"}, and
    Claude Code gave the model that JSON. A plain text (codemem 09c4ef0 and later) stays as it is."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return text
    if isinstance(data, dict) and set(data) == {"result"} and isinstance(data["result"], str):
        return data["result"]
    return text


def notes_of(text: str) -> dict:
    """Which of codemem's notes a result has, by kind (NOTE_KINDS), and keywords_only: the answer came from
    keywords alone (the model was loading, or codemem could not embed). Takes either form of unwrap."""
    text = unwrap(text)
    found = {kind: False for kind in NOTE_KINDS}
    for kind, mark in NOTES:
        found[kind] = found[kind] or mark in text
    found["keywords_only"] = any(found[kind] for kind in KEYWORDS_ONLY_KINDS)
    return found


def note_kinds(text: str) -> list[str]:
    """The kinds of the notes of a result, in the order of NOTE_KINDS. Empty: a full search."""
    found = notes_of(text)
    return [kind for kind in NOTE_KINDS if found[kind]]


def full_search(notes: dict) -> bool:
    return not any(notes.values())


# ---- a small MCP client over stdio

class McpError(Exception):
    pass


class McpClient:
    """A small MCP client over stdio: one JSON-RPC message per line. The server's log goes to a file."""

    PROTOCOL = "2025-11-25"

    def __init__(self, argv: list[str], env: dict, log_path: Path, cwd: str | None = None):
        self._log = open(log_path, "ab")
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log, env=env,
                                     cwd=cwd)
        self._lines: queue.Queue = queue.Queue()
        self._next = 0
        threading.Thread(target=self._read, name="mcp-reader", daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _send(self, message: dict) -> None:
        try:
            self.write_raw((json.dumps(message) + "\n").encode("utf-8"))
        except (BrokenPipeError, OSError) as exc:
            raise McpError(f"the MCP server stopped (exit code {self.proc.poll()}): {exc}") from None

    def write_raw(self, data: bytes) -> None:
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def next_line(self, timeout: float | None = None) -> bytes | None:
        """The next line that the server wrote, as it is. None when the server's output has ended."""
        return self._lines.get(timeout=timeout)

    def drain(self) -> int:
        """Drop the lines that the server wrote and nobody read. Returns how many. A None (the end of the
        output) stays."""
        dropped = 0
        while True:
            try:
                line = self._lines.get_nowait()
            except queue.Empty:
                return dropped
            if line is None:
                self._lines.put(None)
                return dropped
            dropped += 1

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})})

    def request(self, method: str, params: dict, timeout: float) -> dict:
        self._next += 1
        rid = self._next
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise McpError(f"no answer to {method} after {timeout:.0f} s")
            try:
                line = self._lines.get(timeout=left)
            except queue.Empty:
                continue
            if line is None:
                self._lines.put(None)
                raise McpError(f"the MCP server stopped (exit code {self.proc.wait(timeout=10)}) during {method}")
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            if "method" in message and "id" in message:  # a request of the server, for example ping
                if message["method"] == "ping":
                    self._send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
                else:
                    self._send({"jsonrpc": "2.0", "id": message["id"],
                                "error": {"code": -32601, "message": "not supported by this client"}})
                continue
            if message.get("id") != rid:
                continue
            if "error" in message:
                raise McpError(f"{method}: {message['error']}")
            return message.get("result") or {}

    def initialize(self, timeout: float, name: str = "cmeval-replay") -> dict:
        result = self.request("initialize", {"protocolVersion": self.PROTOCOL, "capabilities": {},
                                             "clientInfo": {"name": name, "version": "1"}}, timeout)
        self.notify("notifications/initialized")
        return result

    def call_tool(self, name: str, args: dict, timeout: float) -> dict:
        return self.request("tools/call", {"name": name, "arguments": args}, timeout)

    def close(self) -> int | None:
        """End the server: close its input, then wait; stop it when it does not end."""
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            code = self.proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                code = self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                code = self.proc.wait()
        self._log.close()
        return code


def tool_texts(result: dict) -> tuple[str, str]:
    """The text of a tool result, and the text as Claude Code gives it to the model: the JSON of the structured
    content when the server sends one (codemem 041124e sends {"result": "<text>"}), else the text."""
    text = "\n".join(str(c.get("text", "")) for c in result.get("content") or []
                     if isinstance(c, dict) and c.get("type") == "text")
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return unwrap(text), json.dumps(structured, ensure_ascii=False, separators=(",", ":"))
    return unwrap(text), text


def status_json(text: str) -> dict | None:
    """The JSON line at the end of index_status: state, progress, chunks, vectors, models_loaded, stale."""
    try:
        data = json.loads(text.rsplit("\n\n", 1)[-1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


WARMUP_QUERY = "load the embedding model"
READY_POLL_S = 2.0


def wait_ready(client: McpClient, timeout: float, call_timeout: float, poll: float | None = None) -> dict:
    """Wait until index_status says ready, then until a search is a full search: no note of NOTES. Returns the
    status, its text, the number of warm-up searches and the seconds it took."""
    poll = READY_POLL_S if poll is None else poll
    deadline = time.monotonic() + timeout
    t0 = time.monotonic()
    while True:
        text, _ = tool_texts(client.call_tool("index_status", {}, call_timeout))
        status = status_json(text)
        if status and status.get("state") == "ready":
            break
        if time.monotonic() > deadline:
            state = status.get("state") if status else None
            raise McpError(f"the index was not ready after {timeout:.0f} s (state {state}). A long state of "
                           "indexing or updating can mean that codemem embeds the repo again, for example "
                           "because the index was built on another device")
        time.sleep(poll)
    status_text = text
    warmups = 0
    while True:
        text, _ = tool_texts(client.call_tool("search_code", {"query": WARMUP_QUERY, "k": 1}, call_timeout))
        warmups += 1
        if full_search(notes_of(text)):
            return {"status": status, "status_text": status_text.rsplit("\n\n", 1)[0], "warmup_searches": warmups,
                    "ready_s": round(time.monotonic() - t0, 1)}
        if time.monotonic() > deadline:
            raise McpError(f"searches were not full searches after {timeout:.0f} s: {note_kinds(text)}")
        time.sleep(poll)


# ---- the gate in the container

def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _log(message: str) -> None:
    print(f"cmgate {time.strftime('%H:%M:%S')} {message}", file=sys.stderr, flush=True)


def relay(listener: socket.socket, client: McpClient, accept_timeout: float | None) -> int | None:
    """Take one connection and relay it to the server until either side ends. Returns the server's exit code."""
    listener.settimeout(accept_timeout)
    try:
        conn, _ = listener.accept()
    except socket.timeout:
        _log(f"no connection after {accept_timeout} s; stopping the server")
        listener.close()
        return client.close()
    listener.close()  # one agent, one connection
    conn.settimeout(None)
    dropped = client.drain()
    _log(f"connected; relaying (dropped {dropped} lines that the server wrote before)")

    def to_client() -> None:
        while (line := client.next_line()) is not None:
            try:
                conn.sendall(line)
            except OSError:
                break
        try:
            conn.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    down = threading.Thread(target=to_client, name="cmgate-down", daemon=True)
    down.start()
    while True:
        try:
            data = conn.recv(65536)
        except OSError:
            break
        if not data:
            break
        try:
            client.write_raw(data)
        except OSError:
            break
    _log("the connection ended; stopping the server")
    code = client.close()
    down.join(timeout=10)
    conn.close()
    _log(f"the server ended with exit code {code}")
    return code


def serve(config: dict) -> int:
    """Start codemem's MCP server, wait until it is warm, write the ready file, then relay one connection.
    The ready file holds ok, and either the status and the seconds or the error."""
    t0 = time.monotonic()
    env = {k: v for k, v in os.environ.items() if not k.startswith("CODEMEM_")}
    env.update(config["env"])
    record: dict = {"ok": False, "argv": config["argv"]}
    client, listener = None, None
    try:
        client = McpClient(config["argv"], env, Path(config["log"]), cwd=config.get("cwd"))
        init = client.initialize(config["call_timeout_s"], name="cmeval-gate")
        ready = wait_ready(client, config["timeout_s"], config["call_timeout_s"], config.get("poll_s"))
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(config["socket"])
        listener.listen(1)
        record.update(ok=True, server=init.get("serverInfo"), **ready)
    except (McpError, OSError, ValueError, KeyError) as exc:
        record["error"] = str(exc)
    record["seconds"] = round(time.monotonic() - t0, 3)
    _write_atomic(Path(config["ready_file"]), json.dumps(record, indent=1) + "\n")
    if not record["ok"]:
        _log(f"not warm: {record['error']}")
        if client is not None:
            client.close()
        return 1
    _log(f"warm after {record['seconds']} s ({record['warmup_searches']} warm-up searches)")
    relay(listener, client, config.get("accept_timeout_s"))
    return 0


def connect(path: str) -> int:
    """Relay stdin and stdout to the gate's socket. Claude Code starts this as the codemem MCP server."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(path)
    except OSError as exc:
        print(f"cmgate connect: cannot reach the codemem server at {path}: {exc}", file=sys.stderr, flush=True)
        return 1

    def up() -> None:
        try:
            while data := os.read(0, 65536):
                sock.sendall(data)
        except OSError:
            pass
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    threading.Thread(target=up, name="cmgate-up", daemon=True).start()
    while True:
        try:
            data = sock.recv(65536)
        except OSError:
            break
        if not data:
            break
        view = memoryview(data)
        try:
            while view:
                view = view[os.write(1, view):]
        except OSError:  # Claude Code closed its end
            break
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "serve":
        return serve(json.loads(Path(argv[1]).read_text(encoding="utf-8")))
    if len(argv) == 2 and argv[0] == "connect":
        return connect(argv[1])
    print("usage: cmgate.py serve CONFIG | connect SOCKET", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
