"""Experiment 8, how a card's neighbours are chosen: by similarity to the query (as in s3_lab), at
random, or by the fewest callers (the most specific first). Also: a fixed hub cap of 100 callers in
place of the repo's 99th percentile. Reach = a gold function in the top 10 or named on a card.

    ./run.sh e8_choice.py
"""
from __future__ import annotations

import random
import sys

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import core as C
import lab_common as L
import s3_report as R


def main() -> None:
    for repo, names in (("vllm", ["vllm-L0", "vllm-title"]), ("pandas", ["pandas-L0", "pandas-title", "vague-L1", "vague-L2"])):
        ix = L.Index(repo, vectors=True)
        fu = C.Fuser(ix)
        # a fixed cap: no edge to a callee that has more than 100 callers
        m = ix.in_deg[ix.e_callee] <= 100
        op, o = ix._csr(ix.e_caller[m], ix.e_callee[m])
        ip, i_ = ix._csr(ix.e_callee[m], ix.e_caller[m])
        ix._graphs["k100"] = (op, o, ip, i_)
        sets = L.query_sets(names)
        for name in names:
            run = C.load_run(name, ix)
            rows = []
            for t in sets[name]["tasks"]:
                files, fns = ix.gold_rows(t)
                if not fns:
                    continue
                top = [int(x) for x in run[t["id"]]["product"][:10]]
                s10 = set(top)
                hit10 = any(r in fns for r in top)
                s_code = ix.scores("code", t["vec"])
                out = {"half": t["half"], "hit10": hit10}
                for v in ("b99", "k100"):
                    named_sim, named_deg, named_rand = set(), set(), [set() for _ in range(5)]
                    for r in top:
                        nb = [x for x in set(ix.neighbours(r, v, "both").tolist()) if x not in s10]
                        if not nb:
                            continue
                        a = np.array(nb)
                        sc = s_code[a]
                        named_sim.update(a[np.lexsort((a, -sc))][:3].tolist())
                        deg = ix.in_deg[a] + ix.out_deg[a]
                        named_deg.update(a[np.lexsort((a, deg))][:3].tolist())
                        for s in range(5):
                            rng = random.Random(f"{t['id']}|{r}|{s}")
                            named_rand[s].update(rng.sample(nb, min(3, len(nb))))
                    out[f"{v}|sim"] = hit10 or bool(named_sim & fns)
                    out[f"{v}|fewest_edges"] = hit10 or bool(named_deg & fns)
                    out[f"{v}|random"] = float(np.mean([hit10 or bool(x & fns) for x in named_rand]))
                    out[f"{v}|named"] = len(named_sim)
                rows.append(out)
            for scope in ("all", "held"):
                sel = [r for r in rows if scope == "all" or r["half"] == 1 or name.startswith("vague")]
                cells = [f"top10 {sum(r['hit10'] for r in sel)}"]
                for v in ("b99", "k100"):
                    cells.append(f"{v}: similar {sum(r[f'{v}|sim'] for r in sel)}, random {sum(r[f'{v}|random'] for r in sel):.1f}, "
                                 f"fewest edges {sum(r[f'{v}|fewest_edges'] for r in sel)}, names {np.mean([r[f'{v}|named'] for r in sel]):.1f}")
                print(f"{name:13s} {scope:4s} tasks {len(sel)} | " + " | ".join(cells), flush=True)


if __name__ == "__main__":
    main()
