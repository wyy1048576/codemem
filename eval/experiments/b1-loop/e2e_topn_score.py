"""Score the loop at n = 10 / 25 / 50 results per round against the grep agent, on tasks all four have finished.

Same rules as e2e_score.py: a gold function is SEEN when at least half its lines were shown to the model, EDITED
when the final diff changes or inserts at a line inside it; recall = gold functions seen or edited / all gold
functions (scored tasks only). Per-task columns count tasks whose final diff touches at least one gold function,
every gold function, or every gold file.
Usage: python e2e_topn_score.py
"""
from __future__ import annotations

import collections as C
import json
import re
import statistics as st
from pathlib import Path

HERE = Path(__file__).parent
src = (HERE / "e2e_score.py").read_text(encoding="utf8")
ns = {"__file__": str(HERE / "e2e_score.py"), "__name__": "e2e_score_helpers"}
exec(compile(src[:src.index("import sys\nCOMMON")], "e2e_score.py", "exec"), ns)
tasks, add_range, diff_lines, grep_seen, found, level_gold, excluded = (ns[k] for k in (
    "tasks", "add_range", "diff_lines", "grep_seen", "found", "level_gold", "excluded"))
ALL = HERE / "out" / "e2e-all"
ARMS = {"loop n=10": "loop-n10", "loop n=25": "loop-n25", "loop n=50": "loop", "grep": "grep"}
raw = {}
for f in ("fresh-cpp-v1-68.jsonl", "fresh-v1-py100.jsonl"):
    for line in (HERE.parent.parent / "codemem-7c24558" / "eval" / "tasks" / f).read_text(encoding="utf8").splitlines():
        if line.strip():
            t = json.loads(line)
            raw[t["id"]] = t


def loop_arm(d, tag):
    s = json.loads((d / f"{tag}.summary.json").read_text(encoding="utf8"))
    seen = C.defaultdict(set)
    for h in s["history"]:
        for p, a, b in h.get("shown", []):
            add_range(seen, p, a, b)
        for x in h.get("fix_shown", []):
            m = re.match(r"(.+?) lines (\d+)-(\d+)", x)
            if m:
                add_range(seen, *m.groups())
    return s["cost_usd"], seen, diff_lines((d / f"{tag}.diff").read_text(encoding="utf8")), bool(s["fixed"]), s["rounds"]


T = tasks()
res = {a: C.Counter() for a in ARMS}
rounds = {a: [] for a in ARMS}
per_task = []
for tid, task in sorted(T.items()):
    d = ALL / tid
    if not all((d / f"{tag}.summary.json").exists() for tag in ARMS.values()):
        continue
    gold = level_gold(task, "function")
    scored = bool(gold) and not excluded(task, "line", "function")
    gold_files = set(raw[tid]["gold"]["files"])
    row = {"task": tid, "gold_functions": len(gold) if scored else 0}
    for arm, tag in ARMS.items():
        if tag == "grep":
            s = json.loads((d / "grep.summary.json").read_text(encoding="utf8"))
            cost, seen, edited, changed, n_rounds = (s["cost_usd"] or 0, grep_seen(d / "grep.jsonl"),
                                                     diff_lines((d / "grep.diff").read_text(encoding="utf8")), bool(s["diff_stat"]), None)
        else:
            cost, seen, edited, changed, n_rounds = loop_arm(d, tag)
            rounds[arm].append(n_rounds)
        r = res[arm]
        r["tasks"] += 1
        r["cost"] += cost
        r["no_change"] += not changed
        r["edits_all_gold_files"] += bool(gold_files) and gold_files <= set(edited)
        r["tasks_with_gold_files"] += bool(gold_files)
        if scored:
            hits = [found(g, seen, edited) for g in gold]
            r["scored_tasks"] += 1
            r["gold_functions"] += len(gold)
            r["seen_or_edited"] += sum(s_ or e_ for s_, e_ in hits)
            r["edits_one"] += any(e_ for _, e_ in hits)
            r["edits_all"] += all(e_ for _, e_ in hits)
            row[arm] = [sum(s_ or e_ for s_, e_ in hits), sum(e_ for _, e_ in hits), round(cost, 3)]
    per_task.append(row)

out = {"per_arm": {a: {**r, "median_rounds": st.median(rounds[a]) if rounds[a] else None} for a, r in res.items()}, "per_task": per_task}
(HERE / "e2e_topn_score.json").write_text(json.dumps(out, indent=1), encoding="utf8")
print("| Arm | Tasks | $ per task | Recall (gold functions seen or edited) | Tasks editing >=1 gold function | Tasks editing every gold function | Tasks editing every gold file | Tasks with no change | Median rounds |")
print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
for a, r in res.items():
    st_ = r["scored_tasks"] or 1
    print(f"| {a} | {r['tasks']} | ${r['cost'] / max(r['tasks'], 1):.2f} | {r['seen_or_edited']}/{r['gold_functions']} ({r['seen_or_edited'] / max(r['gold_functions'], 1):.0%}) "
          f"| {r['edits_one']}/{st_} | {r['edits_all']}/{st_} | {r['edits_all_gold_files']}/{r['tasks_with_gold_files']} | {r['no_change']} "
          f"| {out['per_arm'][a]['median_rounds'] if out['per_arm'][a]['median_rounds'] is not None else '—'} |")
