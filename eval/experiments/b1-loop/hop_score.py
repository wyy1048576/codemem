"""Score the one-hop expansion runs (hop_retriever.py): how many gold functions/files outside the top 50 it adds.

Per arm, over DuckDB + pandas (scored tasks only, IoU 0.5 for functions):
  gold functions not in the top 50
    ... call-hoppable: some top-50 result's caller or callee is the gold function (all neighbours, no budget)
    ... added: the gold function is among the budgeted neighbours (15 / 10 / 5 per result)
  gold files that were "one import away" (per_gold_file_loopfull.json, bucket near_one_import)
    ... a call neighbour lies in that file (no budget) / an added neighbour lies in it / an added neighbour is a gold function
Usage: python hop_score.py [RUN_SUFFIX]   (default arc-hop)
"""
from __future__ import annotations

import collections as C
import json
import statistics as st
import sys
from pathlib import Path

from cmeval.metrics.matching import excluded, level_gold, raw_relevance
from cmeval.retriever import Hit
from cmeval.score import MAIN_IOU, run_tasks

SUFFIX = sys.argv[1] if len(sys.argv) > 1 else "arc-hop"
HERE = Path(__file__).parent
ARMS = ("whole", "oneshot", "revise", "diagnose", "loop", "loop-full")
near = C.defaultdict(set)
for row in json.loads((HERE / "per_gold_file_loopfull.json").read_text(encoding="utf8"))["rows"]:
    if row["bucket"] == "near_one_import":
        near[(row["arm"], row["task"])].add(row["path"])


def span_hits(where):
    return [Hit(path=p, start_line=s, end_line=e) for p, s, e in where]


out = {"per_arm": {}, "rows": []}
for arm in ARMS:
    t_ = C.Counter()
    sizes = []
    for repo in ("duckdb", "pandas"):
        run = Path.home() / ".cmeval" / "runs" / f"{repo}-{SUFFIX}{'2' if arm in ('revise', 'diagnose') else ''}"
        meta = json.loads((run / "meta.json").read_text(encoding="utf8"))
        _, tasks = run_tasks(meta)
        for line in (run / f"hop-{arm}.jsonl").read_text(encoding="utf8").splitlines():
            r = json.loads(line)
            task = tasks[r["task_id"]]
            hits = [Hit.from_dict(h) for h in r["hits"]]
            hop = hits[0].extra["hop"]
            top, added = hits[:50], hits[50:]
            sizes.append((hop["picked_with_repeats"], hop["selected"]))
            where = hop["where"]
            every = span_hits(where.values())
            files_every = {w[0] for w in where.values()}
            files_added = {h.path for h in added}
            gold_fns = level_gold(task, "function")
            if gold_fns and not excluded(task, "line", "function"):
                in_top = set().union(*raw_relevance(top, gold_fns, "function", MAIN_IOU))
                reach = set().union(*raw_relevance(every, gold_fns, "function", MAIN_IOU)) if every else set()
                got = set().union(*raw_relevance(added, gold_fns, "function", MAIN_IOU)) if added else set()
                for j, g in enumerate(gold_fns):
                    t_["gold_functions"] += 1
                    if j in in_top:
                        t_["fn_in_top50"] += 1
                        continue
                    t_["fn_not_in_top50"] += 1
                    t_["fn_call_hoppable"] += j in reach
                    t_["fn_added"] += j in got
                    out["rows"].append({"arm": arm, "task": r["task_id"], "gold": f"{g.path}:{g.symbol if hasattr(g, 'symbol') else g}",
                                        "call_hoppable": j in reach, "added": j in got})
            for path in near.get((arm, r["task_id"]), ()):
                t_["near_import_files"] += 1
                t_["near_file_call_neighbour"] += path in files_every
                t_["near_file_added"] += path in files_added
                fns = [g for g in gold_fns if g.path == path]
                t_["near_file_gold_fns"] += len(fns)
                if fns and added:
                    t_["near_file_gold_fn_added"] += len(set().union(*raw_relevance(added, fns, "function", MAIN_IOU)))
    t_["median_picks_with_repeats"] = st.median(a for a, _ in sizes)
    t_["median_unique_added"] = st.median(b for _, b in sizes)
    t_["max_unique_added"] = max(b for _, b in sizes)
    out["per_arm"][arm] = dict(t_)

(HERE / "hop_score.json").write_text(json.dumps(out, indent=1), encoding="utf8")
print(json.dumps(out["per_arm"], indent=1))
