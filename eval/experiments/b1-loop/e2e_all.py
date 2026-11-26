"""Run the two end-to-end arms on every task of one repo: grep agent (e2e_run.py grep) and the codemem loop with a
fix step (e2e_loop.py). Each task gets a fresh copy of the repo at its base commit with git history removed (one
commit, so `git diff` shows the agent's change); the copy is reset between arms. Tasks with both summaries saved
are skipped, so the script can be rerun after a crash.

Usage: python e2e_all.py REPO_NAME [LIMIT]     e.g. duckdb   -> out/e2e-all/<task_id>/
Needs CODEMEM_HOME=~/.codemem-e2e (the loop's index of the copy) and the usual PYTHONPATH.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).parent
PY = sys.executable
NL = chr(10)
name = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
tasks_file = HERE.parent.parent / "codemem-7c24558" / "eval" / "tasks" / {"duckdb": "fresh-cpp-v1-68.jsonl", "pandas": "fresh-v1-py100.jsonl"}[name]
tasks = {json.loads(x)["id"]: json.loads(x) for x in tasks_file.read_text(encoding="utf8").split(NL) if x.strip()}
ids = [json.loads(x)["task_id"] for x in (Path.home() / ".cmeval" / "runs" / f"{name}-arc-hop" / "hop-oneshot.jsonl").read_text(encoding="utf8").split(NL) if x.strip()]
ids = ids[:limit] if limit else ids
copy = Path.home() / "e2e-copies" / name
GIT = ["git", "-c", "core.autocrlf=false", "-c", "core.longpaths=true", "-c", "user.name=e2e", "-c", "user.email=e2e@localhost"]


def _writable(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def fresh_copy(task):
    if copy.exists():
        shutil.rmtree(copy, onerror=_writable)
    copy.mkdir(parents=True)
    git_dir = Path.home() / ".cmeval" / "repos" / (task["repo"].replace("/", "__") + ".git")
    proc = subprocess.Popen(["git", "--git-dir", str(git_dir), "archive", "--format=tar", task["base_commit"]], stdout=subprocess.PIPE)
    with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
        for m in tar:
            if m.isdir() or m.isfile():
                tar.extract(m, copy, filter="data")
    if proc.wait() != 0:
        raise SystemExit(f"git archive failed for {task['id']}")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "base"]):
        subprocess.run(GIT + args, cwd=copy, check=True, capture_output=True)


def reset():
    subprocess.run(GIT + ["reset", "--hard", "-q"], cwd=copy, check=True)
    subprocess.run(GIT + ["clean", "-fdq"], cwd=copy, check=True)


for i, tid in enumerate(ids, 1):
    out = HERE / "out" / "e2e-all" / tid
    if (out / "grep.summary.json").exists() and (out / "loop.summary.json").exists():
        print(f"[{i}/{len(ids)}] {tid}: done already", flush=True)
        continue
    out.mkdir(parents=True, exist_ok=True)
    fresh_copy(tasks[tid])
    if not (out / "grep.summary.json").exists():
        r = subprocess.run([PY, str(HERE / "e2e_run.py"), str(tasks_file), tid, "grep", str(copy), str(out)], capture_output=True, text=True,
                           encoding="utf8", errors="replace")
        (out / "grep.stdout.txt").write_text(r.stdout + NL + r.stderr[-3000:], encoding="utf8")
        reset()
    if not (out / "loop.summary.json").exists():
        r = subprocess.run([PY, str(HERE / "e2e_loop.py"), str(tasks_file), tid, str(copy), str(out)], capture_output=True, text=True,
                           encoding="utf8", errors="replace")
        (out / "loop.stdout.txt").write_text(r.stdout + NL + r.stderr[-3000:], encoding="utf8")
        reset()
    got = {a: json.loads((out / f"{a}.summary.json").read_text(encoding="utf8")).get("cost_usd") if (out / f"{a}.summary.json").exists() else "FAILED"
           for a in ("grep", "loop")}
    print(f"[{i}/{len(ids)}] {tid}: cost {got}", flush=True)
