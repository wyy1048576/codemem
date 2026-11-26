"""Stage 3 report: for each experiment family, the variant chosen on the tuning half (half 0 of
vllm-L0 and pandas-L0, by the hash of the task id), reported on the held-out half (half 1) and on
the vague sets, against the baseline on the same tasks, with a paired bootstrap interval.

Choice: the most tasks gained (gold function in the top 10, summed over the two L0 tuning halves),
then the gain at top 20, then gold files at top 10, then fewer candidates added.

    ./run.sh s3_report.py [<family> ...]
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import lab_common as L

FAMILIES = ["e1", "e2", "e4", "e5", "e6", "e7", "e7fill", "e7kw", "e7kw2", "e9", "e10", "e11", "e13"]
SETS = ["vllm-L0", "pandas-L0", "vague-L0", "vague-L1", "vague-L2", "vllm-title", "pandas-title"]


def load() -> dict[str, dict]:
    data = {}
    for name in SETS:
        src = "pandas-L0" if name == "vague-L0" else name
        f = L.OUT / f"s3-{src}.json"
        if f.is_file():
            data[name] = json.loads(f.read_text("utf-8"))[src]
            data[name + ":meta"] = json.loads(f.read_text("utf-8"))[src + ":meta"]
    if "vague-L0" in data:
        ids = set(L.load_vague())
        data["vague-L0"] = {v: {t: x for t, x in rows.items() if t in ids} for v, rows in data["vague-L0"].items()}
        data["vague-L0:meta"] = {k: {t: x for t, x in rows.items() if t in ids} for k, rows in data["vague-L0:meta"].items()}
    return data


def hit(x, k: int, which: int) -> int:
    return int(x is not None and x[which] is not None and x[which] <= k)


def task_lists(data, sets_tasks):
    """per set: ids of the tasks with a gold function (resp. file) in the snapshot, from the baseline."""
    return sets_tasks


def boot(d: np.ndarray, n: int = 10000, seed: int = 7) -> tuple[float, float, float]:
    if len(d) == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    s = d[rng.integers(0, len(d), size=(n, len(d)))].sum(axis=1)
    lo, hi = np.percentile(s, [2.5, 97.5])
    return float(d.sum()), float(lo), float(hi)


def main() -> None:
    families = sys.argv[1:] or FAMILIES
    data = load()
    halves = {}
    gold = {}
    for name in SETS:
        if name not in data:
            continue
        tasks = L.query_sets([name])[name]["tasks"]
        halves[name] = {t["id"]: t["half"] for t in tasks}
    # tasks with a gold function / a gold file in the snapshot: from the baseline's records
    ix_cache = {}
    for name in halves:
        repo = "vllm" if name.startswith("vllm") else "pandas"
        if repo not in ix_cache:
            ix_cache[repo] = L.Index(repo, vectors=False)
        ix = ix_cache[repo]
        tasks = L.query_sets([name])[name]["tasks"]
        g = {}
        for t in tasks:
            files, fns = ix.gold_rows(t)
            g[t["id"]] = (bool(fns), bool(files))
        gold[name] = g
    out = {}
    for fam in families:
        variants = sorted({v for name in ("vllm-L0", "pandas-L0") if name in data for v in data[name]
                           if (v.split("|")[0] == fam if "|" not in fam else v.startswith(fam + "|"))})
        if not variants:
            continue
        scored = []
        for v in variants:
            gain10 = gain20 = gainf = added = 0.0
            ok = True
            for name in ("vllm-L0", "pandas-L0"):
                if name not in data or v not in data[name]:
                    ok = False
                    break
                rec, base = data[name][v], data[name]["base"]
                for tid, h in halves[name].items():
                    if h != 0:
                        continue
                    has_fn, has_file = gold[name][tid]
                    if has_fn:
                        gain10 += hit(rec.get(tid), 10, 0) - hit(base.get(tid), 10, 0)
                        gain20 += hit(rec.get(tid), 20, 0) - hit(base.get(tid), 20, 0)
                    if has_file:
                        gainf += hit(rec.get(tid), 10, 1) - hit(base.get(tid), 10, 1)
                    added += rec[tid][2] if tid in rec else 0
            if ok:
                scored.append(((gain10, gain20, gainf, -added), v))
        if not scored:
            continue
        scored.sort(reverse=True)
        best = scored[0][1]
        out[fam] = {"chosen": best, "tune": scored[0][0], "n_variants": len(scored),
                    "tune_top5": [(s, v) for s, v in scored[:5]], "report": {}}
        for name in SETS:
            if name not in data or best not in data[name]:
                continue
            rec, base = data[name][best], data[name]["base"]
            held = [tid for tid, h in halves[name].items() if (h == 1 or name.startswith("vague"))]
            row = {}
            for label, which, k, idx in (("fn@10", 0, 10, 0), ("fn@20", 0, 20, 0), ("file@10", 1, 10, 1), ("file@20", 1, 20, 1)):
                ids = [tid for tid in held if gold[name][tid][idx]]
                b = np.array([hit(base.get(tid), k, which) for tid in ids])
                e = np.array([hit(rec.get(tid), k, which) for tid in ids])
                s, lo, hi = boot(e - b)
                row[label] = {"tasks": len(ids), "base": int(b.sum()), "exp": int(e.sum()), "diff": s, "ci": (lo, hi),
                              "won": int(((e - b) > 0).sum()), "lost": int(((e - b) < 0).sum())}
            row["added_mean"] = float(np.mean([rec[tid][2] for tid in held if tid in rec]))
            row["us_median"] = float(np.median([rec[tid][3] for tid in held if tid in rec]))
            out[fam]["report"][name] = row
    tag = "" if families == FAMILIES else "-" + "_".join(f.replace("|", "") for f in families)[:80]
    (L.OUT / f"s3-report{tag}.json").write_text(json.dumps(out, indent=1), "utf-8")
    for fam, v in out.items():
        print(f"\n## {fam}: chosen {v['chosen']} of {v['n_variants']} (tuning gain fn@10 {v['tune'][0]:+.0f}, fn@20 {v['tune'][1]:+.0f}, file@10 {v['tune'][2]:+.0f})")
        print("   next on the tuning half: " + "; ".join(f"{vv} {s[0]:+.0f}/{s[1]:+.0f}" for s, vv in v["tune_top5"][1:4]))
        for name, row in v["report"].items():
            cells = []
            for label in ("fn@10", "fn@20", "file@10", "file@20"):
                c = row[label]
                cells.append(f"{label} {c['base']}->{c['exp']} of {c['tasks']} ({c['diff']:+.0f}, CI {c['ci'][0]:+.0f}..{c['ci'][1]:+.0f}; +{c['won']}/-{c['lost']})")
            print(f"   {name:13s} " + " | ".join(cells) + f" | added {row['added_mean']:.1f}, {row['us_median'] / 1000:.2f} ms")


if __name__ == "__main__":
    main()
