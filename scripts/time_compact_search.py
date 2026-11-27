"""Which thread pool makes a compact search slower on many cores than on one: FAISS's OpenMP
threads, numpy's BLAS threads, or the two together. Step by step, on this machine.

    uv run python scripts/time_compact_search.py --work <a folder with free disk>

Everything else has a default:

  --sizes          vectors per index (default 100000,500000)
  --faiss-threads  FAISS's OpenMP threads to try (default 1,all; all = every CPU this process may use)
  --blas-threads   numpy's BLAS threads to try (default 1,all)
  --queries        searches timed per index and setting, after 10 that warm up (default 50)
  --keep-indexes   keep the indexes: a later run with the same --work reuses them, so that another
                   branch is timed on the same vectors without building them again

It builds each index as scripts/bench_search_scale.py does (the same synthetic vectors: 896
numbers, 1.25 vectors per chunk; about 2.5 GB of disk per million vectors, in --work, which should
be on a local disk: under WSL, not under /mnt/c) and saves its compact search index (4 bits,
rescore 200). Then it starts one child process for each pair of thread counts. A child never
imports torch, so several OpenMP threads are safe in it, on macOS too.

- numpy's BLAS: the child's environment sets OPENBLAS_NUM_THREADS, MKL_NUM_THREADS and
  VECLIB_MAXIMUM_THREADS (OpenBLAS, MKL, Apple's Accelerate) to the count, so they hold before
  numpy is imported.
- FAISS: OMP_NUM_THREADS is set to its count (OpenBLAS reads that one too, but only when
  OPENBLAS_NUM_THREADS is unset), and the child calls faiss.omp_set_num_threads after its imports
  (on macOS, importing codemem sets OMP_NUM_THREADS to 1).

The child loads the compact index from its file and builds the exact one from the rows. After 10
searches of each, it times 50 searches of the compact index in a row, as bench_search_scale.py
times them (Store.vector_search, 50 results: its "search ms"), with each step on its own clock,
then 50 searches of the exact index:

  rotate  the query cut, scaled and rotated (`_coded`: a 1 x 896 by 896 x 896 product in numpy's BLAS)
  coarse  the scan of every 1-bit code (`_scan`: one FAISS search, of one query)
  fine    the scan's best ranked again by their 4-bit codes (one FAISS range search under a bitmap)
  read    the candidates' rows, read from SQLite (`fetch`)
  score   their exact scores (numpy, no BLAS)
  other   what Store.vector_search does around the index
  search  the whole Store.vector_search
  exact   the exact index's whole search of the same queries, the reference

Each column is a median of its own, so the steps need not add up to `search` exactly. Then it
compares every setting with FAISS and BLAS both on one thread, checks that all of them returned
the same results, and ends with one line that says which pool carries the overhead here, and how
long the run took. Send back everything it prints.

To compare two branches (main and a fix), run the script on each with the same flags: the first
with --keep-indexes, so that the second reuses the indexes in --work. The results' fingerprints
must be equal in the two runs. Later commits may add configurations.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

DIM = 896
VEC_TYPE = "code"
EMBEDDER = f"synthetic:{DIM}"
CENTRES = 2000
NOISE = 0.55  # bench_search_scale.py's: nearest neighbours have a similarity of about 0.75
COMPACT = {"bits": 4, "dim": 0, "rescore": 200}
RESULTS = 50  # results asked of each search, as bench_search_scale.py asks
WARM_UP = 10
BLAS_VARS = ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")
STEPS = ("rotate", "coarse", "fine", "read", "score", "other", "search")
NAMES = {"rotate": "the rotation", "coarse": "the coarse scan", "fine": "the fine ranking", "read": "reading the rows",
         "score": "the exact scores", "other": "the store around the index"}
FORMAT = 1  # of the indexes in --work: an index built by another version of this script is built again


def cpus() -> int:
    """The CPUs this process may run on."""
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:  # macOS, Windows
        return os.cpu_count() or 1


def synthetic(n: int, seed: int) -> np.ndarray:
    """bench_search_scale.py's vectors: n around the same 2,000 centres whatever the seed, so that
    queries (another seed) have neighbours in the index."""
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


# --------------------------------------------------------------------------- the children


def cmd_build(args: argparse.Namespace) -> None:
    """The rows, written as bench_search_scale.py's `build` writes them (an exact index in memory as
    they go, as there); no search index is saved."""
    from codemem.store import Store, VectorRow

    index_dir = Path(args.index)
    if index_dir.exists():
        shutil.rmtree(index_dir)
    store = Store(index_dir, vector_backend="faiss")
    vecs = synthetic(args.n, 0)
    rng = np.random.default_rng(1)
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
    for saved in index_dir.glob("vec_*"):
        saved.unlink()
    print(json.dumps({"chunks": chunk}))


def cmd_prepare(args: argparse.Namespace) -> None:
    """The compact index, built from the rows with every thread and saved; read back if it is saved already."""
    import faiss

    from codemem.store import Store

    faiss.omp_set_num_threads(cpus())  # not timed; safe, as nothing here imports torch
    store = Store(Path(args.index), vector_backend="compact", vector_options=COMPACT)
    store.load_vectors()
    store.save_vectors()
    store.close()
    print(json.dumps({"torch": "torch" in sys.modules}))


def _instrument(cs, faiss) -> tuple[dict[str, float], dict]:
    """Clocks on the steps of a CompactVectorStore's search: its methods are wrapped on the instance,
    so the search runs its own code and each step adds what it took to `spent`."""
    spent: dict[str, float] = {}
    seen: dict = {"faiss_threads_in_search": set(), "index_searches": 0, "coarse_scans": 0}

    def timed(name, fn, before=None):
        def run(*args, **kwargs):
            if before is not None:
                before()
            t = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                spent[name] = spent.get(name, 0.0) + time.perf_counter() - t
        return run

    def at_scan() -> None:  # outside the clock: the OpenMP threads FAISS's scan gets here
        seen["faiss_threads_in_search"].add(faiss.omp_get_max_threads())
        seen["coarse_scans"] += 1

    def at_search() -> None:
        seen["index_searches"] += 1

    cs._coded = timed("rotate", cs._coded)
    cs._scan = timed("coarse", cs._scan, at_scan)
    cs._candidates = timed("candidates", cs._candidates)
    cs._fetch = timed("read", cs._fetch)
    cs.search = timed("index", cs.search, at_search)
    return spent, seen


def _fingerprint(searches: list) -> str:
    """Every hit of every search (chunk, vector and the score's exact bits) in 12 hex digits."""
    h = hashlib.sha1()
    for hits in searches:
        h.update(";".join(f"{x.chunk_id},{x.vector_id},{float(x.score).hex()}" for x in hits).encode() + b"|")
    return h.hexdigest()[:12]


def _per_thread(faiss) -> bool:
    """Whether faiss.omp_set_num_threads changes the calling thread's count only: another thread sets
    another count, and this thread's stays."""
    mine = faiss.omp_get_max_threads()
    other, box = (2 if mine == 1 else 1), {}

    def there() -> None:
        faiss.omp_set_num_threads(other)
        box["there"] = faiss.omp_get_max_threads()

    t = threading.Thread(target=there)
    t.start()
    t.join()
    return box.get("there") == other and faiss.omp_get_max_threads() == mine


def _blas_seen() -> str:
    """numpy's BLAS and its thread count as this process has them, where that can be read."""
    try:
        from threadpoolctl import threadpool_info  # optional, only to show that the setting took

        pools = [p for p in threadpool_info() if p.get("user_api") == "blas"]
        if pools:
            return ", ".join(f"{p.get('internal_api')} {p.get('version') or ''}: {p.get('num_threads')} threads"
                             + (f" ({p['threading_layer']})" if p.get("threading_layer") else "") for p in pools)
    except Exception:  # not installed, or a library it cannot read
        pass
    try:  # Linux without threadpoolctl: ask OpenBLAS itself
        with open("/proc/self/maps", encoding="utf-8") as f:
            paths = sorted({line.split()[-1] for line in f if "openblas" in line.lower() and ".so" in line})
        for path in paths:
            lib = ctypes.CDLL(path)
            for name in ("scipy_openblas_get_num_threads64_", "openblas_get_num_threads64_",
                         "scipy_openblas_get_num_threads", "openblas_get_num_threads"):
                fn = getattr(lib, name, None)
                if fn is not None:
                    return f"OpenBLAS ({os.path.basename(path)}): {fn()} threads"
    except OSError:
        pass
    return "not readable here"


def cmd_time(args: argparse.Namespace) -> None:
    import faiss

    from codemem.store import Store

    faiss.omp_set_num_threads(args.faiss)
    index_dir = Path(args.index)
    t = time.perf_counter()
    compact = Store(index_dir, vector_backend="compact", vector_options=COMPACT)
    compact.load_vectors()
    ti = compact._types[VEC_TYPE]
    from_file = not ti.dirty  # a rebuild from the rows leaves it dirty
    exact = Store(index_dir, vector_backend="faiss")  # built from the rows: the folder's file is the compact one
    exact.load_vectors()
    load_s = time.perf_counter() - t
    queries = synthetic(WARM_UP + args.queries, 7).astype(np.float32)
    for q in queries[:WARM_UP]:
        compact.vector_search(VEC_TYPE, q, RESULTS)
        exact.vector_search(VEC_TYPE, q, RESULTS)
    spent, seen = _instrument(ti.store, faiss)
    ms: dict[str, list[float]] = {name: [] for name in (*STEPS, "exact")}
    found_compact, found_exact = [], []
    for q in queries[WARM_UP:]:  # one after the other, as bench_search_scale.py's `measure` asks them
        spent.clear()
        t = time.perf_counter()
        hits = compact.vector_search(VEC_TYPE, q, RESULTS)
        whole = time.perf_counter() - t
        found_compact.append(hits)
        rotate, coarse, candidates = spent.get("rotate", 0.0), spent.get("coarse", 0.0), spent.get("candidates", 0.0)
        read, index = spent.get("read", 0.0), spent.get("index", 0.0)
        for name, s in (("rotate", rotate), ("coarse", coarse), ("fine", candidates - rotate - coarse), ("read", read),
                        ("score", index - candidates - read), ("other", whole - index), ("search", whole)):
            ms[name].append(s * 1000)
    for q in queries[WARM_UP:]:
        t = time.perf_counter()
        found_exact.append(exact.vector_search(VEC_TYPE, q, RESULTS))
        ms["exact"].append((time.perf_counter() - t) * 1000)
    print(json.dumps({
        "faiss_threads": faiss.omp_get_max_threads(), "faiss_threads_in_search": sorted(seen["faiss_threads_in_search"]),
        "index_searches_per_search": seen["index_searches"] / args.queries,
        "coarse_scans_per_search": seen["coarse_scans"] / args.queries,
        "ms": {name: round(float(np.median(v)), 3) for name, v in ms.items()},
        "p90_search_ms": round(float(np.percentile(ms["search"], 90)), 3),
        "compact_from_file": from_file, "load_s": round(load_s, 2), "vectors": len(ti.store),
        "fingerprint": _fingerprint(found_compact), "exact_fingerprint": _fingerprint(found_exact),
        "top10_as_exact": round(float(np.mean([{h.chunk_id for h in a[:10]} == {h.chunk_id for h in b[:10]}
                                               for a, b in zip(found_compact, found_exact)])), 3),
        "per_thread": _per_thread(faiss), "blas": _blas_seen(), "torch": "torch" in sys.modules,
    }))
    compact.close()
    exact.close()


# --------------------------------------------------------------------------- the parent


def _child(env: dict, *argv: object) -> dict:
    out = subprocess.run([sys.executable, os.path.abspath(__file__), *map(str, argv)], env=env, capture_output=True,
                         text=True)
    if out.returncode:
        raise RuntimeError(f"{argv[0]} failed with status {out.returncode}:\n{out.stderr[-3000:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def _env(faiss_threads: int | None = None, blas_threads: int | None = None) -> dict:
    """This process's environment, with the thread counts of one child (None: as it is)."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    if blas_threads is not None:
        env.update(dict.fromkeys(BLAS_VARS, str(blas_threads)))
    if faiss_threads is not None:
        env["OMP_NUM_THREADS"] = str(faiss_threads)
    return env


def _cpu_name() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    try:
        return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return platform.processor()


def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", os.path.dirname(os.path.abspath(__file__)), *args], capture_output=True,
                             text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else "?"
    except (OSError, subprocess.SubprocessError):
        return "?"


def _label(f: int, b: int) -> str:
    return f"FAISS {f}, BLAS {b}"


def _verdict(results: dict, sizes: list[int], faiss_counts: list[int], blas_counts: list[int]) -> str:
    """One line, in plain words: which pool makes a compact search slower on many threads here."""
    F, B = max(faiss_counts), max(blas_counts)
    if 1 not in faiss_counts or 1 not in blas_counts or F == 1 or B == 1:
        return "=> no verdict: it needs 1 and several threads of each pool (--faiss-threads 1,all --blas-threads 1,all)"
    sizes = [n for n in sizes if all((n, f, b) in results for f, b in ((1, 1), (F, 1), (1, B), (F, B)))]
    if not sizes:
        return "=> no verdict: no size was timed in all four settings"

    def extra(n: int, f: int, b: int, step: str = "search") -> float:
        return results[(n, f, b)]["ms"][step] - results[(n, 1, 1)]["ms"][step]

    def big(f: int, b: int) -> bool:  # more than noise at some size: 2 ms, and 15% of the search on one thread
        return any(extra(n, f, b) > max(2.0, 0.15 * results[(n, 1, 1)]["ms"]["search"]) for n in sizes)

    def at(f: int, b: int) -> str:
        return " and ".join(f"{extra(n, f, b):+.1f} ms at {n:,} vectors" for n in sizes)

    def where(f: int, b: int) -> str:
        grown = sorted(((np.mean([extra(n, f, b, s) for n in sizes]), s) for s in STEPS[:-1]), reverse=True)
        named = [f"{NAMES[s]} ({g:+.1f} ms)" for g, s in grown[:2] if g > 1.0]
        return "mostly in " + " and ".join(named) if named else "spread over the steps"

    faiss_alone, blas_alone, both = big(F, 1), big(1, B), big(F, B)
    pools = f"FAISS on {F} threads instead of 1 (BLAS on 1)", f"numpy's BLAS on {B} threads instead of 1 (FAISS on 1)"
    if faiss_alone and not blas_alone:
        return (f"=> On this machine FAISS's OpenMP threads carry the overhead: with {pools[0]} a compact search takes "
                f"{at(F, 1)}, {where(F, 1)}; with {pools[1]} {at(1, B)}; with both on all threads {at(F, B)}.")
    if blas_alone and not faiss_alone:
        return (f"=> On this machine numpy's BLAS threads carry the overhead: with {pools[1]} a compact search takes "
                f"{at(1, B)}, {where(1, B)}; with {pools[0]} {at(F, 1)}; with both on all threads {at(F, B)}.")
    if faiss_alone and blas_alone:
        return (f"=> On this machine each pool adds its own overhead: with {pools[0]} a compact search takes {at(F, 1)}, "
                f"{where(F, 1)}; with {pools[1]} {at(1, B)}, {where(1, B)}; with both {at(F, B)}.")
    if both:
        return (f"=> On this machine neither pool alone carries the overhead, the two together do: with both on all "
                f"threads a compact search takes {at(F, B)}, {where(F, B)}, while {pools[0]} takes {at(F, 1)} and "
                f"{pools[1]} {at(1, B)}.")
    return (f"=> On this machine neither pool makes a compact search slower: with FAISS on {F} and BLAS on {B} threads "
            f"it takes {at(F, B)} against both on 1 (FAISS alone {at(F, 1)}, BLAS alone {at(1, B)}).")


def run(args: argparse.Namespace) -> None:
    import faiss

    import codemem

    started = time.monotonic()
    n_cpu = cpus()

    def counts(text: str) -> list[int]:
        return sorted({n_cpu if t.strip() == "all" else int(t) for t in text.split(",")})

    faiss_counts, blas_counts = counts(args.faiss_threads), counts(args.blas_threads)
    sizes = [int(s) for s in args.sizes.split(",")]
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    blas = np.show_config(mode="dicts")["Build Dependencies"]["blas"]
    print(f"codemem {codemem.__version__} at {os.path.dirname(codemem.__file__)} (git {_git('rev-parse', '--short', 'HEAD')} "
          f"on {_git('rev-parse', '--abbrev-ref', 'HEAD')}) | FAISS {faiss.__version__} | numpy {np.__version__}, BLAS "
          f"{blas.get('name')} {blas.get('version')} ({blas.get('openblas configuration')}) | {platform.platform()} "
          f"{platform.machine()} | {_cpu_name()} | {n_cpu} CPUs | Python {platform.python_version()}", flush=True)
    print(f"Each timing child gets {', '.join(BLAS_VARS)} = the BLAS threads and OMP_NUM_THREADS = the FAISS threads in "
          f"its environment, then calls faiss.omp_set_num_threads(FAISS threads) after its imports. This shell has "
          + ", ".join(f"{k}={os.environ.get(k, 'unset')}" for k in ("OMP_NUM_THREADS", *BLAS_VARS)) + ".", flush=True)
    results: dict[tuple[int, int, int], dict] = {}
    built_s = 0.0
    for n in sizes:
        index = work / f"n{n}"
        t = time.monotonic()
        made = index / "made-by-time_compact_search.json"
        try:
            reuse = json.loads(made.read_text("utf-8")) == {"format": FORMAT, "n": n}
        except (OSError, ValueError):
            reuse = False
        if not reuse:
            free = shutil.disk_usage(work).free
            if free < n * 4000:
                print(f"{n:,} vectors skipped: {work} has {free / 1e9:.1f} GB free and this needs about {n * 4000 / 1e9:.1f} GB")
                continue
            _child(_env(), "build", "--index", index, "--n", n)
        _child(_env(), "prepare", "--index", index)  # reads the saved compact index back when it is current
        made.write_text(json.dumps({"format": FORMAT, "n": n}), "utf-8")
        built_s += time.monotonic() - t
        print(f"{n:,} vectors: {'reused' if reuse else 'built'} in {time.monotonic() - t:.0f} s; timing "
              f"{len(faiss_counts) * len(blas_counts)} settings", flush=True)
        for f in faiss_counts:
            for b in blas_counts:
                results[(n, f, b)] = r = _child(_env(f, b), "time", "--index", index, "--faiss", f, "--queries", args.queries)
                if r["torch"]:
                    print("torch was loaded in a timing child: several OpenMP threads are not safe there on macOS")
        if not args.keep_indexes:
            shutil.rmtree(index, ignore_errors=True)

    for f in faiss_counts:
        for b in blas_counts:
            rows = [(n, results[(n, f, b)]) for n in sizes if (n, f, b) in results]
            if not rows:
                continue
            first = rows[0][1]
            print(f"\n== FAISS on {f} thread{'s' * (f > 1)}, numpy's BLAS on {b} thread{'s' * (b > 1)} == "
                  f"(OMP_NUM_THREADS={f}, {'='.join(BLAS_VARS)}={b}; BLAS as the child sees it: {first['blas']})")
            print(f"{'vectors':>9} " + " ".join(f"{s:>7}" for s in STEPS) + f" | {'exact':>7}   ms, medians of {args.queries}")
            for n, r in rows:
                notes = [] if r["compact_from_file"] else ["compact index rebuilt from the rows"]
                if r["index_searches_per_search"] > 1.05 or r["coarse_scans_per_search"] > 1.05:
                    notes.append(f"{r['index_searches_per_search']:.2f} index searches and {r['coarse_scans_per_search']:.2f} "
                                 "coarse scans per search")
                print(f"{n:>9,} " + " ".join(f"{r['ms'][s]:>7.2f}" for s in STEPS) + f" | {r['ms']['exact']:>7.2f}"
                      + (f"   ({'; '.join(notes)})" if notes else ""))
            inside = sorted({t for _, r in rows for t in r["faiss_threads_in_search"]})
            print(f"FAISS's threads inside a compact search: {', '.join(map(str, inside))}"
                  + ("" if inside == [f] else f" (the store runs its per-query FAISS calls on {inside[0]}, of {f})"))

    if (1, 1) in {(f, b) for _, f, b in results}:
        print(f"\n== a compact search, ms more than with FAISS and BLAS both on 1 thread (the exact search's in brackets) ==")
        others = [(f, b) for f in faiss_counts for b in blas_counts if (f, b) != (1, 1)]
        print(f"{'vectors':>9} " + " ".join(f"{_label(f, b):>20}" for f, b in others))
        for n in sizes:
            if (n, 1, 1) not in results:
                continue
            base = results[(n, 1, 1)]["ms"]
            cells = []
            for f, b in others:
                r = results.get((n, f, b))
                cells.append("" if r is None else f"{r['ms']['search'] - base['search']:+.1f} ({r['ms']['exact'] - base['exact']:+.1f})")
            print(f"{n:>9,} " + " ".join(f"{c:>20}" for c in cells))
    prints = {r["fingerprint"] for r in results.values()}
    exact_prints = {r["exact_fingerprint"] for r in results.values()}
    by_size = {n: {r["fingerprint"] for (m, _, _), r in results.items() if m == n} for n in sizes}
    same = all(len(v) <= 1 for v in by_size.values())
    print(f"\nresults: every setting returned {'the same' if same else 'DIFFERENT'} hits (ids and scores, {args.queries} "
          f"searches of {RESULTS} per size; compact {', '.join(f'{n:,}: ' + '/'.join(sorted(v)) for n, v in by_size.items() if v)}"
          f"; exact {len(exact_prints)} fingerprint{'s' * (len(exact_prints) > 1)}). Compare them between two branches: "
          f"a fix must not change them.")
    per_thread = {r["per_thread"] for r in results.values()}
    print(f"faiss.omp_set_num_threads changes the calling thread's count only, on this machine: "
          f"{'yes' if per_thread == {True} else 'NO' if per_thread == {False} else 'not in every child'}")
    print(_verdict(results, sizes, faiss_counts, blas_counts))
    took = time.monotonic() - started
    print(f"took {took // 60:.0f} min {took % 60:.0f} s ({built_s:.0f} s building or reading the indexes)")
    del prints


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--work", help="a folder with free disk for the indexes (about 2.5 GB per million vectors)")
    p.add_argument("--sizes", default="100000,500000")
    p.add_argument("--faiss-threads", default="1,all")
    p.add_argument("--blas-threads", default="1,all")
    p.add_argument("--queries", type=int, default=50)
    p.add_argument("--keep-indexes", action="store_true")
    sub = p.add_subparsers(dest="cmd")  # the steps `run` starts, each in a process of its own
    for name, fn in (("build", cmd_build), ("prepare", cmd_prepare), ("time", cmd_time)):
        s = sub.add_parser(name)
        s.add_argument("--index", required=True)
        s.add_argument("--n", type=int, default=0)
        s.add_argument("--faiss", type=int, default=1)
        s.add_argument("--queries", type=int, default=50)
        s.set_defaults(fn=fn)
    args = p.parse_args()
    if args.cmd:
        args.fn(args)
    elif not args.work:
        p.error("--work is required")
    else:
        run(args)


if __name__ == "__main__":
    main()
