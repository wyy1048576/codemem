"""Every FAISS call the compact search index makes (add, search, search under a bitmap, the
estimates of chosen codes by a range search under a bitmap, remove, reorder, save, load), on many
code lengths and bit counts: 2,608 combinations, a minute or two.

    uv run python scripts/check_faiss_calls.py

Run it on a platform or a FAISS version the compact index has not been checked on, before a FAISS
upgrade is trusted, and before the longest code (COMPACT_MAX_DIM) or the oldest FAISS
(`_RABITQ_SINCE` in store.py) is changed. The compact index hands FAISS only what these calls
were checked with, because a mistake inside FAISS can end the process instead of raising.

It prints one line per bit count and ends with "all 2608 combinations ran" and exit status 0. If
FAISS faults, the last thing on the screen is the combination it was on (bits, code length,
vectors) and, outside macOS, the Python stack; the exit status is not 0. Send that back, with the
FAISS version and the platform (the first line it prints).

On macOS it can run under Guard Malloc, which puts every allocation against an unmapped page and
unmaps freed memory, so a read or write outside a buffer, or of freed memory, faults at once
instead of going unnoticed (two to three minutes):

    DYLD_INSERT_LIBRARIES=/usr/lib/libgmalloc.dylib uv run python scripts/check_faiss_calls.py

Guard Malloc places allocations on 16-byte boundaries, so an overrun of under 16 bytes past a
buffer whose size is not a multiple of 16 can still be missed; the runs with 208 vectors end the
codes on such a boundary. On macOS a fault ends the script with the signal's number as its exit
status (11 = a bad read or write, 6 = abort) and no crash report: the handler for those signals
is libc's own `_exit`.

`--dangling` runs the one misuse that did abort, as a check that the checker sees it:
`faiss.downcast_index(faiss.deserialize_index(...))` keeps a second Python object for an index
whose only owner is a temporary, deleted when the statement ends. Using the result reads and
writes freed memory. The store keeps the object `deserialize_index` returns, which owns the index.

FAISS 1.15.1 on an M1: every combination ran, also under Guard Malloc; `--dangling` exits with 11
under Guard Malloc and with 6 without it.
"""

from __future__ import annotations

import ctypes
import faulthandler
import platform
import signal
import sys

import faiss
import numpy as np


def exit_quietly_on_native_faults() -> None:
    """macOS: end the process on a native fault with the signal's number as its exit status, and
    no crash report or dialog. Elsewhere: print the Python stack and let the fault end it."""
    if sys.platform != "darwin":
        faulthandler.enable()
        return
    libc = ctypes.CDLL(None)
    libc.signal.restype = ctypes.c_void_p
    libc.signal.argtypes = [ctypes.c_int, ctypes.c_void_p]
    handler = ctypes.cast(libc._exit, ctypes.c_void_p)  # called with the signal number: no Python runs in it
    for sig in (signal.SIGABRT, signal.SIGSEGV, signal.SIGBUS, signal.SIGTRAP, signal.SIGILL, signal.SIGFPE):
        libc.signal(sig, handler)


def params(sel=None):
    return faiss.RaBitQSearchParameters(qb=4, centered=False, sel=sel)


def bitmap_of(mask: np.ndarray):
    bits = np.packbits(mask, bitorder="little")
    return bits, faiss.IDSelectorBitmap(len(bits), faiss.swig_ptr(bits))


def new_index(d: int, bits: int):
    index = faiss.IndexRaBitQ(d, faiss.METRIC_INNER_PRODUCT, bits)
    index.train(np.zeros((1, d), dtype=np.float32))
    return index


