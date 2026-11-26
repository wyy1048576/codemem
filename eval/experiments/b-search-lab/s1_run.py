"""Stage 1 run, one query set (or one shard of it): per task,
  * the product's own search(): codemem.search.search(store, query, Config(), k=50, debug=True), the
    stored question vector handed in by text (prod.Precomputed). Its first 10 are what the MCP tool
    returns for k=10 (same 50 candidates per list, ties ordered by location either way);
  * each of the search's three lists out to 1,000, through the product's own calls: bm25_match() +
    Store.bm25_search(match, 1000) and Store.vector_search(type, vector, 1000) (exact FAISS here).
Kept in out/s1-<set>[.<shard>].json, nothing else is written.

    ./run.sh s1_run.py <set> [<shard> <shards>]
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import lab_common as L
import prod

DEPTH = 1000


def main() -> None:
    name = sys.argv[1]
    shard, shards = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (0, 1)
    qs = L.query_sets([name])[name]
    store, config = prod.open_store(qs["repo"])
    t = time.perf_counter()
    store.load_vectors()
    status = store.search_index_status()
    print(f"{name}: search indexes loaded in {time.perf_counter() - t:.1f} s: {status['index']} ({status['why']})", flush=True)
    pre = prod.Precomputed({task["query"]: task["vec"] for task in qs["tasks"]})
    tasks = [task for i, task in enumerate(qs["tasks"]) if i % shards == shard]
    rows = []
    t_all = time.perf_counter()
    for i, task in enumerate(tasks):
        t0 = time.perf_counter()
        resp = prod.search(store, task["query"], config, k=50, debug=True, embedder_factory=lambda spec, cfg: pre)
        search_s = time.perf_counter() - t0
        match = prod.bm25_match(store, task["query"], config)
        t1 = time.perf_counter()
        bm25 = store.bm25_search(match, DEPTH, config.bm25_weights5()) if match else []
        bm25_s = time.perf_counter() - t1
        lists = {"bm25": [int(c) for c in bm25]}
        scores = {}
        for vt in ("code", "usage"):
            hits = store.vector_search(vt, task["vec"], DEPTH)
            lists[vt] = [h.chunk_id for h in hits]
            scores[vt] = [round(float(h.score), 6) for h in hits]
        rows.append({
            "id": task["id"], "results": [c.chunk_id for c in resp.results], "ranks": [c.ranks for c in resp.results],
            "fused_scores": [c.score for c in resp.results], "signals": resp.signals,
            "ms": {k: round(v * 1000, 2) for k, v in resp.timings.items()}, "search_s": round(search_s, 4),
            "bm25_1000_s": round(bm25_s, 4), "match": match, "lists": lists, "scores": scores,
        })
        if (i + 1) % 25 == 0:
            print(f"{name} shard {shard}: {i + 1}/{len(tasks)} in {time.perf_counter() - t_all:.0f} s", flush=True)
    suffix = f".{shard}" if shards > 1 else ""
    (L.OUT / f"s1-{name}{suffix}.json").write_text(json.dumps({"set": name, "repo": qs["repo"], "rows": rows}), "utf-8")
    print(f"{name} shard {shard}: done, {len(rows)} tasks in {time.perf_counter() - t_all:.0f} s", flush=True)
    store.close()


if __name__ == "__main__":
    main()
