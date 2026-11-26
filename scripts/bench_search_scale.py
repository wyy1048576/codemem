"""What vector search costs as an index grows: memory, disk, start-up and search time, for the
exact index (a full scan of every vector) and the compact one (codes in memory, exact scores from
the database).

    uv run python scripts/bench_search_scale.py --work <a folder with free disk> --out scale.json

Everything else has a default:

  --sizes    how many vectors each index holds (default 100000,200000,500000,1000000)
  --threads  run with OMP_NUM_THREADS set to this (default: unset, so FAISS runs as codemem runs
             it on this machine: every core on Linux and Windows, one on macOS). `--threads 1`
             gives the numbers of one core, to compare machines. On macOS codemem sets it to 1
             whatever this says, and the run says so
  --keep-indexes  do not delete the indexes afterwards

For each size it builds one index of synthetic vectors (clustered, so that a query has
neighbours: 2,000 centres plus noise, 896 numbers, rounded to 2 bytes like real rows), with 1.25
vectors per chunk. It is a `codemem` index with vectors only: no chunks, no keyword table, no
embedding model. Disk: about 2.5 GB per million vectors, plus the saved search indexes, in
`--work`. Memory: the exact index holds 1.9 GB per million vectors, and the last step holds both
indexes at once.

Then, for the exact and the compact index, each in a process of its own so that the memory
readings are clean:

  prepare   open the index with this search index (built from the stored vectors) and save it
  measure   start again: load the saved search index, run 200 searches (50 results), 200 more
            under a filter that keeps a tenth of the chunks, then add and delete 100 vectors

And once, in one process, the searches of both taking turns, query by query, so that a change in
the machine's load falls on both alike. That step also asks FAISS to search the compact index's
4-bit codes by itself (its own two-stage search), reads the vectors it picks and scores them
exactly: the same job as the compact index's three steps, done with one code. It reports how
long each takes and whether the two pick the same candidates.

Send back the table it prints and the JSON file. The agreement columns are a sanity check only:
every vector of a cluster is about equally close to a query of that cluster, which real code is
not. `scripts/check_search_indexes.py` measures agreement on a real index.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

DIM = 896
VEC_TYPE = "code"
EMBEDDER = f"synthetic:{DIM}"
CENTRES = 2000
NOISE = 0.55  # relative size of the noise: nearest neighbours then have a similarity of about 0.75
COMPACT = {"bits": 4, "dim": 0, "rescore": 200}


def memory() -> int:
    """Bytes of memory this process holds: its footprint on macOS (what Activity Monitor shows),
    its resident size on Linux, 0 where neither can be read."""
    if sys.platform == "darwin":
        try:
            lib = ctypes.CDLL("/usr/lib/libproc.dylib")
            buf = (ctypes.c_uint64 * 64)()  # rusage_info_v2: a 16-byte uuid, then 64-bit counters
            if lib.proc_pid_rusage(os.getpid(), 2, ctypes.byref(buf)) == 0:
                return int(buf[2 + 7])  # ri_phys_footprint
        except OSError:
            pass
    try:
        with open("/proc/self/statm", encoding="ascii") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, AttributeError):
        return 0


def synthetic(n: int, seed: int) -> np.ndarray:
    """n vectors around the same 2,000 centres whatever the seed, so that queries (another seed)
    have neighbours in the index."""
    centres = np.random.default_rng(424242).standard_normal((CENTRES, DIM)).astype(np.float32)
    centres /= np.linalg.norm(centres, axis=1, keepdims=True)
    rng = np.random.default_rng(seed)
    out = np.empty((n, DIM), dtype=np.float16)
    for start in range(0, n, 20000):
        m = min(20000, n - start)
        x = centres[rng.integers(0, CENTRES, m)] + NOISE * rng.standard_normal((m, DIM)).astype(np.float32) / np.sqrt(DIM)
        x /= np.linalg.norm(x, axis=1, keepdims=True)
        out[start : start + m] = x
    return out


def open_store(index_dir: Path, backend: str):
    from codemem.store import Store

    return Store(index_dir, vector_backend=backend, vector_options=COMPACT if backend == "compact" else {})


def cmd_build(args: argparse.Namespace) -> None:
    from codemem.store import Store, VectorRow

    index_dir = Path(args.index)
    if index_dir.exists():
        shutil.rmtree(index_dir)
    store = Store(index_dir, vector_backend="faiss")
    vecs = synthetic(args.n, args.seed)
    rng = np.random.default_rng(args.seed + 1)
    t = time.perf_counter()
    chunk, part, n_parts = 0, 0, 1
    for start in range(0, args.n, 4096):
        rows = []
        for i in range(start, min(start + 4096, args.n)):
            if part + 1 >= n_parts:  # next chunk: one in four has two vectors
                chunk, part, n_parts = chunk + 1, 0, 2 if rng.random() < 0.25 else 1
            else:
                part += 1
            rows.append(VectorRow(chunk, part, n_parts, 0, 1000, f"{i:020x}"))
        with store.transaction():
            store.ensure_vec_type(VEC_TYPE, EMBEDDER)
            store.put_vectors(VEC_TYPE, EMBEDDER, rows, vecs[start : start + len(rows)].astype(np.float32))
    store.close()
    for saved in index_dir.glob("vec_*"):  # `prepare` builds each search index from the rows
        saved.unlink()
    print(json.dumps({"n": args.n, "chunks": chunk, "build_s": round(time.perf_counter() - t, 1),
                      "index_db_bytes": (index_dir / "index.db").stat().st_size}))


def cmd_prepare(args: argparse.Namespace) -> None:
    store = open_store(Path(args.index), args.backend)
    t = time.perf_counter()
    store.load_vectors()
    load_s = time.perf_counter() - t
    t = time.perf_counter()
    store.save_vectors()
    print(json.dumps({"built_from_the_rows_s": round(load_s, 2), "save_s": round(time.perf_counter() - t, 2)}))
    store.close()


def _times(fn, queries) -> dict:
    took = []
    for q in queries:
        t = time.perf_counter()
        fn(q)
        took.append((time.perf_counter() - t) * 1000)
    took = np.array(took[1:])
    return {"p50_ms": round(float(np.percentile(took, 50)), 2), "p95_ms": round(float(np.percentile(took, 95)), 2)}


def cmd_measure(args: argparse.Namespace) -> None:
    import faiss

    from codemem.store import VectorRow

    index_dir = Path(args.index)
    queries = synthetic(401, args.seed + 7).astype(np.float32)
    rng = np.random.default_rng(args.seed + 9)
    base = memory()
    store = open_store(index_dir, args.backend)
    t = time.perf_counter()
    store.load_vectors()
    load_s = time.perf_counter() - t
    loaded = memory()
    n_vectors = store.counts()["vectors"][VEC_TYPE]
    chunk_ids = sorted({r[0] for r in store.conn.execute("SELECT DISTINCT chunk_id FROM vectors")})
    allowed = [int(c) for c in rng.choice(chunk_ids, max(1, len(chunk_ids) // 10), replace=False)]
    plain = _times(lambda q: store.vector_search(VEC_TYPE, q, 50), queries[:201])
    filtered = _times(lambda q: store.vector_search(VEC_TYPE, q, 50, allowed), queries[200:])
    new_rows = [VectorRow(10_000_000 + i, 0, 1, 0, 10, f"n{i:019x}") for i in range(100)]
    t = time.perf_counter()
    store.put_vectors(VEC_TYPE, EMBEDDER, new_rows, queries[:100])
    add_ms = (time.perf_counter() - t) * 1000
    ids = [v[0] for v in store.vector_parts(VEC_TYPE, [r.chunk_id for r in new_rows]).values()]
    t = time.perf_counter()
    store.delete_vectors(VEC_TYPE, ids)
    delete_ms = (time.perf_counter() - t) * 1000
    saved = sum(p.stat().st_size for p in index_dir.glob("vec_*") if p.suffix != ".json")
    print(json.dumps({
        "vectors": n_vectors, "loaded_from_the_saved_file_s": round(load_s, 2),
        "memory_mb": round((loaded - base) / 1e6, 1) if base and loaded else None,
        "bytes_per_vector_in_memory": round((loaded - base) / n_vectors) if base and loaded else None,
        "saved_index_mb": round(saved / 1e6, 1), "search": plain, "search_under_a_filter": filtered,
        "add_100_ms": round(add_ms, 1), "delete_100_ms": round(delete_ms, 1), "faiss_threads": faiss.omp_get_max_threads(),
    }))
    store.close()


def cmd_turns(args: argparse.Namespace) -> None:
    """Both indexes in one process, each query asked of each in turn; and FAISS's own search of the
    compact index's 4-bit codes, with the same exact last step."""
    import faiss

    import codemem.store as store_module

    index_dir = Path(args.index)
    queries = synthetic(301, args.seed + 7).astype(np.float32)
    compact = open_store(index_dir, "compact")  # its saved file is the one in the folder
    compact.load_vectors()
    exact = open_store(index_dir, "faiss")  # built from the rows; nothing is saved here
    exact.load_vectors()
    ti = compact._type_index(VEC_TYPE)
    codes = ti.store
    size = max(codes.rescore, 4 * ti.vectors_for(51))  # what a search for 50 chunks scores exactly
    params = faiss.RaBitQSearchParameters(qb=4, centered=False)

    def own(q: np.ndarray) -> np.ndarray:
        x = codes._coded(store_module.prepare(q, ti.dim)[0])
        _, positions = codes._fine.search(x, size, params=params)
        picked = codes._ids[positions[0][positions[0] >= 0]]
        _, vecs = codes._fetch(picked)
        (vecs * store_module.prepare(q, ti.dim)[0]).sum(axis=1)
        return picked

    for q in queries[:20]:  # every page a search reads is in memory before anything is timed
        exact.vector_search(VEC_TYPE, q, 50), compact.vector_search(VEC_TYPE, q, 50), own(q)
    took: dict[str, list[float]] = {"exact": [], "compact": [], "faiss_own_4bit": []}
    same_results, same_candidates = [], []
    for q in queries[20:]:
        t = time.perf_counter()
        a = exact.vector_search(VEC_TYPE, q, 50)
        took["exact"].append(time.perf_counter() - t)
        t = time.perf_counter()
        b = compact.vector_search(VEC_TYPE, q, 50)
        took["compact"].append(time.perf_counter() - t)
        t = time.perf_counter()
        picked = own(q)
        took["faiss_own_4bit"].append(time.perf_counter() - t)
        same_results.append({h.chunk_id for h in a[:10]} == {h.chunk_id for h in b[:10]})
        ours = set(codes._ids[codes._candidates(store_module.prepare(q, ti.dim)[0], size, None)].tolist())
        same_candidates.append(len(ours & set(picked.tolist())) / max(1, len(picked)))
    out = {name: round(float(np.median(v)) * 1000, 2) for name, v in took.items()}
    print(json.dumps({
        "ms_p50": out, "compact_over_exact": round(out["compact"] / out["exact"], 2),
        "faiss_own_over_compact": round(out["faiss_own_4bit"] / out["compact"], 2),
        "top10_equal_to_exact": round(float(np.mean(same_results)), 4),
        "candidates_shared_with_faiss_own": round(float(np.mean(same_candidates)), 4),
        "candidates_scored_exactly": size, "faiss_threads": faiss.omp_get_max_threads(),
    }))
    exact.close()
    compact.close()


