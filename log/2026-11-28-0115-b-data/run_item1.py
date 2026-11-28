"""Item 1 of Andre's entry of 2026-11-27 12:40 / 12:55 UTC: Claude Code with codemem over MCP against grep only.

Arms (the only difference is codemem):
  grep  Claude Code, built-in Read, Edit, Write, Grep, Glob (no shell)
  tool  the same, plus codemem 463171c's MCP server (all its tools allowed), wording `light` (463171c's default)
  detailed  as tool, with the branch wilson/mcp-detailed-wording (463171c plus steering "detailed": a long
        search_code description and server instructions that say when to call it instead of Grep). No hooks in any arm
Both codemem arms register the server with alwaysLoad, as `codemem init` does.
Models: claude-haiku-5-5 and claude-sonnet-5-5. Same prompt (e2e_run.py's), flags and tools in both arms. Prompt
cache on: one Claude Code conversation per run, as Claude Code keeps it.

Every run gets its own folder ~/item1/<level>/<task>/<arm>-<model>-r<rep>/:
  repo/   the repo at the task's base commit (git archive, one commit "base", no history)
  index/  (tool) a copy of the repo's base index, caught up to repo/ by codemem 463171c before the agent starts
The base index of each repo is built once by codemem 463171c at one task's commit (~/item1/base/<repo>); the copy is
then updated from the run's own repo copy (changed files re-chunked and re-embedded; unchanged vectors come from
codemem's vector cache). `codemem status` is saved before the agent starts. codemem's config (~/.codemem-463) makes the
first search wait up to 180 s for the model, so no search should be answered from keywords only; the check counts it.

Outputs per run: <arm>-<model>-r<rep>.{jsonl (stream), diff, summary.json, status.txt, mcp.json} in
analysis/b1-links/llm_query/out/item1/<level>/<task>/.

Usage: python run_item1.py base                       build the two base indexes
       python run_item1.py run LEVELS ARMS MODELS REPS [WORKERS]   e.g. run L1,L2 grep,tool haiku,sonnet 1 4
"""
from __future__ import annotations

import collections as C
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANALYSIS = HERE.parents[1]
WEEK = ANALYSIS.parent
CM = WEEK / "codemem-463"  # git worktree at 463171c
PY = str(ANALYSIS / "xpu-venv" / "Scripts" / "python.exe")
CLAUDE = Path.home() / ".local" / "bin" / "claude.exe"
ROOT = Path.home() / "item1"
OUT = HERE / "out" / "item1"
HOME463 = Path.home() / ".codemem-463"
ENV = {**os.environ, "CODEMEM_HOME": str(HOME463), "PYTHONPATH": f"{CM / 'src'};{ANALYSIS / 'b1-links'}",
       "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"}
SETS = ("e2e-vague8", "e2e-b7")
BASE_TASK = {"pandas": "pandas-dev__pandas-71129", "playwright": "microsoft__playwright-43174"}
TOOLS = "Read,Edit,Write,Grep,Glob"
INDEX_LOCK = threading.Lock()


def tasks(level: str) -> list[dict]:
    out = []
    for s in SETS:
        f = HERE / "out" / s / f"tasks-{level}.jsonl"
        out += [json.loads(x) for x in f.read_text(encoding="utf8").splitlines() if x.strip()]
    return out


def _writable(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def make_copy(task: dict, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest, onerror=_writable)
    dest.mkdir(parents=True)
    git_dir = Path.home() / ".cmeval" / "repos" / (task["repo"].replace("/", "__") + ".git")
    proc = subprocess.Popen(["git", "--git-dir", str(git_dir), "archive", "--format=tar", task["base_commit"]], stdout=subprocess.PIPE)
    with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
        for m in tar:
            if m.isdir() or m.isfile():
                tar.extract(m, dest, filter="data")
    if proc.wait() != 0:
        raise SystemExit(f"git archive failed for {task['id']}")
    git = ["git", "-c", "core.autocrlf=false", "-c", "core.longpaths=true", "-c", "user.name=e2e", "-c", "user.email=e2e@localhost"]
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "base"]):
        subprocess.run(git + args, cwd=dest, check=True, capture_output=True)


