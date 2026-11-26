"""Score grep agent vs codemem loop+fix on the 3 fair pandas pilot tasks (out/e2e-pilot3).

A gold function is SEEN when at least half its lines reached the model as raw code (grep: lines returned by
Read or printed by Grep; loops: results shown whole and the fix call's code, not previews), EDITED when the
final diff touches a line inside it. Gold functions come from the task's gold labels.
"""
import collections as C
import json
import re
from pathlib import Path

HERE = Path(r"C:/Users/user/Desktop/Stanford/CS329M/Claude/Week 1 Task/analysis/b1-links/llm_query")
OUT = HERE / "out" / "e2e-pilot3"
TASKS = HERE.parent.parent / "codemem-7c24558" / "eval" / "tasks" / "fresh-v1.jsonl"
IDS = ["pandas-dev__pandas-68195", "pandas-dev__pandas-68945", "pandas-dev__pandas-68090"]
NL = chr(10)
# loopN: the judge sees N 500-character previews per round; fullN: N results as raw code from the index.
# loop (50 previews) is still on disk but left out of the comparison.
ARMS = ("grep", "loop25", "loop10", "full25", "full10", "full5")
# The query-writing call before round 1. Summaries from before 2026-11-26 13:30 did not count it.
ONESHOT_COST = {"pandas-dev__pandas-68090": 0.0159487, "pandas-dev__pandas-68945": 0.0124387, "pandas-dev__pandas-68195": 0.015018}

src = (HERE / "e2e_score.py").read_text(encoding="utf8")
helpers = src[src.index("def add_range"):src.index("import sys\nCOMMON")]
exec(helpers)  # add_range, rel, diff_lines, grep_seen, found

Span = C.namedtuple("Span", "path start end symbol")
tasks = {t["id"]: t for t in map(json.loads, (x for x in TASKS.read_text(encoding="utf8").split(NL) if x.strip())) if t["id"] in IDS}

rows = []
for tid in IDS:
    d, task = OUT / tid, tasks[tid]
    gold = [Span(g["path"], g["start"], g["end"], g.get("symbol")) for g in task["gold"].get("functions", [])]
    for arm in ARMS:
        f = d / f"{arm}.summary.json"
        if not f.exists():
            rows.append({"task": tid, "arm": arm, "missing": True})
            continue
        s = json.loads(f.read_text(encoding="utf8"))
        if arm == "grep":
            seen = grep_seen(d / "grep.jsonl")
            turns = s.get("turns")
            calls = sum((s.get("tool_calls") or {}).values())
        else:
            # Seen = raw code that reached Sonnet: results shown whole (full arms), and the fix call's code.
            # A 500-character preview does not count.
            seen = C.defaultdict(set)
            for h in s["history"]:
                for (p, a, b), whole in zip(h.get("shown", []), h.get("shown_whole", [])):
                    if whole:
                        add_range(seen, p, a, b)
                for x in h.get("fix_shown") or []:
                    m = re.match(r"(.+?) lines (\d+)-(\d+)", x)
                    if m:
                        add_range(seen, *m.groups())
            turns = s.get("rounds")
            calls = s.get("sonnet_calls")
        edited = diff_lines((d / f"{arm}.diff").read_text(encoding="utf8"))
        hits = [found(g, seen, edited) for g in gold]
        cost = (s.get("cost_usd") or 0) + (0 if arm == "grep" or "oneshot_cost_usd" in s else ONESHOT_COST[tid])
        rows.append({"task": tid, "arm": arm, "cost": cost, "turns": turns, "calls": calls,
                     "seconds": s.get("seconds"), "gold": len(gold), "seen": sum(a for a, _ in hits),
                     "edited": sum(b for _, b in hits), "changed": bool(s.get("diff_stat")),
                     "gold_files": sorted({g.path for g in gold}), "diff_stat": s.get("diff_stat", "")})

(OUT / "score.json").write_text(json.dumps(rows, indent=1), encoding="utf8")
for r in rows:
    if r.get("missing"):
        print(f"{r['task'][-5:]} {r['arm']:5} MISSING")
        continue
    print(f"{r['task'][-5:]} {r['arm']:5} cost ${r['cost']:.3f} turns {r['turns']} calls {r['calls']} {r['seconds']}s "
          f"gold {r['gold']} seen {r['seen']} edited {r['edited']} changed {r['changed']}")
    print("      gold files:", r["gold_files"], "| diff:", r["diff_stat"].replace(NL, " / ")[:200])
for arm in ARMS:
    rs =[r for r in rows if r["arm"] == arm and not r.get("missing")]
    print(f"TOTAL {arm:5} tasks {len(rs)} cost ${sum(r['cost'] for r in rs):.2f} turns {sum(r['turns'] or 0 for r in rs)} "
          f"gold {sum(r['gold'] for r in rs)} seen {sum(r['seen'] for r in rs)} edited {sum(r['edited'] for r in rs)} "
          f"changed {sum(r['changed'] for r in rs)}")
