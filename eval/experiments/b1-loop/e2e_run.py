"""End-to-end: a headless Claude Code agent (Sonnet 5.5, medium effort) tries to fix one issue.

Two arms, same prompt, model and copy of the repo (git history removed, so the fix is not visible):
  grep     built-in Read, Edit, Write, Grep, Glob
  codemem  built-in Read, Edit, Write, plus codemem's search_code and get_chunk (no Grep, Glob or shell)
  codemem+grep  both: Read, Edit, Write, Grep, Glob, search_code, get_chunk (no shell)
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
else:
    raise SystemExit(f"arm {arm!r}")

start = time.time()
log = out / f"{arm}.jsonl"
with open(log, "w", encoding="utf8") as f:
    done = subprocess.run(command, input=PROMPT, stdout=f, stderr=subprocess.PIPE, text=True, encoding="utf8",
                          errors="replace", cwd=repo, timeout=3600, env=os.environ.copy())
seconds = time.time() - start
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
(out / f"{arm}.summary.json").write_text(json.dumps(summary, indent=1), encoding="utf8")
print(json.dumps(summary, indent=1))
