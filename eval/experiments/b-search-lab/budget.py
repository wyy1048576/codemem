"""The character budget of search_code's answer: what the MCP tool returns today (the cards and the
search footer) and with parts 1 and 2 at their defaults (related names on the cards, the next 20
results by name), with the branch's own search() and render, on one query set (or a shard of it).
Today's text is the same response rendered without the related names and the more block: parts 1
and 2 change no result (tests/test_search.py), so it is what main returns.

    ./run_branch.sh budget.py <set> [<shard> <shards>]
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import lab_common as L
import prod
from codemem import prompts
from codemem.render import format_results
from codemem.search import SearchResponse, search


def main() -> None:
    name = sys.argv[1]
    shard, shards = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (0, 1)
    qs = L.query_sets([name])[name]
    store, config = prod.open_store(qs["repo"])
    store.load_vectors()
    assert config.card_relations == 3 and config.more_results == 20
    pre = prod.Precomputed({t["query"]: t["vec"] for t in qs["tasks"]})
    footer = "\n\n" + prompts.search_footer(config.steering)
    rows = []
    for i, t in enumerate(qs["tasks"]):
        if i % shards != shard:
            continue
        resp = search(store, t["query"], config, k=10, embedder_factory=lambda s, c: pre)
        new = format_results(resp) + footer
        for card in resp.results:
            card.related = []
        today = format_results(SearchResponse(resp.query, resp.signals, resp.results)) + footer
        rows.append({"id": t["id"], "today": len(today), "new": len(new), "related_ms": resp.timings.get("relations", 0) * 1000})
    (L.OUT / f"budget-{name}.{shard}.json").write_text(json.dumps(rows), "utf-8")
    print(f"{name} shard {shard}: {len(rows)} searches", flush=True)


if __name__ == "__main__":
    main()
