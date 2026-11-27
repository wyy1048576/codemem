"""Which thread pool makes codemem's compact search slower on many cores than on one, step by
step, on this machine; and whether a candidate fix removes it.

    uv run python scripts/time_compact_search.py --work <a folder with free disk>

WHAT IS MEASURED. codemem has two vector indexes. The exact one (FaissVectorStore in
src/codemem/store.py) holds every vector in 2-byte numbers and answers a query with one FAISS
search. The compact one (CompactVectorStore) holds RaBitQ codes in FAISS and reads the full
vectors back from SQLite. One search of the compact index, for one query, goes through these
steps; each is a column of the tables:

  rotate  the query cut, scaled to length 1 and rotated: a (1 x 896) by (896 x 896) float32
          product, `rows @ rotation` in `_coded`, which numpy hands to its BLAS (OpenBLAS on
          Linux runs a product of this size on all of its threads)
  coarse  FAISS scans every vector's 1-bit code for the query (`_scan`: IndexRaBitQ.search of one
          query; the best 4,000 at 100,000 vectors, 10,000 at 500,000)
  fine    those are ranked again by their 4-bit codes (in `_candidates`: IndexRaBitQ.range_search
          of the one query under a bitmap that selects them; numpy keeps the best 256)
  read    the 256 candidates' full vectors read from SQLite (`fetch`)
  score   numpy scores them exactly (an elementwise product and a row sum, no BLAS) and sorts
  other   what Store.vector_search does around the index (a lock, a read of the epoch, bookkeeping)
  search  the whole Store.vector_search(type, query, 50): what bench_search_scale.py reports as
          "search ms", the number that was 34 to 58 ms slower on 16 cores than on one
  exact   the exact index's whole search of the same queries: the reference (one FAISS call that
          opens a parallel region too; it was as fast on 16 cores as on one)

A clock is wrapped around each of the store's own methods, on the instance, so the search runs
its own code. A cell is the median of 50 searches with the 10th and 90th percentiles under it: a
cost of waking threads shows as spread. Each cell is a median of its own, so the steps need not
add up to `search`. Before it times them, a child asks its 50 queries once untimed: the rows they
read are then in the operating system's page cache in every configuration. (Without that, the
first child to read an index whose pages were pushed out of memory pays reads from the disk in
`read`, whatever its threads: on a Mac short of memory that looked like a 15 to 25 ms overhead of
one thread setting or another, depending only on which child ran first. Configuration i measures
that cost on purpose.)

THE CONFIGURATIONS, each in a child process of its own that never imports torch (several OpenMP
threads are safe in it, on macOS too). "All" is every CPU this process may use (--threads):

  a  both pools on all cores: the fault as measured
  b  numpy's BLAS on 1 thread, FAISS on all: tests the rotation's product
  c  FAISS on 1 thread, numpy's BLAS on all: tests FAISS's parallel regions (one per query and call)
  d  both pools on 1 thread: the reference
  e  as a, with OpenMP's waiting threads passive (OMP_WAIT_POLICY=passive, and GOMP_SPINCOUNT=0
     for GNU OpenMP, KMP_BLOCKTIME=0 for LLVM's or Intel's): tests FAISS's threads that keep
     spinning after a region, holding cores that another pool's threads need
  f  as a, with OpenBLAS's waiting threads passive (OPENBLAS_THREAD_TIMEOUT=4: they sleep after
     2^4 cycles instead of 2^28): tests OpenBLAS's threads that keep spinning after the rotation
     while FAISS works. Run only where numpy's BLAS is OpenBLAS
  g  as a, with candidate fix (ii) applied inside the child, the store's code untouched: the
     compact search's FAISS calls on one OpenMP thread (faiss.omp_set_num_threads(1) around
     `_candidates`, the count put back after; the count is each thread's own)
  h  as a, with candidate fix (i) applied inside the child: the one query row rotated by numpy's
     own loop (np.einsum) instead of the BLAS; a batch of rows (a build) keeps the BLAS
  i  as a, with 50 other queries, each asked for the first time and timed then: their rows come
     from the disk unless the operating system keeps the whole index file in memory. Tests reads
     from the disk, not threads
  j  as d, with 50 more other queries asked for the first time: reads from the disk on one
     thread, to set against i (the hits of i and j are not compared with the others': other queries)
  k  as a, run again after all the others: a thread setting slows both a and k; a page pushed out
     of memory during one child slows that child only

How a pool is set: numpy's BLAS by OPENBLAS_NUM_THREADS, MKL_NUM_THREADS and
VECLIB_MAXIMUM_THREADS (OpenBLAS, MKL, Apple's Accelerate) in the child's environment, so before
numpy is imported. FAISS by OMP_NUM_THREADS there (OpenBLAS reads that one only when
OPENBLAS_NUM_THREADS is unset) and by faiss.omp_set_num_threads after the imports (on macOS,
importing codemem sets OMP_NUM_THREADS to 1). The variables above are taken out of every child's
environment first, so the shell's own settings change nothing. Each table prints the variables its
child was given and what the libraries report from inside it: faiss.omp_get_max_threads(), the
same read inside a compact search, and numpy's BLAS through threadpoolctl when that is importable.
The header names the OpenMP library FAISS loads.

The exact index is searched in a and d only (in the others its column shows "-").

AFTER THE TABLES: what each configuration adds to a search against d; whether every
configuration returned the same hits (ids and scores) for each query, with a fingerprint per size
to compare with another run; the time to build the compact index from the rows on all cores (a)
and on one (d), at the smallest size (--build-sizes), so that a fix that slows builds shows; and a
closing block in plain words, with a verdict of three: threads (which pool, shown by which
configurations, and which fix applies), the disk (the read step is slow only when the rows were
not asked before, whatever the thread count), or neither on this machine; and how long the run
took. bench_search_scale.py times each query the first time it is asked, so its "search ms"
includes reads from the disk wherever the index file is not all in memory: read its numbers
against the disk line as well.


THE INDEXES are built as scripts/bench_search_scale.py builds them (the same synthetic vectors: 896
numbers, around 2,000 centres, 1.25 vectors per chunk), and the compact search index (4 bits,
rescore 200) is saved once. About 2.5 GB of disk per million vectors, in --work, which should be
on a local disk (under WSL: not under /mnt/c). About 2.5 minutes on an 8-core M1 at the default
sizes; the PC's searches were about 3 times slower than the M1's, so about 5 there (the run is
mostly one thread's work), a quarter of it building the indexes, which --keep-indexes saves.

TO COMPARE TWO BRANCHES (main, and a fix in src/), run the script on each with the same flags,
the first with --keep-indexes so that the second reuses the indexes. On the fix branch,
configuration a is the fix as it would ship; its fingerprints must equal main's. Later commits
may add configurations.

Options: --sizes (default 100000,500000), --configs (default abcdefghijk), --threads (what "all"
means; default every CPU), --queries (default 50), --build-sizes (default the smallest size;
"none" skips it), --keep-indexes. It needs numpy, faiss and codemem only.
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
WAIT_VARS = ("OMP_WAIT_POLICY", "GOMP_SPINCOUNT", "KMP_BLOCKTIME", "OPENBLAS_THREAD_TIMEOUT")
STEPS = ("rotate", "coarse", "fine", "read", "score", "other", "search")
NAMES = {"rotate": "the rotation", "coarse": "the coarse scan", "fine": "the fine ranking", "read": "reading the rows",
         "score": "the exact scores", "other": "the store around the index"}
SLOWER_SHARE = 0.15  # more than this share slower counts: run to run, a median of 50 searches moves a few percent
SLOWER_MS = 2.0  # and more than this many ms: at small sizes a few percent is a fraction of a millisecond
FORMAT = 1  # of the indexes in --work: an index built by another version of this script is built again
# key: (FAISS threads, BLAS threads, waiting threads made passive, fix tried, what it is, what it tests)
CONFIGS = {
    "a": ("all", "all", None, None, "both pools on all cores", "the fault as measured"),
    "b": ("all", 1, None, None, "BLAS on 1 thread, FAISS on all", "the rotation's product in numpy's BLAS"),
    "c": (1, "all", None, None, "FAISS on 1 thread, BLAS on all", "FAISS's parallel regions, one per query"),
    "d": (1, 1, None, None, "both pools on 1 thread", "the reference"),
    "e": ("all", "all", "openmp", None, "as a, OpenMP's waiting threads passive",
          "FAISS's threads that spin after a region"),
    "f": ("all", "all", "openblas", None, "as a, OpenBLAS's waiting threads passive",
          "OpenBLAS's threads that spin after the rotation"),
    "g": ("all", "all", None, "faiss-one-thread", "as a, trying fix (ii): FAISS calls on 1 thread",
          "fix (ii) without editing the store"),
    "h": ("all", "all", None, "rotation-numpy", "as a, trying fix (i): the query rotated without BLAS",
          "fix (i) without editing the store"),
    "i": ("all", "all", None, None, "as a, 50 other queries asked for the first time",
          "reads from the disk instead of the page cache"),
    "j": (1, 1, None, None, "as d, 50 more other queries asked for the first time", "reads from the disk on one thread"),
    "k": ("all", "all", None, None, "as a, run again after all the others", "whether a's numbers repeat"),
}
COLD = {"i": 11, "j": 17}  # the seeds of the queries asked for the first time
SAME_QUERIES = "abcdefghk"  # the configurations that ask the same queries: their hits must be equal
FIXES = {"ii": "(ii) the compact search's FAISS calls on one OpenMP thread",
         "i": "(i) the query row rotated without the BLAS"}


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


def openmp_libraries() -> list[str]:
    """The OpenMP runtimes loaded in this process: FAISS's (numpy's OpenBLAS runs on pthreads)."""
    names: list[str] = []
    try:
        with open("/proc/self/maps", encoding="utf-8") as f:
            names = [line.split()[-1] for line in f if "/" in line]
    except OSError:
        if sys.platform == "darwin":
            try:
                dyld = ctypes.CDLL(None)
                dyld._dyld_image_count.restype = ctypes.c_uint32
                dyld._dyld_get_image_name.restype = ctypes.c_char_p
                dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
                names = [dyld._dyld_get_image_name(i).decode() for i in range(dyld._dyld_image_count())]
            except (OSError, AttributeError):
                pass
    return sorted({os.path.basename(n) for n in names
                   if any(k in os.path.basename(n).lower() for k in ("gomp", "libomp", "iomp", "vcomp"))})


def openmp_kind(libraries: list[str]) -> str:
    text = " ".join(libraries).lower()
    for key, kind in (("gomp", "GNU"), ("iomp", "Intel"), ("libomp", "LLVM"), ("vcomp", "MSVC")):
        if key in text:
            return kind
    return "unknown"


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


def _try(cs, name: str, faiss) -> None:
    """A candidate fix, applied to this one index in this process: the store's code is not edited."""
    if name == "faiss-one-thread":  # (ii)
        candidates = cs._candidates

        def one_thread(*args, **kwargs):
            before = faiss.omp_get_max_threads()
            faiss.omp_set_num_threads(1)
            try:
                return candidates(*args, **kwargs)
            finally:
                faiss.omp_set_num_threads(before)

        cs._candidates = one_thread
    elif name == "rotation-numpy":  # (i)
        from codemem.store import prepare

        coded = cs._coded

        def numpy_rotation(vecs, *args, **kwargs):
            rows = np.asarray(vecs, dtype=np.float32)
            if rows.ndim == 2 and len(rows) > 1:  # a batch (a build): the BLAS, as before
                return coded(vecs, *args, **kwargs)
            with np.errstate(invalid="ignore"):
                rows = prepare(rows, cs.code_dim)
            rows[~np.isfinite(rows).all(axis=1)] = 0.0
            return np.einsum("ij,jk->ik", rows, cs._rotation)  # numpy's own loop, one thread

        cs._coded = numpy_rotation
    else:
        raise ValueError(f"no candidate fix called {name}")


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


