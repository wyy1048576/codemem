"""Agent comparison: Claude Code headless on 17 pandas tasks at their base commits, asked where a change goes,
with grep only (shell) and with grep plus codemem. Built from the adopt agent's probe.py (same clean session,
gate, recording proxy, watchdog and cleanup); see .cache/review/briefs/agent-comparison.md.

usage:
  compare.py run <plan.jsonl> [--limit N] [--only RUN_ID]
  compare.py fence <task id>       the fence test with a fake API (no model call)
  compare.py extract [RUN_ID ...]  re-read finished runs
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

C = Path(__file__).resolve().parents[1]  # the folder that holds bin/, runs/ and v3/
CM = Path(__import__("os").environ.get("CODEMEM_REPO", "/path/to/codemem"))  # a codemem checkout
PY = CM / ".cache/wt/faiss-1-16/.venv/bin/python"
MAIN = CM / ".cache/wt/compare-main"
RECALL = CM / ".cache/wt/compare-plus"  # andre/search-recall at da6cd0f, a checkout of my own
CLAUDE = "/opt/homebrew/bin/claude"
TASKS = MAIN / "eval/tasks/e2e/pandas.jsonl"
VAGUE = MAIN / "eval/tasks/vague-b7-v2.jsonl"
RUNS = C / "runs"
LEDGER = RUNS / "ledger.jsonl"
DISCARDS = RUNS / "discards.jsonl"
CAP = 280
MAX_TURNS = 25
# The recipe's hold released the handshake 3 s after the model marker. codemem's warm-up encode (prewarm) is still
# running then, and LocalEmbedder._encode has no lock: a query encoded beside it on the Apple GPU aborts the server
# ("failed assertion _status < MTLCommandBufferStatusCommitted"). bin/holdtest.py: 3 s crashed, 8 s and 12 s answered.
HOLD_MARGIN = "10"
LOCK = None  # the open lock file while a session runs (one heavy process of mine at a time)

sys.path.insert(0, str(MAIN / "eval/src"))
sys.path.insert(0, str(Path(__file__).parent))
from cmeval.proxy import RecordingProxy  # noqa: E402

CODEMEM_TOOLS = {"mcp__codemem__search_code", "mcp__codemem__get_chunk", "mcp__codemem__index_status",
                 "mcp__codemem__refresh_index"}
CODEMEM_ALLOWED = ["mcp__codemem__search_code", "mcp__codemem__get_chunk", "mcp__codemem__index_status"]
# The adopt agent's "shell" condition, word for word: read-only commands each by its own rule; dontAsk refuses
# every other command (its fence-result.txt; my own fence below). rg (--pre runs a program) is left out.
SHELL_ALLOWED = ["Read", "Bash(grep:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)",
                 "Bash(wc:*)", "Bash(cut:*)", "Bash(xargs grep:*)"]
# arm -> (codemem source folder or None, prompt with the upfront list)
ARMS = {
    "grep": (None, False),
    "tool": (MAIN / "src", False),
    "upfront": (None, True),
    "tool+": (RECALL / "src", False),
    "tool-h": (MAIN / "src", False),
    "tool+h": (RECALL / "src", False),
    # block F: V0 = main at 463171c (compare-main moved there); V1 = andre/query-wording; F2 = the list and the tool
    "tool-v0": (MAIN / "src", False),
    "tool-q": (CM / ".cache/wt/query-wording/src", False),
    "upfront+tool": (MAIN / "src", True),
    # block G: track B's switch for repeated results (wilson/search-dedup at 242a7bf), set by the server's env
    "dedup-off": (CM / ".cache/wt/compare-dedup/src", False),
    "dedup-shorten": (CM / ".cache/wt/compare-dedup/src", False),
    "dedup-refill": (CM / ".cache/wt/compare-dedup/src", False),
}
DEDUP_MODE = {"dedup-off": "off", "dedup-shorten": "shorten", "dedup-refill": "refill"}
MODEL_LOCK = CM / ".cache/review/model.lock.d"  # shared with other agents: mkdir to take it, rmdir to give it back
# Arms with codemem's two hooks, installed as the adopt probe did (its probe.py, spec "hooks"): a settings file
# from the arm's own codemem.agents._merge_hooks_json, passed with --settings.
HOOK_ARMS = {"tool-h", "tool+h"}
HOOK_REFUSAL = "This is the first code search of this session"
REFUSED = re.compile(r"Permission to use \S+ has been denied")
BUILTIN_PLUGINS = {"cc-plugin-agents-md", "cc-plugin-telemetry", "cc-plugin-plugin-authoring"}
FOREIGN = ("BSD-licensed", "For coding agents", "CONTRIBUTING.md", "pandas-review", "mcp__easel", "track-c",
           "worklog", "andre/")
# Claude Code adds a gitStatus section to every session. With the empty .git marker it must stay empty:
# branch HEAD, status clean, no recent commits (else codemem's own history would be in the prompt).
EMPTY_GIT = re.compile(r"Current branch: HEAD\\n\\nMain branch \(you will usually use this for PRs\): main\\n\\n"
                       r"Status:\\n\(clean\)\\n\\nRecent commits:\\n\\n\\n")
USAGE_TEXT = re.compile(r"usage limit|limit reached|hit your limit|rate limit|resets? at", re.I)

WRAP = """\
{request}

