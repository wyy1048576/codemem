"""End-to-end runs and their scores: the parts that need no Docker."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from cmeval import e2e_index, e2e_run
from cmeval import generate as gen
from cmeval.cli import main
from cmeval.e2e_run import RunSettings
from cmeval.e2e_score import format_score, score
from cmeval.tasks import save_tasks

from conftest import FIXTURES

STREAM = FIXTURES / "e2e_stream.jsonl"
TOOL_STREAM = FIXTURES / "e2e_stream_tool.jsonl"
FAKE_TOKEN = "FAKE-LOGIN-VALUE-1"
INIT = json.loads(STREAM.read_text().splitlines()[0])
GREP = e2e_run.SETUPS["grep"]
TOOL = e2e_run.SETUPS["tool"]
TOOL_INIT = json.loads(TOOL_STREAM.read_text().splitlines()[0])


def _events(path=STREAM):
    return [json.loads(line) for line in path.read_text().splitlines()]


# ---- pure parts

def test_prompt_frame_v1(make_task):
    prompt = e2e_run.make_prompt(make_task(query="Title\n\nBody text.\n"))
    assert prompt == (
        "The repository in the current directory has the issue below. Change the code of the repository so that "
        "the issue is resolved. Work on your own until you are done: nobody can answer questions.\n\n"
        "<issue>\nTitle\n\nBody text.\n</issue>\n")


def test_setups_and_models():
    assert e2e_run.get_setup("grep").mcp_config == {"mcpServers": {}}
    assert e2e_run.get_setup("tool").codemem and not e2e_run.get_setup("grep").codemem
    with pytest.raises(gen.GenerateError, match="not built yet"):
        e2e_run.get_setup("placebo")
    with pytest.raises(gen.GenerateError, match="no such setup"):
        e2e_run.get_setup("nope")
    e2e_run.check_model("claude-haiku-5-5")
    e2e_run.check_model("claude-sonnet-5-5-20261001")
    for alias in ("haiku", "sonnet", "opus", "claude-sonnet-latest", "default"):
        with pytest.raises(gen.GenerateError, match="full model id"):
            e2e_run.check_model(alias)


def test_parse_stream(tmp_path):
    parsed = e2e_run.parse_stream(STREAM)
    assert parsed["init"]["claude_code_version"] == "2.1.332"
    assert parsed["result"]["num_turns"] == 5
    assert len(parsed["events"]) == 15 and parsed["bad_lines"] == 0
    cut = tmp_path / "cut.jsonl"
    cut.write_text("\n".join(STREAM.read_text().splitlines()[:4]) + '\n{"type": "assi')
    parsed = e2e_run.parse_stream(cut)
    assert parsed["result"] is None and parsed["bad_lines"] == 1 and len(parsed["events"]) == 4
    assert e2e_run.parse_stream(tmp_path / "missing.jsonl")["init"] is None


def test_check_setup():
    assert e2e_run.check_setup(INIT, GREP, "claude-haiku-5-5") == []
    assert e2e_run.check_setup(None, GREP, "claude-haiku-5-5") == ["no init event"]
    bad = {**INIT, "mcp_servers": [{"name": "codemem", "status": "failed"}], "permissionMode": "default",
           "apiKeySource": "ANTHROPIC_API_KEY", "model": "claude-sonnet-5-5", "tools": INIT["tools"] + ["WebFetch"]}
    failed = e2e_run.check_setup(bad, GREP, "claude-haiku-5-5")
    assert failed == ["mcp_servers are ['codemem'], expected []", "mcp server codemem is failed",
                      "permissionMode is default", "apiKeySource is ANTHROPIC_API_KEY",
                      "model is claude-sonnet-5-5, expected claude-haiku-5-5", "web tools are loaded: WebFetch"]
    tool = e2e_run.Setup("tool", {"mcpServers": {}}, ("codemem",), checks=(lambda init: ["extra"],))
    good = {**INIT, "mcp_servers": [{"name": "codemem", "status": "connected"}]}
    assert e2e_run.check_setup(good, tool, "claude-haiku-5-5") == ["extra"]


def test_classify_end():
    ok = {"subtype": "success", "is_error": False}

    def end(result, code, **kw):
        return e2e_run.classify_end(result, code, agent_s=kw.pop("agent_s", 60.0), time_limit_s=3000, **kw)

    assert end(ok, 0) == "finished"
    assert end(ok, 1) == "error"
    assert end({"subtype": "success", "is_error": True}, 0) == "error"
    assert end({"subtype": "error_during_execution", "is_error": True}, 1) == "error"
    assert end(None, 0) == "error" and end(None, None) == "error"
    assert end(None, 124) == "time limit"
    assert end(None, 137, agent_s=3030.0) == "time limit"
    assert end(None, 137, agent_s=100.0) == "error"
    assert end(None, 137, turn_limited=True) == "turn limit"
    assert end(ok, 0, turn_limited=True, usage_evidence={"x": 1}) == "usage limit"


def test_usage_limit_evidence():
    records = [{"seq": 1, "status": 200},
               {"seq": 2, "status": 429, "error": {"type": "rate_limit_error", "message": "limit"},
                "rate_limit_headers": {"anthropic-ratelimit-unified-reset": "1795000000", "retry-after": "60",
                                       "anthropic-ratelimit-unified-status": "rejected"}}]
    evidence = e2e_run.usage_limit_evidence(records, None)
    assert evidence["proxy_429_count"] == 1 and evidence["proxy_429"][0]["seq"] == 2
    assert evidence["reset"] == {"anthropic-ratelimit-unified-reset": "1795000000", "retry-after": "60"}
    hint = e2e_run.reset_hint(evidence)
    assert "anthropic-ratelimit-unified-reset=1795000000 (2026-11-18" in hint and "retry-after=60" in hint
    text = {"is_error": True, "result": "Claude AI usage limit reached|1795000000"}
    assert e2e_run.usage_limit_evidence([], text)["result_text"].startswith("Claude AI usage limit")
    # The agent's own words about a rate limit are not a usage limit.
    assert e2e_run.usage_limit_evidence([], {"is_error": False, "result": "fixed the rate limit bug"}) is None
    assert e2e_run.usage_limit_evidence(records[:1], None) is None
    assert e2e_run.reset_hint(None) == "no reset time in the headers"


def test_turn_counter_counts_message_ids():
    counter = e2e_run.TurnCounter()
    starts = [counter.feed(e) for e in _events()]
    assert counter.turns == 5 and len(counter.sub) == 2
    assert sum(starts) == 5  # a second event of msg_1 and the subagent's events start no turn


def test_count_steps():
    steps = e2e_run.count_steps(_events(), ["auth/sessions.py"])
    assert (steps["turns"], steps["subagent_turns"]) == (5, 2)
    assert steps["tool_calls"] == {"Bash": 1, "Task": 1, "Read": 1, "Edit": 1}
    assert steps["subagent_tool_calls"] == {"Read": 1}
    assert steps["searches"] == {"content": 1, "files": 0, "programs": {"grep": 1}}
    # The subagent's Read is counted apart.
    assert steps["views"]["files_viewed"] == ["auth/sessions.py"]
    assert steps["subagent_files_viewed"] == ["tests/test_sessions.py"]
    assert steps["first_edit_turn"] == 4 and steps["turns_before_first_edit"] == 3
    assert steps["gold"] == {"auth/sessions.py": {"surfaced": 1, "opened": 3, "edited": 4, "named_by_agent": 3}}
    # The names of version 1 stay, as copies.
    assert steps["gold_file_read"] is True and steps["first_gold_read_turn"] == 3
    assert steps["commands"] == [{"turn": 1, "command": "cd /testbed && grep -rn revoke_session . | head -20",
                                  "cut": False, "cwd": ".", "simple": [["other", "cd", []],
                                                                       ["search_content", "grep", ["."]],
                                                                       ["filter", "head", []]]}]
    none = e2e_run.count_steps(_events()[:4], ["auth/sessions.py"])
    assert none["turns_before_first_edit"] is None and not none["gold_file_read"]


def test_token_block():
    summary = {"proxy_complete": True, "messages": {"input_tokens": 1, "output_tokens": 2,
               "cache_creation_input_tokens": 3, "cache_read_input_tokens": 4, "processed_tokens": 10,
               "peak_context_tokens": 8, "requests": 2}}
    result = {"modelUsage": {"m": {"inputTokens": 1, "outputTokens": 2, "cacheCreationInputTokens": 3,
                                   "cacheReadInputTokens": 5}}}
    block = e2e_run.token_block(summary, result)
    assert block["source"] == "proxy" and block["processed_tokens"] == 10 and block["agent"]["processed_tokens"] == 11
    block = e2e_run.token_block({**summary, "proxy_complete": False}, result)
    assert block["source"] == "agent" and block["processed_tokens"] == 11
    block = e2e_run.token_block({**summary, "proxy_complete": False}, None)
    assert block["source"] == "proxy-partial" and block["processed_tokens"] == 10
    assert e2e_run.token_block(None, None)["source"] is None


def test_read_clock_and_prep(tmp_path):
    (tmp_path / "clock.txt").write_text("agent_start 1000000000\nagent_end 3500000000\nexit_code 0\n")
    assert e2e_run.read_clock(tmp_path) == {"agent_start": 10**9, "agent_end": 35 * 10**8, "exit_code": 0,
                                            "agent_s": 2.5}
    (tmp_path / "prep.txt").write_text("start 0\nremove_config 1000000000\nchown 17000000000\nready 17500000000\n")
    prep = e2e_run.read_prep(tmp_path)
    assert prep["steps_s"] == {"remove_config": 1.0, "chown": 16.0, "ready": 0.5} and prep["prep_s"] == 17.5
    assert e2e_run.read_clock(tmp_path / "none") == {}


def test_agent_script():
    script = e2e_run.agent_script("claude-haiku-5-5", RunSettings(time_limit_s=3000))
    assert script.splitlines()[1] == "trap 'chmod -R a+rwX /out' EXIT"
    assert "timeout -k 30 3000 runuser -u agent -- env -u ANTHROPIC_API_KEY HOME=/home/agent" in script
    for part in ("CLAUDE_CONFIG_DIR=/run/claude-empty", "CLAUDE_CODE_DISABLE_CLAUDE_MDS=1",
                 "CLAUDE_CODE_DISABLE_AUTO_MEMORY=1", "CLAUDE_CODE_EFFORT_LEVEL=medium", "ENABLE_TOOL_SEARCH=false",
                 "DISABLE_AUTOUPDATER=1 MCP_TIMEOUT=120000 MCP_TOOL_TIMEOUT=120000", 'claude -p "$(cat /out/prompt.txt)" --model claude-haiku-5-5',
                 "--output-format stream-json --verbose --setting-sources user --strict-mcp-config "
                 "--mcp-config /tmp/mcp.json --disable-slash-commands --no-session-persistence "
                 "--exclude-dynamic-system-prompt-sections --permission-mode bypassPermissions "
                 '--disallowedTools "WebSearch,WebFetch"', "> /out/stream.jsonl 2> /out/stderr.txt < /dev/null",
                 "git diff --cached --binary HEAD > /out/agent.patch", e2e_run.KILL_AGENT):
        assert part in script
    assert FAKE_TOKEN not in script and "OAUTH" not in script
    assert "cmgate" not in script and "codemem_warm" not in script


def test_agent_script_with_the_gate():
    script = e2e_run.agent_script("claude-haiku-5-5", RunSettings(), gate_python="/opt/code mem/.venv/bin/python")
    lines = script.splitlines()
    serve = next(line for line in lines if " serve " in line)
    # The gate runs as the agent's user, without the login token or the proxy's address, in the background.
    assert serve.startswith("runuser -u agent -- env -u CLAUDE_CODE_OAUTH_TOKEN -u ANTHROPIC_BASE_URL HOME=/home/agent "
                            "'/opt/code mem/.venv/bin/python' /tmp/cmgate/cmgate.py serve /tmp/cmgate/cmgate.json")
    assert serve.endswith("&")
    order = [lines.index(serve), lines.index("mark codemem_warm"), lines.index("mark ready"),
             next(i for i, line in enumerate(lines) if line.startswith("s=$(date"))]
    assert order == sorted(order)
    # Not warm: the script stops before Claude Code, and keeps the gate's logs.
    stop = lines.index("  exit 3")
    assert stop < lines.index("mark ready") and "codemem-server.log" in lines[stop - 1]
    assert e2e_run.KILL_AGENT in lines[next(i for i, line in enumerate(lines) if "codemem-gate.log" in line
                                            and i > lines.index("mark ready")) - 1]


def test_codemem_checks():
    ok = {"ok": True}
    clean = {"first": {"turn": 1, "subagent": False, "notes": []}, "first_keywords_only": False}
    assert e2e_run.codemem_checks(ok, clean) == []
    assert e2e_run.codemem_checks(ok, {"first": None, "first_keywords_only": False}) == []  # no search at all
    assert e2e_run.codemem_checks(None, clean) == ["codemem warm-up: no codemem-warm.json"]
    assert e2e_run.codemem_checks({"ok": False, "error": "boom"}, clean) == ["codemem warm-up failed: boom"]
    late = {"first": {"turn": 3, "subagent": False, "notes": ["loading", "not_fresh"]}, "first_keywords_only": True}
    assert e2e_run.codemem_checks(ok, late) == [
        "the first search_code result (turn 3) came from keywords only (loading, not_fresh)"]


def test_token_file_and_binary_checks(tmp_path, monkeypatch):
    path = tmp_path / "claude-token"
    monkeypatch.setenv("CMEVAL_CLAUDE_TOKEN_FILE", str(path))
    assert e2e_run.token_file() == path
    with pytest.raises(gen.GenerateError, match="no token file"):
        e2e_run.check_token_file(path)
    path.write_text(FAKE_TOKEN + "\n")
    path.chmod(0o644)
    with pytest.raises(gen.GenerateError, match="chmod 600") as info:
        e2e_run.check_token_file(path)
    assert FAKE_TOKEN not in str(info.value)
    path.chmod(0o600)
    e2e_run.check_token_file(path)
    assert e2e_run.read_token(path) == FAKE_TOKEN

    monkeypatch.setenv("CMEVAL_CLAUDE_BIN", str(tmp_path / "nothing"))
    with pytest.raises(gen.GenerateError, match="does not exist"):
        e2e_run.claude_bin()
    script = tmp_path / "claude"
    script.write_text("#!/bin/sh\n")
    monkeypatch.setenv("CMEVAL_CLAUDE_BIN", str(script))
    with pytest.raises(gen.GenerateError, match="not a Linux program"):
        e2e_run.claude_bin()
    script.write_bytes(b"\x7fELF" + b"\0" * 12)
    assert e2e_run.claude_bin() == script.resolve()


def test_ensure_network(monkeypatch):
    calls = []
    answers = {"inspect": [subprocess.CompletedProcess([], 1, "", "no such network"),
                           subprocess.CompletedProcess([], 0, "true 172.18.0.1\n", "")]}

    def fake_run(cmd, **kwargs):
        calls.append(cmd[:3])
        if cmd[2] == "inspect":
            return answers["inspect"].pop(0)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(e2e_run, "_run", fake_run)
    assert e2e_run.ensure_network() == "172.18.0.1"
    assert calls == [["docker", "network", "inspect"], ["docker", "network", "create"],
                     ["docker", "network", "inspect"]]
    monkeypatch.setattr(e2e_run, "_run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "false 172.18.0.1", ""))
    with pytest.raises(gen.GenerateError, match="not internal"):
        e2e_run.ensure_network()


def test_redact_secret(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.txt").write_text(f"before {FAKE_TOKEN} after")
    (tmp_path / "y.bin").write_bytes(b"\0\1")
    assert e2e_run.redact_secret(tmp_path, FAKE_TOKEN) == ["a/x.txt"]
    assert (tmp_path / "a" / "x.txt").read_text() == "before [REDACTED] after"


# ---- one run, with the container script run locally

PROXY_LINES = [
    {"seq": 1, "path": "/v1/messages", "status": 200, "response_model": "claude-haiku-5-5", "stream_complete": True,
     "usage": {"input_tokens": 10, "output_tokens": 400, "cache_creation_input_tokens": 40000,
               "cache_read_input_tokens": 0}},
    {"seq": 2, "path": "/v1/messages", "status": 200, "response_model": "claude-haiku-5-5", "stream_complete": True,
     "usage": {"input_tokens": 20, "output_tokens": 500, "cache_creation_input_tokens": 0,
               "cache_read_input_tokens": 150000}},
]


# The hidden tests of the task of a local run. Two added lines are long enough for the mount proof.
TEST_PATCH = """\
diff --git a/tests/test_sessions.py b/tests/test_sessions.py
--- /dev/null
+++ b/tests/test_sessions.py
@@ -0,0 +1,3 @@
+def test_revoke_session_removes_every_session_of_the_user(manager, user):
+    manager.revoke_session(user)
+    assert manager.db.sessions_for(user) == [], "a session of a disabled user is left"
"""


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def _shim(folder, name, text):
    path = folder / name
    path.write_text(text)
    path.chmod(0o755)


# The agent's side of codemem in a local run: start the MCP server of mcp.json (the gate's bridge), do the
# handshake and one search, and write the answer of the search to a file.
AGENT_MCP = r'''
import json, subprocess, sys

config = json.load(open(sys.argv[1]))["mcpServers"].get("codemem")
if config is None:
    sys.exit(0)
proc = subprocess.Popen([config["command"], *config["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE)


def ask(rid, method, params):
    proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n").encode())
    proc.stdin.flush()
    while True:
        message = json.loads(proc.stdout.readline())
        if message.get("id") == rid:
            return message


ask(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "agent"}})
proc.stdin.write(b'{"jsonrpc": "2.0", "method": "notifications/initialized"}\n')
answer = ask(2, "tools/call", {"name": "search_code", "arguments": {"query": "revoke sessions"}})
open(sys.argv[2], "w").write(answer["result"]["content"][0]["text"])
proc.stdin.close()
sys.exit(proc.wait())
'''

# A stand-in for `codemem mcp`: the handshake, index_status (ready from the second call on) and search_code (the
# first search has the loading note). FAKE_SERVER_READY=never keeps it in the state "updating".
FAKE_MCP_SERVER = r'''
import json, os, sys

log = open(os.environ["FAKE_SERVER_LOG"], "a")
log.write(json.dumps({"argv": sys.argv[1:], "backend": os.environ.get("CODEMEM_VECTOR_BACKEND"),
                      "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"), "cwd": os.getcwd()}) + "\n")
log.flush()
status = searches = 0
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    log.write(json.dumps({"method": msg["method"], "params": msg.get("params")}) + "\n")
    log.flush()
    if msg["method"] == "initialize":
        result = {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                  "serverInfo": {"name": "codemem", "version": "0.0-fake"}}
    elif msg["params"]["name"] == "index_status":
        status += 1
        state = "ready" if status > 1 and os.environ.get("FAKE_SERVER_READY") != "never" else "updating"
        text = f"state: {state}\nwatching for changes\n\n" + json.dumps({"state": state, "models_loaded": True})
        result = {"content": [{"type": "text", "text": text}]}
    else:
        searches += 1
        text = "1. auth/sessions.py:1-2  revoke_session  [id 7]"
        if searches == 1:
            text += ("\n\nNote: codemem is still loading its embedding model or its search index (the first "
                     "searches after it starts); these results come from keyword matching only.")
        result = {"content": [{"type": "text", "text": text}]}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
'''


def _local_run(monkeypatch, tmp_path, make_task, *, stream_lines, proxy_lines=PROXY_LINES, sleep=0):
    """Set up a run whose container script runs in local folders. The fake Claude Code prints the stream,
    writes the token to stderr (as an agent that runs `env` could), adds proxy lines, and edits a file. In a
    codemem setup it also searches once through the MCP server of mcp.json (AGENT_MCP). The gate's folder is a
    short one in the system's temp folder: a Unix socket path has a limit of about 100 characters."""
    monkeypatch.delenv(e2e_run.GPUS_ENV, raising=False)
    testbed = tmp_path / "testbed"
    (testbed / "auth").mkdir(parents=True)
    (testbed / "sub" / ".claude").mkdir(parents=True)
    (testbed / "auth" / "sessions.py").write_text("def revoke_session():\n    pass\n")
    (testbed / "CLAUDE.md").write_text("rules\n")
    (testbed / "sub" / "AGENTS.md").write_text("rules\n")
    (testbed / "sub" / ".claude" / "settings.json").write_text("{}\n")
    config = tmp_path / "gitconfig"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{key}_NAME", "t")
        monkeypatch.setenv(f"{key}_EMAIL", "t@t")
    _git(testbed, "init", "-q")
    _git(testbed, "add", "-A")
    _git(testbed, "commit", "-qm", "base")

    stream = tmp_path / "stream.in"
    stream.write_text("".join(json.dumps(e) + "\n" for e in stream_lines))
    proxy_in = tmp_path / "proxy.in"
    proxy_in.write_text("".join(json.dumps(r) + "\n" for r in proxy_lines))
    shims = tmp_path / "shims"
    shims.mkdir()
    for name in ("useradd", "chown"):
        _shim(shims, name, "#!/bin/sh\nexit 0\n")
    _shim(shims, "runuser", '#!/bin/sh\nshift 3\nexec "$@"\n')
    _shim(shims, "timeout", '#!/bin/sh\nshift 3\nexec "$@"\n')
    _shim(shims, "date", f"#!/bin/sh\nexec '{sys.executable}' -c 'import time; print(time.time_ns())'\n")
    out_holder = {}
    fake_claude = shims / "claude"
    (tmp_path / "agent_mcp.py").write_text(AGENT_MCP)
    monkeypatch.setattr(e2e_run, "codemem_python", lambda codemem: sys.executable)
    _shim(shims, "claude", (
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > {tmp_path}/argv.txt\n'
        'echo "login: $CLAUDE_CODE_OAUTH_TOKEN" >&2\n'
        f"'{sys.executable}' {tmp_path}/agent_mcp.py {tmp_path}/mcp.json {tmp_path}/agent-search.txt >&2 || exit 9\n"
        f"cat {stream}\n"
        f'cat {proxy_in} >> "$CMEVAL_TEST_OUT/proxy.jsonl"\n'
        "printf 'def revoke_session():\\n    return 1\\n' > auth/sessions.py\n"
        f"sleep {sleep}\n"))
    monkeypatch.setenv("PATH", f"{shims}:{os.environ['PATH']}")

    token = tmp_path / "claude-token"
    token.write_text(FAKE_TOKEN + "\n")
    token.chmod(0o600)
    monkeypatch.setenv("CMEVAL_CLAUDE_TOKEN_FILE", str(token))
    monkeypatch.setenv("CMEVAL_CLAUDE_BIN", str(fake_claude))
    monkeypatch.setattr(e2e_run, "_is_linux_program", lambda path: True)
    monkeypatch.setattr(e2e_run, "image_exists", lambda tag: True)

    calls = []
    real_run = e2e_run._run

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["docker", "network", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, "true 127.0.0.1\n", "")
        if cmd[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, "sha256:abc\n", "")
        if cmd[:2] != ["docker", "run"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        out = cmd[cmd.index("-v", cmd.index("-v") + 1) + 1].rsplit(":", 1)[0]
        out_holder["out"] = out
        text = Path(out, "agent.sh").read_text()
        assert e2e_run.KILL_AGENT in text
        gate_dir = tempfile.mkdtemp(prefix="cmg-", dir="/tmp")
        for i, part in enumerate(cmd[:-1]):  # the paths that the mount proof searches, where the host has them
            host, target = cmd[i + 1].split(":")[:2] if part == "-v" else ("", "")
            if host != target and target != "/out":
                text = text.replace(f" {shlex.quote(target)} ", f" {shlex.quote(host)} ")
        moves = ((e2e_run.GATE_DIR, gate_dir), ("/testbed", str(testbed)), ("/out", out),
                 (e2e_run.PROOF_DIR, str(tmp_path / "cmproof")))
        for old, new in ((e2e_run.KILL_AGENT, "true"), *moves, ("/run/claude-empty", str(tmp_path / "claude-empty")),
                         ("/tmp/mcp.json", f"{tmp_path}/mcp.json")):
            text = text.replace(old, new)
        for name in ("cmgate.json", "mcp.json"):  # the gate's own paths, as the container would have them
            path = Path(out, name)
            if path.exists():
                data = path.read_text()
                for old, new in moves[:2]:
                    data = data.replace(old, new)
                path.write_text(data)
        assert "kill -9" not in text
        script = tmp_path / "local.sh"
        script.write_text(text)
        env = dict(kwargs.pop("env"))
        env["CMEVAL_TEST_OUT"] = out
        for i, part in enumerate(cmd):
            if part == "-e" and "=" in cmd[i + 1]:
                key, value = cmd[i + 1].split("=", 1)
                env[key] = value
        try:
            return real_run(["bash", str(script)], env=env, **kwargs)
        finally:
            shutil.rmtree(gate_dir, ignore_errors=True)

    monkeypatch.setattr(e2e_run, "_run", fake_run)
    graded = []

    def fake_grade(recipe, task, patch, out, cpus=8):
        graded.append(patch)
        return {"completed": True, "reason": "ok", "grade_s": 1.0}

    monkeypatch.setattr(e2e_run, "grade", fake_grade)
    recipe = gen.Recipe(name="r", repo="acme/auth", base_image="i", test="pytest {files}")
    task = make_task(test_patch=TEST_PATCH)
    gen.task_dir(recipe, task).mkdir(parents=True)
    gen.tests_path(recipe, task).write_text(json.dumps({"fail_to_pass": ["t::a"], "pass_to_pass": []}))
    return recipe, task, calls, graded


def test_run_one_locally(make_task, tmp_path, monkeypatch):
    recipe, task, calls, graded = _local_run(monkeypatch, tmp_path, make_task, stream_lines=_events())
    loads = iter([[1.0, 1.5, 2.0], [3.0, 2.5, 2.0]])
    monkeypatch.setattr(e2e_run, "host_load", lambda: next(loads))
    out = e2e_run.run_dir("r1", task.id, "grep", 1)
    record = e2e_run.run_one(recipe, task, setup="grep", model="claude-haiku-5-5", rep=1, out=out,
                             settings=RunSettings(poll_s=0.05))

    assert record["end"] == "finished" and record["completed"] is True and not record["discard"]
    # The host's load right before and right after the container, in every setup.
    assert record["time"]["host_load_start"] == [1.0, 1.5, 2.0] and record["time"]["host_load_end"] == [3.0, 2.5, 2.0]
    assert record["integrity"]["codemem_mount_proof"] is None
    assert record["run_id"] == "r1" and record["rep"] == 1 and record["identity"]["harness_version"] == "2.1.332"
    assert record["identity"]["prompt_frame"] == "v1" and record["identity"]["image_id"] == "sha256:abc"
    integrity = record["integrity"]
    assert integrity["setup_ok"] and integrity["proxy_complete"] and integrity["cross_check"]["agree"]
    assert sorted(integrity["removed_config_files"]) == ["CLAUDE.md", "sub/.claude/settings.json", "sub/AGENTS.md"]
    assert integrity["redacted_files"] == ["stderr.txt"]
    assert record["tokens"]["source"] == "proxy" and record["tokens"]["processed_tokens"] == 190930
    assert record["steps"]["turns"] == 5 and record["steps"]["num_turns_result"] == 5
    assert record["identity"]["gold_files"] == ["auth/sessions.py"] and record["steps"]["gold_opened"]
    assert record["time"]["agent_s"] >= 0 and set(record["time"]["prep_steps_s"]) == {"remove_config", "chown", "ready"}
    # The patch has the agent's edit, and not the removal of the configuration files.
    assert len(graded) == 1 and e2e_run.patch_files(graded[0]) == {"auth/sessions.py"}
    assert record["outcome"]["patch_files"] == 1 and record["outcome"]["status_lines"] == 1
    assert json.loads((out / "run.json").read_text()) == record
    argv = (tmp_path / "argv.txt").read_text()
    assert "<issue>\nDisabled users stay logged in" in argv and "bypassPermissions" in argv
    run = next(c for c in calls if c[:2] == ["docker", "run"])
    assert "CLAUDE_CODE_OAUTH_TOKEN" in run and not any(FAKE_TOKEN in part for part in run)
    assert ["docker", "rm", "-f", run[run.index("--name") + 1]] in calls
    # The GPU in both setups, and no codemem mount for grep.
    assert run[run.index("--device") + 1] == "nvidia.com/gpu=all" and run.count("-v") == 2
    assert run[run.index("--ulimit"):run.index("--ulimit") + 2] == list(gen.NO_CORE_DUMPS)
    assert record["identity"]["codemem"] is None and record["integrity"]["gpus"] is True
    assert record["outcome"]["unexpected_paths"] == []


def test_no_file_of_a_run_holds_the_token(make_task, tmp_path, monkeypatch):
    recipe, task, _, _ = _local_run(monkeypatch, tmp_path, make_task, stream_lines=_events())
    out = e2e_run.run_dir("r1", task.id, "grep", 1)
    e2e_run.run_one(recipe, task, setup="grep", model="claude-haiku-5-5", rep=1, out=out,
                    settings=RunSettings(poll_s=0.05))
    files = [p for p in out.rglob("*") if p.is_file()]
    assert len(files) > 10
    for path in files:
        assert FAKE_TOKEN.encode() not in path.read_bytes(), path


def test_run_one_discards_a_bad_setup(make_task, tmp_path, monkeypatch):
    events = _events()
    events[0] = {**events[0], "permissionMode": "default"}
    recipe, task, _, graded = _local_run(monkeypatch, tmp_path, make_task, stream_lines=events)
    out = e2e_run.run_dir("r1", task.id, "grep", 1)
    record = e2e_run.run_one(recipe, task, setup="grep", model="claude-haiku-5-5", rep=1, out=out,
                             settings=RunSettings(poll_s=0.05))
    assert record["discard"] and record["discard_reason"] == "setup check failed: permissionMode is default"
    assert record["completed"] is None and graded == []


def test_run_one_stops_at_the_turn_limit(make_task, tmp_path, monkeypatch):
    events = _events()[:-1]  # stopped before the result event
    recipe, task, calls, graded = _local_run(monkeypatch, tmp_path, make_task, stream_lines=events, sleep=1)
    out = e2e_run.run_dir("r1", task.id, "grep", 1)
    record = e2e_run.run_one(recipe, task, setup="grep", model="claude-haiku-5-5", rep=1, out=out,
                             settings=RunSettings(poll_s=0.05, turn_limit=2))
    assert record["end"] == "turn limit" and record["turn_limit"]["how"] == "docker exec kill"
    assert any(c[:2] == ["docker", "exec"] and c[-1] == e2e_run.KILL_AGENT for c in calls)
    assert record["completed"] is True and len(graded) == 1  # graded like any other run
    assert record["integrity"]["cross_check"]["agree"] is None


def test_run_one_preconditions(make_task, monkeypatch, tmp_path):
    recipe = gen.Recipe(name="r", repo="acme/auth", base_image="i", test="pytest {files}")
    task = make_task()
    out = tmp_path / "out"
    monkeypatch.setattr(e2e_run, "image_exists", lambda tag: False)
    with pytest.raises(gen.GenerateError, match="image cmeval-env/r:acme__auth-42 does not exist"):
        e2e_run.run_one(recipe, task, setup="grep", model="claude-haiku-5-5", rep=1, out=out)
    monkeypatch.setattr(e2e_run, "image_exists", lambda tag: True)
    with pytest.raises(gen.GenerateError, match="no tests.json"):
        e2e_run.run_one(recipe, task, setup="grep", model="claude-haiku-5-5", rep=1, out=out)
    with pytest.raises(gen.GenerateError, match="not built yet"):
        e2e_run.run_one(recipe, task, setup="placebo", model="claude-haiku-5-5", rep=1, out=out)
    assert not out.exists()


# ---- a batch

def test_plan_runs_by_repetition_with_setups_taking_turns(make_task):
    a, b = make_task(id="acme__auth-1"), make_task(id="acme__auth-2")
    order = [(t.id[-1], s, r) for t, s, r in e2e_run.plan_runs([a, b], ["grep", "tool"], 2)]
    # The setup that goes first moves from task to task, and again at each repetition.
    assert order == [("1", "grep", 1), ("1", "tool", 1), ("2", "tool", 1), ("2", "grep", 1),
                     ("1", "tool", 2), ("1", "grep", 2), ("2", "grep", 2), ("2", "tool", 2)]
    c = make_task(id="acme__auth-3")
    order = e2e_run.plan_runs([a, b, c], ["grep", "tool", "codemem"], 2)
    assert [s for _, s, _ in order[0::3]] == ["grep", "tool", "codemem", "tool", "codemem", "grep"]
    assert [s for _, s, _ in e2e_run.plan_runs([a], ["grep"], 3)] == ["grep"] * 3


def _record(task_id, setup, rep, *, end="finished", completed=True, discard=False, tokens=1000, seconds=60.0,
            flags=()):
    return {"task_id": task_id, "setup": setup, "rep": rep, "end": end, "completed": None if discard else completed,
            "discard": discard, "discard_reason": "usage limit" if discard else None, "flags": list(flags),
            "tokens": {"processed_tokens": tokens}, "time": {"agent_s": seconds}, "steps": {"turns": 10},
            "usage_limit": {"reset": {"retry-after": "60"}} if end == "usage limit" else None}


def _batch_task_file(make_task, tmp_path, n=3):
    from dataclasses import replace
    recipe = gen.load_recipe("pandas")
    fix = make_task().fix
    tasks = [make_task(id=f"pandas-dev__pandas-{i}", repo=recipe.repo, fix=replace(fix, pr_number=i))
             for i in range(1, n + 1)]
    path = tmp_path / "tasks.jsonl"
    save_tasks(path, tasks)
    for task in tasks[:-1]:  # the last task has no tests.json
        gen.task_dir(recipe, task).mkdir(parents=True)
        gen.tests_path(recipe, task).write_text("{}")
    return path, tasks


def test_cli_run_batch(make_task, tmp_path, monkeypatch, capsys):
    path, _ = _batch_task_file(make_task, tmp_path)
    ends = {"pandas-dev__pandas-1": "finished", "pandas-dev__pandas-2": "usage limit"}
    seen = []

    def fake_run_one(recipe, task, *, setup, model, rep, out, settings, run_id, prompts=None):
        seen.append((task.id, setup, rep, model))
        record = _record(task.id, setup, rep, end=ends[task.id], discard=ends[task.id] == "usage limit")
        out.mkdir(parents=True, exist_ok=True)
        (out / "run.json").write_text(json.dumps(record))
        return record

    monkeypatch.setattr(e2e_run, "run_one", fake_run_one)
    args = ["e2e", "run", "pandas", "--tasks", str(path), "--run-id", "b1"]
    assert main(args + ["--model", "sonnet"]) == 1
    assert "full model id" in capsys.readouterr().err
    assert main(args + ["--setup", "placebo"]) == 1
    assert "not built yet" in capsys.readouterr().err

    assert main(args + ["--dry-run"]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["pandas-dev__pandas-1 grep 1 todo", "pandas-dev__pandas-2 grep 1 todo",
                                         "2 runs: 0 done, 0 to do again, 2 to do"]
    assert "1 tasks have no tests.json" in captured.err and seen == []

    assert main(args) == e2e_run.EXIT_USAGE_LIMIT
    captured = capsys.readouterr()
    assert seen == [("pandas-dev__pandas-1", "grep", 1, "claude-haiku-5-5"),
                    ("pandas-dev__pandas-2", "grep", 1, "claude-haiku-5-5")]
    assert "usage limit; the batch stops. Reset: retry-after=60" in captured.err
    assert "pandas-dev__pandas-1 grep rep 1: finished, completed True, 1000 tokens, 60.0 s, ok" in captured.err

    # Again: the finished run is skipped, the discarded one is done again and the old folder is kept.
    ends["pandas-dev__pandas-2"] = "finished"
    seen.clear()
    assert main(args) == 0
    assert seen == [("pandas-dev__pandas-2", "grep", 1, "claude-haiku-5-5")]
    task_dir = e2e_run.run_dir("b1", "pandas-dev__pandas-2", "grep", 1).parent
    assert sorted(p.name for p in task_dir.iterdir()) == ["1", "1.discarded-1"]
    assert "1 runs done, 1 already done, 0 discarded" in capsys.readouterr().out


def test_batch_stops_after_three_errors(make_task, monkeypatch):
    tasks = [make_task(id=f"acme__auth-{i}") for i in range(1, 6)]

    def fake_run_one(recipe, task, *, setup, model, rep, out, settings, run_id, prompts=None):
        return _record(task.id, setup, rep, end="error", completed=False)

    monkeypatch.setattr(e2e_run, "run_one", fake_run_one)
    lines = []
    batch = e2e_run.run_batch(None, tasks, run_id="b2", setups=["grep"], model="claude-haiku-5-5",
                              progress=lines.append)
    assert batch.exit_code == e2e_run.EXIT_ERRORS and batch.done == 3 and len(lines) == 3


# ---- scoring

def _write(run_id, record):
    out = e2e_run.run_dir(run_id, record["task_id"], record["setup"], record["rep"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.json").write_text(json.dumps(record))


def test_score_tables_and_paired_difference(capsys):
    for rep in (1, 2):
        _write("s1", _record("t1", "grep", rep, completed=rep == 1, tokens=1000, seconds=100.0))
        _write("s1", _record("t1", "other", rep, completed=True, tokens=600, seconds=80.0))
    _write("s1", _record("t2", "grep", 1, completed=False, tokens=2000, seconds=200.0, end="time limit"))
    _write("s1", _record("t2", "other", 1, discard=True, end="usage limit"))
    _write("s1", _record("t3", "other", 1, completed=False, tokens=10**8, seconds=50.0, flags=["cross-check disagrees"]))
    # A folder set aside is not read.
    aside = e2e_run.run_dir("s1", "t1", "grep", 1).with_name("1.discarded-1")
    aside.mkdir()
    (aside / "run.json").write_text(json.dumps(_record("t1", "grep", 1, tokens=10**9)))

    summary = score("s1")
    grep, other = summary["setups"]["grep"], summary["setups"]["other"]
    assert (grep["runs"], grep["discarded"], grep["completed_share"]) == (3, 0, pytest.approx(1 / 3))
    assert grep["tokens_mean"] == pytest.approx(4000 / 3) and grep["tokens_median"] == 1000
    assert grep["ends"] == {"finished": 2, "time limit": 1}
    # The flagged run is in no number.
    assert (other["runs"], other["discarded"], other["flagged"], other["completed_share"]) == (4, 1, 1, 1.0)
    assert other["tokens_mean"] == 600
    assert summary["baseline"] == "grep"
    paired = summary["paired"][0]
    # Only t1 has kept runs in both setups: completed 1.0 - 0.5, tokens 600 - 1000, seconds 80 - 100.
    assert paired == {"setup": "other", "baseline": "grep", "tasks": 1, "completed": 0.5, "tokens": -400.0,
                      "seconds": -20.0}
    assert json.loads((e2e_run.e2e_dir() / "runs" / "s1" / "score.json").read_text()) == summary

    assert main(["e2e", "score", "s1"]) == 0
    out = capsys.readouterr().out
    assert "other - grep over 1 tasks: completed 0.50, tokens -400, seconds -20.0" in out
    assert main(["e2e", "score", "none"]) == 1


# ---- the setup tool: codemem's MCP server in the container

# The first lines of a script that uv makes when the path of its Python holds a space.
UV_SCRIPT = "#!/bin/sh\n'''exec' '{python}' \"$0\" \"$@\"\n' '''\n"

def _codemem_install(tmp_path, monkeypatch, recipe, task):
    """Stand-ins for the codemem program in a virtual environment made by `uv sync` (a script in uv's form for a
    path with a space, and the editable install's .pth file that names <checkout>/src), its uv Python, the
    Hugging Face cache and the task's index. Returns the checkout, the Python root, the cache and index.json."""
    checkout = tmp_path / "codemem"
    bin_dir = checkout / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    _shim(bin_dir, "codemem", UV_SCRIPT.format(python=bin_dir / "python") + FAKE_MCP_SERVER)
    site = checkout / ".venv" / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    (site / "_editable_impl_codemem.pth").write_text(f"{checkout / 'src'}\n")
    (site / "_virtualenv.pth").write_text("import _virtualenv\n")
    (checkout / "src" / "codemem").mkdir(parents=True)
    (checkout / "src" / "codemem" / "__init__.py").write_text("")
    monkeypatch.setenv("FAKE_SERVER_LOG", str(tmp_path / "server-calls.log"))
    python = tmp_path / "uv" / "python" / "cpython-3.12-linux" / "bin" / "python3.12"
    python.parent.mkdir(parents=True)
    _shim(python.parent, "python3.12", f"#!/bin/sh\nexec '{sys.executable}' \"$@\"\n")
    (bin_dir / "python").symlink_to(python)
    monkeypatch.setenv("CMEVAL_CODEMEM_BIN", str(bin_dir / "codemem"))
    hf = tmp_path / "hf"
    hf.mkdir()
    monkeypatch.setenv("HF_HOME", str(hf))
    root = e2e_index.index_root(recipe, task)
    (root / "index" / "vectors").mkdir(parents=True)
    (root / "index" / "index.sqlite").write_bytes(b"x" * 1000)
    (root / "index" / "vectors" / "code.faiss").write_bytes(b"y" * 500)
    meta = {"task_id": task.id, "repo": task.repo, "base_commit": task.base_commit, "codemem_commit": "abc",
            "seconds": 1.0, "summary": "indexed 3 files"}
    (root / "index.json").write_text(json.dumps(meta))
    return checkout, Path(os.path.realpath(python)).parents[1], hf, meta


def test_codemem_mcp_config(make_task, tmp_path, monkeypatch):
    monkeypatch.delenv("CMEVAL_CODEMEM_STEERING", raising=False)
    recipe, task = gen.Recipe(name="r", repo="acme/auth", base_image="i", test="pytest"), make_task()
    checkout, python_root, hf, meta = _codemem_install(tmp_path, monkeypatch, recipe, task)
    codemem = e2e_run.codemem_preconditions(recipe, task, RunSettings(gpus=True))
    assert codemem["checkout"] == checkout and codemem["python_root"] == python_root
    assert codemem["hf_cache"] == hf and codemem["meta"] == meta and codemem["commit"] is None  # not a git checkout
    program = str(checkout / ".venv" / "bin" / "codemem")
    assert e2e_run.codemem_mcp_config(codemem, RunSettings(cpus=4)) == {"mcpServers": {"codemem": {
        "command": program, "args": ["mcp", "/testbed", "--index-dir", "/cmindex"],
        "env": {"HF_HOME": "/hf", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                "CODEMEM_HOME": "/home/agent/.codemem", "CODEMEM_MODEL_IDLE_MINUTES": "0",
                "CODEMEM_VECTOR_BACKEND": "faiss", "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4"},
        "alwaysLoad": True}}}
    venv, src = checkout / ".venv", checkout / "src"
    assert codemem["mounts"] == [venv, src]
    # Only the environment and the source of the checkout, never the checkout itself (its eval/ holds the fixes).
    assert e2e_run.codemem_mounts(codemem, Path("/runs/x/cmindex")) == [
        "-v", f"{venv}:{venv}:ro", "-v", f"{src}:{src}:ro", "-v", f"{python_root}:{python_root}:ro",
        "-v", f"{hf}:/hf:ro", "-v", "/runs/x/cmindex:/cmindex"]
    monkeypatch.setenv("CMEVAL_CODEMEM_STEERING", "strong")
    env = e2e_run.codemem_mcp_config(codemem, RunSettings(cpus=4))["mcpServers"]["codemem"]["env"]
    assert env["CODEMEM_STEERING"] == "strong"
    monkeypatch.setenv("CMEVAL_CODEMEM_STEERING", "hard")
    with pytest.raises(gen.GenerateError, match="must be one of none, light, strong"):
        e2e_run.codemem_mcp_config(codemem, RunSettings(cpus=4))


def test_codemem_preconditions(make_task, tmp_path, monkeypatch):
    recipe, task = gen.Recipe(name="r", repo="acme/auth", base_image="i", test="pytest"), make_task()
    checkout, _, hf, meta = _codemem_install(tmp_path, monkeypatch, recipe, task)
    on = RunSettings(gpus=True)

    def fails(match, settings=on):
        with pytest.raises(gen.GenerateError, match=match):
            e2e_run.codemem_preconditions(recipe, task, settings)

    fails("needs the GPU in the container", RunSettings(gpus=False))
    program = checkout / ".venv" / "bin" / "codemem"
    program.chmod(0o644)
    fails("is not executable.*run cmeval e2e index r")
    program.chmod(0o755)
    (program.parent / "python").unlink()
    fails("no python beside")
    (program.parent / "python").symlink_to("/usr/bin/python3")
    fails("a folder of the system")
    (program.parent / "python").unlink()
    (program.parent / "python").symlink_to(tmp_path / "uv" / "python" / "cpython-3.12-linux" / "bin" / "python3.12")
    monkeypatch.setenv("CMEVAL_CODEMEM_BIN", str(tmp_path / "none"))
    fails("does not exist")
    monkeypatch.setenv("CMEVAL_CODEMEM_BIN", str(program))
    index_json = e2e_index.index_root(recipe, task) / "index.json"
    index_json.write_text(json.dumps({**meta, "base_commit": "f" * 40}))
    fails(r"no index for base commit 0123456789ab .*\(another commit\); run cmeval e2e index r first")
    index_json.unlink()
    fails(r"\(missing\); run cmeval e2e index r")
    index_json.write_text(json.dumps(meta))
    hf.rmdir()
    fails("no Hugging Face cache")
    hf.mkdir()
    e2e_run.codemem_preconditions(recipe, task, on)


def test_check_setup_of_tool_and_grep():
    model = "claude-haiku-5-5"
    assert e2e_run.check_setup(TOOL_INIT, TOOL, model) == []
    failed = {**TOOL_INIT, "mcp_servers": [{"name": "codemem", "status": "failed"}]}
    assert e2e_run.check_setup(failed, TOOL, model) == ["mcp server codemem is failed"]
    no_tool = {**TOOL_INIT, "tools": [t for t in TOOL_INIT["tools"] if t != "mcp__codemem__search_code"]}
    assert e2e_run.check_setup(no_tool, TOOL, model) == ["tool mcp__codemem__search_code is not loaded"]
    assert e2e_run.check_setup({**TOOL_INIT, "mcp_servers": []}, TOOL, model) == [
        "mcp_servers are [], expected ['codemem']"]
    two = {**TOOL_INIT, "mcp_servers": TOOL_INIT["mcp_servers"] + [{"name": "other", "status": "connected"}]}
    assert e2e_run.check_setup(two, TOOL, model) == ["mcp_servers are ['codemem', 'other'], expected ['codemem']"]
    # Only the shape {"name", "status"} is accepted.
    assert e2e_run.check_setup({**TOOL_INIT, "mcp_servers": ["codemem"]}, TOOL, model) == [
        'mcp_servers is not a list of name and status objects: ["codemem"]']
    # grep: no MCP server and no MCP tool.
    assert e2e_run.check_setup(TOOL_INIT, GREP, model) == [
        "mcp_servers are ['codemem'], expected []",
        "mcp tools are loaded: mcp__codemem__get_chunk, mcp__codemem__index_status, mcp__codemem__refresh_index, "
        "mcp__codemem__search_code"]


def _spy_docker_run(monkeypatch, seen, *, fail=False):
    """Look at the index copy while the container runs, and let codemem add a file to it."""
    inner = e2e_run._run

    def spy(cmd, **kwargs):
        if cmd[:2] == ["docker", "run"]:
            seen["cmd"] = cmd
            copy = Path(next(part for part in cmd if part.endswith(":/cmindex")).rsplit(":", 1)[0])
            seen["files"] = sorted(str(p.relative_to(copy)) for p in copy.rglob("*"))
            seen["modes"] = {oct(p.stat().st_mode & 0o777) for p in [copy, *copy.rglob("*")]}
            (copy / "index.sqlite-wal").write_bytes(b"z" * 100)
            if fail:
                raise RuntimeError("docker went away")
        return inner(cmd, **kwargs)

    monkeypatch.setattr(e2e_run, "_run", spy)


def test_run_one_tool_locally(make_task, tmp_path, monkeypatch):
    recipe, task, calls, graded = _local_run(monkeypatch, tmp_path, make_task, stream_lines=_events(TOOL_STREAM))
    checkout, python_root, hf, meta = _codemem_install(tmp_path, monkeypatch, recipe, task)
    seen = {}
    _spy_docker_run(monkeypatch, seen)
    out = e2e_run.run_dir("r1", task.id, "tool", 1)
    record = e2e_run.run_one(recipe, task, setup="tool", model="claude-haiku-5-5", rep=1, out=out,
                             settings=RunSettings(poll_s=0.05))

    assert record["integrity"]["setup_ok"] and not record["discard"] and record["completed"] is True
    # The gate: warm before the agent, outside its clock. Its warm-up searched until a search had no note.
    warm = record["integrity"]["codemem_warm"]
    assert warm["ok"] and warm["warmup_searches"] == 2 and warm["status"]["state"] == "ready"
    assert "watching for changes" in warm["status_text"]
    prep = record["time"]["prep_steps_s"]
    assert list(prep) == ["remove_config", "chown", "mount_proof", "codemem_warm", "ready"]
    assert record["time"]["codemem_warm_s"] == prep["codemem_warm"] >= 1.0
    marks = dict(line.split() for line in (out / "prep.txt").read_text().splitlines())
    clock = e2e_run.read_clock(out)
    assert int(marks["mount_proof"]) < int(marks["codemem_warm"]) < int(marks["ready"]) <= clock["agent_start"]
    assert "warm after" in (out / "codemem-gate.log").read_text()
    # The agent's first search went through the bridge to the warm server, and got a full search.
    assert e2e_run.codemem_gate.note_kinds((tmp_path / "agent-search.txt").read_text()) == []
    calls = [json.loads(line) for line in (tmp_path / "server-calls.log").read_text().splitlines()]
    started = [c for c in calls if "argv" in c]
    assert len(started) == 1 and started[0]["argv"][0] == "mcp" and started[0]["backend"] == "faiss"
    assert started[0]["token"] is None and Path(started[0]["cwd"]).resolve() == (tmp_path / "testbed").resolve()
    inits = [c["params"]["clientInfo"]["name"] for c in calls if c.get("method") == "initialize"]
    assert inits == ["cmeval-gate", "agent"]
    mcp = json.loads((out / "mcp.json").read_text())["mcpServers"]["codemem"]
    assert mcp["command"] == sys.executable and mcp["args"][1:] == ["connect", mcp["args"][0].replace(
        "cmgate.py", "codemem.sock")]
    assert mcp["env"]["CODEMEM_VECTOR_BACKEND"] == "faiss"
    fallbacks = record["integrity"]["codemem_fallback_searches"]
    assert fallbacks["searches"] == 2 and fallbacks["fell_back"] == 0 and not fallbacks["first_keywords_only"]
    run = seen["cmd"]
    assert run[run.index("--device") + 1] == "nvidia.com/gpu=all"
    venv, src = checkout / ".venv", checkout / "src"
    assert run[run.index(f"{out}:/out") + 1:run.index(record["identity"]["image"])] == [
        "-v", f"{venv}:{venv}:ro", "-v", f"{src}:{src}:ro", "-v", f"{python_root}:{python_root}:ro",
        "-v", f"{hf}:/hf:ro", "-v", f"{out / 'cmindex'}:/cmindex"]
    # The mount proof passed before codemem started: the checkout held only .venv and src, and no mounted path
    # held a line of the fix. The phrases file is gone, and no file of the run holds a phrase.
    proof = record["integrity"]["codemem_mount_proof"]
    assert proof["ok"] and proof["found"] and proof["script_says"] == "ok" and proof["hits"] == []
    assert proof["checkout"] == str(checkout) and proof["checkout_eval"] == "absent"
    assert proof["checkout_entries"] == proof["expected_entries"] == [".venv", "src"]
    assert proof["paths"] == ["/usr/local/bin/claude", "/out", str(venv), str(src), str(python_root), "/hf",
                              "/cmindex"]
    assert proof["phrases"] == {"patch": 0, "test_patch": 2} and proof["grep_exit"] == 1
    assert proof["seconds"] == prep["mount_proof"]
    assert not (out / e2e_run.PROOF_PHRASES).exists()
    for path in out.rglob("*"):
        assert not path.is_file() or b"disabled user is left" not in path.read_bytes(), path
    # The copy was there during the run, open to all users, and is gone after it.
    assert seen["files"] == ["index.sqlite", "vectors", "vectors/code.faiss"] and seen["modes"] == {"0o666", "0o777"}
    assert not (out / "cmindex").exists()
    assert record["identity"]["codemem"] == {
        "commit": None, "bin": str(checkout / ".venv" / "bin" / "codemem"), "index": meta, "steering": "default",
        "index_bytes_before": 1500, "index_bytes_after": 1600, "index_copy_removed": True}
    assert json.loads((out / "mcp.json").read_text())["mcpServers"]["codemem"]["alwaysLoad"] is True
    assert record["integrity"]["gpus"] is True and record["outcome"]["unexpected_paths"] == []
    steps = record["steps"]
    assert steps["codemem_calls"] == 5 and steps["first_codemem_turn"] == 1
    assert steps["mcp_tools"] == {"mcp__codemem__index_status": 1, "mcp__codemem__search_code": 2,
                                  "mcp__codemem__get_chunk": 1, "mcp__codemem__refresh_index": 1}


def _keyword_first(events):
    """The tool stream with the loading note of codemem 041124e on the first search_code result, in the JSON
    form of that version."""
    events = json.loads(json.dumps(events))
    note = ("1. auth/sessions.py:33 x\n\nNote: the embedding model is still loading (the first search after codemem "
            "starts)")
    events[4]["message"]["content"][0]["content"] = json.dumps({"result": note})
    return events


def test_run_one_tool_discards_a_first_search_from_keywords(make_task, tmp_path, monkeypatch):
    stream = _keyword_first(_events(TOOL_STREAM))
    recipe, task, _, graded = _local_run(monkeypatch, tmp_path, make_task, stream_lines=stream)
    _codemem_install(tmp_path, monkeypatch, recipe, task)
    out = e2e_run.run_dir("r1", task.id, "tool", 1)
    record = e2e_run.run_one(recipe, task, setup="tool", model="claude-haiku-5-5", rep=1, out=out,
                             settings=RunSettings(poll_s=0.05))
    assert record["discard"] and not graded and record["completed"] is None
    assert record["discard_reason"] == ("setup check failed: the first search_code result (turn 2) came from keywords "
                                        "only (loading)")
    fallbacks = record["integrity"]["codemem_fallback_searches"]
    assert fallbacks["first_keywords_only"] and fallbacks["calls"] == [{"turn": 2, "subagent": False,
                                                                       "notes": ["loading"]}]
    assert e2e_run.run_state(out) == "redo"


def test_run_one_tool_stops_before_the_agent_when_codemem_is_not_warm(make_task, tmp_path, monkeypatch):
    recipe, task, _, graded = _local_run(monkeypatch, tmp_path, make_task, stream_lines=_events(TOOL_STREAM))
    _codemem_install(tmp_path, monkeypatch, recipe, task)
    monkeypatch.setenv("FAKE_SERVER_READY", "never")
    monkeypatch.setattr(e2e_run, "GATE_TIMEOUT_S", 1)
    out = e2e_run.run_dir("r1", task.id, "tool", 1)
    record = e2e_run.run_one(recipe, task, setup="tool", model="claude-haiku-5-5", rep=1, out=out,
                             settings=RunSettings(poll_s=0.05))
    assert not (tmp_path / "argv.txt").exists()  # Claude Code did not start
    assert record["end"] == "error" and record["discard"] and not graded
    failures = record["integrity"]["setup_failures"]
    assert failures[0] == "no init event" and failures[1].startswith("codemem warm-up failed: the index was not ready")
    assert record["integrity"]["codemem_warm"]["ok"] is False and record["time"]["agent_s"] is None
    assert record["time"]["codemem_warm_s"] is not None and "codemem_warm" in (out / "prep.txt").read_text()
    assert "not warm" in (out / "codemem-gate.log").read_text()


def test_run_one_removes_the_index_copy_when_it_fails(make_task, tmp_path, monkeypatch):
    recipe, task, _, _ = _local_run(monkeypatch, tmp_path, make_task, stream_lines=_events(TOOL_STREAM))
    _codemem_install(tmp_path, monkeypatch, recipe, task)
    seen = {}
    _spy_docker_run(monkeypatch, seen, fail=True)
    out = e2e_run.run_dir("r1", task.id, "tool", 1)
    with pytest.raises(RuntimeError, match="docker went away"):
        e2e_run.run_one(recipe, task, setup="tool", model="claude-haiku-5-5", rep=1, out=out,
                        settings=RunSettings(poll_s=0.05))
    assert seen["files"] and not (out / "cmindex").exists()


def test_run_one_without_gpus(make_task, tmp_path, monkeypatch):
    recipe, task, calls, _ = _local_run(monkeypatch, tmp_path, make_task, stream_lines=_events())
    monkeypatch.setenv(e2e_run.GPUS_ENV, "0")
    assert RunSettings().gpus is False
    out = e2e_run.run_dir("r1", task.id, "grep", 1)
    record = e2e_run.run_one(recipe, task, setup="grep", model="claude-haiku-5-5", rep=1, out=out,
                             settings=RunSettings(poll_s=0.05))
    run = next(c for c in calls if c[:2] == ["docker", "run"])
    assert "--device" not in run and record["integrity"]["gpus"] is False
    _codemem_install(tmp_path, monkeypatch, recipe, task)
    with pytest.raises(gen.GenerateError, match="needs the GPU"):
        e2e_run.run_one(recipe, task, setup="tool", model="claude-haiku-5-5", rep=1, out=out,
                        settings=RunSettings(poll_s=0.05))


def test_unexpected_paths():
    patch = "".join(f"diff --git a/{p} b/{p}\n--- /dev/null\n+++ b/{p}\n@@ -0,0 +1 @@\n+x\n"
                    for p in ("auth/x.py", ".codemem/index.db", "sub/.codemem.toml", ".mcp.json"))
    assert e2e_run.unexpected_paths(patch) == [".codemem/index.db", ".mcp.json", "sub/.codemem.toml"]


def test_cli_dry_run_shows_the_index(make_task, tmp_path, monkeypatch, capsys):
    path, tasks = _batch_task_file(make_task, tmp_path)
    recipe = gen.load_recipe("pandas")
    _codemem_install(tmp_path, monkeypatch, recipe, tasks[0])
    args = ["e2e", "run", "pandas", "--tasks", str(path), "--run-id", "d1", "--setup", "grep", "--setup", "tool",
            "--dry-run"]
    assert main(args) == 0
    assert capsys.readouterr().out.splitlines()[:4] == [
        "pandas-dev__pandas-1 grep 1 todo", "pandas-dev__pandas-1 tool 1 todo index ok",
        "pandas-dev__pandas-2 tool 1 todo index missing", "pandas-dev__pandas-2 grep 1 todo"]


# ---- cmeval e2e index

FAKE_CODEMEM = """#!/bin/sh
echo "$@" >> "{calls}"
echo "$CODEMEM_VECTOR_BACKEND $CODEMEM_HOME" >> "{calls}.env"
test -f "$2/app.py" || exit 3
mkdir -p "$4"
echo data > "$4/index.sqlite"
echo "indexing $2 -> $4" >&2
echo "indexed 1 files (1 changed, 0 deleted); chunks +1 ~0 -0; edges 0; embedded {{'code': 1}} in 0.01s"
"""


def test_cli_index(remote, make_task, tmp_path, monkeypatch, capsys):
    from dataclasses import replace
    recipe_file = tmp_path / "demo.toml"
    recipe_file.write_text('repo = "acme/demo"\nbase_image = "x"\ntest = "pytest"\n')
    recipe = gen.load_recipe(recipe_file)
    tasks = [make_task(id="acme__demo-42", repo="acme/demo", base_commit=remote.shas[0]),
             make_task(id="acme__demo-43", repo="acme/demo", base_commit=remote.shas[1],
                       fix=replace(make_task().fix, pr_number=43))]
    task_file = tmp_path / "tasks.jsonl"
    save_tasks(task_file, tasks)
    gen.task_dir(recipe, tasks[0]).mkdir(parents=True)
    gen.tests_path(recipe, tasks[0]).write_text("{}")  # the second task has no tests.json
    args = ["e2e", "index", str(recipe_file), "--tasks", str(task_file)]

    monkeypatch.setenv("CMEVAL_CODEMEM_BIN", str(tmp_path / "none"))
    assert main(args) == 1
    assert "does not exist or is not executable" in capsys.readouterr().err

    checkout = tmp_path / "codemem"
    (checkout / "src").mkdir(parents=True)
    (checkout / "src" / "a.py").write_text("A = 1\n")
    _git(checkout, "init", "-q")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-qm", "codemem")
    commit = _git(checkout, "rev-parse", "HEAD").strip()
    (checkout / ".venv" / "bin").mkdir(parents=True)
    calls = tmp_path / "calls.txt"
    _shim(checkout / ".venv" / "bin", "codemem", FAKE_CODEMEM.format(calls=calls))
    monkeypatch.setenv("CMEVAL_CODEMEM_BIN", str(checkout / ".venv" / "bin" / "codemem"))
    # What the shell of the build has: its codemem home, where the vector cache is, and a search index of its own.
    monkeypatch.setenv("CODEMEM_HOME", str(tmp_path / "codemem-home"))
    monkeypatch.setenv("CODEMEM_VECTOR_BACKEND", "compact")

    assert main(args) == 0
    err = capsys.readouterr().err
    root = e2e_index.index_root(recipe, tasks[0])
    meta = json.loads((root / "index.json").read_text())
    assert meta["task_id"] == "acme__demo-42" and meta["repo"] == "acme/demo"
    assert meta["base_commit"] == remote.shas[0] and meta["codemem_commit"] == commit
    assert meta["summary"].startswith("indexed 1 files (1 changed, 0 deleted)") and meta["seconds"] >= 0
    assert (root / "src" / "app.py").read_text() == "VERSION = 1\n" and (root / "index" / "index.sqlite").exists()
    assert "1 tasks have no tests.json" in err and f"acme__demo-42: {meta['seconds']} s, indexed 1 files" in err
    assert calls.read_text().split() == ["index", str(root / "src"), "--index-dir", str(root / "index")]
    # The build names the search index that a run names (test_codemem_mcp_config), whatever the shell says,
    # and gets the rest of the shell's environment as it is.
    assert Path(f"{calls}.env").read_text().split() == ["faiss", str(tmp_path / "codemem-home")]
    assert e2e_index.index_state(recipe, tasks[0]) == "ok"

    # The same commits: skipped. --force builds again, and deletes the blocks made on the old index. A change in
    # codemem's src/ builds again.
    (root / "block-L0.json").write_text("{}")
    assert main(args) == 0
    assert "acme__demo-42: skipped" in capsys.readouterr().err and len(calls.read_text().splitlines()) == 1
    assert (root / "block-L0.json").exists()
    assert main(args + ["--force"]) == 0
    assert len(calls.read_text().splitlines()) == 2 and not (root / "block-L0.json").exists()
    (checkout / "src" / "a.py").write_text("A = 2\n")
    assert main(args) == 0
    assert len(calls.read_text().splitlines()) == 3
    assert json.loads((root / "index.json").read_text())["codemem_commit"] == commit + "-dirty"

    # A failed build leaves no index.json.
    (root / "src" / "app.py").unlink()
    assert main(args + ["--force"]) == 1
    assert "exit code 3" in capsys.readouterr().err and not (root / "index.json").exists()


def test_score_tool_against_grep(capsys):
    steps = e2e_run.count_steps(_events(TOOL_STREAM), ["auth/sessions.py"])
    for task_id in ("t1", "t2"):
        _write("s2", {**_record(task_id, "grep", 1, tokens=1000, seconds=100.0),
                      "steps": e2e_run.count_steps(_events(), ["auth/sessions.py"]), "identity": {"codemem": None}})
    _write("s2", {**_record("t1", "tool", 1, tokens=800, seconds=90.0), "steps": steps,
                  "identity": {"codemem": {"commit": "abc"}}})
    _write("s2", {**_record("t2", "tool", 1, tokens=900, seconds=95.0),
                  "steps": {**steps, "codemem_calls": 0, "first_codemem_turn": None},
                  "identity": {"codemem": {"commit": "abc"}}})
    summary = score("s2")
    behaviour = summary["setups"]["tool"]["behaviour"]
    assert (behaviour["codemem_share"], behaviour["codemem_calls_mean"], behaviour["first_codemem_turn_mean"]) == \
        (0.5, 2.5, 1.0)
    assert summary["paired"] == [{"setup": "tool", "baseline": "grep", "tasks": 2, "completed": 0.0,
                                  "tokens": -150.0, "seconds": -7.5}]
    text = format_score(summary)
    assert "tool - grep over 2 tasks: completed 0.00, tokens -150, seconds -7.5" in text
    assert "used  codemem 1st call" in text
    assert text.splitlines()[-1].endswith("0.50      2.5      1.0")


def test_recount_and_score_count_the_fallback_searches_of_old_runs(capsys):
    """Runs made before the count: recount fills integrity.codemem_fallback_searches from the stream and discards
    nothing; score then reports the count for the setup with codemem."""
    gold = {"gold_files": ["auth/sessions.py"]}
    streams = {"t1": _keyword_first(_events(TOOL_STREAM)), "t2": _events(TOOL_STREAM)}
    for task_id, events in streams.items():
        _write("s3", {**_record(task_id, "grep", 1), "identity": {**gold, "codemem": None}, "integrity": {}})
        _write("s3", {**_record(task_id, "tool", 1), "identity": {**gold, "codemem": {"commit": "041124e"}},
                      "integrity": {"setup_ok": True}})
        out = e2e_run.run_dir("s3", task_id, "tool", 1)
        (out / "stream.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        (e2e_run.run_dir("s3", task_id, "grep", 1) / "stream.jsonl").write_text(STREAM.read_text())
    assert "codemem fallbacks" not in format_score(score("s3"))
    assert main(["e2e", "recount", "s3"]) == 0
    printed = capsys.readouterr().out
    assert "t1 tool rep 1: " in printed and "codemem fallback searches - -> 1 of 2 (first from keywords)" in printed
    assert "t2 tool rep 1: " in printed and "codemem fallback searches - -> 0 of 2" in printed
    assert "fallback" not in next(line for line in printed.splitlines() if line.startswith("t1 grep"))
    t1 = json.loads((e2e_run.run_dir("s3", "t1", "tool", 1) / "run.json").read_text())
    assert t1["integrity"]["codemem_fallback_searches"]["first_keywords_only"] and not t1["discard"]
    assert t1["integrity"]["setup_ok"] is True
    grep = json.loads((e2e_run.run_dir("s3", "t1", "grep", 1) / "run.json").read_text())
    assert grep["integrity"] == {}
    summary = score("s3")
    assert summary["setups"]["grep"]["codemem_fallbacks"] is None
    f = summary["setups"]["tool"]["codemem_fallbacks"]
    assert (f["runs"], f["searches"], f["fell_back"], f["keywords_only"]) == (2, 4, 1, 1)
    assert f["first_keywords_only_runs"] == 1
    assert ("codemem fallbacks: 1 of 4 searches had a note (loading 1) in 1 of 2 runs; first search from keywords "
            "only: 1 runs, and 0 discarded runs") in format_score(summary)
    # A run discarded for its first search counts apart; one without the count is named.
    _write("s3", {**_record("t3", "tool", 1, discard=True), "identity": {"codemem": {"commit": "abc"}},
                  "integrity": {"codemem_fallback_searches": t1["integrity"]["codemem_fallback_searches"]}})
    _write("s3", {**_record("t4", "tool", 1), "identity": {"codemem": {"commit": "abc"}}, "integrity": {}})
    text = format_score(score("s3"))
    assert "1 runs, and 1 discarded runs; 1 runs without the count (run cmeval e2e recount)" in text


def test_python_root_holds_the_alias_and_the_real_install(tmp_path):
    from cmeval.e2e_index import codemem_python_root

    pythons = tmp_path / "uv" / "python"
    real = pythons / "cpython-3.11.18-linux" / "bin"
    real.mkdir(parents=True)
    (real / "python3.11").write_text("")
    (pythons / "cpython-3.11-linux").symlink_to(pythons / "cpython-3.11.18-linux")
    bin_dir = tmp_path / "checkout" / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(pythons / "cpython-3.11-linux" / "bin" / "python3.11")
    (bin_dir / "codemem").write_text("")
    assert codemem_python_root(bin_dir / "codemem") == pythons


def test_diagnostic_args(monkeypatch):
    monkeypatch.delenv("CMEVAL_E2E_DIAG_ARGS", raising=False)
    monkeypatch.delenv("CMEVAL_E2E_BODIES", raising=False)
    plain = e2e_run.agent_script("claude-haiku-5-5", RunSettings(time_limit_s=3000))
    assert e2e_run.diagnostic_args() == [] and not e2e_run.keep_bodies()
    monkeypatch.setenv("CMEVAL_E2E_DIAG_ARGS", "--thinking-display summarized")
    monkeypatch.setenv("CMEVAL_E2E_BODIES", "1")
    script = e2e_run.agent_script("claude-haiku-5-5", RunSettings(time_limit_s=3000))
    assert e2e_run.diagnostic_args() == ["--thinking-display", "summarized"] and e2e_run.keep_bodies()
    assert '"WebSearch,WebFetch" --thinking-display summarized >' in script
    assert script.replace(" --thinking-display summarized", "") == plain


def test_prompt_levels(make_task, tmp_path):
    task = make_task()
    assert e2e_run.make_prompt(task) == e2e_run.make_prompt(task, e2e_run.PromptSet())
    path = tmp_path / "vague.jsonl"
    rows = [{"id": task.id, "level": "L1", "prompt": "Logins fail after a reset.\n"},
            {"id": task.id, "level": "L2", "prompt": "Fix login after reset."}]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n\n", encoding="utf-8")
    one, two = e2e_run.load_prompts(path, "L1"), e2e_run.load_prompts(path, "L2")
    assert one.level == "L1" and one.source == "vague.jsonl" and one.sha256 == two.sha256
    text = e2e_run.make_prompt(task, one)
    assert "<issue>\nLogins fail after a reset.\n</issue>" in text and task.query.strip() not in text
    assert "Fix login after reset." in e2e_run.make_prompt(task, two)
    with pytest.raises(gen.GenerateError, match="no L1 prompt"):
        e2e_run.make_prompt(make_task(id="acme__auth-2"), one)
    with pytest.raises(gen.GenerateError, match="a prompts file holds L1, L2"):
        e2e_run.load_prompts(path, "L0")
    path.write_text(json.dumps(rows[0]) + "\n" + json.dumps(rows[0]) + "\n", encoding="utf-8")
    with pytest.raises(gen.GenerateError, match="second L1 prompt"):
        e2e_run.load_prompts(path, "L1")
    path.write_text('{"id": "x"}\n', encoding="utf-8")
    with pytest.raises(gen.GenerateError, match="not a prompt row"):
        e2e_run.load_prompts(path, "L1")



# ---- what the container of a codemem setup can read

def test_codemem_mount_paths_refuses_another_layout(make_task, tmp_path, monkeypatch):
    from cmeval.e2e_index import codemem_mount_paths

    recipe, task = gen.Recipe(name="r", repo="acme/auth", base_image="i", test="pytest"), make_task()
    checkout, _, _, _ = _codemem_install(tmp_path, monkeypatch, recipe, task)
    venv, program = checkout / ".venv", checkout / ".venv" / "bin" / "codemem"
    site = venv / "lib" / "python3.12" / "site-packages"
    assert codemem_mount_paths(program) == [venv, checkout / "src"]

    def fails(match):
        with pytest.raises(gen.GenerateError, match=match):
            codemem_mount_paths(program)

    # The plain shebang form is read too; another Python is refused.
    text = program.read_text()
    program.write_text(f"#!{venv / 'bin' / 'python'}\n" + text.split("\n", 3)[3])
    assert codemem_mount_paths(program) == [venv, checkout / "src"]
    program.write_text(f"#!/bin/sh\nexec '{sys.executable}' \"$@\"\n")
    fails("does not start the Python of its environment")
    program.write_text(text)
    # A .pth path outside the environment that is not <checkout>/src: the container would not have it.
    (checkout / "eval" / "src").mkdir(parents=True)
    (site / "extra.pth").write_text(f"{checkout / 'eval' / 'src'}\n")
    fails(r"extra.pth adds .*eval/src to the path")
    # A path in the environment is fine, and a path that does not exist is skipped, as Python does.
    (site / "extra.pth").write_text(f"# note\n{venv / 'lib'}\n{tmp_path / 'gone'}\n")
    assert codemem_mount_paths(program) == [venv, checkout / "src"]
    (site / "__editable___codemem_0_2_0_finder.py").write_text("MAPPING = {}\n")
    fails("editable finder modules")
    (site / "__editable___codemem_0_2_0_finder.py").unlink()
    # Not editable: a codemem folder in site-packages needs no source folder.
    (site / "_editable_impl_codemem.pth").unlink()
    fails("codemem is not installed")
    (site / "codemem").mkdir()
    assert codemem_mount_paths(program) == [venv]
    (venv / "lib" / "python3.11" / "site-packages").mkdir(parents=True)
    fails("2 site-packages folders")
    (venv / "lib" / "python3.11" / "site-packages").rmdir()
    # A Python install in the checkout, outside the environment: the container would not have it.
    (checkout / "pythons").mkdir()
    (checkout / "pythons" / "python3.12").write_text("")
    (venv / "bin" / "python").unlink()
    (venv / "bin" / "python").symlink_to(checkout / "pythons" / "python3.12")
    fails("in the checkout, but outside the environment")


def test_proof_phrases(make_task):
    patch = ("--- a/x.py\n+++ b/x.py\n@@ -1 +1,5 @@\n-    value = compute_the_value_of_this(thing, other)\n"
             "+    value = compute_the_value_of_this(thing, other)\n+    short = 1\n"
             "+    result = a_very_long_function_name_for_the_fix(first, second)\n"
             "+\tsecond_long_line_of_the_real_fix_for_the_proof(x)\r\n"
             "+    this_line_is_in_the_issue_text_as_well_so_skip_it()\n")
    task = make_task(patch=patch, test_patch=None)
    phrases = e2e_run.proof_phrases(task, avoid="see this_line_is_in_the_issue_text_as_well_so_skip_it() fail")
    # Long added lines only, without the moved line, the short line and the line of the issue text.
    assert phrases == {"patch": ["result = a_very_long_function_name_for_the_fix(first, second)",
                                 "second_long_line_of_the_real_fix_for_the_proof(x)"], "test_patch": []}
    many = "".join(f"+line_{i}_of_the_hidden_tests_which_is_long_enough_{'x' * i}\n" for i in range(5))
    phrases = e2e_run.proof_phrases(make_task(test_patch=many), avoid="")
    assert phrases["patch"] == [] and len(phrases["test_patch"]) == 3
    assert phrases["test_patch"][0].startswith("line_4_")


def test_mount_targets_and_proof_checks():
    volumes = ["-v", "/h/claude:/usr/local/bin/claude:ro", "-v", "/runs/1:/out", "-v", "/a/.venv:/a/.venv:ro"]
    assert e2e_run.mount_targets(volumes) == ["/usr/local/bin/claude", "/out", "/a/.venv"]
    good = {"found": True, "checkout": "/a", "expected_entries": [".venv", "src"], "script_says": "ok",
            "checkout_eval": "absent", "checkout_entries": [".venv", "src"], "grep_exit": 1, "other_errors": 0,
            "hits": [], "grep_errors": []}
    assert e2e_run.proof_checks(good) == []
    # Files that the agent's user cannot read are no exposure.
    assert e2e_run.proof_checks({**good, "grep_exit": 2, "grep_errors": ["grep: /hf/x: Permission denied"]}) == []
    assert e2e_run.proof_checks({**good, "grep_exit": 2, "other_errors": 1,
                                 "grep_errors": ["grep: /cmindex: No such file or directory"]}) == [
        "mount proof: the search failed (exit 2): grep: /cmindex: No such file or directory"]
    assert e2e_run.proof_checks({**good, "found": False}) == ["mount proof: no mount-proof.txt; the proof did not run"]
    bad = {**good, "script_says": "failed", "checkout_eval": "present", "grep_exit": 0,
           "checkout_entries": [".venv", "eval", "src"], "hits": ["/a/src/tasks.jsonl"]}
    assert e2e_run.proof_checks(bad) == [
        "mount proof: /a/eval is present in the container",
        "mount proof: /a holds ['.venv', 'eval', 'src'] in the container, expected ['.venv', 'src']",
        "mount proof: a line of the real fix or the hidden tests is in /a/src/tasks.jsonl",
        "mount proof: the search failed (exit 0): no message"]
    assert e2e_run.proof_checks({**good, "script_says": "failed"}) == ["mount proof: the container script says failed"]


def test_read_proof(tmp_path):
    assert e2e_run.read_proof(tmp_path) is None
    (tmp_path / "mount-proof.txt").write_text(
        "proof failed\ncheckout_eval absent\ncheckout_entries .venv src \ngrep_exit 0\nother_errors 0\n"
        "hit /a/src/x y.txt\ngrep_error grep: /hf/z: Permission denied\n")
    assert e2e_run.read_proof(tmp_path) == {
        "script_says": "failed", "checkout_eval": "absent", "checkout_entries": [".venv", "src"], "grep_exit": 0,
        "other_errors": 0, "hits": ["/a/src/x y.txt"], "grep_errors": ["grep: /hf/z: Permission denied"]}


def test_run_one_tool_stops_when_a_mounted_path_holds_the_fix(make_task, tmp_path, monkeypatch):
    recipe, task, _, graded = _local_run(monkeypatch, tmp_path, make_task, stream_lines=_events(TOOL_STREAM))
    checkout, _, _, _ = _codemem_install(tmp_path, monkeypatch, recipe, task)
    # A copy of the task's line in a mounted folder, as eval/tasks/e2e/*.jsonl was in the old mount.
    leak = checkout / "src" / "tasks.jsonl"
    leak.write_text(json.dumps({"id": task.id, "test_patch": TEST_PATCH}) + "\n")
    out = e2e_run.run_dir("r1", task.id, "tool", 1)
    record = e2e_run.run_one(recipe, task, setup="tool", model="claude-haiku-5-5", rep=1, out=out,
                             settings=RunSettings(poll_s=0.05))
    assert not (tmp_path / "argv.txt").exists() and not (tmp_path / "server-calls.log").exists()
    assert record["end"] == "error" and record["discard"] and not graded
    assert record["integrity"]["setup_failures"] == [
        "no init event", f"mount proof: a line of the real fix or the hidden tests is in {leak}",
        "mount proof: the search failed (exit 0): no message"]
    proof = record["integrity"]["codemem_mount_proof"]
    assert proof["ok"] is False and proof["script_says"] == "failed" and proof["hits"] == [str(leak)]
    assert record["integrity"]["codemem_warm"] is None and not (out / e2e_run.PROOF_PHRASES).exists()


def test_run_one_tool_stops_when_the_checkout_holds_more(make_task, tmp_path, monkeypatch):
    recipe, task, _, graded = _local_run(monkeypatch, tmp_path, make_task, stream_lines=_events(TOOL_STREAM))
    checkout, _, _, _ = _codemem_install(tmp_path, monkeypatch, recipe, task)
    (checkout / "eval" / "tasks").mkdir(parents=True)
    out = e2e_run.run_dir("r1", task.id, "tool", 1)
    record = e2e_run.run_one(recipe, task, setup="tool", model="claude-haiku-5-5", rep=1, out=out,
                             settings=RunSettings(poll_s=0.05))
    assert not (tmp_path / "argv.txt").exists() and record["discard"] and not graded
    assert record["integrity"]["setup_failures"][1:] == [
        f"mount proof: {checkout}/eval is present in the container",
        f"mount proof: {checkout} holds ['.venv', 'eval', 'src'] in the container, expected ['.venv', 'src']"]


def test_host_load(tmp_path):
    path = tmp_path / "loadavg"
    path.write_text("0.52 1.25 2.00 3/812 41234\n")
    assert e2e_run.host_load(path) == [0.52, 1.25, 2.0]
    assert e2e_run.host_load(tmp_path / "none") is None
    path.write_text("")
    assert e2e_run.host_load(path) is None