def _hits_hash(hits) -> str:
    """One search's hits (chunk, vector and the score's exact bits) in 12 hex digits."""
    text = ";".join(f"{x.chunk_id},{x.vector_id},{float(x.score).hex()}" for x in hits)
    return hashlib.sha1(text.encode()).hexdigest()[:12]


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
    """numpy's BLAS and its threads as threadpoolctl reads them from inside this process."""
    try:
        from threadpoolctl import threadpool_info
    except ImportError:
        return "threadpoolctl is not importable here: see the variables given"
    pools = [p for p in threadpool_info() if p.get("user_api") == "blas"]
    if not pools:
        return "threadpoolctl reads no BLAS here (it cannot read Accelerate): see the variables given"
    return ", ".join(f"{p.get('internal_api')} {p.get('version') or ''}: {p.get('num_threads')} threads"
                     + (f" ({p['threading_layer']})" if p.get("threading_layer") else "") for p in pools)


def _spread(values: list[float]) -> dict[str, float]:
    return {k: round(float(np.percentile(values, p)), 3) for k, p in (("p10", 10), ("p50", 50), ("p90", 90))}


def cmd_time(args: argparse.Namespace) -> None:
    import faiss

    from codemem.store import Store

    faiss.omp_set_num_threads(args.faiss)
    index_dir = Path(args.index)
    compact = Store(index_dir, vector_backend="compact", vector_options=COMPACT)
    compact.load_vectors()
    ti = compact._types[VEC_TYPE]
    from_file = not ti.dirty  # a rebuild from the rows leaves it dirty
    if args.try_fix:
        _try(ti.store, args.try_fix, faiss)
    if args.cold:  # other queries, asked for the first time when they are timed; 10 more warm the threads up
        queries = synthetic(args.queries, args.cold).astype(np.float32)
        warm_up = synthetic(WARM_UP, args.cold + 1).astype(np.float32)
    else:  # each query asked once before it is timed: the rows it reads are in the page cache
        queries = warm_up = synthetic(args.queries, 7).astype(np.float32)
    for q in warm_up:
        compact.vector_search(VEC_TYPE, q, RESULTS)
    spent, seen = _instrument(ti.store, faiss)
    ms: dict[str, list[float]] = {name: [] for name in STEPS}
    found = []
    for q in queries:  # one after the other, as bench_search_scale.py's `measure` asks them
        spent.clear()
        t = time.perf_counter()
        hits = compact.vector_search(VEC_TYPE, q, RESULTS)
        whole = time.perf_counter() - t
        found.append(_hits_hash(hits))
        rotate, coarse, candidates = spent.get("rotate", 0.0), spent.get("coarse", 0.0), spent.get("candidates", 0.0)
        read, index = spent.get("read", 0.0), spent.get("index", 0.0)
        for name, s in (("rotate", rotate), ("coarse", coarse), ("fine", candidates - rotate - coarse), ("read", read),
                        ("score", index - candidates - read), ("other", whole - index), ("search", whole)):
            ms[name].append(s * 1000)
    out = {"ms": {name: _spread(v) for name, v in ms.items()}, "hits": found, "compact_from_file": from_file,
           "faiss_threads": faiss.omp_get_max_threads(), "faiss_threads_in_search": sorted(seen["faiss_threads_in_search"]),
           "index_searches_per_search": seen["index_searches"] / args.queries,
           "coarse_scans_per_search": seen["coarse_scans"] / args.queries}
    if args.exact:
        exact = Store(index_dir, vector_backend="faiss")  # built from the rows: the folder's file is the compact one
        exact.load_vectors()
        for q in queries[:WARM_UP]:
            exact.vector_search(VEC_TYPE, q, RESULTS)
        took, exact_found = [], []
        for q in queries:
            t = time.perf_counter()
            exact_found.append(_hits_hash(exact.vector_search(VEC_TYPE, q, RESULTS)))
            took.append((time.perf_counter() - t) * 1000)
        out["ms"]["exact"] = _spread(took)
        out["exact_hits"] = exact_found
        exact.close()
    compact.close()
    if args.build:  # the compact index from the rows, as a start without its file builds it; kept nowhere
        store = Store(index_dir, vector_backend="compact", vector_options=COMPACT)
        t = time.perf_counter()
        store._rebuild(VEC_TYPE, store._epoch(VEC_TYPE), store.vector_dim(VEC_TYPE))
        out["build_s"] = round(time.perf_counter() - t, 2)
        store.close()
    out.update(per_thread=_per_thread(faiss), blas=_blas_seen(), openmp=openmp_libraries(), torch="torch" in sys.modules)
    print(json.dumps(out))


