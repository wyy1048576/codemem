"""End-to-end: a headless Claude Code agent (Sonnet 5.5, medium effort) tries to fix one issue.

Two arms, same prompt, model and copy of the repo (git history removed, so the fix is not visible):
  grep     built-in Read, Edit, Write, Grep, Glob
  codemem  built-in Read, Edit, Write, plus codemem's search_code and get_chunk (no Grep, Glob or shell)
  codemem+grep  both: Read, Edit, Write, Grep, Glob, search_code, get_chunk (no shell)
  mcp      as codemem+grep, plus hybrid_v2's rules as instructions (system_mcp.txt, appended to Claude Code's system
           prompt) and hooks (mcp_hooks.py: repeated greps, a note when stuck, one review before the first stop after
           an edit); codemem's server through mcp_codemem.py (waits for the model, plain text, logs each search).
           Prompt cache on, as for every arm here: one Claude Code conversation.
Neither arm can build or run code. The full event stream is saved, then summarised: cost, tokens, turns,
time, tool calls by name, and the diff.

Usage: python e2e_run.py TASKS.jsonl TASK_ID ARM REPO_COPY OUT_DIR
"""
from __future__ import annotations

import collections as C
import json
import os
import subprocess
import sys
import time
from pathlib import Path

tasks_file, task_id, arm, repo, out_dir = sys.argv[1:6]
out = Path(out_dir).resolve()
out.mkdir(parents=True, exist_ok=True)
task = next(t for t in (json.loads(x) for x in Path(tasks_file).read_text(encoding="utf8").split("\n") if x.strip())
            if t["id"] == task_id)
HERE = Path(__file__).resolve().parent
ANALYSIS = Path(__file__).resolve().parents[2]
CLAUDE = Path.home() / ".local" / "bin" / "claude.exe"
PROMPT = (f"Fix the GitHub issue below in this repository ({task['repo']}, at the commit the issue was filed against). "
          "You cannot build, compile or run anything: read the code and make the code change you believe fixes the "
          "root cause. When you are done, reply with a short summary of the change.\n\n"
          f"<issue>\n{task['query']}\n</issue>")
common = [str(CLAUDE), "-p", "--model", "claude-sonnet-5-5", "--effort", "medium", "--output-format", "stream-json",
          "--verbose", "--permission-mode", "acceptEdits", "--setting-sources", "", "--strict-mcp-config",
          "--no-session-persistence", "--disable-slash-commands", "--max-budget-usd", "5"]
if arm == "grep":
    command = common + ["--tools", "Read,Edit,Write,Grep,Glob", "--allowedTools", "Read,Edit,Write,Grep,Glob"]
elif arm in ("codemem", "codemem+grep"):
    env = {"PYTHONPATH": str(ANALYSIS / "b1-links"), "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
           "CODEMEM_HOME": str(Path.home() / ".codemem-e2e")}
    mcp = {"mcpServers": {"codemem": {"command": str(ANALYSIS / "xpu-venv" / "Scripts" / "python.exe"),
                                      "args": ["-m", "codemem", "mcp", str(Path(repo).resolve())], "env": env}}}
    (out / "mcp.json").write_text(json.dumps(mcp, indent=1), encoding="utf8")
    builtin = "Read,Edit,Write,Grep,Glob" if arm == "codemem+grep" else "Read,Edit,Write"
    command = common + ["--tools", builtin, "--mcp-config", str(out / "mcp.json"),
                        "--allowedTools", builtin + ",mcp__codemem__search_code,mcp__codemem__get_chunk"]
elif arm in ("mcp", "mcp0"):  # hybrid_v2 as Claude Code + codemem's MCP server + hooks + instructions (no loop of our own)
    # mcp also has PR #26's steering (main's light wording and footer, the agent note, the first-search and lost-trail
    # hooks, alwaysLoad); mcp0 (the first smoke test) has only our own hooks and system_mcp.txt
    pr26 = arm == "mcp"
    py = str(ANALYSIS / "xpu-venv" / "Scripts" / "python.exe")
    env = {"PYTHONPATH": str(ANALYSIS / "b1-links"), "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
           "CODEMEM_HOME": str(Path.home() / ".codemem-e2e"), "CODEMEM_CALL_LOG": str(out / f"{arm}.codemem.jsonl"),
           "MCP_PR26": "1" if pr26 else "0"}
    (out / f"{arm}.codemem.jsonl").unlink(missing_ok=True)
    server = {"command": py, "args": [str(HERE / "mcp_codemem.py"), str(Path(repo).resolve())], "env": env} | ({"alwaysLoad": True} if pr26 else {})
    (out / f"{arm}.mcp.json").write_text(json.dumps({"mcpServers": {"codemem": server}}, indent=1), encoding="utf8")
    hook_dir = out / f"{arm}.hooks"
    hook_dir.mkdir(exist_ok=True)
    for f in hook_dir.iterdir():
        f.unlink()
    pyp = Path(py).as_posix()
    hook = {"type": "command", "command": f'"{pyp}" "{(HERE / "mcp_hooks.py").as_posix()}" "{hook_dir.as_posix()}"'}
    pre = [{"matcher": "Grep", "hooks": [hook]}]
    post = [{"matcher": "Grep|Edit|Write|MultiEdit|mcp__codemem__search_code", "hooks": [hook]}]
    if pr26:  # the matchers of `codemem init --write-hooks` (pr26/hook.py PRE_MATCHER, POST_MATCHER); no Bash tool here
        h26 = {"type": "command", "command": f'"{pyp}" "{(HERE / "pr26_hook.py").as_posix()}" "{(hook_dir / "pr26.log.jsonl").as_posix()}"'}
        pre.append({"matcher": "Grep|Glob|mcp__codemem__search_code", "hooks": [h26]})
        post.append({"matcher": "Grep|Glob|Read|mcp__codemem__(search_code|get_chunk)", "hooks": [h26]})
    settings = {"hooks": {"PreToolUse": pre, "PostToolUse": post, "Stop": [{"hooks": [hook]}]}}
    (out / f"{arm}.settings.json").write_text(json.dumps(settings, indent=1), encoding="utf8")
    system = (HERE / "system_mcp.txt").read_text(encoding="utf8")
    if pr26:  # the agent note `codemem init` writes into CLAUDE.md (light), here in the system prompt: the runs load no CLAUDE.md
        sys.path.insert(0, str(HERE))
        from pr26 import prompts as p26
        system = p26.agent_notes("light") + chr(10) + system
    builtin = "Read,Edit,Write,Grep,Glob"
    command = common + ["--tools", builtin, "--mcp-config", str(out / f"{arm}.mcp.json"), "--settings", str(out / f"{arm}.settings.json"),
                        "--append-system-prompt", system,
                        "--allowedTools", builtin + ",mcp__codemem__search_code,mcp__codemem__get_chunk"]
