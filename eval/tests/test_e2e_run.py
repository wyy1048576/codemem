"""End-to-end runs and their scores: the parts that need no Docker."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cmeval import e2e_run
from cmeval import generate as gen
from cmeval.cli import main
from cmeval.e2e_run import RunSettings
from cmeval.e2e_score import score
from cmeval.tasks import save_tasks

from conftest import FIXTURES

STREAM = FIXTURES / "e2e_stream.jsonl"
FAKE_TOKEN = "FAKE-LOGIN-VALUE-1"
INIT = json.loads(STREAM.read_text().splitlines()[0])
GREP = e2e_run.SETUPS["grep"]


def _events():
    return [json.loads(line) for line in STREAM.read_text().splitlines()]


# ---- pure parts

def test_prompt_frame_v1(make_task):
    prompt = e2e_run.make_prompt(make_task(query="Title\n\nBody text.\n"))
    assert prompt == (
        "The repository in the current directory has the issue below. Change the code of the repository so that "
        "the issue is resolved. Work on your own until you are done: nobody can answer questions.\n\n"
        "<issue>\nTitle\n\nBody text.\n</issue>\n")


def test_setups_and_models():
    assert e2e_run.get_setup("grep").mcp_config == {"mcpServers": {}}
    with pytest.raises(gen.GenerateError, match="not built yet"):
        e2e_run.get_setup("tool")
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
                 "DISABLE_AUTOUPDATER=1", 'claude -p "$(cat /out/prompt.txt)" --model claude-haiku-5-5',
                 "--output-format stream-json --verbose --setting-sources user --strict-mcp-config "
                 "--mcp-config /tmp/mcp.json --disable-slash-commands --no-session-persistence "
                 "--exclude-dynamic-system-prompt-sections --permission-mode bypassPermissions "
                 '--disallowedTools "WebSearch,WebFetch"', "> /out/stream.jsonl 2> /out/stderr.txt < /dev/null",
                 "git diff --cached --binary HEAD > /out/agent.patch", e2e_run.KILL_AGENT):
        assert part in script
    assert FAKE_TOKEN not in script and "OAUTH" not in script


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


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def _shim(folder, name, text):
    path = folder / name
    path.write_text(text)
    path.chmod(0o755)


def _local_run(monkeypatch, tmp_path, make_task, *, stream_lines, proxy_lines=PROXY_LINES, sleep=0):
    """Set up a run whose container script runs in local folders. The fake Claude Code prints the stream,
    writes the token to stderr (as an agent that runs `env` could), adds proxy lines, and edits a file."""
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
    _shim(shims, "claude", (
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > {tmp_path}/argv.txt\n'
        'echo "login: $CLAUDE_CODE_OAUTH_TOKEN" >&2\n'
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
        for old, new in ((e2e_run.KILL_AGENT, "true"), ("/testbed", str(testbed)), ("/out", out),
                         ("/run/claude-empty", str(tmp_path / "claude-empty")),
                         ("/tmp/mcp.json", f"{tmp_path}/mcp.json")):
            text = text.replace(old, new)
        assert "kill -9" not in text
        script = tmp_path / "local.sh"
        script.write_text(text)
        env = dict(kwargs.pop("env"))
        env["CMEVAL_TEST_OUT"] = out
        for i, part in enumerate(cmd):
            if part == "-e" and "=" in cmd[i + 1]:
                key, value = cmd[i + 1].split("=", 1)
                env[key] = value
        return real_run(["bash", str(script)], env=env, **kwargs)

    monkeypatch.setattr(e2e_run, "_run", fake_run)
    graded = []

    def fake_grade(recipe, task, patch, out, cpus=8):
        graded.append(patch)
        return {"completed": True, "reason": "ok", "grade_s": 1.0}

    monkeypatch.setattr(e2e_run, "grade", fake_grade)
    recipe = gen.Recipe(name="r", repo="acme/auth", base_image="i", test="pytest {files}")
    task = make_task()
    gen.task_dir(recipe, task).mkdir(parents=True)
    gen.tests_path(recipe, task).write_text(json.dumps({"fail_to_pass": ["t::a"], "pass_to_pass": []}))
    return recipe, task, calls, graded


def test_run_one_locally(make_task, tmp_path, monkeypatch):
    recipe, task, calls, graded = _local_run(monkeypatch, tmp_path, make_task, stream_lines=_events())
    out = e2e_run.run_dir("r1", task.id, "grep", 1)
    record = e2e_run.run_one(recipe, task, setup="grep", model="claude-haiku-5-5", rep=1, out=out,
                             settings=RunSettings(poll_s=0.05))

    assert record["end"] == "finished" and record["completed"] is True and not record["discard"]
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
        e2e_run.run_one(recipe, task, setup="tool", model="claude-haiku-5-5", rep=1, out=out)
    assert not out.exists()


# ---- a batch

def test_plan_runs_by_repetition_with_setups_taking_turns(make_task):
    a, b = make_task(id="acme__auth-1"), make_task(id="acme__auth-2")
    order = [(t.id[-1], s, r) for t, s, r in e2e_run.plan_runs([a, b], ["grep", "tool"], 2)]
    assert order == [("1", "grep", 1), ("1", "tool", 1), ("2", "grep", 1), ("2", "tool", 1),
                     ("1", "tool", 2), ("1", "grep", 2), ("2", "tool", 2), ("2", "grep", 2)]
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

    def fake_run_one(recipe, task, *, setup, model, rep, out, settings, run_id):
        seen.append((task.id, setup, rep, model))
        record = _record(task.id, setup, rep, end=ends[task.id], discard=ends[task.id] == "usage limit")
        out.mkdir(parents=True, exist_ok=True)
        (out / "run.json").write_text(json.dumps(record))
        return record

    monkeypatch.setattr(e2e_run, "run_one", fake_run_one)
    args = ["e2e", "run", "pandas", "--tasks", str(path), "--run-id", "b1"]
    assert main(args + ["--model", "sonnet"]) == 1
    assert "full model id" in capsys.readouterr().err
    assert main(args + ["--setup", "tool"]) == 1
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

    def fake_run_one(recipe, task, *, setup, model, rep, out, settings, run_id):
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
