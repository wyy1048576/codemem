"""Rerun the end-to-end loop (e2e_loop.py) with fewer results shown per round: n = 10 and 25 (n = 50 is loop.*).

Tasks: those in out/e2e-all/ where both grep and the n = 50 loop have finished. Each run gets a fresh copy of the
repo at its base commit (as in e2e_all.py) and writes out/e2e-all/<task>/loop-n<N>.{summary.json,diff}, plus
loop-n<N>.stdout.txt. Finished runs are skipped. Before using the pandas copy it waits until no other session's
pilot (run_pilot3.py) is running, since that pilot uses the same copy.

Usage: python e2e_topn.py REPO_NAME [N ...]     (default N: 10 25)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.argv, rest = sys.argv[:2], sys.argv[2:]
import importlib.util

src = (HERE / "e2e_all.py").read_text(encoding="utf8")
helpers = src[:src.index("for i, tid in enumerate(ids, 1):")]  # tasks, copy path, fresh_copy, reset
ns = {"__file__": str(HERE / "e2e_all.py"), "__name__": "e2e_all_helpers"}
exec(compile(helpers, "e2e_all.py", "exec"), ns)
name, tasks, tasks_file, fresh_copy, reset, PY = ns["name"], ns["tasks"], ns["tasks_file"], ns["fresh_copy"], ns["reset"], ns["PY"]
NS = [int(x) for x in rest] or [10, 25]
ALL = HERE / "out" / "e2e-all"
ids = [d.name for d in sorted(ALL.iterdir()) if d.name in tasks
       and (d / "grep.summary.json").exists() and (d / "loop.summary.json").exists()]


def other_pilot_running() -> bool:
    out = subprocess.run(["powershell", "-NoProfile", "-c",
                          "(Get-CimInstance Win32_Process -Filter \"name='python.exe'\").CommandLine"],
                         capture_output=True, text=True).stdout
    return "run_pilot3" in out


if name == "pandas":
    while other_pilot_running():
        print("waiting for the other session's pandas pilot to finish", flush=True)
        time.sleep(60)

print(f"{name}: {len(ids)} tasks, n = {NS}", flush=True)
for i, tid in enumerate(ids, 1):
    out = ALL / tid
    todo = [n for n in NS if not (out / f"loop-n{n}.summary.json").exists()]
    if not todo:
        print(f"[{i}/{len(ids)}] {tid}: done already", flush=True)
        continue
    fresh_copy(tasks[tid])
    for n in todo:
        env = {**os.environ, "LOOP_N": str(n), "LOOP_TAG": f"loop-n{n}"}
        r = subprocess.run([PY, str(HERE / "e2e_loop.py"), str(tasks_file), tid, str(ns["copy"]), str(out)], capture_output=True,
                           text=True, encoding="utf8", errors="replace", env=env)
        (out / f"loop-n{n}.stdout.txt").write_text(r.stdout + "\n" + r.stderr[-3000:], encoding="utf8")
        reset()
        f = out / f"loop-n{n}.summary.json"
        cost = json.loads(f.read_text(encoding="utf8"))["cost_usd"] if f.exists() else "FAILED"
        print(f"[{i}/{len(ids)}] {tid} n={n}: cost {cost}", flush=True)
