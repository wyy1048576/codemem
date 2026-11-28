"""Arm 1: one Sonnet call per task that reads the one-shot top 50 plus the one-hop picks (hop_retriever.py).

Shown set = the saved hop-oneshot hits (top 50, then the picks). Each is shown as its card header plus its full
source at the task's commit (from git), cut at FULL_CODE_CHARS, the same format as loop-full. Sonnet answers with
the loop judge prompt (round 1, no earlier rounds), so the cost is one loop-full-style call over a bigger list.
Cached like every other call (llm.extract "loop_full").

Usage: python hop_feed.py [THREADS]   -> out/hop_feed.jsonl
"""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import llm
from aug_retriever import FULL_CODE_CHARS

HERE = Path(__file__).parent
TASKS = HERE.parent.parent / "codemem-7c24558" / "eval" / "tasks"
REPOS = Path.home() / ".cmeval" / "repos"
NL = chr(10)


def blob(git_dir: Path, sha: str, path: str, memo: dict) -> list[str]:
    if (sha, path) not in memo:
        out = subprocess.run(["git", "--git-dir", str(git_dir), "show", f"{sha}:{path}"], capture_output=True)
        memo[(sha, path)] = out.stdout.decode("utf8", "replace").splitlines()
    return memo[(sha, path)]


def one(item):
    task, hits = item
    git_dir = REPOS / (task["repo"].replace("/", "__") + ".git")
    memo, parts = {}, []
    for i, h in enumerate(hits, start=1):
        lines = blob(git_dir, task["base_commit"], h["path"], memo)
        code = NL.join(lines[h["start_line"] - 1:h["end_line"]])
        if len(code) > FULL_CODE_CHARS:
            cut = code[:FULL_CODE_CHARS]
            code = cut + f"{NL}[... {code.count(NL) - cut.count(NL)} more lines not shown]"
        parts.append(f"{i}. {h['path']}:{h['start_line']}-{h['end_line']}  {h.get('symbol') or ''}{NL}{code}")
    shown = (NL + NL).join(parts)
    record = llm.extract("loop_full", llm.loop_input(task["repo"], task["query"], [], 1, shown))
    out = llm.clean_loop(record["output"], task["query"], shown, len(hits))
    return {"task_id": task["id"], "shown": [[h["path"], h["start_line"], h["end_line"]] for h in hits],
            "shown_chars": len(shown), "cost_usd": record.get("cost_usd"), "found": out["found"],
            "picks": [[hits[p - 1]["path"], hits[p - 1]["start_line"], hits[p - 1]["end_line"]] for p in out["picks"]]}


if __name__ == "__main__":
    tasks = {}
    for f in ("fresh-cpp-v1-68.jsonl", "fresh-v1-py100.jsonl"):
        for x in (TASKS / f).read_text(encoding="utf8").split(NL):
            if x.strip():
                t = json.loads(x)
                tasks[t["id"]] = t
    items = []
    for repo in ("duckdb", "pandas"):
        for x in (Path.home() / ".cmeval" / "runs" / f"{repo}-arc-hop" / "hop-oneshot.jsonl").read_text(encoding="utf8").split(NL):
            if x.strip():
                r = json.loads(x)
                items.append((tasks[r["task_id"]], r["hits"]))
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    items = items[:limit] if limit else items
    with ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 4) as pool:
        rows = list(pool.map(one, items))
    (HERE / "out" / "hop_feed.jsonl").write_text(NL.join(json.dumps(r) for r in rows) + NL, encoding="utf8")
    print(f"{len(rows)} tasks, ${sum(r['cost_usd'] or 0 for r in rows):.2f}, median chars {sorted(r['shown_chars'] for r in rows)[len(rows) // 2]}")
