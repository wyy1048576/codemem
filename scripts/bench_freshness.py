"""How long until an edit is searchable: the cost of an update on a big repo, without the model.

Uses the fake embedder, so the numbers are the update's own work (scan, chunk, link, texts,
storage), the part that grows with the repo. Add the model's cost per changed text (measure it
with `--model jinaai/jina-code-embeddings-0.5b` on a small repo) to get save-to-searchable.

Runs on any codemem version: an update with paths (the watcher's way) is used when the Indexer
supports it, else a full update.

usage: python scripts/bench_freshness.py REPO INDEX_DIR FILE_TO_EDIT [--model fake:896] [--out JSON]

FILE_TO_EDIT gets one line appended inside one function's body (moving every later line of the
file down by one), then the edit is undone. The repo is left as it was.
"""

from __future__ import annotations

import argparse
import inspect
import json
import platform
import time
from pathlib import Path

from codemem import __version__
from codemem.chunker import chunk_source
from codemem.config import Config, VectorConfig
from codemem.indexer import Indexer
from codemem.store import Store


def config(model: str) -> Config:
    cfg = Config(vector_cache="off")
    cfg.vectors = {"code": VectorConfig(model=model), "usage": VectorConfig(model=model)}
    return cfg


def edit_inside_a_function(path: Path, rel: str) -> bytes:
    """Append `_codemem_bench_edit = 1` after the last line of a mid-file function. Returns the
    original bytes."""
    original = path.read_bytes()
    chunks = [c for c in chunk_source(original, rel) if c.kind in ("function", "method") and c.end_line - c.start_line >= 5]
    target = chunks[len(chunks) // 2]
    lines = original.decode("utf-8").split("\n")
    last = lines[target.end_line - 1]
    indent = last[: len(last) - len(last.lstrip())]
    lines.insert(target.end_line, f"{indent}_codemem_bench_edit = 1")
    path.write_bytes("\n".join(lines).encode("utf-8"))
    print(f"edited {rel}: after line {target.end_line}, inside {target.qualname}", flush=True)
    return original


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", type=Path)
    ap.add_argument("index_dir", type=Path)
    ap.add_argument("file")
    ap.add_argument("--model", default="fake:896")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    cfg = config(args.model)
    store = Store(args.index_dir)
    indexer = Indexer(args.repo, store, cfg)
    params = inspect.signature(indexer.update).parameters
    has_paths = "paths" in params
    lazy = {"save": False} if "save" in params else {}  # the MCP server saves the FAISS files later
    results: dict[str, dict] = {}

    def run(label: str, **kwargs) -> None:
        t = time.perf_counter()
        stats = indexer.update(**kwargs)
        wall = time.perf_counter() - t
        timings = {k: round(v, 3) for k, v in stats.timings.items()}
        row = {"wall_s": round(wall, 3), "files_changed": stats.files_changed, "embedded": stats.embedded,
               "model_embedded": stats.model_embedded,
               "chunks_added": stats.chunks_added, "chunks_updated": stats.chunks_updated, "timings": timings}
        for extra in ("queued", "relinked"):
            if hasattr(stats, extra):
                row[extra] = getattr(stats, extra)
        results[label] = row
        print(f"{label}: {wall:.2f}s  {row}", flush=True)

    def timed(label: str, fn) -> None:
        t = time.perf_counter()
        fn()
        results[label] = {"wall_s": round(time.perf_counter() - t, 3)}
        print(f"{label}: {results[label]['wall_s']:.2f}s", flush=True)

    if not store.get_meta("indexed_at"):
        run("full build")
    run("no-op update (scan)")
    # A long-lived server (MCP) loads its search indexes once; every save after that is warm.
    timed("load the search indexes (once per process)", store.load_vectors)
    target = args.repo / args.file
    original = edit_inside_a_function(target, args.file)
    try:
        if has_paths:
            run("one-function edit (paths)", paths=[args.file], **lazy)
        else:
            run("one-function edit (scan)")
    finally:
        target.write_bytes(original)
    if has_paths:
        run("undo (paths)", paths=[args.file], **lazy)
    else:
        run("undo (scan)")
    timed("save the search indexes", store.save_vectors)
    store.close()
    meta = {"codemem": __version__, "machine": platform.machine(), "python": platform.python_version(),
            "repo": str(args.repo), "file": args.file, "model": args.model, "update_with_paths": has_paths}
    if args.out:
        args.out.write_text(json.dumps({"meta": meta, "results": results}, indent=2) + "\n")


if __name__ == "__main__":
    main()
