"""Per-tool cost and token totals for grep / loopk_nc / hybrid on e2e-b45 (tasks where all three arms finished).

A loop step's cost is the cost of the Sonnet call that read that step's results (found in the LLM answer cache by
matching the step's notes). The call that writes the first query is counted in the arm's total, not in any step.
Tokens: input = input + cache-write + cache-read tokens; output = output tokens (thinking included)."""
import collections as C
import glob
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
BASE = HERE / "out" / "e2e-b45"

by_analysis, firsts = {}, []
for kind in ("hybrid", "loopk"):
    for f in glob.glob(str(HERE / "out" / "cache" / f"{kind}-*-nocache" / "*.json")):
        r = json.loads(Path(f).read_text(encoding="utf8"))
        by_analysis[(kind, r["output"]["analysis"].strip())] = r
for kind in ("hybrid_first", "oneshot_k"):
    for f in glob.glob(str(HERE / "out" / "cache" / f"{kind}-*-nocache" / "*.json")):
        firsts.append(json.loads(Path(f).read_text(encoding="utf8")))


def tok(u):
    return (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0),
            u.get("output_tokens", 0))


def first_tokens(cost):
    """The first call is matched by its cost (it is not in the history); good enough for token totals."""
    m = [r for r in firsts if abs((r.get("cost_usd") or 0) - cost) < 1e-9]
    return tok(m[0]["usage"]) if m else (0, 0)


ARMS = ("grep", "loopk_nc", "hybrid", "hybrid_v2")
rows = [r for r in json.loads((BASE / "score.json").read_text(encoding="utf8")) if r["arm"] in ARMS]
done = C.defaultdict(dict)
for r in rows:
    if not r.get("missing"):
        done[(r["level"], r["task"])][r["arm"]] = r
unmatched = 0
agg = C.defaultdict(lambda: C.defaultdict(float))
for (level, tid), arms in done.items():
    if len(arms) < len(ARMS):
        continue
    group = ("pandas" if "pandas" in tid else "playwright", level)
    for arm, r in arms.items():
        s = json.loads((BASE / level / tid / f"{arm}.summary.json").read_text(encoding="utf8"))
        a = agg[(group, arm)]
        a["tasks"] += 1
        a["cost"] += r["cost"]
        a["edited"] += r["edited"]
        a["gold"] += r["gold"]
        a["task_hit"] += r["task_hit"]
        if arm == "grep":
            i, o = tok(s["usage"])
            a["in"] += i
            a["out"] += o
            a["turns"] += s["turns"] or 0
            continue
        if arm == "hybrid_v2":  # per-step cost and tokens are in the history
            for h in s["history"]:
                a[f"n_{h['tool']}"] += 1
                a[f"c_{h['tool']}"] += h.get("call_cost") or 0
                t = h.get("tokens") or {}
                i, o = tok(t)
                a["in"] += i
                a["out"] += o
                a["cache_read"] += t.get("cache_read_input_tokens", 0)
            fi, fo = first_tokens(s.get("first_call_cost_usd") or 0)
            a["in"] += fi
            a["out"] += fo
            a["first_cost"] += s.get("first_call_cost_usd") or 0
            continue
        kind = "hybrid" if arm == "hybrid" else "loopk"
        step_cost = 0.0
        for h in s["history"]:
            if "analysis" not in h:
                continue
            rec = by_analysis.get((kind, h["analysis"]))
            if rec is None:
                unmatched += 1
                continue
            tool = h.get("tool", "codemem")
            a[f"n_{tool}"] += 1
            a[f"c_{tool}"] += rec["cost_usd"] or 0
            step_cost += rec["cost_usd"] or 0
            i, o = tok(rec["usage"])
            a["in"] += i
            a["out"] += o
        fi, fo = first_tokens(r["cost"] - step_cost)
        a["in"] += fi
        a["out"] += fo
        a["first_cost"] += r["cost"] - step_cost

print("unmatched steps:", unmatched)
out = []
for (group, arm), a in sorted(agg.items()):
    per = {t: (a[f"c_{t}"] / a[f"n_{t}"] if a[f"n_{t}"] else None) for t in ("codemem", "grep", "read", "open", "review", "retry")}
    out.append({"repo": group[0], "level": group[1], "arm": arm, **{k: round(v, 4) for k, v in a.items()},
                **{f"per_{t}": v for t, v in per.items()},
                "usd_per_1k_tokens": a["cost"] / (a["in"] + a["out"]) * 1000})
    print(group, arm, json.dumps(out[-1]))
Path(__file__).with_suffix(".json").write_text(json.dumps(out, indent=1), encoding="utf8")
