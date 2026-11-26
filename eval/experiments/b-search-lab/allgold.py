"""Fixes that change two or more functions: how many of them a search shows. For each such task,
the gold functions among the 10 cards, and among the cards plus the names the branch adds
(related callers and callees; results 11 to 30 by name). The branch's own search on the index copies.

    PYTHONPATH=<search-recall>/src python allgold.py <set>
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace

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
    assert config.card_relations == 3 and config.more_results == 20, (config.card_relations, config.more_results)
    ix = L.Index(repo, vectors=False)
    pre = prod.Precomputed({t["query"]: t["vec"] for t in qs["tasks"]})
    rows = []
    for t in qs["tasks"]:
        _, fns = ix.gold_rows(t)
        gold = {int(ix.ids[r]) for r in fns}
        if len(gold) < 2:
            continue
        # one search with 40 names after the cards: the first 20 are the branch's own block (same ranking),
        # the ones after them feed the control for the graph (as many deeper results as there are related names)
        resp = S.search(store, t["query"], replace(config, more_results=40), k=10, embedder_factory=lambda s, c: pre)
        top = {c.chunk_id for c in resp.results}
        rel = {r.chunk_id for c in resp.results for r in c.related}
        listed = [m.chunk_id for m in resp.more]
        more = set(listed[:20])
        deeper = listed[20:20 + len(rel)]
        rows.append({"id": t["id"], "half": t.get("half"), "n": len(gold), "top": len(gold & top),
                     "rel": len(gold & (top | rel)), "more": len(gold & (top | more)),
                     "page": len(gold & (top | rel | more)),
                     "control": len(gold & (top | more | set(deeper))), "n_rel": len(rel), "n_deeper": len(deeper)})
    (L.OUT / f"allgold-{name}.json").write_text(json.dumps(rows), "utf-8")

    def show(label, rs):
        if not rs:
            print(label, "no tasks"); return
        n = len(rs)
        line = [f"{label}: {n} tasks, {sum(r['n'] for r in rs)} gold functions (mean {np.mean([r['n'] for r in rs]):.1f} a task)"]
        for key, what in (("top", "the 10 cards"), ("rel", "cards + related names"), ("more", "cards + next 20"),
                          ("page", "cards + related + next 20"), ("control", "cards + next 20 + as many deeper results as related names")):
            every = sum(r[key] == r["n"] for r in rs)
            two = sum(r[key] >= 2 for r in rs)
            share = sum(r[key] for r in rs) / sum(r["n"] for r in rs)
            line.append(f"   {what:<62} every gold function: {every:>3} of {n} | at least two: {two:>3} | share of gold functions: {share:.0%}")
        print("\n".join(line), flush=True)

    held = [r for r in rows if r["half"] == 1] if not name.startswith("vague") else rows
    show(f"{name} held out" if not name.startswith("vague") else name, held)
    if not name.startswith("vague"):
        show(f"{name} all", rows)
    print("related names a search (mean):", round(float(np.mean([r["n_rel"] for r in rows])), 1),
          "| deeper results used by the control (mean):", round(float(np.mean([r["n_deeper"] for r in rows])), 1))
    store.close()


if __name__ == "__main__":
    main()
