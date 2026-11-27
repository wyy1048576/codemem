"""Score the vague-prompt runs: out/e2e-vague8/<LEVEL>/<task>/<arm>.* for L1 and L2.

A gold function is SEEN when at least half its lines reached the model as raw code (grep: lines returned by Read
or printed by Grep; loops: results shown whole, the fix call's code and earlier picks shown again, not previews), EDITED when the final diff
touches a line inside it. Cost of a loop includes its query-writing call. Usage: python score_vague8.py
"""
import collections as C
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / "out" / os.environ.get("VAGUE_SET", "e2e-vague8")
NL = chr(10)
ARMS = ("grep", "full5", "full10", "full25", "full50", "loopk", "loopk_nc", "full10t", "merged10", "loopks", "loopks_nc", "hybrid")

src = (HERE / "e2e_score.py").read_text(encoding="utf8")
exec(src[src.index("def add_range"):src.index("import sys\nCOMMON")])  # add_range, rel, diff_lines, grep_seen, found
Span = C.namedtuple("Span", "path start end symbol")

rows = []
for level in ("L1", "L2"):
    f = BASE / f"tasks-{level}.jsonl"
    if not f.exists():
        continue
    for task in (json.loads(x) for x in f.read_text(encoding="utf8").split(NL) if x.strip()):
        tid, d = task["id"], BASE / level / task["id"]
        gold = [Span(g["path"], g["start"], g["end"], g.get("symbol")) for g in task["gold"].get("functions", [])]
        for arm in ARMS:
            sf = d / f"{arm}.summary.json"
            if not sf.exists():
                rows.append({"level": level, "task": tid, "arm": arm, "missing": True})
                continue
            s = json.loads(sf.read_text(encoding="utf8"))
            if arm == "grep":
                seen, turns = grep_seen(d / "grep.jsonl"), s.get("turns")
            else:
                seen = C.defaultdict(set)
                for h in s["history"]:
                    for (p, a, b), whole in zip(h.get("shown", []), h.get("shown_whole", [])):
                        if whole:
                            add_range(seen, p, a, b)
                    for x in (h.get("fix_shown") or []) + (h.get("picked_shown") or []):
                        m = re.match(r"(.+?) lines (\d+)-(\d+)", x)
                        if m:
                            add_range(seen, *m.groups())
                turns = s.get("rounds")
            edited = diff_lines((d / f"{arm}.diff").read_text(encoding="utf8"))
            hits = [found(g, seen, edited) for g in gold]
            rows.append({"level": level, "task": tid, "arm": arm, "cost": s.get("cost_usd") or 0, "turns": turns,
                         "seconds": s.get("seconds"), "gold": len(gold), "seen": sum(a for a, _ in hits),
                         "edited": sum(b for _, b in hits), "task_hit": any(b for _, b in hits),
                         "changed": bool(s.get("diff_stat"))})

(BASE / "score.json").write_text(json.dumps(rows, indent=1), encoding="utf8")
for level in ("L1", "L2"):
    print(f"== {level}: arm, tasks, cost $, turns, gold fns, seen, edited, tasks with a gold fn edited, tasks with a change")
    for arm in ARMS:
        rs = [r for r in rows if r["level"] == level and r["arm"] == arm and not r.get("missing")]
        miss = sum(1 for r in rows if r["level"] == level and r["arm"] == arm and r.get("missing"))
        print(f"{arm:7} {len(rs):2} {sum(r['cost'] for r in rs):6.2f} {sum(r['turns'] or 0 for r in rs):4} "
              f"{sum(r['gold'] for r in rs):3} {sum(r['seen'] for r in rs):3} {sum(r['edited'] for r in rs):3} "
              f"{sum(r['task_hit'] for r in rs):2} {sum(r['changed'] for r in rs):2}" + (f"  missing {miss}" if miss else ""))
