"""Experiment 7's keyword part for a set whose s3 run had no keyword variants yet: the keyword list
from a shortened issue (title, first 32/64/128 words, the names in it), in place of the whole issue's
(e7kw) or beside it (e7kw2), merged into out/s3-<set>.json. Needs no vectors.

    ./run.sh s3_e7kw.py <set>
"""
from __future__ import annotations

import json
import sys

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import core as C
import lab_common as L


def main() -> None:
    name = sys.argv[1]
    qs = L.query_sets([name])[name]
    repo = qs["repo"]
    ix = L.Index(repo, vectors=False)
    fu = C.Fuser(ix)
    run = C.load_run(name, ix)
    bv = json.loads((L.OUT / f"bm25v-{repo}.json").read_text("utf-8"))
    path = L.OUT / f"s3-{name}.json"
    data = json.loads(path.read_text("utf-8"))
    rec = data[name]
    base_cands = {}
    for t in qs["tasks"]:
        tid = t["id"]
        files, fns = ix.gold_rows(t)
        r = run[tid]
        order0, sc0 = fu.baseline(r)
        cands = set(sc0)
        for var in ("title", "w32", "w64", "w128", "idents", "idents_q"):
            kw = np.array([ix.row_of[c] for c in bv[tid][var]], dtype=np.int64)
            for fam, lists in (("e7kw", [("bm25", kw[:50], 1.0), ("code", r["lists"]["code"][:50], 1.0), ("usage", r["lists"]["usage"][:50], 1.0)]),
                               ("e7kw2", [("bm25", r["lists"]["bm25"][:50], 1.0), ("code", r["lists"]["code"][:50], 1.0),
                                          ("usage", r["lists"]["usage"][:50], 1.0), ("bm25b", kw[:50], 1.0)])):
                order, sc = fu.fuse(lists)
                fn = C.first_rank(order, fns) if fns else None
                fl = C.first_rank(order, files, ix.file_of) if files else None
                rec.setdefault(f"{fam}|{var}", {})[tid] = (fn, fl, len(set(sc) - cands), 0)
    path.write_text(json.dumps(data), "utf-8")
    print(f"{name}: e7kw merged for {len(qs['tasks'])} tasks")


if __name__ == "__main__":
    main()