Do not change any file. Find where in this repository the change for this request has to be
made. When you are confident, answer with one JSON object and nothing after it:
{{"files": [up to 3 file paths, the most likely first], "functions": [up to 5 function or method names, as Class.method where it applies, the most likely first]}}
"""
UPFRONT_HEAD = "Possibly relevant code, from a search by meaning (it may be wrong):"


def load_tasks() -> dict:
    return {t["id"]: t for t in (json.loads(l) for l in TASKS.read_text().split("\n") if l.strip())}


def load_vague() -> dict:
    out = {}
    for line in VAGUE.read_text().split("\n"):
        if line.strip():
            r = json.loads(line)
            out[(r["id"], r["level"])] = r["prompt"]
    return out


def request_text(task: dict, level: str, vague: dict) -> str:
    return task["query"].strip() if level == "L0" else vague[(task["id"], level)].strip()


def upfront_lines(task_id: str, level: str) -> list[str]:
    path = C / "upfront" / f"{task_id}-{level}.json"
    hits = json.loads(path.read_text())
    hits = hits.get("results", hits) if isinstance(hits, dict) else hits
    lines = []
    for h in hits[:20]:
        lines.append(f"{h['path']}:{h['start_line']}  {h.get('qualname') or h.get('name') or ''}".rstrip())
    return lines


def make_prompt(task: dict, level: str, vague: dict, arm: str) -> str:
    body = WRAP.format(request=request_text(task, level, vague))
    if ARMS[arm][1]:
        lines = upfront_lines(task["id"], level)
        if len(lines) != 20:
            raise SystemExit(f"{task['id']} {level}: the upfront list has {len(lines)} lines, not 20")
        body = UPFRONT_HEAD + "\n" + "\n".join(lines) + "\n\n" + body
    return body


def ledger_count() -> int:
    if not LEDGER.exists():
        return 0
    return sum(1 for line in LEDGER.read_text().split("\n") if line.strip() and not json.loads(line).get("fake"))


def heavy_lock():
    """An exclusive lock (fcntl) that every session, build and dry run of mine holds while it runs."""
    import fcntl
    f = open(C / "logs/heavy.lock", "a")
    fcntl.flock(f, fcntl.LOCK_EX)
    return f


def busy_processes() -> list[str]:
    """Any process that loads an embedding model, and any headless Claude Code session (another agent's)."""
    out = subprocess.run(["pgrep", "-fl", "codemem mcp|serve-embeddings|-m codemem|claude -p|omp/real_check"],
                         capture_output=True, text=True).stdout
    # a shell wrapper whose command text only mentions these words (another agent's waiting loop) loads nothing
    return [line for line in out.split("\n") if re.match(r"^\d+ ", line) and not re.match(r"^\d+ (/bin/)?(z|ba)?sh -c ", line)]


def free_memory() -> int:
    out = subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout.strip().split("\n")[-1]
    m = re.search(r"(\d+)%", out)
    return int(m.group(1)) if m else 100


def wait_for_quiet(max_wait: float = 3600) -> None:
    t0 = time.time()
    while True:
        found, free = busy_processes(), free_memory()
        if not found and free >= 15:
            return
        if time.time() - t0 > max_wait:
            raise SystemExit("the machine stayed busy: " + "; ".join(found) + f" free {free}%")
        print(f"  waiting: free {free}%; " + "; ".join(f[:100] for f in found), flush=True)
        time.sleep(20)


def clean_env(base_url: str) -> dict:
    """The adopt agent's environment for Claude Code, word for word (the runner's, minus its container parts)."""
    env = {k: os.environ[k] for k in ("HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG") if k in os.environ}
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    env.update({
        "ANTHROPIC_BASE_URL": base_url,
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_EFFORT_LEVEL": "medium",
        "ENABLE_TOOL_SEARCH": "false",
        "DISABLE_AUTOUPDATER": "1",
        "MCP_TIMEOUT": "120000",
        "MCP_TOOL_TIMEOUT": "120000",
    })
    return env


def server_env(src: Path, home: Path) -> dict:
    root = str(CM)
    return {
        "PYTHONPATH": str(src),
        "CODEMEM_STEERING": "light",  # main's default (config.py); the adopt runs set it the same
        "CODEMEM_VECTOR_BACKEND": "faiss",
        "CODEMEM_MODEL_IDLE_MINUTES": "0",
        "CODEMEM_HOME": str(home),
        "HF_HOME": root + "/.cache/huggingface",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TORCH_HOME": root + "/.cache/torch",
        "XDG_CACHE_HOME": root + "/.cache/xdg",
        "MPLCONFIGDIR": root + "/.cache/mpl",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    }


def expected_tools(arm: str) -> set:
    return {"Read", "Bash"} | (CODEMEM_TOOLS if ARMS[arm][0] else set())


def build_cmd(prompt: str, model: str, arm: str, mcp_json: Path, cd: bool = False,
              settings: Path | None = None) -> list[str]:
    allowed = SHELL_ALLOWED + (["Bash(cd:*)"] if cd else []) + (CODEMEM_ALLOWED if ARMS[arm][0] else [])
    return [CLAUDE, "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose",
            "--setting-sources", "project", "--strict-mcp-config", "--mcp-config", str(mcp_json),
            "--disable-slash-commands", "--no-session-persistence", "--exclude-dynamic-system-prompt-sections",
            "--tools", "Read,Bash", "--allowedTools", ",".join(allowed),
            "--permission-mode", "dontAsk", "--max-turns", str(MAX_TURNS), "--include-hook-events"] + (
            ["--settings", str(settings)] if settings else [])


def write_hook_settings(out: Path, src: Path, home: Path) -> Path:
    """codemem's two hooks exactly as `codemem init --write-hooks` writes them (agents._merge_hooks_json), with a
    command that runs this arm's code and the session's own CODEMEM_HOME. Written by the arm's own code."""
    hook_cmd = f"env PYTHONPATH={src} CODEMEM_HOME={home} {PY} -m codemem hook"
    p = subprocess.run([str(PY), "-c", "import sys; from pathlib import Path; from codemem import agents; "
                        "print(agents._merge_hooks_json(Path(sys.argv[1]), sys.argv[2]))",
                        str(out / "no-such-settings.json"), hook_cmd],
                       env={"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "")},
                       capture_output=True, text=True, check=True)
    path = out / "settings.json"
    path.write_text(p.stdout.strip() + "\n")
    return path


def gate(init: dict, model: str, arm: str) -> list[str]:
    bad = []
    tools = set(init.get("tools") or [])
    want = expected_tools(arm)
    if tools != want:
        bad.append(f"tools differ: extra {sorted(tools - want)}, missing {sorted(want - tools)}")
    servers = [(s.get("name"), s.get("status")) for s in init.get("mcp_servers") or []]
    if servers != ([("codemem", "connected")] if ARMS[arm][0] else []):
        bad.append(f"mcp_servers are {servers}")
    other = [p for p in init.get("plugins") or [] if p.get("path") != "builtin" or p.get("name") not in BUILTIN_PLUGINS]
    if other:
        bad.append(f"plugins loaded: {other}")
    if init.get("permissionMode") != "dontAsk":
        bad.append(f"permissionMode is {init.get('permissionMode')}")
    if init.get("model") != model:
        bad.append(f"model is {init.get('model')}")
    if init.get("skills"):
        bad.append(f"skills loaded: {init.get('skills')}")
    return bad


def body_check(out: Path, bodies: str = "bodies") -> dict:
    for path in sorted((out / bodies).glob("*.request")):
        try:
            b = json.loads(path.read_bytes())
        except ValueError:
            continue
        if not b.get("tools"):
            continue
        raw = path.read_text(errors="replace")
        foreign = [w for w in FOREIGN if w in raw]
        if "gitStatus" in raw and not EMPTY_GIT.search(raw):
            foreign.append("a gitStatus section that is not empty")
        return {"first_request": path.name, "tools": [t.get("name") for t in b.get("tools") or []],
                "foreign": foreign, "git_section_empty": bool(EMPTY_GIT.search(raw)), "bytes": len(raw)}
    return {"first_request": None}


def kill_tree(proc: subprocess.Popen) -> None:
    for sig, wait in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 0.0)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            break
        t = time.time()
        while proc.poll() is None and time.time() - t < wait:
            time.sleep(0.1)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def leftover_servers(index_dir: Path) -> list[int]:
    out = subprocess.run(["pgrep", "-f", str(index_dir)], capture_output=True, text=True).stdout
    return [int(x) for x in out.split()]


def write_mcp(out: Path, arm: str, task_id: str, idx: Path, home: Path) -> Path:
    src = ARMS[arm][0]
    if src is None:
        mcp = {"mcpServers": {}}
    else:
        server_cmd = [str(PY), str(C / "bin/mcp_hold.py"), str(out / "server.log"), HOLD_MARGIN, "120", "--",
                      str(PY), "-m", "codemem", "mcp", str(C / "tasks" / task_id / "repo"), "--index-dir", str(idx)]
        env = server_env(src, home)
        if arm in DEDUP_MODE:
            env["CODEMEM_SEARCH_DEDUP"] = DEDUP_MODE[arm]
        mcp = {"mcpServers": {"codemem": {"command": server_cmd[0], "args": server_cmd[1:],
                                          "env": env, "alwaysLoad": True}}}
    path = out / "mcp.json"
    path.write_text(json.dumps(mcp, indent=1))
    return path


def run_one(spec: dict, *, tasks: dict, vague: dict, fake_script: list | None = None) -> dict:
    rid, arm, task_id = spec["run"], spec["arm"], spec["task"]
    out = RUNS / rid
    if (out / "record.json").exists():
        rec = json.loads((out / "record.json").read_text())
        print(f"{rid}: done already ({rec.get('status')})", flush=True)
        return rec
    if fake_script is None and ledger_count() >= CAP:
        raise SystemExit(f"the cap of {CAP} sessions is reached")
    if out.exists():
        shutil.move(str(out), str(out) + f".interrupted-{int(time.time())}")
    out.mkdir(parents=True)
    src = ARMS[arm][0]
    if src is not None and not src.is_dir():
        raise SystemExit(f"{rid}: no source folder {src}")
    task = tasks[task_id]
    prompt = make_prompt(task, spec["level"], vague, arm)
    (out / "prompt.txt").write_text(prompt)
    (out / "spec.json").write_text(json.dumps({**spec, "src": str(src) if src else None}, indent=1))
    repo = C / "tasks" / task_id / "repo"
    wait_for_quiet()  # hard: no other model-loading process or headless session, memory as the brief says
    tq = time.time()
    subprocess.run([str(C / "bin/quiet.sh")])  # the coordinator's checks; after 10 min with none of ours, it goes on
    note = (C / "logs/quiet.log").read_text().strip().split("\n")[-1]
    machine = {"quiet": "STARTED ANYWAY" not in note, "quiet_note": note, "waited_s": round(time.time() - tq), "hot": subprocess.run(
        ["sh", "-c", "ps -axo pid,pcpu,command | awk '$2>50 && /Python/ {print $1, $2, $3, $4}'"],
        capture_output=True, text=True).stdout.strip().split("\n"), "swap": subprocess.run(
        ["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout.strip()}
    wait_for_quiet()
    lock = heavy_lock()
    t_lock, noted = time.time(), False
    while True:
        try:
            MODEL_LOCK.mkdir()
            break
        except FileExistsError:
            if not noted and time.time() - t_lock > 600:
                with open(C / "progress.md", "a") as f:
                    f.write(f"\n- {time.strftime('%H:%M')}: waiting over 10 minutes for `model.lock.d` before {rid}.\n")
                noted = True
            time.sleep(5)
    idx, home = C / "idx" / rid, C / "home-runs" / rid
    shutil.rmtree(idx, ignore_errors=True)
    shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True)
    if src is not None:
        idx.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cp", "-c", "-R", str(C / "tasks" / task_id / "index"), str(idx)], check=True)
    mcp_json = write_mcp(out, arm, task_id, idx, home)
    fake_api = None
    upstream = "https://api.anthropic.com"
    if fake_script is not None:
        from fakeapi import FakeAPI  # noqa: E402
        fake_api = FakeAPI(fake_script, out / "fakebodies").start()
        upstream = fake_api.url
    proxy = RecordingProxy(out / "proxy.jsonl", upstream=upstream, bodies_dir=out / "bodies").start()
    settings = write_hook_settings(out, src, home) if arm in HOOK_ARMS else None
    cmd = build_cmd(prompt, spec["model"], arm, mcp_json, cd=bool(spec.get("cd")), settings=settings)
    (out / "cmd.json").write_text(json.dumps(cmd[:2] + ["<prompt.txt>"] + cmd[3:], indent=1))
    if fake_script is None and ledger_count() == 0:
        with open(C / "progress.md", "a") as f:
            f.write(f"\n- **First real session started at {time.strftime('%H:%M:%S')}**: `{rid}`.\n")
    with open(LEDGER, "a") as f:
        f.write(json.dumps({"run": rid, "start": time.strftime("%Y-%m-%dT%H:%M:%S"), "fake": fake_script is not None,
                            **spec}) + "\n")
    t0 = time.time()
    status, why = "finished", []
    proc = subprocess.Popen(cmd, cwd=str(repo), env=clean_env(proxy.url), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=open(out / "stderr.txt", "w"), start_new_session=True,
                            text=True, bufsize=1)
    state = {"init": False, "stop": None, "init_s": None}

    foreign: set[str] = set()

    def watchdog() -> None:
        last_scan = 0.0
        while proc.poll() is None:
            reason = None
            if time.time() - last_scan > 5:  # a foreign model process during the session: its seconds are set aside
                last_scan = time.time()
                pids = subprocess.run(["pgrep", "-f", "codemem mcp|codemem index|codemem search|serve-embeddings|pytest|claude -p|omp/real_check"],
                                      capture_output=True, text=True).stdout.split()
                for pid in pids:
                    info = subprocess.run(["ps", "-o", "pgid=", "-o", "command=", "-p", pid], capture_output=True,
                                          text=True).stdout.strip()
                    if not info:
                        continue
                    pgid, _, command = info.partition(" ")
                    command = command.strip()
                    if pgid.strip() == str(proc.pid) or str(C) in info or re.match(r"^(/bin/)?(z|ba)?sh -c ", command):
                        continue
                    foreign.add(command.split("\n")[0][:160])
            if time.time() - t0 > 900:
                reason = ("timeout", "15 minutes")
            elif (out / "proxy.jsonl").exists():
                for l in (out / "proxy.jsonl").read_text().split("\n"):
                    if not l.strip():
                        continue
                    r = json.loads(l)
                    unified = (r.get("rate_limit_headers") or {}).get("anthropic-ratelimit-unified-status")
                    if r.get("status") == 429:
                        reason = ("usage_limit", "the proxy saw a 429")
                        break
                    if unified not in (None, "allowed", "allowed_warning"):
                        reason = ("usage_limit", f"subscription status {unified}")
                        break
            if reason:
                state["stop"] = reason
                kill_tree(proc)
                return
            time.sleep(0.5)

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        with open(out / "stream.jsonl", "w") as stream:
            for line in proc.stdout:
                stream.write(line)
                stream.flush()
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                kind = (ev.get("type"), ev.get("subtype"))
                if "hook" in str(ev.get("subtype") or "") or ev.get("type") == "hook":
                    # Only the hooks arms have hooks: codemem's two, from their own --settings file (user and
                    # project settings are not loaded). Any other hook, or any other kind of hook event, stops.
                    if arm not in HOOK_ARMS or ev.get("hook_event") not in ("PreToolUse", "PostToolUse"):
                        status, why = "aborted", [f"a hook event: {line[:300]}"]
                        break
                    continue
                if kind == ("system", "init") and not state["init"]:
                    bad = gate(ev, spec["model"], arm)
                    if bad:
                        status, why = "aborted", bad
                        break
                    state["init"], state["init_s"] = True, round(time.time() - t0, 1)
                    print(f"  {rid}: init ok after {state['init_s']} s", flush=True)
                    continue
                if not state["init"] and ev.get("type") in ("assistant", "user", "result"):
                    status, why = "aborted", ["an event before the init event"]
                    break
                if (ev.get("type") == "result" and ev.get("is_error") and ev.get("subtype") != "error_max_turns"
                        and USAGE_TEXT.search(str(ev.get("result") or ""))):
                    status, why = "usage_limit", [str(ev.get("result"))[:300]]
                    break
                if kind == ("system", "api_retry") and (ev.get("error_status") == 429
                                                        or USAGE_TEXT.search(str(ev.get("error") or ""))):
                    status, why = "usage_limit", [line[:300]]
                    break
    finally:
        kill_tree(proc)
        proxy.stop()
        if fake_api is not None:
            fake_api.stop()
    if state["stop"] and status == "finished":
        status, why = state["stop"][0], [state["stop"][1]]
    for r in (json.loads(l) for l in (out / "proxy.jsonl").read_text().split("\n") if l.strip()):
        if r.get("status") == 429:
            status, why = "usage_limit", [f"proxy saw a 429: {r.get('error')}"]
    wall = time.time() - t0
    for _ in range(100):
        if not leftover_servers(idx):
            break
        time.sleep(0.2)
    for pid in leftover_servers(idx):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    shutil.rmtree(idx, ignore_errors=True)
    shutil.rmtree(home, ignore_errors=True)
    try:
        MODEL_LOCK.rmdir()  # the lock this session made
    except OSError:
        pass
    lock.close()
    rec = {"run": rid, **spec, "fake": fake_script is not None, "status": status, "why": why, "wall_s": round(wall, 1),
           "init_s": state["init_s"], "machine": machine, "foreign_overlap": sorted(foreign),
           "body": body_check(out)}
    if rec["body"].get("foreign"):
        rec["status"], rec["why"] = "aborted", [f"foreign context in the first request: {rec['body']['foreign']}"]
    log_text = (out / "server.log").read_text(errors="replace") if (out / "server.log").exists() else ""
    rec["server_starts"] = log_text.count("] server pid ")
    rec["server_crashed"] = "failed assertion" in log_text or "server exited with -6" in log_text
    if rec["status"] == "finished":
        rec.update(extract(out, task))
    (out / "record.json").write_text(json.dumps(rec, indent=1))
    print(f"  {rid}: {rec['status']} {rec['why']} in {wall:.0f} s", flush=True)
    return rec


# ---------------------------------------------------------------- reading a run

EDGE = r"(?<![\w.-]){}(?![\w.])"


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text(c.get("text") if isinstance(c, dict) and "text" in c else c) for c in content)
    if isinstance(content, dict):
        return json.dumps(content)
    return "" if content is None else str(content)


def result_text(text: str) -> str:
    t = text.strip()
    if t.startswith("{"):
        try:
            d = json.loads(t)
        except ValueError:
            return text
        if isinstance(d, dict) and isinstance(d.get("result"), str):
            return d["result"]
    return text


def gold_in(text: str, gold: list[str]) -> list[str]:
    return [g for g in gold if re.search(EDGE.format(re.escape(g)), text)]


CARD = re.compile(r"(?m)^(\d+)\.\s+(\S+?):(\d+)-(\d+)\s{2}(.+?)\s{2}\[id (\d+)\]")
MORE_HEADER = "More results, by name (ask get_chunk for any of them):"
REL_ITEM = re.compile(r"(\S+) \((\S+?):(\d+)\)")


def cards(text: str) -> list[dict]:
    return [{"rank": int(m.group(1)), "path": m.group(2), "start": int(m.group(3)), "end": int(m.group(4)),
             "name": m.group(5), "id": int(m.group(6))} for m in CARD.finditer(result_text(text))]


def parse_result(text: str) -> dict:
    """The cards, the names in their `related:` lines, and the lines of the More block (tool+)."""
    body = result_text(text)
    related, more, in_more, rank = [], [], False, 0
    for line in body.split("\n"):
        m = CARD.match(line)
        if m:
            rank = int(m.group(1))
            continue
        if line.startswith("   related: "):
            related += [{"card": rank, "name": x.group(1), "path": x.group(2), "line": int(x.group(3))}
                        for x in REL_ITEM.finditer(line[len("   related: "):])]
            continue
        if line.strip() == MORE_HEADER:
            in_more = True
            continue
        if in_more:
            mm = re.match(r"^(\S+?):(\d+)\s{2}(.+)$", line.strip())
            if mm:
                more.append({"path": mm.group(1), "line": int(mm.group(2)), "name": mm.group(3)})
            elif not line.strip():
                in_more = False
    return {"cards": cards(body), "related": related, "more": more, "has_more_block": MORE_HEADER in body}


SHORT_LINE = re.compile(r"^   \(shown earlier (as a card|in full by get_chunk), unchanged\)$")
MARKS = ("(changed since shown earlier)", "(shown earlier, other lines this time)")


def parse_dedup(text: str, k: int, gold: list[str], gold_fns: list[str]) -> dict:
    """Full cards and short lines of a search_code page (wilson/search-dedup), with marks and the refilled ones."""
    body = result_text(text)
    lines = body.split("\n")
    entries = []
    for i, line in enumerate(lines):
        m = CARD.match(line)
        if not m:
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        short = bool(SHORT_LINE.match(nxt))
        mark = next((mk for mk in MARKS if nxt.strip() == mk), None)
        entries.append({"rank": int(m.group(1)), "path": m.group(2), "start": int(m.group(3)), "name": m.group(5),
                        "id": int(m.group(6)), "short": short, "mark": mark})
    def is_fn(e):
        return e["path"] in gold and bool(name_hits([e["name"]], gold_fns)["full"])
    fn_where = "card" if any(is_fn(e) and not e["short"] for e in entries) else (
        "short" if any(is_fn(e) and e["short"] for e in entries) else "none")
    return {"full": sum(not e["short"] for e in entries), "short": sum(e["short"] for e in entries),
            "changed": sum(e["mark"] == MARKS[0] for e in entries), "other_lines": sum(e["mark"] == MARKS[1] for e in entries),
            "refilled": [f"{e['path']}:{e['start']} {e['name']}" for e in entries if e["rank"] > k and not e["short"]],
            "refilled_fn": sum(1 for e in entries if e["rank"] > k and not e["short"] and is_fn(e)),
            "short_items": [{"id": e["id"], "path": e["path"], "start": e["start"], "name": e["name"]} for e in entries if e["short"]],
            "only_new_note": "of these results are new to this session" in body,
            "chars": len(body), "fn_where": fn_where if gold_fns else None}


def gold_where(parsed: dict, gold: list[str], gold_fns: list[str]) -> dict:
    """Where a gold file and a gold function first appear in a result: card, related, more or absent."""
    def fn(name: str, path: str) -> bool:
        return path in gold and bool(name_hits([name.split(" (")[0]], gold_fns)["full"])
    out = {}
    for what, test in (("file", lambda n, p: p in gold), ("function", fn)):
        if what == "function" and not gold_fns:
            out[what] = None
            continue
        if any(test(c["name"], c["path"]) for c in parsed["cards"]):
            out[what] = "card"
        elif any(test(r["name"], r["path"]) for r in parsed["related"]):
            out[what] = "related"
        elif any(test(m["name"], m["path"]) for m in parsed["more"]):
            out[what] = "more"
        else:
            out[what] = "absent"
    return out


def next_step(calls: list[dict], i: int, parsed: dict, results: dict) -> dict:
    """What the agent did right after the result of calls[i] (a search_code): the first call of a later turn."""
    first = calls[i]
    later = [c for c in calls[i + 1:] if c["turn"] > first["turn"]]
    if not later:
        return {"step": "answered", "call": None}
    c = later[0]
    card_paths = {x["path"] for x in parsed["cards"]}
    card_ids = {str(x["id"]) for x in parsed["cards"]}
    listed = [(x["path"], x["name"]) for x in parsed["related"] + parsed["more"]]
    listed_paths = {p for p, _ in listed} - card_paths
    def short(n: str) -> str:
        return re.split(r"[.:]", n.split(" (")[0].split("> ")[-1])[-1]
    card_names = {short(x["name"]) for x in parsed["cards"]}
    listed_names = {short(n) for _, n in listed} - card_names
    arg = c["arg"]
    if c["kind"] == "search_code":
        step = "search again"
    elif c["kind"] == "get_chunk":
        ref = str(c.get("ref") or arg)
        if any(ref.strip('"{} ').endswith(x) for x in card_ids) or any(p in ref for p in card_paths):
            step = "get_chunk: a card"
        elif any(p in ref for p in listed_paths) or any(n and n in ref for n in listed_names):
            step = "get_chunk: a related/more name"
        else:
            step = "get_chunk: other"
    elif c["kind"] == "file read":
        if any(p in arg for p in card_paths):
            step = "read: a card's file"
        elif any(p in arg for p in listed_paths):
            step = "read: a related/more file"
        else:
            step = "read: other file"
    elif c["kind"] == "shell search":
        words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", arg))
        if words & listed_names:
            step = "grep: a related/more name"
        elif words & card_names or any(p in arg for p in card_paths):
            step = "grep: a card name or file"
        elif any(p in arg for p in listed_paths):
            step = "grep: a related/more file"
        else:
            step = "grep: unrelated to the result"
    else:
        step = "other: " + c["kind"]
    return {"step": step, "call": f"t{c['turn']} {c['tool']} {arg[:160]}"}


def last_part(name: str) -> str:
    return re.split(r"[.:]", name.strip().rstrip("()"))[-1]


def name_hits(names: list[str], gold_fns: list[str]) -> dict:
    """Rule "full": the name, less any module or path prefix, equals a gold qualified name (Class.method).
    Rule "last": its last dotted part equals a gold symbol's last part."""
    full, last = [], []
    for n in names:
        n2 = n.strip().rstrip("()").replace("::", ".").replace(":", ".")
        for g in gold_fns:
            if n2 == g or n2.endswith("." + g):
                full.append(g)
            if last_part(n2) == last_part(g):
                last.append(g)
    return {"full": sorted(set(full)), "last": sorted(set(last))}


def bash_kind(cmd: str) -> str:
    c = cmd.strip()
    first = re.split(r"\s+", c, 1)[0] if c else ""
    if "grep" in c.split("|")[0] or first in ("rg", "find", "ls", "fd") or re.search(r"\|\s*(xargs\s+)?grep", c):
        return "shell search"
    if first in ("cat", "head", "tail", "sed", "nl", "awk", "less", "more"):
        return "file read"
    if first in ("wc", "cut", "sort", "uniq", "pwd", "echo"):
        return "shell other"
    return "other"


def call_kind(name: str, inp: dict) -> str:
    if name == "Read":
        return "file read"
    if name == "Bash":
        return bash_kind(str(inp.get("command", "")))
    if name.endswith("search_code"):
        return "search_code"
    if name.endswith("get_chunk"):
        return "get_chunk"
    return "other"


def arg_of(name: str, inp: dict, repo: str) -> str:
    if name.endswith("search_code"):
        extra = {k: v for k, v in inp.items() if k != "query"}
        return str(inp.get("query", "")) + (f" {json.dumps(extra)}" if extra else "")
    if name == "Read":
        return str(inp.get("file_path", "")).replace(repo + "/", "") + (
            f" @{inp.get('offset')}" if inp.get("offset") else "") + (f"+{inp.get('limit')}" if inp.get("limit") else "")
    if name.endswith("get_chunk"):
        return json.dumps(inp)
    if name == "Bash":
        return str(inp.get("command", "")).replace(repo + "/", "")
    return json.dumps(inp)[:300]


def ls_paths(cmd: str, text: str) -> str:
    """`ls DIR` prints bare names: give them their folder, so a gold file listed there counts as seen."""
    m = re.match(r"^ls(?:\s+-\S+)*\s+([^\s|;&]+)\s*$", cmd.strip())
    if not m:
        return text
    d = m.group(1).rstrip("/")
    return text + "\n" + "\n".join(f"{d}/{w}" for w in re.split(r"\s+", text) if w and "/" not in w)


def parse_answer(text: str) -> dict | None:
    """The last JSON object with a "files" key in the final text."""
    best = None
    for m in re.finditer(r"\{", text or ""):
        depth, j = 0, m.start()
        for j in range(m.start(), len(text)):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
        try:
            d = json.loads(text[m.start():j + 1])
        except ValueError:
            continue
        if isinstance(d, dict) and "files" in d:
            best = d
    return best


def norm_path(p: str, repo: str) -> str:
    p = str(p).strip().replace(repo + "/", "")
    p = re.sub(r"^\./", "", p)
    return re.sub(r":\d+(-\d+)?$", "", p)


def proxy_times(out: Path) -> dict:
    from datetime import datetime
    recs = [json.loads(l) for l in (out / "proxy.jsonl").read_text().split("\n") if l.strip()]
    main = [r for r in recs if r.get("path") == "/v1/messages" and (r.get("tools") or 0) > 0 and r.get("start")]
    if not main:
        return {}
    t = lambda r: datetime.fromisoformat(r["start"]).timestamp()  # noqa: E731
    first = min(t(r) for r in main)
    end = max(t(r) + (r.get("ms_end") or 0) / 1000 for r in main)
    util = None
    for r in recs:
        h = r.get("rate_limit_headers") or {}
        if "anthropic-ratelimit-unified-7d-utilization" in h:
            util = h
    return {"answer_s": round(end - first, 1), "main_requests": len(main), "requests": len(recs),
            "side_models": sorted({r.get("model") for r in recs if r.get("path") == "/v1/messages"} - {None}),
            "unified_status": (util or {}).get("anthropic-ratelimit-unified-status"),
            "util_7d": (util or {}).get("anthropic-ratelimit-unified-7d-utilization"),
            "util_5h": (util or {}).get("anthropic-ratelimit-unified-5h-utilization")}


def request_of(out: Path) -> str:
    """The request part of the prompt (without the upfront list and the wrapper)."""
    text = (out / "prompt.txt").read_text() if (out / "prompt.txt").exists() else ""
    if text.startswith(UPFRONT_HEAD):
        text = text.split("\n\n", 1)[1] if "\n\n" in text else text
    return text.split("\n\nDo not change any file.")[0]


def memory_names(query: str, task: dict, request: str) -> list[str]:
    """Gold function and class names (last part) that the query holds and the request does not."""
    names = {f["symbol"].split(".")[-1] for f in task["gold"]["functions"]} | {
        c["symbol"].split(".")[-1] for c in task["gold"]["classes"]}
    found = []
    for n in sorted(n for n in names if n and len(n) > 2):
        pat = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(n) + r"(?![A-Za-z0-9_])")
        if pat.search(query) and not pat.search(request):
            found.append(n)
    return found


def extract(out: Path, task: dict) -> dict:
    repo = str(C / "tasks" / task["id"] / "repo")
    gold = task["gold"]["files"]
    gold_fns = [f["symbol"] for f in task["gold"]["functions"]]
    events = [json.loads(l) for l in (out / "stream.jsonl").read_text().split("\n") if l.strip().startswith("{")]
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    turns, calls, results = [], [], {}
    for e in events:
        if e.get("type") == "assistant":
            msg = e.get("message") or {}
            mid = msg.get("id")
            if mid not in turns:
                turns.append(mid)
            for b in msg.get("content") or []:
                if b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    calls.append({"turn": turns.index(mid) + 1, "id": b.get("id"), "tool": b.get("name"),
                                  "kind": call_kind(b.get("name", ""), inp), "arg": arg_of(b.get("name", ""), inp, repo),
                                  "input": inp})
        elif e.get("type") == "user":
            content = (e.get("message") or {}).get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        results[b.get("tool_use_id")] = {"text": _text(b.get("content")), "is_error": b.get("is_error")}
    for c in calls:
        r = results.get(c["id"]) or {}
        text = r.get("text", "")
        c["error"] = bool(r.get("is_error"))
        c["refused"] = c["error"] and bool(REFUSED.search(text))
        seen_text = ls_paths(c["arg"], text) if c["tool"] == "Bash" else text
        c["gold_in_result"] = [] if c["error"] else gold_in(result_text(seen_text), gold)
        c["result_chars"] = len(text)
        opened = []
        if not c["error"]:
            if c["tool"] == "Read":
                fp = norm_path(c["input"].get("file_path", ""), repo)
                opened = [g for g in gold if fp == g]
            elif c["kind"] == "file read":
                opened = gold_in(c["arg"], gold)
            elif c["kind"] == "get_chunk":
                opened = [cd["path"] for cd in cards(text) if cd["path"] in gold] or gold_in(text[:400], gold)
        c["opened_gold"] = sorted(set(opened))
        if c["kind"] == "get_chunk":
            c["ref"] = c["input"].get("ref")
        if c["kind"] == "search_code":
            parsed = parse_result(text)
            c["parsed"] = parsed
            cs = parsed["cards"]
            c["json_wrapped"] = text.strip().startswith('{"result"')
            c["has_more_block"] = parsed["has_more_block"]
            c["names_arg"] = c["input"].get("names")
            c["k_arg"] = c["input"].get("k")
            c["other_args"] = {k: v for k, v in c["input"].items() if k not in ("query", "names", "k")}
            c["gold_where"] = gold_where(parsed, gold, gold_fns)
            c["cards"] = len(cs)
            c["card_list"] = [f"{cd['path']}:{cd['start']} {cd['name']}" for cd in cs]
            c["related_list"] = [f"{r['path']}:{r['line']} {r['name']}" for r in parsed["related"]]
            c["more_list"] = [f"{m['path']}:{m['line']} {m['name']}" for m in parsed["more"]]
            c["dedup"] = parse_dedup(text, int(c["input"].get("k") or 10), gold, gold_fns)
            c["gold_file_rank"] = next((cd["rank"] for cd in cs if cd["path"] in gold), None)
            hits = name_hits([cd["name"] for cd in cs if cd["path"] in gold], gold_fns)
            c["gold_fn_in_results"] = hits
            c["gold_fn_rank"] = next((cd["rank"] for cd in cs if cd["path"] in gold
                                      and name_hits([cd["name"]], gold_fns)["full"]), None)
            c["keyword_only"] = "keyword matching only" in text
            c["result_head"] = text[:400]
        del c["input"]
    for i, c in enumerate(calls):
        if c["kind"] == "search_code":
            c["next_step"] = next_step(calls, i, c["parsed"], results)
    for c in calls:
        c.pop("parsed", None)
    for c in calls:
        c["hook_refused"] = bool(c["error"] and HOOK_REFUSAL in (results.get(c["id"]) or {}).get("text", ""))
    hook_refused = [i for i, c in enumerate(calls) if c["hook_refused"]]
    after_refusal = None
    if hook_refused:
        i = hook_refused[0]
        later = [c for c in calls[i + 1:] if c["turn"] > calls[i]["turn"]]
        if not later:
            after_refusal = "answered"
        else:
            n = later[0]
            if n["kind"] == "search_code":
                after_refusal = "search_code"
            elif n["tool"] == "Bash" and n["arg"].strip() == calls[i]["arg"].strip():
                after_refusal = "the same grep again"
            elif n["kind"] == "shell search":
                after_refusal = "another grep"
            elif n["kind"] == "file read":
                after_refusal = "a file read"
            else:
                after_refusal = "other: " + n["kind"]
    searches = [c for c in calls if c["kind"] == "search_code"]
    first = searches[0] if searches else None
    final_text = result.get("result") if isinstance(result.get("result"), str) else ""
    # what the agent did with each short result: reopened it later (get_chunk, a read of its file, the same query)?
    short_follow = []
    for i, c in enumerate(calls):
        for item in (c.get("dedup") or {}).get("short_items") or []:
            later = [x for x in calls[i + 1:] if x["turn"] > c["turn"]]
            how = None
            for x in later:
                if x["kind"] == "get_chunk" and (str(item["id"]) in x["arg"] or item["path"] in x["arg"]):
                    how = "get_chunk"
                elif x["kind"] == "file read" and item["path"] in x["arg"]:
                    how = "read its file"
                elif x["kind"] == "search_code" and x["arg"].split(" {")[0].strip().lower() == c["arg"].split(" {")[0].strip().lower():
                    how = "the same query again"
                if how:
                    break
            named = any(last_part(f) == last_part(item["name"].split(" (")[0]) for f in
                        ((parse_answer(final_text) or {}).get("functions") or []))
            short_follow.append({"turn": c["turn"], "item": f"{item['path']}:{item['start']} {item['name']}",
                                 "reopened": how, "named_in_answer": named})
    answer = parse_answer(final_text) if result.get("subtype") == "success" else None
    files = [norm_path(p, repo) for p in (answer or {}).get("files") or []] if answer else []
    fns = [str(f) for f in (answer or {}).get("functions") or []] if answer else []
    fn_hits = name_hits(fns, gold_fns)
    usage = result.get("usage") or {}
    tok = {k: usage.get(k) or 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                          "cache_creation_input_tokens")}
    tok["total"] = sum(tok.values())
    return {
        "init": {k: init.get(k) for k in ("model", "permissionMode", "apiKeySource", "mcp_servers", "tools", "plugins",
                                          "claude_code_version", "cwd")},
        "calls": calls,
        "n_turns": len(turns),
        "answered": answer is not None,
        "answer": answer,
        "final_text_tail": (final_text or "")[-600:],
        "files": files,
        "functions": fns,
        "gold_files": gold,
        "gold_functions": gold_fns,
        "gold_file_first": bool(files) and files[0] in gold,
        "gold_file_any": any(f in gold for f in files),
        "gold_fn_full": bool(fn_hits["full"]) if gold_fns else None,
        "gold_fn_last": bool(fn_hits["last"]) if gold_fns else None,
        "fn_hits": fn_hits,
        "n_calls": len(calls),
        "kinds": [c["kind"] for c in calls],
        "refused": [f"t{c['turn']} {c['arg'][:150]}" for c in calls if c["refused"]],
        "n_refused": sum(1 for c in calls if c["refused"]),
        "refused_turns": len({c["turn"] for c in calls if c["refused"]}
                             - {c["turn"] for c in calls if not c["refused"]}),
        "gold_seen_turn": next((c["turn"] for c in calls if c["gold_in_result"]), None),
        "gold_read_turn": next((c["turn"] for c in calls if c["opened_gold"]), None),
        "called_search": bool(searches),
        "n_searches": len(searches),
        "first_search_turn": first["turn"] if first else None,
        "first_search_call_index": calls.index(first) + 1 if first else None,
        "first_query": first["arg"] if first else None,
        "first_search_gold_file_rank": first.get("gold_file_rank") if first else None,
        "first_search_gold_fn": first.get("gold_fn_in_results") if first else None,
        "first_keyword_only": first.get("keyword_only") if first else None,
        "first_json_wrapped": first.get("json_wrapped") if first else None,
        "first_search_failed": bool(first and (first.get("error") or str(first.get("result_head", "")).startswith("Connection closed"))),
        "search_errors": [f"t{c['turn']} {c.get('result_head', '')[:80]}" for c in searches if c.get("error")],
        "first_has_more_block": first.get("has_more_block") if first else None,
        "first_cards": first.get("cards") if first else None,
        "first_k": first.get("k_arg") if first else None,
        "first_names": first.get("names_arg") if first else None,
        "any_names": [c.get("names_arg") for c in searches if c.get("names_arg")],
        "first_gold_where": first.get("gold_where") if first else None,
        "first_query_words": len(re.sub(r" \{.*\}$", "", first["arg"]).split()) if first else None,
        "first_query_memory": memory_names(re.sub(r" \{.*\}$", "", first["arg"]), task, request_of(out)) if first else None,
        "first_next_step": first.get("next_step") if first else None,
        "n_get_chunk": sum(1 for c in calls if c["kind"] == "get_chunk"),
        "dedup_searches": [{"turn": c["turn"], **{k: v for k, v in (c.get("dedup") or {}).items() if k != "short_items"}}
                           for c in searches],
        "short_follow": short_follow,
        "hook_first_refused": bool(hook_refused),
        "hook_refused_call": calls[hook_refused[0]]["arg"][:160] if hook_refused else None,
        "hook_after_refusal": after_refusal,
        "hook_later_refusals": max(0, len(hook_refused) - 1),
        "result": {k: result.get(k) for k in ("subtype", "is_error", "num_turns", "duration_ms", "duration_api_ms",
                                              "total_cost_usd")},
        "tokens": tok,
        "model_usage": result.get("modelUsage"),
        **proxy_times(out),
    }


