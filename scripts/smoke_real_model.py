"""Smoke test with the real embedding model on a medium repo; records timings.

    uv run python scripts/smoke_real_model.py --repo-url https://github.com/psf/requests --ref v2.32.3

Clones the repo into the given work dir (default: ~/.codemem/smoke), indexes it
into a separate index dir, runs a few queries, and prints a JSON report.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

from codemem.config import codemem_home, load_config
from codemem.indexer import Indexer
from codemem.search import search
from codemem.store import Store

QUERIES = [
    "retry a request when the connection fails",
    "where are cookies merged into the outgoing request",
    "handle redirects and strip the authorization header",
    "parse the content type header charset",
    "disable SSL certificate verification",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-url", default="https://github.com/psf/requests")
    ap.add_argument("--ref", default="v2.32.3")
    ap.add_argument("--work-dir", type=Path, default=codemem_home() / "smoke")
    ap.add_argument("--device", default=None)
    ap.add_argument("--out", type=Path, default=None, help="also write the JSON report here")
    args = ap.parse_args()

    name = args.repo_url.rstrip("/").split("/")[-1]
    repo = args.work_dir / f"{name}@{args.ref}"
    if not repo.exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", args.ref, args.repo_url, str(repo)], check=True
        )
    index_dir = args.work_dir / f"index-{name}@{args.ref}"

    config = load_config(repo)
    if args.device:
        config.device = args.device
    store = Store(index_dir)
    progress_last = [0.0]

    def progress(phase, done, total):
        if time.monotonic() - progress_last[0] > 5:
            progress_last[0] = time.monotonic()
            print(f"  {phase} {done}/{total}", file=sys.stderr, flush=True)

    print(f"indexing {repo} (full) ...", file=sys.stderr)
    stats = Indexer(repo, store, config, progress=progress).update(full=True)

    t = time.perf_counter()
    noop = Indexer(repo, store, config).update()
    noop_s = time.perf_counter() - t

    search(store, "warmup", config)  # model already loaded by indexing; warm caches
    latencies, results = [], {}
    for q in QUERIES:
        t = time.perf_counter()
        resp = search(store, q, config, k=5)
        latencies.append(time.perf_counter() - t)
        results[q] = [f"{r.location} {r.qualname}" for r in resp.results]

    report = {
        "repo": f"{args.repo_url}@{args.ref}",
        "machine": {"platform": platform.platform(), "processor": platform.processor(), "device": config.device},
        "models": {v: config.model_id(v) for v in config.enabled_vec_types()},
        "counts": store.counts(),
        "full_index": {"seconds": round(stats.timings["total"], 1), **{k: round(v, 2) for k, v in stats.timings.items()}},
        "embedded": stats.embedded,
        "noop_update_seconds": round(noop_s, 3),
        "noop_embedded": noop.embedded,
        "query_latency_ms": {
            "median": round(statistics.median(latencies) * 1000, 1),
            "max": round(max(latencies) * 1000, 1),
        },
        "results": results,
    }
    store.close()
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
