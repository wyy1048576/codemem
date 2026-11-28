"""Generate one-shot extractions. `--smoke` tries one issue from another repo and prints it.

Usage: python generate.py TASKS.jsonl (--smoke | --task ID | --repo owner/name [--workers 4]) [--kind oneshot|oneshot_v2]
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from cmeval.tasks import load_tasks

import llm

parser = argparse.ArgumentParser()
parser.add_argument("tasks")
parser.add_argument("--repo")
parser.add_argument("--smoke", action="store_true")
parser.add_argument("--task")
parser.add_argument("--kind", default="oneshot", choices=("oneshot", "oneshot_v2"))
parser.add_argument("--workers", type=int, default=4)
args = parser.parse_args()
tasks = load_tasks(args.tasks)
print("kind", args.kind, "prompt sha", llm.PROMPTS[args.kind][2], flush=True)

if args.smoke or args.task:
    task = next(t for t in tasks if (t.id == args.task if args.task else t.repo != "duckdb/duckdb"))
    record = llm.extract(args.kind, llm.oneshot_input(task.repo, task.query))
    print(task.id, record["models"], record["cost_usd"], record["stop_reason"])
    print(json.dumps(llm.clean(record["output"], task.query), ensure_ascii=False, indent=1))
    raise SystemExit

selected = [t for t in tasks if t.repo == args.repo]
total = 0.0
with ThreadPoolExecutor(args.workers) as pool:
    futures = {pool.submit(llm.extract, args.kind, llm.oneshot_input(t.repo, t.query)): t for t in selected}
    for number, future in enumerate(as_completed(futures), start=1):
        record = future.result()
        total += record.get("cost_usd") or 0
        print(f"{number}/{len(selected)} {futures[future].id}", flush=True)
print(f"done: {len(selected)} extractions, list-price cost ${total:.2f}")