# ---------------------------------------------------------------- running a spec, with discards

class StopRun(Exception):
    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def discard_reason(rec: dict) -> str | None:
    """A session whose first search shows that the wrong thing ran is discarded and run again."""
    if rec.get("status") != "finished" or not rec.get("called_search"):
        return None
    if rec.get("first_keyword_only"):
        return "keyword matching only: the hold did not work"
    if rec.get("first_search_failed"):
        return "the server died at the first search (the hold did not wait for the warm-up)"
    if rec.get("first_json_wrapped"):
        return "the result came as a JSON string: the code of 8d86da8 ran, not 09c4ef0"
    if (rec.get("arm") == "tool+" and not rec.get("first_has_more_block")
            and (rec.get("first_cards") or 0) >= (rec.get("first_k") or 10)):
        return "no 'More results, by name' block: the tool+ code did not run"
    return None


def run_spec(spec: dict, tasks: dict, vague: dict) -> dict:
    why = None
    for attempt in range(3):
        print(f"{time.strftime('%H:%M:%S')} {spec['run']} ({ledger_count()} sessions so far)", flush=True)
        rec = run_one(spec, tasks=tasks, vague=vague)
        why = discard_reason(rec)
        if why:
            dest = RUNS / f"{spec['run']}.discard-{int(time.time())}"
            shutil.move(str(RUNS / spec["run"]), str(dest))
            with open(DISCARDS, "a") as f:
                f.write(json.dumps({"run": spec["run"], "moved_to": dest.name, "why": why,
                                    "time": time.strftime("%H:%M:%S")}) + "\n")
            print(f"  DISCARD {spec['run']}: {why}", flush=True)
            continue
        if rec["status"] != "finished":
            raise StopRun(f"{spec['run']} ended {rec['status']}: {rec['why']}", 3 if rec["status"] == "usage_limit" else 2)
        print(f"  7-day use of the subscription: {rec.get('util_7d')} ({rec.get('unified_status')})", flush=True)
        return rec
    raise StopRun(f"{spec['run']}: discarded three times ({why}); fix before going on", 4)


