"""Part 4 with the branch's own search(): `tests_apart` on, held-out halves and the vague sets. A gold
function in the 10 cards, against today's; and the tasks where a named test calls a gold function
(an edge in the index from the test to it; callees over 100 callers left out, as the cards do).

    ./run_branch.sh validate_part4.py <set>
"""
from __future__ import annotations

import json
import sys

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import lab_common as L
import prod
import codemem.search as S


def main() -> None:
    name = sys.argv[1]
    qs = L.query_sets([name])[name]
    repo = qs["repo"]
    store, config = prod.open_store(repo)
    store.load_vectors()
    ix = L.Index(repo, vectors=False)
    pre = prod.Precomputed({t["query"]: t["vec"] for t in qs["tasks"]})
    rows = []
    for t in qs["tasks"]:
        if not (t["half"] == 1 or name.startswith("vague")):
            continue
        files, fns = ix.gold_rows(t)
        if not fns:
            continue
        gold = {int(ix.ids[r]) for r in fns}
        config.tests_apart = False
        today = S.search(store, t["query"], config, k=10, embedder_factory=lambda s, c: pre)
        config.tests_apart = True
        apart = S.search(store, t["query"], config, k=10, embedder_factory=lambda s, c: pre)
        named = [x.chunk_id for x in apart.tests]
        near = store.neighbours(named, S.RELATION_MAX_CALLERS)
        calls = {o for links in near.values() for o, rel in links if rel == "calls"}
        rows.append({"today": bool({c.chunk_id for c in today.results} & gold), "apart": bool({c.chunk_id for c in apart.results} & gold),
                     "test_calls_gold": bool(calls & gold), "ms": apart.timings.get("tests_apart", 0) * 1000,
                     "tests_in_today": sum(c.is_test for c in today.results)})
    out = {"set": name, "tasks": len(rows), "today": sum(r["today"] for r in rows), "tests_apart": sum(r["apart"] for r in rows),
           "named_test_calls_gold": sum(r["test_calls_gold"] for r in rows),
           "of_them_not_in_cards": sum(r["test_calls_gold"] and not r["apart"] for r in rows),
           "tests_among_todays_10": float(np.mean([r["tests_in_today"] for r in rows])),
           "tests_apart_ms_median": float(np.median([r["ms"] for r in rows]))}
    print(json.dumps(out), flush=True)
    (L.OUT / f"validate-part4-{name}.json").write_text(json.dumps(out, indent=1), "utf-8")
    store.close()


if __name__ == "__main__":
    main()
