"""The worked example's page: what search_code returns for pandas-dev__pandas-68195 at L2, today and
with the branch's parts (related names, the next results by name, a guessed name), on the real
pandas index; and with tests named apart."""
from __future__ import annotations

import sys

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import lab_common as L
import prod
from codemem import prompts
from codemem.render import format_results
from codemem.search import SearchResponse, search

TID = "pandas-dev__pandas-68195"
qs = L.query_sets(["vague-L2"])["vague-L2"]
t = next(x for x in qs["tasks"] if x["id"] == TID)
store, config = prod.open_store("pandas")
store.load_vectors()
pre = prod.Precomputed({t["query"]: t["vec"]})
f = lambda s, c: pre  # noqa: E731
resp = search(store, t["query"], config, k=10, embedder_factory=f)
today = SearchResponse(resp.query, resp.signals, [r for r in resp.results])
related = {r.chunk_id: r.related for r in resp.results}
for r in today.results:
    r.related = []
print("=== TODAY ===\n" + format_results(today))
for r in resp.results:
    r.related = related[r.chunk_id]
print("\n=== PARTS 1 AND 2 ===\n" + format_results(resp))
named = search(store, t["query"], config, k=10, names=["merge_asof"], embedder_factory=f)
print("\n=== WITH names=['merge_asof'] (cards only) ===")
print("\n".join(line for line in format_results(named).splitlines() if line[:1].isdigit() or line.startswith("   related")))
config.tests_apart = True
apart = search(store, t["query"], config, k=10, embedder_factory=f)
print("\n=== TESTS APART (cards' heads and the tests block) ===")
text = format_results(apart).splitlines()
print("\n".join(line for line in text if line[:1].isdigit()))
i = text.index("Tests that match:")
print("\n".join(text[i:i + 6]))
