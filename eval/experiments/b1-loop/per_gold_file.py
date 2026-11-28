"""Per gold file, for each arm: is it in the top 50, and if not, is it one import/export away from a top-50 file?

In top 50:      a top-50 hit is in the gold file. Split by whether a gold function of that file is itself
                matched (IoU 0.5), only other code of the file is, or the file has no gold function.
Not in top 50:  near  = a top-50 file imports it or is imported by it (C++: or is its header/source partner,
                        or one import away from that partner)
                far   = none of those
                not indexed = codemem does not index the file (language, size, ignored folder)
Control: how often the same neighbour test passes using the top 50 of a different task in the same repo.

Usage: python per_gold_file.py LINKS_DIR OUT.json [RUN_SUFFIX] [ARM,ARM,...]
Defaults: runs duckdb-arc-llm and pandas-arc-llm, arms whole, oneshot, revise.
"""
from __future__ import annotations

import collections as C
import gzip
import json
import statistics as st
import sys
from pathlib import Path

from cmeval.metrics.matching import level_gold, raw_relevance
from cmeval.retriever import Hit
from cmeval.score import MAIN_IOU, run_tasks

SUFFIX = sys.argv[3] if len(sys.argv) > 3 else "arc-llm"
RUNS = {"duckdb": Path.home() / f".cmeval/runs/duckdb-{SUFFIX}", "pandas": Path.home() / f".cmeval/runs/pandas-{SUFFIX}"}
ARMS = tuple(sys.argv[4].split(",")) if len(sys.argv) > 4 else ("whole", "oneshot", "revise")
links_dir, out_path = Path(sys.argv[1]), Path(sys.argv[2])
file_rows = {}
for line in gzip.open(links_dir / "gold_links.jsonl.gz", "rt", encoding="utf8"):
    r = json.loads(line)
    if r.get("kind") == "file":
        file_rows[(r["task"], r["path"])] = r


def neighbours(row) -> set[str]:
    out = set(row["file_out"]) | set(row["file_in"]) | set(row["file_partners"]) | set(row["partner_out"]) | set(row["partner_in"])
    out.discard(row["path"])
    return out


def read(run: Path, name: str) -> dict:
    return {r["task_id"]: r for r in map(json.loads, (run / f"{name}.jsonl").read_text(encoding="utf8").split("\n")[:-1])}


result = {"rows": [], "summary": {}}
for repo, run in RUNS.items():
    meta = json.loads((run / "meta.json").read_text(encoding="utf8"))
    _, tasks = run_tasks(meta)
    lines = {arm: read(run, arm) for arm in ARMS}
    ids = sorted(lines["whole"])
    for arm in ARMS:
        counts = C.Counter()
        control = []
        for t in ids:
            task = tasks[t]
            raw = lines[arm][t]["hits"][:50]
            hits = [Hit.from_dict(h) for h in raw]
            paths = [h.path for h in hits]
            file_order = list(dict.fromkeys(paths))
            gold_fns = level_gold(task, "function")
            matched = raw_relevance(hits, gold_fns, "function", MAIN_IOU) if gold_fns else [set() for _ in hits]
            found_fn = {i for rel in matched for i in rel}
            for path in level_gold(task, "file"):
                row = file_rows[(t, path)]
                fns = [i for i, g in enumerate(gold_fns) if g.path == path]
                entry = {"repo": repo, "arm": arm, "task": t, "path": path, "gold_functions": len(fns)}
                if path in file_order:
                    entry["file_rank"] = file_order.index(path) + 1
                    if not fns:
                        entry["bucket"] = "in_top50_no_gold_function"
                    elif any(i in found_fn for i in fns):
                        entry["bucket"] = "in_top50_gold_function_found"
                    else:
                        entry["bucket"] = "in_top50_same_file_only"
                elif not row["file_indexed"]:
                    entry["bucket"], entry["why"] = "not_indexed", row["file_why_not"]
                else:
                    near = neighbours(row) & set(paths)
                    entry["bucket"] = "near_one_import" if near else "far"
                    entry["near_via"] = sorted(near)[:5]
                    others = [o for o in ids if o != t]
                    control.append(st.mean(bool(neighbours(row) & {h["path"] for h in lines[arm][o]["hits"][:50]}) for o in others))
                counts[entry["bucket"]] += 1
                counts["gold_files"] += 1
                counts["top10"] += entry.get("file_rank", 99) <= 10
                result["rows"].append(entry)
        counts["control_near_rate"] = round(st.mean(control), 3) if control else None
        result["summary"][f"{repo}/{arm}"] = dict(counts)

out_path.write_text(json.dumps(result, indent=1), encoding="utf8")
order = ["gold_files", "top10", "in_top50_gold_function_found", "in_top50_same_file_only", "in_top50_no_gold_function",
         "near_one_import", "far", "not_indexed", "control_near_rate"]
print("arm".ljust(16), *(k[:14].rjust(15) for k in order))
for key, counts in result["summary"].items():
    print(key.ljust(16), *(str(counts.get(k, 0)).rjust(15) for k in order))
