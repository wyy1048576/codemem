"""Grep agent and the full-code codemem loop (n = 5, 10, 25, 50) on the 8 contamination-free, validated, fair
pilot tasks with vague prompts (L1 or L2 of eval/tasks/vague-pilot18-v2.jsonl on main).

Tasks: out/e2e-vague8/tasks-<LEVEL>.jsonl (the fresh task with `query` replaced by the vague prompt; the issue as
written is kept in `query_L0`). Outputs: out/e2e-vague8/<LEVEL>/<task_id>/<arm>.*. Each task gets a fresh copy of
the repo at its base commit (no history), reset between arms. Finished arms are skipped; a failed arm is tried
once more (Windows file locks on the index have failed a run before).

Usage: python run_vague8.py L1|L2     (CODEMEM_HOME=~/.codemem-e2e, PYTHONPATH as e2e_all.py)
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

HERE = Path(__file__).resolve().parent
PY = sys.executable
NL = chr(10)
LEVEL = sys.argv[1]
BASE = HERE / "out" / "e2e-vague8"
tasks_file = BASE / f"tasks-{LEVEL}.jsonl"
tasks = [json.loads(x) for x in tasks_file.read_text(encoding="utf8").split(NL) if x.strip()]
ARMS = ["grep", "full5", "full10", "full25", "full50"]
GIT = ["git", "-c", "core.autocrlf=false", "-c", "core.longpaths=true", "-c", "user.name=e2e", "-c", "user.email=e2e@localhost"]


def _writable(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def copy_dir(task) -> Path:
    return Path.home() / "e2e-copies" / task["repo"].split("/")[1]


def fresh_copy(task):
    copy = copy_dir(task)
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


def reset(task):
    subprocess.run(GIT + ["reset", "--hard", "-q"], cwd=copy_dir(task), check=True)
    subprocess.run(GIT + ["clean", "-fdq"], cwd=copy_dir(task), check=True)


def run_arm(task, arm, out):
    copy = copy_dir(task)
    if arm == "grep":
        cmd, env = [PY, str(HERE / "e2e_run.py"), str(tasks_file), task["id"], "grep", str(copy), str(out)], os.environ.copy()
    else:
        n = arm.removeprefix("full")
        cmd = [PY, str(HERE / "e2e_loop.py"), str(tasks_file), task["id"], str(copy), str(out)]
        env = os.environ.copy() | {"LOOP_N": n, "LOOP_TAG": arm, "LOOP_FULL": "1"}
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf8", errors="replace", env=env)
    (out / f"{arm}.stdout.txt").write_text(r.stdout + NL + r.stderr[-3000:], encoding="utf8")
    reset(task)


for i, task in enumerate(tasks, 1):
    out = BASE / LEVEL / task["id"]
    todo = [a for a in ARMS if not (out / f"{a}.summary.json").exists()]
    if not todo:
        print(f"[{LEVEL} {i}/{len(tasks)}] {task['id']}: done already", flush=True)
        continue
    out.mkdir(parents=True, exist_ok=True)
    fresh_copy(task)
    for arm in todo:
        for attempt in (1, 2):
            run_arm(task, arm, out)
            if (out / f"{arm}.summary.json").exists():
                break
        s = out / f"{arm}.summary.json"
        cost = json.loads(s.read_text(encoding="utf8")).get("cost_usd") if s.exists() else "FAILED"
        print(f"[{LEVEL} {i}/{len(tasks)}] {task['id']} {arm}: cost {cost}", flush=True)
