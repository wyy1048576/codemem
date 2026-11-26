"""Stage 1: the product's own search() on an index copy, 50 results per task, with the rank each
result had in each list. One query set per run; the raw results are kept in out/s1-<set>.json.

    python s1_baseline.py <set> [<set> ...]      sets: vllm-L0 pandas-L0 vague-L0 vague-L1 vague-L2 vllm-title pandas-title
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import lab_common as L
import prod


def main() -> None:
    names = sys.argv[1:]
    sets = L.query_sets(names)
    stores: dict[str, tuple] = {}
    for name in names:
        qs = sets[name]
        repo = qs["repo"]
        if repo not in stores:
            stores[repo] = prod.open_store(repo)
            t = time.perf_counter()
            stores[repo][0].load_vectors()
            print(f"{repo}: search indexes loaded in {time.perf_counter() - t:.1f} s; "
                  f"{json.dumps(stores[repo][0].search_index_status())[:300]}", flush=True)
        store, config = stores[repo]
        pre = prod.Precomputed({t["query"]: t["vec"] for t in qs["tasks"]})
        rows = []
        t0 = time.perf_counter()
        for i, task in enumerate(qs["tasks"]):
            resp = prod.search(store, task["query"], config, k=50, debug=True, embedder_factory=lambda spec, cfg: pre)
            rows.append({"id": task["id"], "results": [c.chunk_id for c in resp.results],
                         "ranks": [c.ranks for c in resp.results],
                         "ms": {k: round(v * 1000, 2) for k, v in resp.timings.items()}})
            if (i + 1) % 50 == 0:
                print(f"{name}: {i + 1}/{len(qs['tasks'])} in {time.perf_counter() - t0:.0f} s", flush=True)
        (L.OUT / f"s1-{name}.json").write_text(json.dumps({"set": name, "repo": repo, "k": 50, "rows": rows}), "utf-8")
        print(f"{name}: done, {len(rows)} tasks in {time.perf_counter() - t0:.0f} s", flush=True)
    for store, _ in stores.values():
        store.close()


if __name__ == "__main__":
    main()
