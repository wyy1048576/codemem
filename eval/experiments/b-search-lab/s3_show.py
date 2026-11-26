"""Held-out results of named variants (no choice made here): half 1 of the L0 and title sets, all
17 vague tasks, against the baseline on the same tasks, with the paired bootstrap interval.

    ./run.sh s3_show.py <variant> [<variant> ...]
"""
from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import lab_common as L
import s3_report as R


def main() -> None:
    data = R.load()
    sets = L.query_sets([n for n in R.SETS if n in data])
    ixs = {r: L.Index(r, vectors=False) for r in ("vllm", "pandas")}
    for v in sys.argv[1:]:
        print(f"\n## {v}")
        for name in R.SETS:
            if name not in data or v not in data[name]:
                continue
            ix = ixs[sets[name]["repo"]]
            rec, base = data[name][v], data[name]["base"]
            cells = []
            for label, which, k in (("fn@10", 0, 10), ("fn@20", 0, 20), ("file@10", 1, 10)):
                ids = []
                for t in sets[name]["tasks"]:
                    if not (t["half"] == 1 or name.startswith("vague")):
                        continue
                    files, fns = ix.gold_rows(t)
                    if (fns if which == 0 else files):
                        ids.append(t["id"])
                b = np.array([R.hit(base.get(t), k, which) for t in ids])
                e = np.array([R.hit(rec.get(t), k, which) for t in ids])
                s, lo, hi = R.boot(e - b)
                cells.append(f"{label} {b.sum()}->{e.sum()} of {len(ids)} ({s:+.0f}, CI {lo:+.0f}..{hi:+.0f}; +{int(((e - b) > 0).sum())}/-{int(((e - b) < 0).sum())})")
            print(f"   {name:13s} " + " | ".join(cells))


if __name__ == "__main__":
    main()