# ---------------------------------------------------------------- the fence

def fence(task_id: str, cd: bool = False) -> None:
    """The adopt agent's fence test (bin/fence.py), run in my task folder with my exact command line and a fake
    API that asks for each test command. No model call is made."""
    from fakeapi import FakeAPI  # noqa: E402
    work = C / "tasks" / task_id / "repo"
    before = sorted(str(p.relative_to(work)) for p in work.rglob("*"))
    R = "pandas/core/reshape"
    refuse = [
        "touch probe_was_here.txt",
        f'grep -rn "def merge_asof" {R} > probe_redirect.txt',
        f"sed -n '1w probe_sedw.txt' {R}/merge.py",
        f"grep -rn merge_asof {R}; touch probe_chain.txt",
        f"head -1 {R}/merge.py && touch probe_and.txt",
        f"cat {R}/merge.py | tee probe_tee.txt",
        f'grep "$(touch probe_subst.txt)" {R}/merge.py',
        f'grep "`touch probe_tick.txt`" {R}/merge.py',
        f'rg --pre "touch" merge_asof {R}',
        f"rg --pre=./probe_pre.sh merge_asof {R}",
        f"find {R} -name merge.py -exec touch probe_find.txt ;",
        "echo x > probe_echo.txt",
        f"ls {R} > probe_ls.txt",
        "xargs touch probe_xargs.txt < /dev/null",
        "cat <(touch probe_procsub.txt)",
        f"wc -l {R}/merge.py; python3 -c \"open('probe_py.txt','w')\"",
        f"grep -rln merge_asof {R} | xargs rm -f probe_none.txt",
        f"cat {R}/merge.py >> probe_append.txt",
        f"sort -o probe_sorto.txt {R}/merge.py",
        f"grep -rn merge_asof {R} | sort -o probe_sorto2.txt",
        f"uniq {R}/merge.py probe_uniq.txt",
        "env touch probe_env.txt",
        "command touch probe_command.txt",
        "timeout 5 touch probe_timeout.txt",
        "nice touch probe_nice.txt",
        f"split -l 1000 {R}/merge.py probe_split_",
        f"base64 -i {R}/__init__.py -o probe_b64.txt",
        f"xxd {R}/__init__.py probe_xxd.txt",
        "git init probe_gitdir",
        f"diff {R}/merge.py {R}/concat.py > probe_diff.txt",
        f"file -C -m probe_magic {R}/merge.py",
        f"cp {R}/merge.py probe_cp.txt",
        "mkdir probe_dir",
        f"cat {R}/merge.py | xargs -I{{}} touch probe_xargsI.txt",
        f"grep -rn merge_asof {R} | xargs grep -n x > probe_xg.txt",
        f"head -1 {R}/merge.py | sh",
        f"ls {R} | bash",
        "echo touch probe_echo2.txt | sh",
        f"tail -n 1 {R}/merge.py | tee -a probe_tee2.txt",
        "git log -1",
        "cd .. && ls",
        f"cat {CM}/CLAUDE.md > /dev/null; touch probe_abs.txt",
    ]
    if cd:  # the coordinator's cases for the list with Bash(cd:*)
        refuse += ["cd pandas && touch probe_cd_touch.txt",
                   "cd /tmp && python -c \"open('probe_cd_py.txt','w')\"",
                   "cd pandas; echo hi > probe_cd_echo.txt",
                   "cd pandas && sed -n '1w probe_cd_sedw.txt' core/api.py",
                   "cd pandas && cat core/api.py > probe_cd_redirect.txt",
                   "cd pandas && grep -n def core/api.py | tee probe_cd_tee.txt"]
    run = ([f"cd pandas && grep -n def core/api.py", "cd pandas/core/reshape && grep -n merge_asof merge.py | head -3"]
           if cd else []) + [
        f'grep -rn "def merge_asof" {R} | head -3',
        f"ls {R}",
        f"cat {R}/__init__.py | head -5",
        f"wc -l {R}/merge.py",
        f"tail -2 {R}/merge.py",
        f"sed -n '1,3p' {R}/merge.py",
        f'grep -rln merge_asof {R} | xargs grep -n "def merge_asof"',
        f"grep -rn merge_asof {R} | cut -c1-60 | head -3",
        f"grep -rn merge_asof {R} | sort | head -3",
        f"grep -c merge_asof {R}/merge.py",
        "pwd",
    ]
    (work / "probe_pre.sh").write_text("#!/bin/sh\ntouch probe_pre_ran.txt\ncat \"$1\"\n")
    (work / "probe_pre.sh").chmod(0o755)
    cmds = [(c, "refuse") for c in refuse] + [(c, "run") for c in run]
    script = [[{"type": "tool_use", "id": f"toolu_fence_{i:02d}", "name": "Bash",
                "input": {"command": c, "description": "fence test"}} for i, (c, _) in enumerate(cmds)],
              [{"type": "tool_use", "id": "toolu_fence_read", "name": "Read",
                "input": {"file_path": str(work / R / "__init__.py")}}],
              [{"type": "text", "text": "Done."}]]
    fdir = C / ("fence-cd" if cd else "fence")
    shutil.rmtree(fdir, ignore_errors=True)
    for stray in ("probe_cd_py.txt",):
        Path("/tmp", stray).unlink(missing_ok=True)
    lock = heavy_lock()
    fdir.mkdir(parents=True)
    api = FakeAPI(script, fdir / "bodies").start()
    empty = fdir / "mcp.json"
    empty.write_text(json.dumps({"mcpServers": {}}))
    cmd = build_cmd("Fence test.", "claude-haiku-5-5", "grep", empty, cd=cd)
    t0 = time.time()
    p = subprocess.run(cmd, cwd=str(work), env=clean_env(api.url), capture_output=True, text=True, timeout=600)
    api.stop()
    lock.close()
    (fdir / "stream.jsonl").write_text(p.stdout)
    (fdir / "stderr.txt").write_text(p.stderr)
    (fdir / "cmd.json").write_text(json.dumps(cmd, indent=1))
    events = [json.loads(l) for l in p.stdout.split("\n") if l.strip().startswith("{")]
    init = next((e for e in events if e.get("subtype") == "init"), {})
    print("init tools:", init.get("tools"), "| mcp:", init.get("mcp_servers"), "| mode:", init.get("permissionMode"),
          "| cwd:", init.get("cwd"), "| %.0f s" % (time.time() - t0))
    print("gate:", gate(init, "claude-haiku-5-5", "grep") or "clean")
    res = {}
    for e in events:
        if e.get("type") == "user" and isinstance((e.get("message") or {}).get("content"), list):
            for b in e["message"]["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    res[b["tool_use_id"]] = (bool(b.get("is_error")), _text(b.get("content")))
    bad = 0
    for i, (c, want) in enumerate(cmds):
        err, text = res.get(f"toolu_fence_{i:02d}", (None, "NO RESULT"))
        ok = (want == "refuse") == bool(err)
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} want {want:6} got {'refused' if err else 'ran':7} | {c[:66]:66} | {text[:90]!r}")
    err, text = res.get("toolu_fence_read", (None, "NO RESULT"))
    print(f"{'ok ' if not err else 'BAD'} want run    got {'refused' if err else 'ran':7} | Read tool on {R}/__init__.py | {text[:60]!r}")
    bad += bool(err)
    (work / "probe_pre.sh").unlink()
    after = sorted(str(p.relative_to(work)) for p in work.rglob("*"))
    made = sorted(set(after) - set(before)) + [f"/tmp/{x}" for x in ("probe_cd_py.txt",) if Path("/tmp", x).exists()]
    gone = sorted(set(before) - set(after))
    print("files written by the session:", made or "none", "| files gone:", gone or "none")
    body = body_check(fdir)
    print("first request:", body)
    holds = not made and not gone and bad == 0
    print("FENCE HOLDS" if holds else "FENCE BROKEN", "| mismatches:", bad)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    tasks, vague = load_tasks(), load_vague()
    if args[0] == "fence":
        fence(args[1], cd="--cd" in args)
    elif args[0] == "run":
        plan = [json.loads(l) for l in Path(args[1]).read_text().split("\n") if l.strip()]
        only = args[args.index("--only") + 1] if "--only" in args else None
        limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
        done = 0
        for spec in plan:
            if only and spec["run"] != only:
                continue
            if limit is not None and done >= limit:
                break
            try:
                run_spec(spec, tasks, vague)
            except StopRun as e:
                print(f"STOP: {e}", flush=True)
                sys.exit(e.code)
            done += 1
    elif args[0] == "fake":
        spec = json.loads(args[1])
        script = json.loads(Path(args[2]).read_text())
        rec = run_one(spec, tasks=tasks, vague=vague, fake_script=script)
        print(json.dumps({k: rec.get(k) for k in ("status", "why", "init_s", "body", "answered", "files", "functions",
                                                   "gold_file_first", "gold_fn_full", "gold_fn_last", "gold_seen_turn",
                                                   "gold_read_turn", "first_query", "first_search_gold_file_rank",
                                                   "first_search_gold_fn", "first_keyword_only", "kinds", "answer_s",
                                                   "n_turns", "tokens")}, indent=1))
    elif args[0] == "extract":
        ids = args[1:] or sorted(p.name for p in RUNS.iterdir() if (p / "record.json").exists() and "." not in p.name)
        for rid in ids:
            out = RUNS / rid
            rec = json.loads((out / "record.json").read_text())
            if rec.get("status") != "finished":
                continue
            rec.update(extract(out, tasks[rec["task"]]))
            (out / "record.json").write_text(json.dumps(rec, indent=1))
            print(rid, "extracted")


if __name__ == "__main__":
    main()
