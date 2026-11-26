"""An MCP server's tools as one shell command, for an agent that has only a shell (plan section 4.2).

mini-SWE-agent gives the model a shell and nothing else, so the model cannot call an MCP tool. This file puts
the tools of an MCP server on the shell's path, without changing what they return:

  serve   starts the MCP server as a child process, does the MCP handshake, and then waits on a Unix socket.
          It writes info.json (the server's name, its instructions, and each tool's name, description and
          input schema), and one line to calls.jsonl for each tool call
  call    one tool call from the shell. It reads info.json to know the tools, sends the call to the socket and
          prints the text that the tool returned

So `codemem search_code "where do users log in"` in the container returns the text that codemem's MCP tool
`search_code` returns to Claude Code, from one long-lived server process that keeps the model loaded and follows
the agent's edits, as in the setup `tool` of Claude Code.

The file uses only the standard library, and it does not import cmeval: the runner copies it into the run's
folder, and the container runs it with the Python of codemem's environment.

Exit codes of `call`: 0 the tool answered, 1 the tool answered with an error, 2 the command line is wrong,
3 the server cannot be reached, 4 no answer in time.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import socketserver
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

PROTOCOL_VERSION = "2025-06-18"
DEFAULT_DIR = "/tmp/cmbridge"
DIR_ENV = "CMEVAL_BRIDGE_DIR"
CALL_TIMEOUT_ENV = "CMEVAL_BRIDGE_CALL_TIMEOUT"
HANDSHAKE_TIMEOUT = 120.0
CALL_TIMEOUT = 120.0
MAX_LOGGED_CHARS = 100_000
ALIASES = {"search": "search_code", "get": "get_chunk", "status": "index_status", "refresh": "refresh_index"}

EXIT_TOOL_ERROR, EXIT_USAGE, EXIT_UNREACHABLE, EXIT_TIMEOUT = 1, 2, 3, 4


def bridge_dir() -> Path:
    return Path(os.environ.get(DIR_ENV) or DEFAULT_DIR)


# ---- the MCP side

class McpError(Exception):
    """The server answered a request with an error, went away, or did not answer in time."""


class McpProcess:
    """An MCP server on stdio: newline-delimited JSON-RPC. One thread reads its answers."""

    def __init__(self, command: list[str], *, env: dict | None = None, stderr=None, cwd: str | None = None) -> None:
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, env=env,
                                     cwd=cwd)
        self._ids = 0
        self._lock = threading.Lock()  # guards the ids, the waiters and the server's stdin
        self._waiters: dict[int, dict] = {}
        self._reader = threading.Thread(target=self._read, name="mcp-reader", daemon=True)
        self._reader.start()

    def _send(self, message: dict) -> None:
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def _read(self) -> None:
        for raw in self.proc.stdout:
            try:
                message = json.loads(raw)
            except ValueError:
                continue  # stdout carries protocol messages only; a stray line is skipped
            if not isinstance(message, dict):
                continue
            if "method" in message:
                # A request from the server (for example roots/list): this client offers nothing. A message
                # without an id is a notification and needs no answer.
                if "id" in message:
                    with self._lock:
                        try:
                            self._send({"jsonrpc": "2.0", "id": message["id"],
                                        "error": {"code": -32601, "message": "not supported by this client"}})
                        except OSError:
                            pass
                continue
            with self._lock:
                waiter = self._waiters.get(message.get("id"))
            if waiter is not None:
                waiter["answer"] = message
                waiter["done"].set()
        # The server closed its output: wake everyone who still waits.
        with self._lock:
            waiters = list(self._waiters.values())
        for waiter in waiters:
            waiter["done"].set()

    def alive(self) -> bool:
        return self.proc.poll() is None

    def notify(self, method: str, params: dict | None = None) -> None:
        with self._lock:
            self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})})

    def request(self, method: str, params: dict | None = None, timeout: float = CALL_TIMEOUT) -> dict:
        waiter = {"done": threading.Event(), "answer": None}
        with self._lock:
            self._ids += 1
            request_id = self._ids
            self._waiters[request_id] = waiter
            try:
                self._send({"jsonrpc": "2.0", "id": request_id, "method": method,
                            **({"params": params} if params is not None else {})})
            except OSError as exc:
                del self._waiters[request_id]
                raise McpError(f"the server does not take requests: {exc}") from None
        try:
            if not waiter["done"].wait(timeout):
                raise McpError(f"no answer to {method} in {timeout:g} s")
        finally:
            with self._lock:
                self._waiters.pop(request_id, None)
        answer = waiter["answer"]
        if answer is None:
            raise McpError(f"the server went away before it answered {method} (exit code {self.proc.poll()})")
        if "error" in answer:
            error = answer["error"] if isinstance(answer["error"], dict) else {"message": str(answer["error"])}
            raise McpError(f"{method}: {error.get('message')} (code {error.get('code')})")
        result = answer.get("result")
        return result if isinstance(result, dict) else {}

    def handshake(self, timeout: float = HANDSHAKE_TIMEOUT) -> dict:
        """initialize, then the list of tools. Returns what info.json holds."""
        t0 = time.monotonic()
        init = self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                           "clientInfo": {"name": "cmeval-bridge", "version": "1"}}, timeout)
        self.notify("notifications/initialized")
        tools, cursor = [], None
        while True:
            page = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout)
            tools += [t for t in page.get("tools") or [] if isinstance(t, dict) and isinstance(t.get("name"), str)]
            cursor = page.get("nextCursor")
            if not cursor:
                break
        return {"server": init.get("serverInfo"), "protocol_version": init.get("protocolVersion"),
                "instructions": init.get("instructions") or "",
                "tools": [{"name": t["name"], "description": t.get("description") or "",
                           "input_schema": t.get("inputSchema") or {}} for t in tools],
                "handshake_s": round(time.monotonic() - t0, 3)}

    def call(self, tool: str, arguments: dict, timeout: float = CALL_TIMEOUT) -> tuple[str, bool]:
        """One tool call: the text of the answer, and whether the tool marked it as an error."""
        result = self.request("tools/call", {"name": tool, "arguments": arguments}, timeout)
        return result_text(result), bool(result.get("isError"))

    def stop(self) -> None:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def result_text(result: dict) -> str:
    """The text blocks of a tools/call result, in order. A result with no text block gives its structured
    content as JSON, so that nothing is lost."""
    blocks = result.get("content") if isinstance(result.get("content"), list) else []
    texts = [str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    if texts:
        return "\n".join(texts)
    structured = result.get("structuredContent")
    return json.dumps(structured, ensure_ascii=False) if structured is not None else ""


# ---- serve

class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        bridge: Bridge = self.server.bridge  # type: ignore[attr-defined]
        try:
            request = json.loads(self.rfile.readline() or b"null")
        except ValueError:
            request = None
        if not isinstance(request, dict) or not isinstance(request.get("tool"), str):
            answer = {"ok": False, "error": "a request is one JSON line with tool and arguments"}
        else:
            arguments = request.get("arguments") if isinstance(request.get("arguments"), dict) else {}
            answer = bridge.call(request["tool"], arguments, float(request.get("timeout") or CALL_TIMEOUT))
        try:
            self.wfile.write((json.dumps(answer, ensure_ascii=False) + "\n").encode("utf-8"))
        except OSError:
            pass  # the caller went away (for example its command hit the time limit)


class _SocketServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


class Bridge:
    """The MCP server process, the socket, and the log of calls."""

    def __init__(self, folder: Path, command: list[str]) -> None:
        self.folder = folder
        self.command = command
        self.mcp: McpProcess | None = None
        self._log_lock = threading.Lock()
        self._n = 0

    def start(self) -> dict:
        self.folder.mkdir(parents=True, exist_ok=True)
        stderr = open(self.folder / "server.log", "ab")
        self.mcp = McpProcess(self.command, stderr=stderr)
        info = self.mcp.handshake()
        info.update(command=self.command, started_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        # info.json appears only when the server is ready: `call` and the runner wait for it. Written beside
        # and renamed, so that nobody reads half a file.
        part = self.folder / "info.json.part"
        part.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        part.replace(self.folder / "info.json")
        return info

    def call(self, tool: str, arguments: dict, timeout: float) -> dict:
        assert self.mcp is not None
        start = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        t0 = time.monotonic()
        try:
            text, is_error = self.mcp.call(tool, arguments, timeout)
            answer = {"ok": True, "text": text, "is_error": is_error}
        except McpError as exc:
            answer = {"ok": False, "error": str(exc), "timeout": "no answer" in str(exc)}
        ms = round((time.monotonic() - t0) * 1000, 1)
        with self._log_lock:
            self._n += 1
            text = answer.get("text") or ""
            line = {"n": self._n, "start": start, "tool": tool, "arguments": arguments, "ms": ms,
                    "ok": answer["ok"], "is_error": answer.get("is_error"), "error": answer.get("error"),
                    "chars": len(text), "text": text[:MAX_LOGGED_CHARS], "cut": len(text) > MAX_LOGGED_CHARS}
            with open(self.folder / "calls.jsonl", "a", encoding="utf-8") as log:
                log.write(json.dumps({k: v for k, v in line.items() if v is not None}, ensure_ascii=False) + "\n")
        return {**answer, "ms": ms}


def serve(folder: Path, command: list[str]) -> int:
    bridge = Bridge(folder, command)
    socket_path = folder / "socket"
    try:
        bridge.start()
    except (McpError, OSError) as exc:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "failed.txt").write_text(f"{exc}\n", encoding="utf-8")
        print(f"cm_bridge: the MCP server did not start: {exc}", file=sys.stderr)
        if bridge.mcp is not None:
            bridge.mcp.stop()
        return 1
    socket_path.unlink(missing_ok=True)
    with _SocketServer(str(socket_path), _Handler) as server:
        server.bridge = bridge  # type: ignore[attr-defined]
        watcher = threading.Thread(target=_stop_with_the_server, args=(bridge, server), daemon=True)
        watcher.start()
        try:
            server.serve_forever(poll_interval=0.2)
        finally:
            bridge.mcp.stop()
    return 0


def _stop_with_the_server(bridge: Bridge, server: _SocketServer) -> None:
    """When the MCP server process ends, the bridge ends too: a later `call` then fails at once with exit code 3."""
    while bridge.mcp is not None and bridge.mcp.alive():
        time.sleep(0.5)
    (bridge.folder / "socket").unlink(missing_ok=True)
    server.shutdown()


# ---- call

def _kind(schema: dict) -> str:
    """The JSON type of a property: its type, or the first type of anyOf that is not null."""
    if isinstance(schema.get("type"), str):
        return schema["type"]
    for option in schema.get("anyOf") or []:
        if isinstance(option, dict) and option.get("type") not in (None, "null"):
            return option["type"]
    return "string"


def _convert(name: str, value: str, schema: dict):
    kind = _kind(schema)
    try:
        if kind == "integer":
            return int(value)
        if kind == "number":
            return float(value)
    except ValueError:
        raise UsageError(f"--{name} takes a number, not {value!r}") from None
    if kind == "boolean":
        if value.lower() in ("true", "1", "yes"):
            return True
        if value.lower() in ("false", "0", "no"):
            return False
        raise UsageError(f"--{name} takes true or false, not {value!r}")
    if kind == "array":
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


class UsageError(Exception):
    pass


def _properties(tool: dict) -> tuple[dict, list[str]]:
    schema = tool.get("input_schema") or {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = [name for name in schema.get("required") or [] if name in properties]
    return properties, required


def usage_line(tool: dict, program: str = "codemem") -> str:
    """For example: codemem search_code "<query>" [--k N] [--path_prefix TEXT] [--kinds A,B] [--tests TEXT]"""
    properties, required = _properties(tool)
    parts = [program, tool["name"]] + [f'"<{name}>"' for name in required]
    for name, schema in properties.items():
        if name not in required:
            shown = {"integer": "N", "number": "N", "boolean": "true|false", "array": "A,B"}.get(_kind(schema), "TEXT")
            parts.append(f"[--{name} {shown}]")
    return " ".join(parts)


def usage_text(info: dict, program: str = "codemem") -> str:
    lines = [f"{program}: the tools of the {(info.get('server') or {}).get('name') or 'MCP'} server, as commands.", ""]
    for tool in info.get("tools") or []:
        lines.append("  " + usage_line(tool, program))
        if tool.get("description"):
            lines.append("      " + " ".join(str(tool["description"]).split()))
    return "\n".join(lines)


def parse_arguments(tool: dict, words: list[str]) -> dict:
    """The arguments of a tool call from the words of the command line. Words without -- fill the required
    properties in order. When the tool has one required property, all such words together are its value, so a
    query that was not put in quotes still arrives whole."""
    properties, required = _properties(tool)
    arguments: dict = {}
    plain: list[str] = []
    i = 0
    while i < len(words):
        word = words[i]
        if word == "--":
            plain += words[i + 1:]
            break
        if word.startswith("--") and len(word) > 2:
            name, eq, value = word[2:].partition("=")
            name = name.replace("-", "_")
            if name not in properties:
                known = ", ".join(f"--{p}" for p in properties if p not in required) or "none"
                raise UsageError(f"{tool['name']} has no option --{name} (options: {known})")
            if not eq:
                if i + 1 >= len(words):
                    raise UsageError(f"--{name} needs a value")
                i += 1
                value = words[i]
            arguments[name] = _convert(name, value, properties[name])
        else:
            plain.append(word)
        i += 1
    missing = [name for name in required if name not in arguments]
    if len(missing) == 1 and plain:
        arguments[missing[0]] = _convert(missing[0], " ".join(plain), properties[missing[0]])
        plain, missing = [], []
    else:
        for name in list(missing):
            if not plain:
                break
            arguments[name] = _convert(name, plain.pop(0), properties[name])
            missing.remove(name)
    if missing:
        raise UsageError(f"{tool['name']} needs {', '.join(missing)}")
    if plain:
        raise UsageError(f"{tool['name']}: too many words: {' '.join(plain)}")
    return arguments


def call(words: list[str], folder: Path, program: str = "codemem") -> int:
    info_path = folder / "info.json"
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"{program}: the server is not running (no {info_path})", file=sys.stderr)
        return EXIT_UNREACHABLE
    if not words or words[0] in ("-h", "--help", "help"):
        print(usage_text(info, program))
        return 0 if words else EXIT_USAGE
    tools = {t["name"]: t for t in info.get("tools") or []}
    name = words[0] if words[0] in tools else ALIASES.get(words[0], words[0])
    if name not in tools:
        print(f"{program}: no tool {words[0]!r}.\n\n{usage_text(info, program)}", file=sys.stderr)
        return EXIT_USAGE
    if any(word in ("-h", "--help") for word in words[1:]):
        print("  " + usage_line(tools[name], program) + "\n      " + " ".join(str(tools[name]["description"]).split()))
        return 0
    try:
        arguments = parse_arguments(tools[name], words[1:])
    except UsageError as exc:
        print(f"{program}: {exc}\nusage: {usage_line(tools[name], program)}", file=sys.stderr)
        return EXIT_USAGE
    timeout = float(os.environ.get(CALL_TIMEOUT_ENV) or CALL_TIMEOUT)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout + 5)
            sock.connect(str(folder / "socket"))
            sock.sendall((json.dumps({"tool": name, "arguments": arguments, "timeout": timeout}) + "\n").encode("utf-8"))
            data = b""
            while not data.endswith(b"\n"):
                piece = sock.recv(65536)
                if not piece:
                    break
                data += piece
    except TimeoutError:
        print(f"{program}: no answer in {timeout:g} s", file=sys.stderr)
        return EXIT_TIMEOUT
    except OSError as exc:
        print(f"{program}: the server cannot be reached: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    try:
        answer = json.loads(data)
    except ValueError:
        print(f"{program}: the server closed the connection without an answer", file=sys.stderr)
        return EXIT_UNREACHABLE
    if not answer.get("ok"):
        print(f"{program}: {answer.get('error')}", file=sys.stderr)
        return EXIT_TIMEOUT if answer.get("timeout") else EXIT_UNREACHABLE
    print(answer.get("text") or "")
    return EXIT_TOOL_ERROR if answer.get("is_error") else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["call"]:
        # No argparse here: every word after `call` belongs to the tool, also --help and --k.
        program = os.environ.get("CMEVAL_BRIDGE_PROGRAM") or "codemem"
        return call(argv[1:], bridge_dir(), program)
    parser = argparse.ArgumentParser(prog="cm_bridge", description="the tools of an MCP server as a shell command")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("serve", help="start the MCP server and wait for calls")
    p.add_argument("--dir", type=Path, default=None, help=f"folder of the socket, info.json and the logs "
                   f"(default ${DIR_ENV} or {DEFAULT_DIR})")
    p.add_argument("server", nargs=argparse.REMAINDER, help="-- the MCP server's command")
    sub.add_parser("call", help="call a tool: call TOOL [words] [--option value]")
    args = parser.parse_args(argv)
    command = args.server[1:] if args.server[:1] == ["--"] else args.server
    if not command:
        parser.error("serve needs the MCP server's command after --")
    return serve(args.dir or bridge_dir(), command)


if __name__ == "__main__":
    sys.exit(main())
