"""Grep agent and the codemem loop arms on tasks with vague prompts: by default the 8 contamination-free, validated,
fair pilot tasks (L1 / L2 of eval/tasks/vague-pilot18-v2.jsonl on main); VAGUE_SET=e2e-b7 for the 6 b7 tasks.

Arms: grep; fullN (e2e_loop.py, judge sees N results as raw code, separate fix call; fullNt: test results condensed);
loopk / loopk_nc (e2e_loopk.py: Sonnet picks k, one call per round; prompt cache on / off; loopk_nc is the chosen
loop); loopks / loopks_nc (e2e_loop.py with Sonnet picking k but separate judge and fix calls); mergedN (e2e_loopk.py
with k fixed at N); hybrid (e2e_hybrid.py: grep or codemem search, Sonnet's choice each step).

Tasks: out/e2e-vague8/tasks-<LEVEL>.jsonl (the fresh task with `query` replaced by the vague prompt; the issue as
written is kept in `query_L0`). Outputs: out/e2e-vague8/<LEVEL>/<task_id>/<arm>.*. Each task gets a fresh copy of
the repo at its base commit (no history), reset between arms. Finished arms are skipped; a failed arm is tried
once more (Windows file locks on the index have failed a run before).

Usage: python run_vague8.py L1|L2 [ARMS,...] [TASK_IDS,...]     (CODEMEM_HOME=~/.codemem-e2e, PYTHONPATH as e2e_all.py)
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
BASE = HERE / "out" / os.environ.get("VAGUE_SET", "e2e-vague8")  # VAGUE_SET=e2e-b7 for the b7 tasks
tasks_file = BASE / f"tasks-{LEVEL}.jsonl"
tasks = [json.loads(x) for x in tasks_file.read_text(encoding="utf8").split(NL) if x.strip()]
ARMS = sys.argv[2].split(",") if len(sys.argv) > 2 else ["grep", "full5", "full10", "full25", "full50"]
if len(sys.argv) > 3:  # only these task ids (comma-separated)
    tasks = [t for t in tasks if t["id"] in sys.argv[3].split(",")]
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
    elif arm == "hybrid":  # e2e_hybrid.py: each step Sonnet picks grep or codemem search (loopk_nc, k 3/5/10)
        cmd = [PY, str(HERE / "e2e_hybrid.py"), str(tasks_file), task["id"], str(copy), str(out)]
        env = os.environ.copy() | {"LOOP_TAG": arm, "LLM_NO_PROMPT_CACHE": "1"}
    elif arm in ("loopks", "loopks_nc"):  # loop-k with separate judge and fix calls; _nc: no prompt caching
        cmd = [PY, str(HERE / "e2e_loop.py"), str(tasks_file), task["id"], str(copy), str(out)]
        env = os.environ.copy() | {"LOOP_TAG": arm, "LOOP_FULL": "1", "LOOP_CHOOSE_K": "1",
                                   "LLM_NO_PROMPT_CACHE": "1" if arm.endswith("_nc") else "0"}
    elif arm in ("loopk", "loopk_nc") or arm.startswith("merged"):  # loopk_nc: no prompt caching; mergedN: N fixed
        cmd = [PY, str(HERE / "e2e_loopk.py"), str(tasks_file), task["id"], str(copy), str(out)]
        # e2e_loopk.py turns the prompt cache off by default; loopk and mergedN were run with it on
        env = os.environ.copy() | {"LOOP_TAG": arm, "LLM_NO_PROMPT_CACHE": "1" if arm == "loopk_nc" else "0"} |             ({"LOOP_FIXED_K": arm.removeprefix("merged")} if arm.startswith("merged") else {})
    else:
        n = arm.removeprefix("full").removesuffix("t")  # fullNt: test results condensed (LOOP_CONDENSE_TESTS)
        cmd = [PY, str(HERE / "e2e_loop.py"), str(tasks_file), task["id"], str(copy), str(out)]
        env = os.environ.copy() | {"LOOP_N": n, "LOOP_TAG": arm, "LOOP_FULL": "1"} |             ({"LOOP_CONDENSE_TESTS": "1"} if arm.endswith("t") else {})
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
