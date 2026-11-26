"""Cost and gold-function recall of the three end-to-end arms (50 tasks, 80 scored gold functions).

  hop-feed   one Sonnet call reading the one-shot top 50 + the one-hop picks (out/hop_feed.jsonl)
  loop+fix   codemem loop with a fix step (out/e2e-all/<task>/loop.*)
  grep       Claude Code agent with Read/Edit/Write/Grep/Glob (out/e2e-all/<task>/grep.*)

A gold function (base-commit line span) is SEEN when at least half of its lines were shown to the model: a result
or code block shown to Sonnet (hop-feed, loop+fix), or a line returned by a Read or Grep call (grep agent). It is
EDITED when the final diff changes or inserts at a line inside its span. Found = seen or edited.
Usage: python e2e_score.py [--common]
"""
from __future__ import annotations

import collections as C
import json
import re
from pathlib import Path

from cmeval.metrics.matching import excluded, level_gold
from cmeval.score import run_tasks

HERE = Path(__file__).parent
NL = chr(10)
ALL = HERE / "out" / "e2e-all"


def tasks():
    out = {}
    for repo in ("duckdb", "pandas"):
        _, t = run_tasks(json.loads((Path.home() / ".cmeval" / "runs" / f"{repo}-arc-hop" / "meta.json").read_text(encoding="utf8")))
        out.update(t)
    return out


def add_range(seen, path, a, b):
    seen[path].update(range(int(a), int(b) + 1))


def rel(path, copy_root=None):
    p = path.replace("\\", "/")
    m = re.search(r"/e2e-copies/[^/]+/(.*)$", p)
    return m.group(1) if m else p.lstrip("./")


def diff_lines(patch):
    """Base-side lines each file's diff touches (removed lines, and the base line an insertion follows)."""
    out, path, base = C.defaultdict(set), None, 0
    for line in patch.split(NL):
        if line.startswith("--- "):
            continue
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            base = int(re.match(r"@@ -(\d+)", line).group(1))
        elif path is None:
            continue
        elif line.startswith("-"):
            out[path].add(base)
            base += 1
        elif line.startswith("+"):
            out[path].update({max(base - 1, 1), base})
        elif line.startswith(" "):
            base += 1
    return out


def grep_seen(log):
    seen, uses = C.defaultdict(set), {}
    for x in log.read_text(encoding="utf8").split(NL):
        if not x.startswith("{"):
            continue
        e = json.loads(x)
        content = e.get("message", {}).get("content") if isinstance(e.get("message"), dict) else None
        for c in content if isinstance(content, list) else []:
            if c.get("type") == "tool_use":
                uses[c["id"]] = c
            elif c.get("type") == "tool_result" and c.get("tool_use_id") in uses:
                use = uses[c["tool_use_id"]]
                text = c["content"] if isinstance(c["content"], str) else " ".join(y.get("text", "") for y in c["content"] if isinstance(y, dict))
                if use["name"] == "Read":
                    path = rel(use["input"].get("file_path", ""))
                    for m in re.finditer(r"^\s*(\d+)\t", text, re.M):
                        seen[path].add(int(m.group(1)))
                elif use["name"] == "Grep" and use["input"].get("output_mode") == "content":
                    default = rel(use["input"].get("path", "")) if Path(use["input"].get("path", "x")).suffix else None
                    for m in re.finditer(r"^(?:(.+?)[:-])?(\d+)[:-]", text, re.M):
                        path = rel(m.group(1)) if m.group(1) else default
                        if path:
                            seen[path].add(int(m.group(2)))
    return seen


def found(span, seen, edited):
    lines = set(range(span.start, span.end + 1))
    s = len(lines & seen.get(span.path, set())) * 2 >= len(lines)
    e = bool(lines & edited.get(span.path, set()))
    return s, e


import sys
COMMON = "--common" in sys.argv  # only tasks every arm has finished
T = tasks()
feed = {r["task_id"]: r for r in map(json.loads, (HERE / "out" / "hop_feed.jsonl").read_text(encoding="utf8").split(NL)[:-1])}
res = {a: C.Counter() for a in ("hop-feed", "loop+fix", "grep")}
per_task = []
for tid, task in sorted(T.items()):
    gold = level_gold(task, "function")
    scored = bool(gold) and not excluded(task, "line", "function")
    d = ALL / tid
    arms = {}
    if tid in feed:
        seen = C.defaultdict(set)
        for p, a, b in feed[tid]["shown"]:
            add_range(seen, p, a, b)
        arms["hop-feed"] = (feed[tid]["cost_usd"] or 0, seen, {}, None)
    if (d / "loop.summary.json").exists():
        s = json.loads((d / "loop.summary.json").read_text(encoding="utf8"))
        seen = C.defaultdict(set)
        for h in s["history"]:
            for p, a, b in h.get("shown", []):
                add_range(seen, p, a, b)
            for x in h.get("fix_shown", []):
                m = re.match(r"(.+?) lines (\d+)-(\d+)", x)
                if m:
                    add_range(seen, *m.groups())
        arms["loop+fix"] = (s["cost_usd"], seen, diff_lines((d / "loop.diff").read_text(encoding="utf8")), bool(s["fixed"]))
    if (d / "grep.summary.json").exists():
        s = json.loads((d / "grep.summary.json").read_text(encoding="utf8"))
        arms["grep"] = (s["cost_usd"] or 0, grep_seen(d / "grep.jsonl"), diff_lines((d / "grep.diff").read_text(encoding="utf8")),
                        bool(s["diff_stat"]))
    if COMMON and len(arms) < 3:
        continue
    row = {"task": tid}
    for arm, (cost, seen, edited, changed) in arms.items():
        r = res[arm]
        r["tasks"] += 1
        r["cost_x1000"] += round(cost * 1000)
        r["made_a_change"] += bool(changed)
        if scored:
            for g in gold:
                s_, e_ = found(g, seen, edited)
                r["gold_functions"] += 1
                r["seen"] += s_
                r["edited"] += e_
                r["seen_or_edited"] += s_ or e_
            row[arm] = sum(any(found(g, seen, edited)) for g in gold)
    row["gold"] = len(gold) if scored else 0
    per_task.append(row)

(HERE / "e2e_score.json").write_text(json.dumps({"per_arm": res, "per_task": per_task}, indent=1), encoding="utf8")
print("arm        tasks  cost $   $/task  gold fns  seen  edited  seen-or-edited (recall)  tasks with a code change")
for arm, r in res.items():
    n = r["gold_functions"] or 1
    print(f"{arm:10} {r['tasks']:5}  {r['cost_x1000'] / 1000:7.2f}  {r['cost_x1000'] / 1000 / max(r['tasks'], 1):6.3f}  {r['gold_functions']:8}  "
          f"{r['seen']:4}  {r['edited']:6}  {r['seen_or_edited']:4} ({r['seen_or_edited'] / n:.0%})   {r['made_a_change']}")