def _sub(threads: int, *argv: str) -> dict:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    if threads:
        env["OMP_NUM_THREADS"] = str(threads)
    out = subprocess.run([sys.executable, __file__, *argv], env=env, capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(f"{argv}: {out.stderr[-3000:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def cmd_run(args: argparse.Namespace) -> None:
    import faiss

    import codemem

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    rows = []
    print(f"codemem {codemem.__version__} | FAISS {faiss.__version__} | {platform.machine()} {platform.platform()} | "
          f"{os.cpu_count()} CPUs | OMP_NUM_THREADS {'=' + str(args.threads) if args.threads else 'unset'}", flush=True)
    if sys.platform == "darwin" and args.threads > 1:
        print(f"macOS: importing codemem sets OMP_NUM_THREADS to 1 (codemem/__init__.py), so every step runs FAISS on "
              f"one thread, not {args.threads}", flush=True)
    head = (f"{'vectors':>9} {'index':<8} {'memory MB':>10} {'saved MB':>9} {'from file s':>11} {'from rows s':>11} "
            f"{'search ms':>10} {'filtered ms':>11} | in turns: {'exact':>7} {'compact':>8} {'FAISS own':>9} {'same top 10':>11} {'same candidates':>15}")
    print(head, flush=True)
    for n in [int(s) for s in args.sizes.split(",")]:
        index = work / f"n{n}"
        free = shutil.disk_usage(work).free
        if free < n * 4000:
            print(f"{n:>9} skipped: {work} has {free / 1e9:.1f} GB free and this size needs about {n * 4000 / 1e9:.1f} GB", flush=True)
            continue
        built = _sub(args.threads, "build", "--index", str(index), "--n", str(n))
        entry: dict = {"n": n, **built}
        for backend in ("faiss", "compact"):  # the compact one last: its saved file is what `turns` loads
            prepared = _sub(args.threads, "prepare", "--index", str(index), "--backend", backend)
            entry[backend] = {**prepared, **_sub(args.threads, "measure", "--index", str(index), "--backend", backend)}
        entry["turns"] = _sub(args.threads, "turns", "--index", str(index))
        rows.append(entry)
        for backend in ("faiss", "compact"):
            m, t = entry[backend], entry["turns"]
            tail = (f" | {'':>9} {t['ms_p50']['exact']:>7} {t['ms_p50']['compact']:>8} {t['ms_p50']['faiss_own_4bit']:>9} "
                    f"{t['top10_equal_to_exact']:>11} {t['candidates_shared_with_faiss_own']:>15}") if backend == "compact" else ""
            print(f"{n if backend == 'faiss' else '':>9} {'exact' if backend == 'faiss' else 'compact':<8} "
                  f"{m['memory_mb'] if m['memory_mb'] is not None else 'n/a':>10} {m['saved_index_mb']:>9} "
                  f"{m['loaded_from_the_saved_file_s']:>11} {m['built_from_the_rows_s']:>11} {m['search']['p50_ms']:>10} "
                  f"{m['search_under_a_filter']['p50_ms']:>11}{tail}", flush=True)
        if not args.keep_indexes:
            shutil.rmtree(index, ignore_errors=True)
    Path(args.out).write_text(json.dumps({
        "codemem": codemem.__version__, "faiss": faiss.__version__, "machine": f"{platform.machine()} {platform.platform()}",
        "cpus": os.cpu_count(), "omp_num_threads": args.threads or None, "measured": time.strftime("%Y-%m-%d %H:%M %z"),
        "dim": DIM, "centres": CENTRES, "noise": NOISE, "compact": COMPACT, "results": rows,
    }, indent=1), "utf-8")
    print(f"\nwritten to {args.out}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--work", help="a folder with free disk for the indexes (about 2.5 GB per million vectors)")
    p.add_argument("--out", default="search-scale.json", help="the JSON file to write")
    p.add_argument("--sizes", default="100000,200000,500000,1000000")
    p.add_argument("--threads", type=int, default=0, help="OMP_NUM_THREADS for every step (0 = leave it unset)")
    p.add_argument("--keep-indexes", action="store_true")
    sub = p.add_subparsers(dest="cmd")  # the steps `run` starts, each in a process of its own
    for name, fn in (("build", cmd_build), ("prepare", cmd_prepare), ("measure", cmd_measure), ("turns", cmd_turns)):
        s = sub.add_parser(name)
        s.add_argument("--index", required=True)
        s.add_argument("--n", type=int, default=0)
        s.add_argument("--backend", default="faiss")
        s.add_argument("--seed", type=int, default=0)
        s.set_defaults(fn=fn)
    args = p.parse_args()
    if args.cmd:
        args.fn(args)
    elif not args.work:
        p.error("--work is required")
    else:
        cmd_run(args)


if __name__ == "__main__":
    main()
