"""Compare the whole-issue baseline with the Sonnet arms, task by task.

Primary test, fixed before scoring: function MRR of each arm vs whole issue, paired Wilcoxon,
Holm across the 4 arms. Everything else is descriptive.

Usage: python compare_arms.py RUN_DIR OUT_PREFIX [ARM,ARM,...] [BASE]
Defaults: the four Sonnet arms of the first run, against "whole".
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

from cmeval.metrics.accuracy import accuracy_metrics
from cmeval.metrics.matching import excluded, file_units, level_gold, raw_relevance
from cmeval.metrics.stats import differences, holm, paired_bootstrap_ci, wilcoxon
from cmeval.retriever import Hit
from cmeval.score import MAIN_IOU, run_tasks

import llm

ARMS = tuple(sys.argv[3].split(",")) if len(sys.argv) > 3 else ("oneshot", "oneshot-guess", "revise", "revise-guess")
BASE = sys.argv[4] if len(sys.argv) > 4 else "whole"
SHOWN = tuple(dict.fromkeys(("whole", BASE, *ARMS)))
METRICS = ("mrr", "recall@10", "success@10", "recall@50", "success@50", "found")
run_dir, prefix = Path(sys.argv[1]), Path(sys.argv[2])
meta = json.loads((run_dir / "meta.json").read_text(encoding="utf8"))
_, tasks = run_tasks(meta)
granularity = meta["systems"][0]["granularity"]
lines = {name: {r["task_id"]: r for r in map(json.loads, (run_dir / f"{name}.jsonl").read_text(encoding="utf8").splitlines())}
         for name in SHOWN}
ids = sorted(lines["whole"])
assert len(ids) == 25 and all(set(lines[a]) == set(ids) for a in ARMS), "arms do not cover the same 25 tasks"


def metrics(task, raw_hits, level):
    if excluded(task, granularity, level):
        return None
    hits = [Hit.from_dict(h) for h in raw_hits]
    gold = level_gold(task, level)
    relevance = raw_relevance(hits, gold, level, MAIN_IOU)
    units = file_units(hits, relevance) if level == "file" else relevance
    values = accuracy_metrics(units, len(gold))
    values["found"] = float(any(units))
    values["first_rank"] = next((rank for rank, found in enumerate(units, start=1) if found), None)
    return values


def bucket(row):
    if row["success@10"]:
        return "all_top10"
    if row["success@50"]:
        return "all_top50"
    return "some_top50" if row["found"] else "none_top50"


scores = {name: {level: {t: metrics(tasks[t], lines[name][t]["hits"], level) for t in ids} for level in ("function", "file")}
          for name in lines}
result = {"prompt_sha": llm.PROMPT_SHA, "prompt_sha_v2": llm.PROMPT_SHA_V2, "prompt_sha_loop": llm.PROMPT_SHA_LOOP, "base": BASE, "levels": {}, "primary": {}, "buckets": {}, "per_task": [], "leak_check": {}}
for level in ("function", "file"):
    scored = [t for t in ids if scores["whole"][level][t] is not None]
    result["levels"][level] = {"n": len(scored)}
    for name in lines:
        result["levels"][level][name] = {m: round(st.mean(scores[name][level][t][m] for t in scored), 4) for m in METRICS}

scored = [t for t in ids if scores["whole"]["function"][t] is not None]
base = [scores[BASE]["function"][t]["mrr"] for t in scored]
tests = []
for arm in ARMS:
    values = [scores[arm]["function"][t]["mrr"] for t in scored]
    delta = differences(values, base)
    test = wilcoxon(delta)
    ci = paired_bootstrap_ci(values, base)
    tests.append(test.p)
    result["primary"][arm] = {"mrr_diff": round(st.mean(delta), 4), "ci95": [round(ci[0], 4), round(ci[1], 4)], "p": test.p,
                              "wins": sum(d > 0 for d in delta), "losses": sum(d < 0 for d in delta), "ties": sum(d == 0 for d in delta)}
for arm, adjusted in zip(ARMS, holm(tests)):
    result["primary"][arm]["p_holm"] = adjusted

for name in lines:
    counts = dict.fromkeys(("all_top10", "all_top50", "some_top50", "none_top50"), 0)
    for t in scored:
        counts[bucket(scores[name]["function"][t])] += 1
    result["buckets"][name] = counts

for t in scored:
    row = {"task": t, "gold_functions": len(level_gold(tasks[t], "function"))}
    for name in lines:
        s = scores[name]["function"][t]
        row[name] = {"first_rank": s["first_rank"], "recall@10": round(s["recall@10"], 3), "recall@50": round(s["recall@50"], 3)}
    result["per_task"].append(row)

missed = [t for t in scored if not scores[BASE]["function"][t]["found"]]
result["missed_by_whole"] = {"tasks": missed, **{a: sum(bool(scores[a]["function"][t]["found"]) for t in missed) for a in ARMS}}
lost = {a: [t for t in scored if scores[BASE]["function"][t]["found"] and not scores[a]["function"][t]["found"]] for a in ARMS}
result["lost_by_arm"] = lost

for arm in [a for a in ARMS if a in ("oneshot", "revise", "diagnose", "diagnose-base")]:
    named = pinned = dropped = 0
    for t in ids:
        aug = lines[arm][t]["hits"][0]["extra"]["augmentation"]
        extraction = aug["extraction"]
        gold = set(tasks[t].gold.files)
        named += any(any(g == x or g.endswith("/" + x) for g in gold) for x in extraction["guessed_location"])
        pinned += aug["pins"] > 0
        dropped += extraction["dropped_anchors"]
    result["leak_check"][arm] = {"tasks_where_a_guess_names_a_gold_file": named, "tasks_with_pins": pinned, "anchors_dropped": dropped}
result["sonnet"] = {}
for label, cache in (("v1", llm.CACHE), ("v2", llm.CACHE_V2), ("loop", llm.CACHE_LOOP), ("loop_full", llm.PROMPTS["loop_full"][3])):
    records = [json.loads(p.read_text(encoding="utf8")) for p in cache.glob("*.json")]
    result["sonnet"][label] = {"cached_calls": len(records), "list_price_usd": round(sum(r.get("cost_usd") or 0 for r in records), 2)}

prefix.with_suffix(".json").write_text(json.dumps(result, indent=1), encoding="utf8")
print(json.dumps({k: result[k] for k in ("levels", "primary", "buckets", "missed_by_whole", "lost_by_arm", "leak_check", "sonnet")}, indent=1))
print("\ntask | " + " | ".join(SHOWN) + " (first correct rank)")
for row in result["per_task"]:
    print(row["task"].split("-")[-1], *(row[n]["first_rank"] or "-" for n in SHOWN), sep=" | ")