def exercise(rng: np.random.Generator, d: int, bits: int, n: int) -> None:
    x = rng.standard_normal((n, d)).astype(np.float32)
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    x[n // 2] = 0  # a zero vector
    index = new_index(d, bits)
    index.add(np.ascontiguousarray(x[: n // 3]))
    index.add(np.ascontiguousarray(x[n // 3:]))
    q = np.ascontiguousarray(x[1:2])
    for k in (1, 17, n):
        index.search(q, min(k, index.ntotal), params=params())
    index.search(np.zeros((1, d), dtype=np.float32), 5, params=params())
    for share in (0.0, 0.01, 0.3, 1.0):
        mask = rng.random(index.ntotal) < share
        keep, sel = bitmap_of(mask)
        _, pos = index.search(q, min(9, index.ntotal), params=params(sel))
        assert set(pos[0][pos[0] >= 0].tolist()) <= set(np.flatnonzero(mask).tolist())
        # the store ranks the scan's best again: a range search with no threshold returns the
        # estimate of every chosen code, and of no other
        _, estimates, pos = index.range_search(q, -1e30, params=params(sel))
        assert sorted(pos.tolist()) == np.flatnonzero(mask).tolist() and np.isfinite(estimates).all()
    gone = np.zeros(index.ntotal, dtype=bool)
    gone[[0, index.ntotal - 1]] = True
    gone |= rng.random(index.ntotal) < 0.2
    keep, sel = bitmap_of(gone)
    removed = index.remove_ids(sel)
    assert removed == gone.sum() and index.ntotal == n - removed
    index.add(np.ascontiguousarray(x[:7]))
    index.search(q, min(11, index.ntotal), params=params())
    order = rng.permutation(index.ntotal).astype(np.int64)  # the store moves codes to the order of their ids
    before = faiss.vector_to_array(index.codes).reshape(index.ntotal, -1).copy()
    index.permute_entries(order)
    assert np.array_equal(faiss.vector_to_array(index.codes).reshape(index.ntotal, -1), before[order])
    index.search(q, min(11, index.ntotal), params=params())
    owner = faiss.deserialize_index(faiss.serialize_index(index))  # this object owns the C++ index
    assert owner.thisown and owner.ntotal == index.ntotal and owner.codes.size() == owner.ntotal * owner.code_size
    owner.add(np.ascontiguousarray(x[:5]))
    mask = rng.random(owner.ntotal) < 0.5
    keep, sel = bitmap_of(mask)
    owner.search(q, min(13, owner.ntotal), params=params(sel))
    everything = np.ones(owner.ntotal, dtype=bool)
    keep, sel = bitmap_of(everything)
    assert owner.remove_ids(sel) == len(everything) and owner.ntotal == 0
    owner.add(np.ascontiguousarray(x[:3]))
    owner.search(q, 3, params=params())


def dangling() -> None:
    index = new_index(64, 1)
    x = np.random.default_rng(0).standard_normal((700, 64)).astype(np.float32)
    index.add(x)
    view = faiss.downcast_index(faiss.deserialize_index(faiss.serialize_index(index)))  # the owner dies here
    view.add(x[:3])  # freed memory
    print("no fault this time", flush=True)


def main() -> None:
    exit_quietly_on_native_faults()
    print(f"FAISS {faiss.__version__}, {platform.machine()} {platform.platform()}, Python {platform.python_version()}", flush=True)
    if "--dangling" in sys.argv:
        dangling()
        return
    rng = np.random.default_rng(0)
    around = (192, 256, 384, 512, 768, 896, 1024, 1536, 2048, 3072, 4096)
    dims = sorted(set(range(1, 131)) | {d + o for d in around for o in (-1, 0, 1)})
    count = 0
    for bits in range(1, 9):
        for d in dims:
            for n in (208, 203):
                # what it is on, should FAISS end the process: the last thing on the screen
                print(f"\rbits {bits}, code length {d}, {n} vectors   ", end="", file=sys.stderr, flush=True)
                exercise(rng, d, bits, n)
                count += 1
        print(f"\rbits {bits}: {len(dims)} code lengths x 2 sizes ran        ", flush=True)
    print(f"FAISS {faiss.__version__}: all {count} combinations ran, code lengths {dims[0]} to {dims[-1]}, bits 1 to 8", flush=True)


if __name__ == "__main__":
    main()
