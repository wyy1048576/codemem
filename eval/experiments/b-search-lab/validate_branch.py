"""The branch's own search (andre/search-recall) on the index copies, to check that what the lab
measured is what the product now does: reach with the cards' relations (card_relations = 3, the
default), the top 10 with names passed apart from a short query, and the time both take.

    PYTHONPATH=<search-recall>/src python validate_branch.py <set> [names]
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import core as C
import lab_common as L
import prod
import codemem.search as S


def main() -> None:
    name = sys.argv[1]
    with_names = sys.argv[2:] == ["names"]
    qs = L.query_sets([name])[name]
    repo = qs["repo"]
    store, config = prod.open_store(repo)
    store.load_vectors()
    assert config.card_relations == 3, config.card_relations
    ix = L.Index(repo, vectors=False)
    pre = prod.Precomputed({t["query"]: t["vec"] for t in qs["tasks"]})
    l0 = {t["id"]: t["query"] for t in L.load_tasks(repo)}
    rows = []
    for t in qs["tasks"]:
        if not (t["half"] == 1 or name.startswith("vague")):
            continue
        files, fns = ix.gold_rows(t)
        if not fns:
            continue
        gold_ids = {int(ix.ids[r]) for r in fns}
        t0 = time.perf_counter()
        resp = S.search(store, t["query"], config, k=10, embedder_factory=lambda s, c: pre)
        total = time.perf_counter() - t0
        top = [c.chunk_id for c in resp.results]
        named = {r.chunk_id for c in resp.results for r in c.related}
        row = {"hit10": bool(set(top) & gold_ids), "reach": bool((set(top) | named) & gold_ids), "named": len(named),
               "relations_ms": resp.timings.get("relations", 0) * 1000, "total_ms": total * 1000}
        if with_names:
            names = C.identifiers(l0[t["id"]])
            r2 = S.search(store, t["query"], config, k=10, names=names, embedder_factory=lambda s, c: pre)
            row["hit10_names"] = bool({c.chunk_id for c in r2.results} & gold_ids)
            row["names_ms"] = r2.timings.get("names", 0) * 1000
        rows.append(row)
    out = {"set": name, "tasks": len(rows), "top10": sum(r["hit10"] for r in rows), "reach": sum(r["reach"] for r in rows),
           "named_mean": float(np.mean([r["named"] for r in rows])),
           "relations_ms_median": float(np.median([r["relations_ms"] for r in rows])),
           "relations_ms_p90": float(np.percentile([r["relations_ms"] for r in rows], 90)),
           "search_ms_median": float(np.median([r["total_ms"] for r in rows]))}
    if with_names:
        out["top10_with_names"] = sum(r["hit10_names"] for r in rows)
        out["names_ms_median"] = float(np.median([r["names_ms"] for r in rows]))
    print(json.dumps(out), flush=True)
    (L.OUT / f"validate-{name}.json").write_text(json.dumps(out, indent=1), "utf-8")
    store.close()


if __name__ == "__main__":
    main()
