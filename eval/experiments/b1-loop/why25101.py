"""Where codemem ranks the 25101 gold code for the loop's own queries and for grep-like queries."""
import json, os, sys
from pathlib import Path
from codemem.config import load_config
from codemem.search import search
from codemem.service import CodememService
from aug_retriever import AugRetriever

repo = Path(sys.argv[1])
service = CodememService(repo, config=load_config(repo)); service.repo_root = repo
service.update(full=False)
store = service.store
s = AugRetriever.__new__(AugRetriever); s.config = service.config
GOLD = {"duckdb.TopNHeap.Sink", "duckdb.TopNHeap.EntryShouldBeAdded", "duckdb.TopNHeap.AddEntryToHeap"}
FILE = "src/execution/operator/order/physical_top_n.cpp"


def where(ids):
    ch = store.get_chunks(ids)
    gold = next((i + 1 for i, c in enumerate(ids) if ch[c].qualname in GOLD), None)
    file = next((i + 1 for i, c in enumerate(ids) if ch[c].path == FILE), None)
    return f"gold fn {gold or '-':>4}  file {file or '-':>4}  of {len(ids)}"


task = next(json.loads(l) for l in open(sys.argv[2], encoding="utf8") if json.loads(l)["id"].endswith("25101"))
issue = task["query"]
r = next(json.loads(l) for l in open(os.path.expanduser("~/.cmeval/runs/duckdb-arc-loopfull/loop-full.jsonl"), encoding="utf8") if "25101" in l)
hist = r["hits"][0]["extra"]["augmentation"]["history"]
print("== the loop's own lists (rank of first gold function / first chunk of physical_top_n.cpp)")
for h in hist:
    q = h["query"]
    dense = f"{q['intent']}\n{q['symptom']}"
    lists = {"dense code": s._ranked(store, dense, "code", 1000), "dense usage": s._ranked(store, dense, "usage", 1000),
             "anchors bm25": s._ranked(store, " ".join(q["anchors"]), "bm25", 1000)}
    if h["round"] == 1:
        for sig in ("bm25", "code", "usage"):
            lists[f"whole issue {sig}"] = s._ranked(store, issue, sig, 1000)
    for name, ids in lists.items():
        print(f"round {h['round']} {name:18} {where(ids)}")
    for p in q.get("look_in", []):
        print(f"round {h['round']} look_in {p}")
print("\n== grep-like and hypothesis queries, one signal each (top 1000)")
for text in ["limit == 0", "LIMIT 0", "TOP_N Top: 0", "TOP_N", "TopN", "heap_size", "TopN limit 0",
             "TopNHeap Sink limit 0 empty heap", "top n operator with limit 0 reads from an empty heap",
             "ORDER BY with LIMIT 0 crashes in the top-n operator"]:
    for sig in ("bm25", "code"):
        print(f"{sig:5} {text!r:58} {where(s._ranked(store, text, sig, 1000))}")
service.close()
