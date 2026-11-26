"""Embed, once, the short queries the lab needs and the indexes' model made no vector of yet:
the vague pandas prompts (L1, L2) and every task's issue title (pandas, vLLM). Query prefix as the
product embeds a query (Embedder.embed_queries). Saved to qvec-extra.npz; the model is then freed."""
from __future__ import annotations

import sys
import time

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import lab_common as L

from codemem.config import load_config
from codemem.embedder import make_embedder


def main() -> None:
    config = load_config()
    embedder = make_embedder(config.vectors["code"], config)
    want = "jinaai/jina-code-embeddings-0.5b|doc|L1024|float16|mps"
    if embedder.key != want:
        sys.exit(f"this machine embeds with {embedder.key}, the indexes were built with {want}")
    vague = L.load_vague()
    ids = sorted(vague)
    out: dict[str, np.ndarray] = {"vague_ids": np.array(ids)}
    t = time.perf_counter()
    for level in ("L1", "L2"):
        out[f"vague_{level}"] = embedder.embed_queries([vague[i][level] for i in ids]).astype(np.float32)
    print(f"vague: {len(ids)} tasks x 2 levels in {time.perf_counter() - t:.0f} s", flush=True)
    for repo in ("pandas", "vllm"):
        tasks = L.load_tasks(repo)
        t = time.perf_counter()
        titles = [L.title_of(x["query"]) for x in tasks]
        out[f"{repo}_title_ids"] = np.array([x["id"] for x in tasks])
        out[f"{repo}_title"] = embedder.embed_queries(titles).astype(np.float32)
        print(f"{repo}: {len(titles)} titles in {time.perf_counter() - t:.0f} s", flush=True)
        # a check that this process embeds as the stored question vectors were embedded
        again = embedder.embed_queries([tasks[0]["query"], tasks[1]["query"]]).astype(np.float32)
        cos = [float(again[i] @ tasks[i]["vec"]) for i in range(2)]
        print(f"{repo}: cosine of two issue texts embedded now with their stored vectors: {cos}", flush=True)
    np.savez(L.EXTRA_VECS, **out)
    print("saved", L.EXTRA_VECS, {k: v.shape for k, v in out.items()})


if __name__ == "__main__":
    main()