# --------------------------------------------------------------------------- the parent


def _child(env: dict, *argv: object) -> dict:
    out = subprocess.run([sys.executable, os.path.abspath(__file__), *map(str, argv)], env=env, capture_output=True,
                         text=True)
    if out.returncode:
        raise RuntimeError(f"{argv[0]} failed with status {out.returncode}:\n{out.stderr[-3000:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def _env(given: dict[str, str] | None = None) -> dict:
    """This process's environment for a child: as it is (None), or without any thread variable but `given`."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    if given is not None:
        for name in ("OMP_NUM_THREADS", *BLAS_VARS, *WAIT_VARS):
            env.pop(name, None)
        env.update(given)
    return env


def _given(key: str, n_all: int, omp: str) -> dict[str, str]:
    """The variables configuration `key` sets."""
    faiss_threads, blas_threads, wait = CONFIGS[key][:3]
    f = n_all if faiss_threads == "all" else faiss_threads
    b = n_all if blas_threads == "all" else blas_threads
    given = {"OMP_NUM_THREADS": str(f), **dict.fromkeys(BLAS_VARS, str(b))}
    if wait == "openmp":
        given["OMP_WAIT_POLICY"] = "passive"
        if omp == "GNU":
            given["GOMP_SPINCOUNT"] = "0"
        elif omp in ("LLVM", "Intel"):
            given["KMP_BLOCKTIME"] = "0"
    elif wait == "openblas":
        given["OPENBLAS_THREAD_TIMEOUT"] = "4"
    return given


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


def _same_results(results: dict, sizes: list[int], keys: list[str], field: str) -> list[str]:
    """Per size: whether every configuration returned the same hits for each query."""
    lines = []
    for n in sizes:
        runs = {k: results[(n, k)][field] for k in keys if (n, k) in results and field in results[(n, k)]}
        if not runs:
            continue
        first = next(iter(runs.values()))
        same = sum(len({run[i] for run in runs.values()}) == 1 for i in range(len(first)))
        ref = "a" if "a" in runs else next(iter(runs))
        differ = [f"{k} differs from {ref} in {sum(x != y for x, y in zip(run, runs[ref]))}" for k, run in runs.items()
                  if run != runs[ref]]
        whole = hashlib.sha1("".join(runs[ref]).encode()).hexdigest()[:12]
        lines.append(f"{n:,} vectors: {'yes' if same == len(first) else 'NO'}, {same} of {len(first)} queries, in "
                     f"{', '.join(runs)}" + (f" ({'; '.join(differ)})" if differ else "") + f"; fingerprint of {ref}: {whole}")
    return lines


def _closing(results: dict, sizes: list[int], n_all: int) -> list[str]:
    """The closing block, in plain words: threads (which pool, by which configurations, which fix),
    the disk (a first read of rows), or neither."""
    def have(key: str) -> bool:
        return all((n, key) in results for n in sizes)

    if not sizes or not (have("a") and have("d")):
        return ["=> no verdict: it needs configurations a and d at every size"]

    def med(key: str, n: int, step: str = "search") -> float:
        return results[(n, key)]["ms"][step]["p50"]

    def extra(key: str, n: int, step: str = "search", base: str = "d") -> float:
        return med(key, n, step) - med(base, n, step)

    def at(key: str, base: str = "d") -> str:
        return " and ".join(f"{extra(key, n, base=base):+.1f} ms at {n:,}" for n in sizes)

    def slower(key: str, n: int, base: str = "d") -> bool:
        x = extra(key, n, base=base)
        return x > SLOWER_MS and x > SLOWER_SHARE * med(base, n)

    def steps_of(key: str, base: str = "d") -> tuple[str, str | None]:
        grown = sorted(((float(np.mean([extra(key, n, s, base) for n in sizes])), s) for s in STEPS[:-1]), reverse=True)
        big = max(1.0, 0.1 * float(np.mean([extra(key, n, base=base) for n in sizes])))
        named = [f"{NAMES[s]} ({g:+.1f} ms)" for g, s in grown if g > big][:3]
        return (", ".join(named) if named else "no one step (it is spread over all of them)"), (grown[0][1] if named else None)

    lines: list[str] = []
    exact = (" and ".join(f"{extra('a', n, 'exact'):+.1f} ms" for n in sizes)
             if all("exact" in results[(n, k)]["ms"] for n in sizes for k in "ad") else "not run")
    slow_a = [n for n in sizes if slower("a", n)]
    slow_k = [n for n in sizes if have("k") and slower("k", n)]
    again = f" and again after all the others (k) {at('k')}" if have("k") else ""
    threads, unsettled = "", ""
    if not slow_a and not slow_k:
        lines.append(f"THREADS: no. On all {n_all} cores (a) a compact search takes {at('a')} vectors against one core "
                     f"each (d){again}; the exact search {exact}.")
    elif have("k") and slow_a != slow_k:
        one_off = "a" if len(slow_a) > len(slow_k) else "k"
        where, _ = steps_of(one_off)
        lines.append(f"THREADS: not shown. Of the two runs on all {n_all} cores only {one_off} was slower than one core "
                     f"each (d): a {at('a')}, k {at('k')}, in {where}. A thread setting slows both; a change of one run "
                     "is what a page pushed out of memory during it does. Run the script again to be sure.")
        unsettled = f"only one of two runs on all cores ({one_off}) was slower than one core: run the script again"
    else:
        where, top = steps_of("a")
        lines.append(f"THREADS: yes. On all {n_all} cores (a) a compact search takes {at('a')} vectors more than on one "
                     f"core each (d){again}; the exact search {exact}.")
        lines.append(f"  It sits in {where}, against d, as a mean over the sizes."
                     + (f" {NAMES[top].capitalize()} runs no thread of its own: it waits, for cores that other threads "
                        "hold or for the disk (the DISK line tells which)." if top in ("read", "score", "other") else ""))
        fault = {n: extra("a", n) for n in sizes}
        verdicts: dict[str, str] = {}
        for key in "bcefgh":
            if not have(key):
                continue
            if all(extra(key, n) <= max(SLOWER_MS, 0.25 * fault[n]) for n in sizes):
                verdicts[key] = "gone"
            elif all(extra(key, n) <= 0.75 * fault[n] for n in sizes):
                verdicts[key] = "partly"
            else:
                verdicts[key] = "stays"

        def listed(kind: str) -> str:
            return "; ".join(f"{k}, {CONFIGS[k][4]} ({at(k)})" for k, v in verdicts.items() if v == kind) or "none"

        lines.append(f"  It disappears in: {listed('gone')}.")
        lines.append(f"  It shrinks to between a quarter and three quarters in: {listed('partly')}.")
        lines.append(f"  It stays in: {listed('stays')}.")
        gone = {k for k, v in verdicts.items() if v == "gone"}
        if "c" in gone and "b" not in gone:
            cause, detail, fix = "FAISS's OpenMP threads", "a parallel region for each FAISS call of one query", "ii"
        elif "b" in gone and "c" not in gone:
            cause, detail, fix = "numpy's BLAS threads", "the rotation's product", "i"
        elif "b" in gone and "c" in gone:
            cause, detail, fix = "the two pools together", "either one on 1 thread removes it", None
        else:
            cause, detail, fix = "neither pool's thread count alone", "see e and f: threads that spin", None
        notes = [f"{CONFIGS[k][4][6:]} removes it as well: {who}'s threads spin and hold cores"
                 for k, who in (("e", "FAISS"), ("f", "OpenBLAS")) if k in gone]
        tried = {"g": "ii", "h": "i"}
        if fix is None:
            fix = next((tried[k] for k in "gh" if verdicts.get(k) == "gone"), None)
        lines.append(f"  So it comes from {cause} ({detail})." + (f" {'; '.join(notes)}." if notes else ""))
        measured = [f"fix {FIXES[tried[k]]} leaves {at(k)} ({k}: {verdicts[k]})" for k in "gh" if k in verdicts]
        if measured:
            lines.append(f"  Measured here: {'; '.join(measured)}.")
        passive = [f"making {CONFIGS[k][4][6:]} ({k}, a setting of the whole process)" for k in "ef" if k in gone]
        instead = "neither candidate removes it; " + (" or ".join(passive) + " does" if passive else "look at e and f")
        lines.append(f"  The fix that applies: {FIXES[fix] if fix else instead}"
                     + (". It must also leave the hits the same and the build time as it was (both above)." if fix else "."))
        threads = f"threads: {cause}, in {where}; " + (f"fix {FIXES[fix]} applies" if fix else instead)
    disk = ""
    if have("i"):
        # against the faster of the two warm runs on all cores, so that a one-off slow run of a hides nothing
        warm = {n: min(("a", "k") if have("k") else ("a",), key=lambda key: med(key, n)) for n in sizes}
        cold_all = {n: med("i", n) - med(warm[n], n) for n in sizes}
        cold = [n for n in sizes if (cold_all[n] > SLOWER_MS and cold_all[n] > SLOWER_SHARE * med(warm[n], n))
                or (have("j") and slower("j", n, base="d"))]
        one = f", and on one thread (j against d) {at('j')}" if have("j") else ""
        on_all = " and ".join(f"{cold_all[n]:+.1f} ms at {n:,}" for n in sizes)
        read = " and ".join(f"{med('i', n, 'read') - med(warm[n], n, 'read'):+.1f} ms" for n in sizes)
        if cold:
            lines.append(f"DISK: yes. Queries asked for the first time take, on all cores (i against a), {on_all}{one}; "
                         f"in reading the rows {read} (i). The index file is not all in memory here, so a first search of "
                         "a query reads rows from the disk, whatever the thread count. bench_search_scale.py times each "
                         "query the first time it is asked, so its \"search ms\" includes these reads on such a machine: "
                         "read its numbers (last night's too) against this line.")
            disk = "reads from the disk: a query's first search reads its rows from the disk, whatever the threads"
        else:
            lines.append(f"DISK: no. Queries asked for the first time take, on all cores (i against a), {on_all}{one}: "
                         "the operating system keeps the index file in memory here.")
    if unsettled:
        lines.append(f"=> Not settled on this machine: {unsettled}" + (f"; and {disk}." if disk else "."))
    elif threads and disk:
        lines.append(f"=> On this machine both: {threads}; and {disk}.")
    elif threads:
        lines.append(f"=> On this machine the overhead comes from {threads}.")
    elif disk:
        lines.append(f"=> On this machine the overhead is {disk}; not threads.")
    else:
        lines.append("=> Neither shows on this machine: a compact search on all cores is as fast as on one"
                     + (", and a first search of a query reads nothing from the disk." if have("i") else "."))
    return lines


def run(args: argparse.Namespace) -> None:
    import faiss

    import codemem

    started = time.monotonic()
    n_all = args.threads or cpus()
    sizes = [int(s) for s in args.sizes.split(",")]
    build_sizes = ([] if args.build_sizes == "none" else [int(s) for s in args.build_sizes.split(",")]
                   if args.build_sizes else [min(sizes)])
    keys = [k for k in args.configs if k in CONFIGS]
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    blas = np.show_config(mode="dicts")["Build Dependencies"]["blas"]
    openblas = "openblas" in str(blas.get("name", "")).lower()
    if "f" in keys and not openblas:
        keys.remove("f")
    omp_libs = openmp_libraries()
    omp = openmp_kind(omp_libs)
    print(f"codemem {codemem.__version__} at {os.path.dirname(codemem.__file__)} (git {_git('rev-parse', '--short', 'HEAD')} "
          f"on {_git('rev-parse', '--abbrev-ref', 'HEAD')}) | FAISS {faiss.__version__}, OpenMP: {', '.join(omp_libs) or '?'} "
          f"({omp}) | numpy {np.__version__}, BLAS {blas.get('name')} {blas.get('version')} "
          f"({blas.get('openblas configuration')}) | {platform.platform()} {platform.machine()} | {_cpu_name()} | "
          f"{cpus()} CPUs, all = {n_all} | Python {platform.python_version()}", flush=True)
    print("This shell has " + ", ".join(f"{k}={os.environ.get(k, 'unset')}" for k in ("OMP_NUM_THREADS", *BLAS_VARS, *WAIT_VARS))
          + "; every timing child gets only the variables its table names." + ("" if openblas else
          " numpy's BLAS is not OpenBLAS here, so configuration f is not run."), flush=True)
    results: dict[tuple[int, str], dict] = {}
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
        print(f"{n:,} vectors: index {'reused' if reuse else 'built'} in {time.monotonic() - t:.0f} s; timing "
              f"configurations {', '.join(keys)}", flush=True)
        for key in keys:
            given = _given(key, n_all, omp)
            argv: list[object] = ["time", "--index", index, "--faiss", given["OMP_NUM_THREADS"], "--queries", args.queries]
            if key in "ad":
                argv.append("--exact")
            if key in COLD:
                argv += ["--cold", COLD[key]]
            if key in "ad" and n in build_sizes:
                argv.append("--build")
            if CONFIGS[key][3]:
                argv += ["--try-fix", CONFIGS[key][3]]
            results[(n, key)] = r = _child(_env(given), *argv)
            r["given"] = given
            if r["torch"]:
                print(f"torch was loaded in the child of {key}: several OpenMP threads are not safe there on macOS")
        if not args.keep_indexes:
            shutil.rmtree(index, ignore_errors=True)

    for key in keys:
        rows = [(n, results[(n, key)]) for n in sizes if (n, key) in results]
        if not rows:
            continue
        first = rows[0][1]
        inside = sorted({t for _, r in rows for t in r["faiss_threads_in_search"]})
        print(f"\n== {key}: {CONFIGS[key][4]} (tests: {CONFIGS[key][5]}) ==")
        print("given: " + " ".join(f"{k}={v}" for k, v in first["given"].items()))
        print(f"inside: faiss.omp_get_max_threads() = {first['faiss_threads']}, inside a compact search "
              f"{', '.join(map(str, inside))}; BLAS: {first['blas']}")
        print(f"{'vectors':>9} {'':>6} " + " ".join(f"{s:>7}" for s in STEPS) + f" | {'exact':>7}   ms over {args.queries} searches")
        for n, r in rows:
            for stat in ("p50", "p10", "p90"):
                exact = f"{r['ms']['exact'][stat]:>7.2f}" if "exact" in r["ms"] else f"{'-':>7}"
                label = {"p50": "median", "p10": "p10", "p90": "p90"}[stat]
                print(f"{f'{n:,}' if stat == 'p50' else '':>9} {label:>6} "
                      + " ".join(f"{r['ms'][s][stat]:>7.2f}" for s in STEPS) + f" | {exact}")
            notes = [] if r["compact_from_file"] else ["the compact index was rebuilt from the rows: its file was refused"]
            if r["index_searches_per_search"] > 1.05 or r["coarse_scans_per_search"] > 1.05:
                notes.append(f"{r['index_searches_per_search']:.2f} index searches and {r['coarse_scans_per_search']:.2f} "
                             "coarse scans per search")
            if "build_s" in r:
                notes.append(f"building the compact index from the rows: {r['build_s']:.1f} s")
            for note in notes:
                print(f"{'':>17}{note}")

    print("\n== a compact search, ms more than in d (both pools on 1 thread); the exact search's in brackets ==")
    others = [k for k in keys if k != "d"]
    print(f"{'vectors':>9} " + " ".join(f"{k:>15}" for k in others))
    for n in sizes:
        if (n, "d") not in results:
            continue
        base = results[(n, "d")]["ms"]
        cells = []
        for k in others:
            r = results.get((n, k))
            if r is None:
                cells.append("")
                continue
            ex = f" ({r['ms']['exact']['p50'] - base['exact']['p50']:+.1f})" if "exact" in r["ms"] and "exact" in base else ""
            cells.append(f"{r['ms']['search']['p50'] - base['search']['p50']:+.1f}{ex}")
        print(f"{n:>9,} " + " ".join(f"{c:>15}" for c in cells))
    print("\nsame results (ids and scores of every hit, query by query), compact index:")
    for line in _same_results(results, sizes, [k for k in keys if k in SAME_QUERIES], "hits"):
        print("  " + line)
    print("same results, exact index (a, d):")
    for line in _same_results(results, sizes, keys, "exact_hits"):
        print("  " + line)
    print("  Compare the fingerprints with another run (main against a fix branch): a fix must not change them.")
    builds = [(n, k, results[(n, k)]["build_s"]) for n in sizes for k in "ad" if (n, k) in results and "build_s" in results[(n, k)]]
    if builds:
        print("building the compact index from the rows: " + "; ".join(
            f"{n:,} vectors on {'all cores (a)' if k == 'a' else 'one core (d)'}: {s:.1f} s" for n, k, s in builds))
    per_thread = {r["per_thread"] for r in results.values()}
    print(f"faiss.omp_set_num_threads changes the calling thread's count only, on this machine: "
          f"{'yes' if per_thread == {True} else 'NO' if per_thread == {False} else 'not in every child'}")
    print("\n== what this says ==")
    for line in _closing(results, [n for n in sizes if (n, "a") in results], n_all):
        print(line)
    took = time.monotonic() - started
    print(f"took {took // 60:.0f} min {took % 60:.0f} s ({built_s:.0f} s building or reading the indexes)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--work", help="a folder with free disk for the indexes (about 2.5 GB per million vectors)")
    p.add_argument("--sizes", default="100000,500000")
    p.add_argument("--configs", default="abcdefghijk", help="which configurations to run (letters, see above)")
    p.add_argument("--threads", type=int, default=0, help="what 'all' means (default: every CPU this process may use)")
    p.add_argument("--queries", type=int, default=50)
    p.add_argument("--build-sizes", default="", help="sizes at which a and d time a build from the rows (default: the smallest)")
    p.add_argument("--keep-indexes", action="store_true")
    sub = p.add_subparsers(dest="cmd")  # the steps `run` starts, each in a process of its own
    for name, fn in (("build", cmd_build), ("prepare", cmd_prepare), ("time", cmd_time)):
        s = sub.add_parser(name)
        s.add_argument("--index", required=True)
        s.add_argument("--n", type=int, default=0)
        s.add_argument("--faiss", type=int, default=1)
        s.add_argument("--queries", type=int, default=50)
        s.add_argument("--exact", action="store_true")
        s.add_argument("--build", action="store_true")
        s.add_argument("--cold", type=int, default=0, help="the seed of queries asked for the first time")
        s.add_argument("--try-fix", default="")
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