def codemem(*args: str, timeout: int = 7200) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-m", "codemem", *args], env=ENV, capture_output=True, text=True, encoding="utf8",
                          errors="replace", timeout=timeout)


def build_base() -> None:
    by_id = {t["id"]: t for t in tasks("L1")}
    for repo, tid in BASE_TASK.items():
        d = ROOT / "base" / repo
        if (d / "index" / "index.db").exists():
            print(repo, "base exists")
            continue
        make_copy(by_id[tid], d / "repo")
        t = time.time()
        r = codemem("index", str(d / "repo"), "--index-dir", str(d / "index"))
        print(repo, "indexed in", round(time.time() - t), "s, exit", r.returncode, r.stdout[-800:], r.stderr[-1500:], flush=True)


def prompt(task: dict) -> str:  # e2e_run.py's prompt
    return (f"Fix the GitHub issue below in this repository ({task['repo']}, at the commit the issue was filed against). "
            "You cannot build, compile or run anything: read the code and make the code change you believe fixes the "
            "root cause. When you are done, reply with a short summary of the change.\n\n"
            f"<issue>\n{task['query']}\n</issue>")


def run_one(level: str, task: dict, arm: str, model: str, rep: int) -> str:
    name = f"{arm}-{model}-r{rep}"
    out = OUT / level / task["id"]
    out.mkdir(parents=True, exist_ok=True)
    if (out / f"{name}.summary.json").exists():
        return f"{level} {task['id']} {name}: exists"
    work = ROOT / level / task["id"] / name
    repo = work / "repo"
    make_copy(task, repo)
    command = [str(CLAUDE), "-p", "--model", MODELS[model], "--output-format", "stream-json", "--verbose",
               "--permission-mode", "acceptEdits", "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence",
               "--disable-slash-commands", "--max-budget-usd", "5", "--tools", TOOLS]
    status, prep = None, {}
    if arm in ("tool", "detailed", "pr85"):
        index = work / "index"
        if index.exists():
            shutil.rmtree(index, onerror=_writable)
        # The task's index: the repo's base index brought up to the task's commit once (from a copy of the repo at
        # that commit), then copied for each run and checked against the run's own copy (identical files: no change).
        task_index = ROOT / "taskidx" / task["id"] / "index"
        with INDEX_LOCK:  # one catch-up at a time (the GPU and the vector cache)
            if not (task_index.parent / "done").exists():
                if task_index.parent.exists():
                    shutil.rmtree(task_index.parent, onerror=_writable)
                base = ROOT / "base" / task["repo"].split("/")[1] / "index"
                shutil.copytree(base, task_index, ignore=shutil.ignore_patterns("write.lock", "*.tmp"))
                make_copy(task, task_index.parent / "repo")
                t = time.time()
                r = codemem("index", str(task_index.parent / "repo"), "--index-dir", str(task_index))
                (task_index.parent / "catchup.json").write_text(json.dumps(
                    {"seconds": round(time.time() - t, 1), "exit": r.returncode, "tail": (r.stdout + r.stderr)[-1500:]}), encoding="utf8")
                if r.returncode == 0:
                    (task_index.parent / "done").write_text("", encoding="utf8")
        shutil.copytree(task_index, index, ignore=shutil.ignore_patterns("write.lock", "*.tmp"))
        t = time.time()
        r = codemem("index", str(repo), "--index-dir", str(index))
        prep = {"task_index": json.loads((task_index.parent / "catchup.json").read_text(encoding="utf8")),
                "catchup_seconds": round(time.time() - t, 1), "catchup_exit": r.returncode, "catchup_tail": (r.stdout + r.stderr)[-1500:]}
        st = codemem("status", str(repo), "--index-dir", str(index))
        status = st.stdout + st.stderr
        (out / f"{name}.status.txt").write_text(status, encoding="utf8")
        senv = {k: ENV[k] for k in ("CODEMEM_HOME", "PYTHONPATH", "PYTHONUTF8", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")}
        if arm == "detailed":  # branch wilson/mcp-detailed-wording: 463171c with steering "detailed" (prompts only)
            senv |= {"PYTHONPATH": f"{WEEK / 'codemem-detailed' / 'src'};{ANALYSIS / 'b1-links'}", "CODEMEM_STEERING": "detailed"}
        if arm == "pr85":  # PR #85, wilson/no-hooks at 4902671: light wording with when-to-search, k 1-10, augmented query fields
            senv |= {"PYTHONPATH": f"{WEEK / 'codemem-nohooks' / 'src'};{ANALYSIS / 'b1-links'}"}
        # alwaysLoad: what `codemem init` writes (agents.py), so the tools are not kept behind Claude Code's tool search
        mcp = {"mcpServers": {"codemem": {"command": PY, "args": ["-m", "codemem", "mcp", str(repo), "--index-dir", str(index)],
                                          "env": senv, "alwaysLoad": True}}}
        (out / f"{name}.mcp.json").write_text(json.dumps(mcp, indent=1), encoding="utf8")
        command += ["--mcp-config", str(out / f"{name}.mcp.json"), "--allowedTools", TOOLS + ",mcp__codemem"]
    else:
        command += ["--allowedTools", TOOLS]
    start = time.time()
    log = out / f"{name}.jsonl"
    with open(log, "w", encoding="utf8") as f:
        done = subprocess.run(command, input=prompt(task), stdout=f, stderr=subprocess.PIPE, text=True, encoding="utf8",
                              errors="replace", cwd=repo, timeout=3600, env=os.environ.copy())
    seconds = time.time() - start
    events = [json.loads(x) for x in log.read_text(encoding="utf8").splitlines() if x.strip().startswith("{")]
    tools = C.Counter()
    for e in events:
        if e.get("type") == "assistant":
            for c in e["message"].get("content", []):
                if c.get("type") == "tool_use":
                    tools[c["name"]] += 1
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    patch = subprocess.run(["git", "diff"], cwd=repo, capture_output=True, text=True, encoding="utf8").stdout
    (out / f"{name}.diff").write_text(patch, encoding="utf8")
    summary = {"arm": arm, "model": MODELS[model], "rep": rep, "level": level, "task": task["id"], "exit": done.returncode,
               "seconds": round(seconds), "cost_usd": result.get("total_cost_usd"), "turns": result.get("num_turns"),
               "usage": result.get("usage"), "model_usage": result.get("modelUsage"), "tool_calls": dict(tools),
               "subtype": result.get("subtype"), "claude_code_version": init.get("claude_code_version"),
               "tools_available": init.get("tools"), "mcp_servers": init.get("mcp_servers"),
               "final": (result.get("result") or "")[:1500], "stderr": done.stderr[-500:], **prep}
    (out / f"{name}.summary.json").write_text(json.dumps(summary, indent=1), encoding="utf8")
    return f"{level} {task['id']} {name}: ${summary['cost_usd']} {summary['turns']} turns {summary['seconds']} s tools {dict(tools)}"


def main() -> None:
    if sys.argv[1] == "base":
        build_base()
        return
    levels, arms, models, reps = (sys.argv[i].split(",") for i in range(2, 6))
    workers = int(sys.argv[6]) if len(sys.argv) > 6 else 4
    only = os.environ.get("ITEM1_REPO")  # e.g. pandas: only that repo's tasks
    jobs = [(lv, t, a, m, int(r)) for r in reps for lv in levels for m in models for t in tasks(lv) for a in arms
            if not only or t["repo"].endswith("/" + only)]
    with ThreadPoolExecutor(workers) as ex:
        for fut in [ex.submit(run_one, *j) for j in jobs]:
            try:
                print(fut.result(), flush=True)
            except Exception as e:  # noqa: BLE001
                print("FAILED", repr(e)[:500], flush=True)


if __name__ == "__main__":
    main()
