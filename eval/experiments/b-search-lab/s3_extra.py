"""Stage 3, the experiments that are not one ranking choice: 3 (random neighbours and the placebo,
at the settings experiment 1 chose), 8 (reach), the measurements of 9 and 13, the teammate's
version, and 12 (a query in two parts: dense on the short text, keywords on the L0 issue's names).

    ./run.sh s3_extra.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import core as C
import lab_common as L
import s3_report as R


def hit(x, k=10, which=0):
    return int(x is not None and x[which] is not None and x[which] <= k)


def main() -> None:
    data = R.load()
    sets = L.query_sets([n for n in R.SETS if n in data])
    halves = {n: {t["id"]: t["half"] for t in sets[n]["tasks"]} for n in sets}
    ixs = {r: L.Index(r, vectors=False) for r in ("vllm", "pandas")}
    gold = {}
    for n in sets:
        ix = ixs[sets[n]["repo"]]
        gold[n] = {t["id"]: tuple(bool(x) for x in ix.gold_rows(t))[::-1] for t in sets[n]["tasks"]}  # (has_fn, has_file)
    out: dict = {}

    def held(n):
        return [t for t, h in halves[n].items() if h == 1 or n.startswith("vague")]

    def count(n, rec, ids, k=10, which=0, avg_seeds=None):
        if avg_seeds:
            return float(np.mean([sum(hit(data[n][v].get(t), k, which) for t in ids) for v in avg_seeds]))
        return sum(hit(rec.get(t), k, which) for t in ids)

    # ---- 3: similarity-chosen neighbours (experiment 1, both directions) against random ones and the placebo
    grid = sorted({tuple(v.split("|")[1:5]) for v in data["vllm-L0"] if v.startswith("e3rand|")})
    best, best_s = None, None
    for v, n_, m_, w_ in grid:
        name = f"e1|{v}|both|{n_}|{m_}|{w_}"
        s = 0
        for n in ("vllm-L0", "pandas-L0"):
            ids = [t for t, h in halves[n].items() if h == 0 and gold[n][t][0]]
            s += count(n, data[n][name], ids) - count(n, data[n]["base"], ids)
        if best_s is None or s > best_s:
            best, best_s = (v, n_, m_, w_), s
    e3 = {"chosen": best, "tune_gain": best_s, "rows": {}}
    v, n_, m_, w_ = best
    for n in R.SETS:
        if n not in data:
            continue
        ids = [t for t in held(n) if gold[n][t][0]]
        base = count(n, data[n]["base"], ids)
        sim = count(n, data[n][f"e1|{v}|both|{n_}|{m_}|{w_}"], ids)
        rnd = count(n, None, ids, avg_seeds=[f"e3rand|{v}|{n_}|{m_}|{w_}|s{s}" for s in range(5)])
        plc = count(n, None, ids, avg_seeds=[f"e3placebo|{n_}|{m_}|{w_}|s{s}" for s in range(5)])
        rnd_all = {vv: count(n, None, ids, avg_seeds=[f"e3rand|{vv}|{n_}|{m_}|{w_}|s{s}" for s in range(5)]) for vv in ("a", "b99", "b90", "c")}
        sim_all = {vv: count(n, data[n][f"e1|{vv}|both|{n_}|{m_}|{w_}"], ids) for vv in ("a", "b99", "b90", "c")}
        e3["rows"][n] = {"tasks": len(ids), "base": base, "similar": sim, "random": rnd, "placebo": plc,
                         "similar_by_version": sim_all, "random_by_version": rnd_all}
    # the teammate's version: every caller and callee of all 50 results, after rank 50
    tm = {}
    for n in ("vllm-L0", "pandas-L0", "vague-L2"):
        rows = data[n + ":meta"]["teammate"]
        added = [a for a, g in rows.values()]
        golds = [g for a, g in rows.values()]
        tm[n] = {"tasks": len(rows), "added_median": float(np.median(added)), "added_mean": float(np.mean(added)),
                 "gold_among_added": int(sum(golds)), "added_total": int(sum(added)),
                 "tasks_with_a_gold_function_added": int(sum(g > 0 for g in golds))}
    e3["teammate"] = tm
    out["e3"] = e3
    # ---- 8: reach: a gold function in the top 10 or named on a card (each card names its r neighbours)
    e8 = {}
    for n in R.SETS:
        if n not in data:
            continue
        ids = [t for t in halves[n] if gold[n][t][0]]
        row = {"tasks": len(ids), "top10": sum(hit(data[n]["base"].get(t)) for t in ids)}
        for v in sorted(x for x in data[n] if x.startswith("e8|")):
            rec = data[n][v]
            row[v] = {"reach": sum(1 for t in ids if rec[t][0]), "named_mean": float(np.mean([rec[t][1] for t in ids]))}
        e8[n] = row
    out["e8"] = e8
    # ---- 9 (measure): misses whose gold function a test chunk of the top 10 / any list's top 50 calls
    e9 = {}
    for n in R.SETS:
        if n not in data or "tests_bridge" not in data[n + ":meta"]:
            continue
        meta = data[n + ":meta"]["tests_bridge"]
        miss = [t for t in halves[n] if gold[n][t][0] and not hit(data[n]["base"].get(t))]
        row = {"misses": len(miss)}
        for v in ("a", "b99", "b90", "c"):
            vals = [meta[t][v] for t in miss]
            row[v] = {"callee_of_top10_test": sum(x[0] for x in vals), "within_2_of_top10_test": sum(x[1] for x in vals),
                      "callee_of_top50_test": sum(x[2] for x in vals), "within_2_of_top50_test": sum(x[3] for x in vals)}
        row["test_chunks_in_top10_mean"] = float(np.mean([meta[t]["a"][4] for t in halves[n]]))
        row["test_chunks_in_lists_top50_mean"] = float(np.mean([meta[t]["a"][5] for t in halves[n]]))
        e9[n] = row
    out["e9_measure"] = e9
    # ---- 13 (measure): tasks whose gold file is not among the top-10 files: is one among the files most
    # often changed together with a top-10 file (each file's 5; or the 5 of the summed counts)?
    e13 = {}
    for n in R.SETS:
        if n not in data or "cochange" not in data[n + ":meta"]:
            continue
        meta = data[n + ":meta"]["cochange"]
        miss = [t for t in halves[n] if meta[t]["has_file"] and not meta[t]["gold_file_in_top10_files"]]
        e13[n] = {"tasks_with_file": sum(1 for t in halves[n] if meta[t]["has_file"]), "file_misses": len(miss),
                  "in_per_file_top5": sum(meta[t]["gold_in_per_file_top5"] for t in miss),
                  "in_summed_top5": sum(meta[t]["gold_in_summed_top5"] for t in miss),
                  "commits_before_mean": float(np.mean([meta[t]["commits_before"] for t in halves[n]])),
                  "commits_before_min": int(min(meta[t]["commits_before"] for t in halves[n]))}
    out["e13_measure"] = e13
    # ---- 12: a query in two parts
    e12 = {}
    fus = {r: C.Fuser(ixs[r]) for r in ixs}
    for short, l0set in (("vague-L2", "pandas-L0"), ("vague-L1", "pandas-L0"), ("pandas-title", "pandas-L0"), ("vllm-title", "vllm-L0")):
        if short not in sets or not (L.OUT / f"bm25v-{sets[short]['repo']}.json").is_file():
            continue
        repo = sets[short]["repo"]
        ix, fu = ixs[repo], fus[repo]
        run_s = C.load_run(short, ix)
        run_0 = C.load_run(l0set, ix)
        bv = json.loads((L.OUT / f"bm25v-{repo}.json").read_text("utf-8"))
        rows = defaultdict(dict)
        n_with_idents = 0
        for t in sets[short]["tasks"]:
            tid = t["id"]
            files, fns = ix.gold_rows(t)
            rs, r0 = run_s[tid], run_0[tid]
            ident = np.array([ix.row_of[c] for c in bv[tid]["idents"]], dtype=np.int64)
            ident_q = np.array([ix.row_of[c] for c in bv[tid]["idents_q"]], dtype=np.int64)
            n_with_idents += bool(bv[tid]["idents_text"].strip())
            variants = {
                "short (as is)": [("bm25", rs["lists"]["bm25"][:50], 1), ("code", rs["lists"]["code"][:50], 1), ("usage", rs["lists"]["usage"][:50], 1)],
                "L0 (as is)": [("bm25", r0["lists"]["bm25"][:50], 1), ("code", r0["lists"]["code"][:50], 1), ("usage", r0["lists"]["usage"][:50], 1)],
                "dense short + keywords on L0 names": [("bm25", ident[:50], 1), ("code", rs["lists"]["code"][:50], 1), ("usage", rs["lists"]["usage"][:50], 1)],
                "dense short + keywords on L0 names and quotes": [("bm25", ident_q[:50], 1), ("code", rs["lists"]["code"][:50], 1), ("usage", rs["lists"]["usage"][:50], 1)],
                "short as is + keywords on L0 names (4 lists)": [("bm25", rs["lists"]["bm25"][:50], 1), ("code", rs["lists"]["code"][:50], 1),
                                                                 ("usage", rs["lists"]["usage"][:50], 1), ("names", ident[:50], 1)],
                "dense short + keywords on the whole L0 issue": [("bm25", r0["lists"]["bm25"][:50], 1), ("code", rs["lists"]["code"][:50], 1), ("usage", rs["lists"]["usage"][:50], 1)],
            }
            for name, lists in variants.items():
                order, _ = fu.fuse(lists)
                fn = C.first_rank(order, fns) if fns else None
                fl = C.first_rank(order, files, ix.file_of) if files else None
                rows[name][tid] = (fn, fl, bool(fns), bool(files), t["half"])
        res = {"tasks": len(sets[short]["tasks"]), "tasks_whose_L0_has_names": n_with_idents}
        for name, rec in rows.items():
            fnids = [t for t, x in rec.items() if x[2]]
            flids = [t for t, x in rec.items() if x[3]]
            res[name] = {"fn@10": sum(hit(rec[t]) for t in fnids), "fn@20": sum(hit(rec[t], 20) for t in fnids),
                         "file@10": sum(hit(rec[t], 10, 1) for t in flids), "fn_tasks": len(fnids), "file_tasks": len(flids)}
            base = rows["short (as is)"]
            d = np.array([hit(rec[t]) - hit(base[t]) for t in fnids])
            res[name]["fn@10_vs_short"] = R.boot(d)
        e12[short] = res
    out["e12"] = e12
    (L.OUT / "s3-extra.json").write_text(json.dumps(out, indent=1, default=str), "utf-8")
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
