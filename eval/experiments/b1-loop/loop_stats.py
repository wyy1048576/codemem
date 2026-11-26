"""How the search loop behaved per task: rounds used, whether Sonnet said found, and whether it was right.

"Right" uses the answer key only here, after the run: a pick is correct when it matches a gold function
(IoU 0.5), or for tasks with no gold function, when it is in a gold file.

Usage: python loop_stats.py [--arm NAME] RUN_DIR [RUN_DIR ...]   (default arm: loop)
"""
from __future__ import annotations

import collections as C
import json
import sys
from pathlib import Path

from cmeval.metrics.matching import level_gold, raw_relevance
from cmeval.retriever import Hit
from cmeval.score import MAIN_IOU, run_tasks

args = sys.argv[1:]
ARM = "loop"
if args[:1] == ["--arm"]:
    ARM, args = args[1], args[2:]
total = C.Counter()
for run in map(Path, args):
    meta = json.loads((run / "meta.json").read_text(encoding="utf8"))
    _, tasks = run_tasks(meta)
    rows = [json.loads(x) for x in (run / f"{ARM}.jsonl").read_text(encoding="utf8").split("\n")[:-1]]
    print(f"\n{run.name}: task | rounds | said found | picks | a pick is gold | first gold rank in round | cost $")
    for r in sorted(rows, key=lambda r: r["task_id"]):
        task = tasks[r["task_id"]]
        aug = r["hits"][0]["extra"]["augmentation"]
        hits = [Hit.from_dict(h) for h in r["hits"]]
        picks = hits[:aug["picks"]]
        gold = level_gold(task, "function")
        if gold:
            pick_ok = any(raw_relevance(picks, gold, "function", MAIN_IOU)) if picks else False
        else:
            pick_ok = any(h.path in set(task.gold.files) for h in picks)
        first_round = next((h["round"] for h in aug["history"] if any(
            any(p.startswith(g + ":") for g in task.gold.files) for p in h.get("picked", []))), None)
        print(r["task_id"].rsplit("-", 1)[1], aug["rounds"], aug["found"], aug["picks"], pick_ok, first_round or "-",
              aug["cost_usd"], sep=" | ")
        total["tasks"] += 1
        total[f"rounds_{aug['rounds']}"] += 1
        total["said_found"] += aug["found"]
        total["said_found_and_right"] += aug["found"] and pick_ok
        total["said_found_but_wrong"] += aug["found"] and not pick_ok
        total["not_found_but_a_pick_right"] += (not aug["found"]) and pick_ok
        total["cost_usd_x100"] += round(aug["cost_usd"] * 100)
print("\n" + json.dumps(dict(sorted(total.items())), indent=1))
