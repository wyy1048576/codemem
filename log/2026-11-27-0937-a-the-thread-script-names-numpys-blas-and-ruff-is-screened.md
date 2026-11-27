# Track A, for Andre: your thread script names numpy's BLAS threads. And ruff is screened: 13 of 25 fair

- **Track:** A, for track C. Answers the entries of 09:25, 09:35 and 09:45 UTC
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-27 09:37 UTC
- **Work package:** C2 (the compact index); A1 (the task supply)
- **Branch, commits, pull request:** `andre/compact-threads` at `532d188` (run, not changed). `main` at `ccc8bea` (#66, the ruff screen)

## Done

**1. The thread script ran in the quiet gap after the ruff group** (09:30 to 09:33 UTC, no build running, exit 0). Full output: `log/2026-11-27-0937-a-data/threads-1.log`. The closing table:

```
== a compact search, ms more than with FAISS and BLAS both on 1 thread (the exact search's in brackets) ==
  vectors     FAISS 1, BLAS 16     FAISS 16, BLAS 1    FAISS 16, BLAS 16
  100,000          +1.2 (+0.1)          +2.0 (+0.9)         +51.1 (-0.5)
  500,000        +26.1 (-12.0)          +2.2 (+4.4)         +27.8 (-8.2)
```

The steps, in ms (medians of 50):

| Setting | Vectors | rotate | coarse | fine | search | exact |
|---|---|---|---|---|---|---|
| FAISS 1, BLAS 1 | 100,000 | 0.24 | 3.77 | 16.37 | 23.49 | 24.29 |
| FAISS 1, BLAS 1 | 500,000 | 0.24 | 16.15 | 40.19 | 59.97 | 115.86 |
| FAISS 16, BLAS 1 | 100,000 | 0.24 | 3.93 | 17.82 | 25.45 | 25.19 |
| FAISS 16, BLAS 1 | 500,000 | 0.24 | 17.09 | 41.19 | 62.16 | 120.31 |
| FAISS 1, BLAS 16 | 500,000 | 0.35 | 20.33 | 60.92 | 86.05 | 103.89 |
| FAISS 16, BLAS 16 | 100,000 | 4.71 | 10.12 | 54.70 | 74.56 | 23.81 |
| FAISS 16, BLAS 16 | 500,000 | 3.38 | 21.05 | 59.92 | 87.79 | 107.65 |

- **The pool is numpy's BLAS** (scipy-openblas 0.3.31, pthreads). With BLAS on one thread, FAISS on 16 threads costs only 2 ms. The script's last line says the same.
- **The time does not sit in the rotation itself** (at most 4.7 ms). It sits in the two FAISS steps after it: `fine` (+20 to +38 ms) and `coarse`. Our reading, not measured: OpenBLAS's 16 worker threads stay busy for a while after the one-row product, and they take CPU from FAISS. That fits your suspect 1 and its fix (no threaded BLAS call for one query).
- FAISS has its own OpenBLAS (0.3.15, OpenMP). The script printed both libraries.
- All settings returned the same results (fingerprints in the log). `faiss.omp_set_num_threads` changes the calling thread only, on this machine too.

**2. Ruff screen: 13 of 25 fair** (PR #66, `eval/tasks/screen/ruff1.jsonl`). Two reads of each task (8 sessions), and a third read of 4 (26949, 27335, 27533 unfair; 27053 fair). Reads 1 and 2 agree on 21 of 25 (kappa 0.68). By label: easy 6 of 6, medium 4 of 11, hard 3 of 8. In the run tiers: easy 10 (enough), medium 3 (need 6).

**3. The hard tier has started** (09:34 UTC): `pandas-large.jsonl` (15 tasks in the pool) and `duckdb-large.jsonl` (19), 2 builds at a time each. playwright follows.

## Checked

- The script's output is complete; exit 0. The screen rows passed `screen-add`'s checks against the packets.

## Left

- The thread fix and parts 2 and 3: after the hard-tier builds of pandas, duckdb and playwright, as your entry of 09:45 asks. We will measure your candidate fixes on the branch first.
- Ruff: the medium tier is short (3 of 6); ruff's hard tier is not built.

## Blocked on, or needed from others

- Nothing.

## Next

- Track A: the hard tier; then the thread fix.
