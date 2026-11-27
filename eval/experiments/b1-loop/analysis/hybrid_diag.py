"""Where the hybrid loses: per task and level where grep, loopk_nc and hybrid all finished (e2e-b45). No LLM calls."""
import collections as C
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
BASE = HERE / "out" / "e2e-b45"
tasks = {}
for lv in ("L1", "L2"):
    for l in (BASE / f"tasks-{lv}.jsonl").read_text(encoding="utf8").split("\n"):
        if l.strip():
            t = json.loads(l)
            tasks[(lv, t["id"])] = t
score = {(r["level"], r["task"], r["arm"]): r for r in json.loads((BASE / "score.json").read_text(encoding="utf8")) if not r.get("missing")}


def in_gold(path, a, b, gold):
    return any(g["path"] == path and a <= g["end"] and b >= g["start"] for g in gold)


def first_gold_step(hist, gold, loop=False):
    """First step (1-based) whose results put a gold function in front of Sonnet: a codemem result overlapping it,
    or a grep line inside it. None if never."""
    for i, h in enumerate(hist, 1):
        for p, a, b in h.get("shown", []):
            if in_gold(p, a, b, gold):
                return i
        for x in h.get("grep_shown", []):
            p, n = x.rsplit(":", 1)
            if in_gold(p, int(n), int(n), gold):
                return i
    return None


rows = []
for (lv, tid), t in tasks.items():
    if not all((lv, tid, a) in score for a in ("grep", "loopk_nc", "hybrid")):
        continue
    gold = t["gold"]["functions"]
    hs = json.loads((BASE / lv / tid / "hybrid.summary.json").read_text(encoding="utf8"))
    ls = json.loads((BASE / lv / tid / "loopk_nc.summary.json").read_text(encoding="utf8"))
    hist = [h for h in hs["history"] if "action" in h]
    g, l, h = (score[(lv, tid, a)] for a in ("grep", "loopk_nc", "hybrid"))
    fg = first_gold_step(hist, gold)
    lg = first_gold_step([x for x in ls["history"] if "shown" in x], gold)
    grep_steps = [x for x in hist if x["tool"] == "grep"]
    rows.append({
        "level": lv, "task": tid, "gold": len(gold),
        "edited": {"grep": g["edited"], "loopk": l["edited"], "hybrid": h["edited"]},
        "cost": {"grep": round(g["cost"], 3), "loopk": round(l["cost"], 3), "hybrid": round(h["cost"], 3)},
        "first_tool": hist[0]["tool"] if hist else None, "first_k": hist[0].get("k") if hist else None,
        "tools": [x["tool"] for x in hist], "steps": len(hist),
        "hybrid_first_gold_step": fg, "loopk_first_gold_round": lg,
        "loopk_rounds": l["turns"], "fixed": bool(hs.get("fixed")),
        "edit_failed": sum(1 for x in hist if x.get("edit_attempt", "").startswith("did not apply")),
        "grep_zero": sum(1 for x in grep_steps if x.get("matches") == 0),
        "grep_capped": sum(1 for x in grep_steps if (x.get("matches") or 0) > 40),
        "grep_matches": [x.get("matches") for x in grep_steps],
        "picked_chunks_last": len(hist[-1].get("picked_shown", [])) if hist else 0,
    })

N = len(rows)
print("task-levels with all three arms:", N)
best = lambda r: max(r["edited"]["grep"], r["edited"]["loopk"])
print("hybrid edits fewer gold fns than the better of grep / loopk:", sum(r["edited"]["hybrid"] < best(r) for r in rows),
      "| more:", sum(r["edited"]["hybrid"] > best(r) for r in rows),
      "| fewer than loopk:", sum(r["edited"]["hybrid"] < r["edited"]["loopk"] for r in rows),
      "| fewer than grep:", sum(r["edited"]["hybrid"] < r["edited"]["grep"] for r in rows))
print("hybrid costs more than the cheaper of grep / loopk:", sum(r["cost"]["hybrid"] > min(r["cost"]["grep"], r["cost"]["loopk"]) for r in rows))
print("first tool:", C.Counter(r["first_tool"] for r in rows), "first k:", C.Counter(r["first_k"] for r in rows if r["first_tool"] == "codemem"))
print("tool after step 1:", C.Counter(x for r in rows for x in r["tools"][1:]))
seq = C.Counter(" ".join(r["tools"][:4]) for r in rows)
print("most common first steps:", seq.most_common(8))
print("loopk shows gold in round 1:", sum(r["loopk_first_gold_round"] == 1 for r in rows),
      "| hybrid shows gold in step 1:", sum(r["hybrid_first_gold_step"] == 1 for r in rows),
      "| hybrid never shows gold:", sum(r["hybrid_first_gold_step"] is None for r in rows),
      "| loopk never:", sum(r["loopk_first_gold_round"] is None for r in rows))
both = [r for r in rows if r["hybrid_first_gold_step"] and r["loopk_first_gold_round"]]
print("when both show gold: hybrid first-gold step mean", round(sum(r["hybrid_first_gold_step"] for r in both) / len(both), 2),
      "loopk round mean", round(sum(r["loopk_first_gold_round"] for r in both) / len(both), 2))
lag = [r["steps"] - r["hybrid_first_gold_step"] for r in rows if r["hybrid_first_gold_step"] and r["fixed"]]
print("hybrid steps after gold first shown until the edit (fixed runs):", C.Counter(lag))
seen_not_edited = [r for r in rows if r["hybrid_first_gold_step"] and r["edited"]["hybrid"] == 0]
print("hybrid showed gold but edited none:", len(seen_not_edited), [f"{r['level']} {r['task'][-12:]}" for r in seen_not_edited])
print("grep steps:", sum(len(r["grep_matches"]) for r in rows), "| 0 matches:", sum(r["grep_zero"] for r in rows),
      "| over 40 matches (cut):", sum(r["grep_capped"] for r in rows))
print("failed edits:", sum(r["edit_failed"] for r in rows), "| runs with no edit applied:", sum(not r["fixed"] for r in rows))
# by first tool
for ft in ("codemem", "grep"):
    rs = [r for r in rows if r["first_tool"] == ft]
    if rs:
        print(f"first tool {ft}: {len(rs)} runs, hybrid / loopk / grep edited {sum(r['edited']['hybrid'] for r in rs)} / "
              f"{sum(r['edited']['loopk'] for r in rs)} / {sum(r['edited']['grep'] for r in rs)} of {sum(r['gold'] for r in rs)}, "
              f"cost {sum(r['cost']['hybrid'] for r in rs):.2f} / {sum(r['cost']['loopk'] for r in rs):.2f} / {sum(r['cost']['grep'] for r in rs):.2f}, "
              f"steps {sum(r['steps'] for r in rs)}")
print("\nlosses (hybrid edited fewer than the better arm):")
for r in rows:
    if r["edited"]["hybrid"] < best(r):
        print(f"  {r['level']} {r['task'][-16:]:16} edited h/l/g {r['edited']['hybrid']}/{r['edited']['loopk']}/{r['edited']['grep']} of {r['gold']}"
              f"  tools {' '.join(r['tools'])}  gold shown at step {r['hybrid_first_gold_step']} (loopk round {r['loopk_first_gold_round']})"
              f"  grep matches {r['grep_matches']}")
(Path(__file__).with_suffix(".json")).write_text(json.dumps(rows, indent=1), encoding="utf8")
