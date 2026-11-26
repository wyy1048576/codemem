"""Experiment 12 on the held-out half (titles) and all vague tasks: the short query as is, against
the short query plus the L0 issue's names as a fourth, keyword-only list (no setting is chosen, so
both halves are reported). Also the L0 query plus its own names as a fourth list.

    ./run.sh e12_held.py
"""
from __future__ import annotations

import json
import sys

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import core as C
import lab_common as L
import s3_report as R


def choose_weight() -> None:
    """The names list's weight, chosen on half 0 of the title and L0 sets of both repos (functions at
    top 10, plus files at top 10 as the tie-break)."""
    for w in (0.25, 0.5, 0.75, 1.0):
        tot_fn = tot_file = 0
        for short, l0 in (("vllm-title", "vllm-L0"), ("pandas-title", "pandas-L0")):
            qs = L.query_sets([short])[short]
            repo = qs["repo"]
            ix = L.Index(repo, vectors=False)
            fu = C.Fuser(ix)
            rs, r0 = C.load_run(short, ix), C.load_run(l0, ix)
            bv = json.loads((L.OUT / f"bm25v-{repo}.json").read_text("utf-8"))
            for t in qs["tasks"]:
                if t["half"] != 0:
                    continue
                files, fns = ix.gold_rows(t)
                names = np.array([ix.row_of[c] for c in bv[t["id"]]["idents"]], dtype=np.int64)
                for run in (rs, r0):
                    a = run[t["id"]]["lists"]
                    base, _ = fu.fuse([(s_, a[s_][:50], 1) for s_ in C.SIGNALS])
                    exp, _ = fu.fuse([(s_, a[s_][:50], 1) for s_ in C.SIGNALS] + [("names", names[:50], w)])
                    if fns:
                        tot_fn += C.hit(C.first_rank(exp, fns), 10) - C.hit(C.first_rank(base, fns), 10)
                    if files:
                        tot_file += C.hit(C.first_rank(exp, files, ix.file_of), 10) - C.hit(C.first_rank(base, files, ix.file_of), 10)
        print(f"names weight {w}: half 0, short and L0 queries of both repos: functions at top 10 {tot_fn:+d}, files {tot_file:+d}", flush=True)


def main() -> None:
    if sys.argv[1:] == ["choose"]:
        return choose_weight()
    for short, l0 in (("vllm-title", "vllm-L0"), ("pandas-title", "pandas-L0"), ("vague-L1", "pandas-L0"), ("vague-L2", "pandas-L0")):
        qs = L.query_sets([short])[short]
        repo = qs["repo"]
        ix = L.Index(repo, vectors=False)
        fu = C.Fuser(ix)
        rs, r0 = C.load_run(short, ix), C.load_run(l0, ix)
        bv = json.loads((L.OUT / f"bm25v-{repo}.json").read_text("utf-8"))
        res = {"short": {}, "short+names": {}, "L0": {}, "L0+names": {}}
        for t in qs["tasks"]:
            tid = t["id"]
            files, fns = ix.gold_rows(t)
            names = np.array([ix.row_of[c] for c in bv[tid]["idents"]], dtype=np.int64)
            a, b = rs[tid]["lists"], r0[tid]["lists"]
            for key, lists in (("short", [("bm25", a["bm25"][:50], 1), ("code", a["code"][:50], 1), ("usage", a["usage"][:50], 1)]),
                               ("short+names", [("bm25", a["bm25"][:50], 1), ("code", a["code"][:50], 1), ("usage", a["usage"][:50], 1), ("names", names[:50], 1)]),
                               ("L0", [("bm25", b["bm25"][:50], 1), ("code", b["code"][:50], 1), ("usage", b["usage"][:50], 1)]),
                               ("L0+names", [("bm25", b["bm25"][:50], 1), ("code", b["code"][:50], 1), ("usage", b["usage"][:50], 1), ("names", names[:50], 1)])):
                order, _ = fu.fuse(lists)
                res[key][tid] = (C.first_rank(order, fns) if fns else None, C.first_rank(order, files, ix.file_of) if files else None,
                                 bool(fns), bool(files), t["half"])
        for scope in ("half 1", "all"):
            ids = [tid for tid, x in res["short"].items() if scope == "all" or x[4] == 1 or short.startswith("vague")]
            cells = []
            for which, label, k in ((0, "fn@10", 10), (0, "fn@20", 20), (1, "file@10", 10)):
                sel = [tid for tid in ids if res["short"][tid][2 + which]]
                h = {key: np.array([R.hit(res[key][tid], k, which) for tid in sel]) for key in res}
                s1, lo1, hi1 = R.boot(h["short+names"] - h["short"])
                s2, lo2, hi2 = R.boot(h["L0+names"] - h["L0"])
                cells.append(f"{label} of {len(sel)}: short {h['short'].sum()} -> +names {h['short+names'].sum()} ({s1:+.0f}, {lo1:+.0f}..{hi1:+.0f}); "
                             f"L0 {h['L0'].sum()} -> +names {h['L0+names'].sum()} ({s2:+.0f}, {lo2:+.0f}..{hi2:+.0f})")
            print(f"{short:13s} {scope}: " + " | ".join(cells), flush=True)
            if short.startswith("vague"):
                break


if __name__ == "__main__":
    main()