elif arm == "mcpmd":  # codemem over MCP, no hooks, no appended prompt: only a CLAUDE.md that says when to call it
    py = str(ANALYSIS / "xpu-venv" / "Scripts" / "python.exe")
    env = {"PYTHONPATH": str(ANALYSIS / "b1-links"), "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
           "CODEMEM_HOME": str(Path.home() / ".codemem-e2e"), "CODEMEM_CALL_LOG": str(out / f"{arm}.codemem.jsonl"),
           "MCP_PR26": "0"}
    (out / f"{arm}.codemem.jsonl").unlink(missing_ok=True)
    server = {"command": py, "args": [str(HERE / "mcp_codemem.py"), str(Path(repo).resolve())], "env": env, "alwaysLoad": True}
    (out / f"{arm}.mcp.json").write_text(json.dumps({"mcpServers": {"codemem": server}}, indent=1), encoding="utf8")
    # Only our CLAUDE.md is loaded: the repo's own CLAUDE.md and .claude/ (skills, settings) are moved aside for the run,
    # since the grep arm never loads them (--setting-sources "").
    aside = out / f"{arm}.aside"
    if aside.exists():
        import shutil
        shutil.rmtree(aside)
    aside.mkdir()
    for name in ("CLAUDE.md", ".claude", "CLAUDE.local.md"):
        if (Path(repo) / name).exists():
            os.replace(Path(repo) / name, aside / name)
    (Path(repo) / "CLAUDE.md").write_text((HERE / "claude_md_codemem.md").read_text(encoding="utf8"), encoding="utf8")
    builtin = "Read,Edit,Write,Grep,Glob"
    command = [("project" if x == "" and i and common[i - 1] == "--setting-sources" else x) for i, x in enumerate(common)]
    command += ["--tools", builtin, "--mcp-config", str(out / f"{arm}.mcp.json"),
                "--allowedTools", builtin + ",mcp__codemem__search_code,mcp__codemem__get_chunk"]
else:
    raise SystemExit(f"arm {arm!r}")

start = time.time()
log = out / f"{arm}.jsonl"
with open(log, "w", encoding="utf8") as f:
    done = subprocess.run(command, input=PROMPT, stdout=f, stderr=subprocess.PIPE, text=True, encoding="utf8",
                          errors="replace", cwd=repo, timeout=3600, env=os.environ.copy())
seconds = time.time() - start
if arm == "mcpmd":  # put the repo's own files back before the diff
    (Path(repo) / "CLAUDE.md").unlink(missing_ok=True)
    for f in (out / f"{arm}.aside").iterdir():
        os.replace(f, Path(repo) / f.name)
events = [json.loads(x) for x in log.read_text(encoding="utf8").split("\n") if x.strip().startswith("{")]
tools = C.Counter()
for e in events:
    if e.get("type") == "assistant":
        for c in e["message"].get("content", []):
            if c.get("type") == "tool_use":
                tools[c["name"]] += 1
result = next((e for e in reversed(events) if e.get("type") == "result"), {})
diff = subprocess.run(["git", "diff", "--stat"], cwd=repo, capture_output=True, text=True).stdout
patch = subprocess.run(["git", "diff"], cwd=repo, capture_output=True, text=True, encoding="utf8").stdout
(out / f"{arm}.diff").write_text(patch, encoding="utf8")
summary = {"arm": arm, "task": task_id, "exit": done.returncode, "seconds": round(seconds),
           "cost_usd": result.get("total_cost_usd"), "turns": result.get("num_turns"), "usage": result.get("usage"),
           "models": sorted((result.get("modelUsage") or {}).keys()), "tool_calls": dict(tools),
           "subtype": result.get("subtype"), "diff_stat": diff.strip(), "final": (result.get("result") or "")[:1500],
           "stderr": done.stderr[-500:]}
if arm in ("mcp", "mcp0", "mcpmd"):
    hl = [json.loads(x) for f in (out / f"{arm}.hooks").glob("*.log.jsonl") for x in f.read_text(encoding="utf8").splitlines() if x.strip()]
    cl = out / f"{arm}.codemem.jsonl"
    calls = [json.loads(x) for x in cl.read_text(encoding="utf8").splitlines() if x.strip()] if cl.exists() else []
    summary |= {"hook_events": hl, "codemem_searches": len(calls), "codemem_ks": [c["k"] for c in calls],
                "codemem_keyword_only": sum(bool(c["models_loading"]) for c in calls)}
(out / f"{arm}.summary.json").write_text(json.dumps(summary, indent=1), encoding="utf8")
print(json.dumps(summary, indent=1))
