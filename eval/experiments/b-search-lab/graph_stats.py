"""The stored call graph of each index: degrees, hubs, test chunks, and the three edge versions
the graph experiments use: (a) all edges; (b) without hub callees (more than K callers, K at the
99th and the 90th percentile of callers per callee); (c) only edges whose callee's name is defined
once in the repo (callable kinds, per language family, as the indexer resolves calls).

    ./run.sh graph_stats.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import lab_common as L
from codemem.store import _family


def main() -> None:
    out = {}
    for name in ("vllm", "pandas"):
        con = sqlite3.connect(f"file:{L.REPOS[name]['index']}/index.db?mode=ro", uri=True)
        chunks = {r[0]: r[1:] for r in con.execute("SELECT chunk_id, name, qualname, kind, language, is_test FROM chunks")}
        e = np.array(con.execute("SELECT caller_id, callee_id FROM edges").fetchall(), dtype=np.int64)
        callers_per = Counter(e[:, 1].tolist())
        callees_per = Counter(e[:, 0].tolist())
        cp = np.array(list(callers_per.values()))
        ce = np.array(list(callees_per.values()))
        defs = Counter((_family(lang), nm) for nm, _, kind, lang, _ in chunks.values() if kind in ("function", "method", "class"))
        unique = np.array([defs[(_family(chunks[c][3]), chunks[c][0])] == 1 for c in e[:, 1].tolist()])
        k99, k90 = int(np.percentile(cp, 99)), int(np.percentile(cp, 90))
        deg_of_callee = np.array([callers_per[c] for c in e[:, 1].tolist()])
        hubs = sorted(callers_per.items(), key=lambda kv: -kv[1])[:8]
        out[name] = {
            "chunks": len(chunks), "test_chunks": sum(1 for v in chunks.values() if v[4]),
            "edges": int(len(e)), "distinct_callers": len(callees_per), "distinct_callees": len(callers_per),
            "callers_per_callee": {"median": float(np.median(cp)), "p90": float(np.percentile(cp, 90)),
                                   "p99": float(np.percentile(cp, 99)), "max": int(cp.max())},
            "callees_per_caller": {"median": float(np.median(ce)), "p90": float(np.percentile(ce, 90)),
                                   "p99": float(np.percentile(ce, 99)), "max": int(ce.max())},
            "top_hubs": [(chunks[c][1], chunks[c][2], n) for c, n in hubs],
            "edges_b99": int((deg_of_callee <= k99).sum()), "K99": k99,
            "edges_b90": int((deg_of_callee <= k90).sum()), "K90": k90,
            "edges_c_unique_name": int(unique.sum()),
            "edges_from_test_callers": int(sum(chunks[c][4] for c in e[:, 0].tolist())),
        }
        print(name, json.dumps(out[name], indent=1), flush=True)
    (L.OUT / "graph-stats.json").write_text(json.dumps(out, indent=1), "utf-8")


if __name__ == "__main__":
    main()
