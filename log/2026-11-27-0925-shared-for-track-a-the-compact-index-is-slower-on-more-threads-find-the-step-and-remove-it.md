# For track A: the compact index searches slower on 16 threads than on one. The script is on `andre/compact-threads`. What we know, what we suspect, how to find the step on your PC, and the goals for removing it

- **Track:** shared: from track C's session, for track A. It answers your step 3 of 09:10 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 09:25 UTC
- **Work package:** C2 (the compact index), found by your run 3
- **Branch, commits, pull request:** `andre/compact-threads` (pushed, `532d188`, on `main` `463171c`): one new file, `scripts/time_compact_search.py`. No change to codemem's code yet

## Done

**Why this matters.** codemem must not get slower when a machine has more cores. The compact index is what `auto` picks for a large repository, and a user should never have to set a thread count to make it fast. **It does not touch the runs:** they use the exact index. So this must not delay them; a quiet quarter of an hour is enough for the first step.

**What your run 3 showed** (06:20 UTC; one query at a time, median ms):

| Vectors | Exact, all cores | Exact, one core | Compact, all cores | Compact, one core |
|---|---|---|---|---|
| 100,000 | 20.58 | 18.79 | 80.0 | 22.27 |
| 200,000 | 39.32 | 38.52 | 76.47 | 25.84 |
| 500,000 | 95.27 | 91.05 | 90.79 | 59.25 |
| 1,000,000 | 190.45 | 190.41 | 148.52 | 114.86 |

The exact search does not care about threads. The compact search pays 34 to 58 ms more on all cores, at every size. On one core it beats the exact search from 200,000 vectors; on all cores only from 1,000,000. `--threads 1` sets `OMP_NUM_THREADS=1`, which limits FAISS's threads and, on your numpy, OpenBLAS's as well (it reads `OPENBLAS_NUM_THREADS`, then `OMP_NUM_THREADS`). So the table cannot say which of the two pools costs the time.

**What one compact search does** (`CompactVectorStore.search` in `src/codemem/store.py`, read at `463171c`):

| Step | The call | Size | Who may thread it |
|---|---|---|---|
| rotate the query (`_coded`) | one row times the rotation: 1 x 896 by 896 x 896, in numpy's BLAS (`sgemv`) | 800,000 multiply-adds: far under a millisecond of work | **OpenBLAS**, which threads this product whenever the matrix has more than about 9,000 numbers |
| coarse scan (`_scan`) | one FAISS `search` of ONE query over every 1-bit code | all codes | **FAISS's OpenMP**, if this call opens a parallel region for one query |
| fine ranking (`_candidates`) | one FAISS `range_search` of ONE query under a bitmap, over the scan's best | 4,000 to 20,000 codes | **FAISS's OpenMP**, likewise |
| read the rows, exact scores | SQLite, then numpy without BLAS | 256 rows | nobody |

The exact index makes one FAISS call for a query and no BLAS product. So the compact search has three places where a pool of 16 threads can be woken for a job that one thread finishes in a millisecond or two.

**The suspects, in the order we believe them, with the test and the fix of each.** The script's default run has the four settings that tell them apart (FAISS threads 1 or all, BLAS threads 1 or all), each in its own process, with every step on its own clock.

| Suspect | It is the one if | The fix it calls for |
|---|---|---|
| 1. OpenBLAS threads the one-row rotation | the overhead goes away with BLAS on 1 thread and FAISS on all, and it sits in the `rotate` column | rotate a single query without a threaded BLAS call (a one-row product needs no threads). The batch rotation of a build keeps its threads |
| 2. FAISS opens a parallel region for one query | it goes away with FAISS on 1 thread and BLAS on all, and sits in `coarse` or `fine` | run the two per-query FAISS calls on one OpenMP thread. `faiss.omp_set_num_threads` sets the count of the calling thread only (checked on a Mac: another Python thread keeps its own count), so a search thread can do this without slowing the writer's `add` |
| 3. The two pools together | it goes away only when both are on 1 thread, or each pool alone removes part of it; the slow step is a FAISS step that follows the rotation | both fixes; or make waiting threads passive (try `OMP_WAIT_POLICY=passive` in the environment of one run and see if `coarse` drops) |
| 4. Something of WSL 2 | none of the above removes it | say so with the table; then it is not codemem's to fix, and we note it |

**How to run it** (from the repo root of a checkout of `andre/compact-threads`; nothing else running on the PC):

```bash
git fetch origin && git checkout origin/andre/compact-threads && uv sync
uv run python scripts/time_compact_search.py --work <a folder on the Linux disk, not /mnt/c, with 2 GB free> --keep-indexes
```

- Defaults: 100,000 and 500,000 vectors, 50 timed searches a setting. About 3 to 4 minutes on 16 cores, most of it building the larger index. A second run with the same `--work` reuses the indexes and takes about 2 minutes.
- It prints, for each of the four settings, the median of `rotate`, `coarse`, `fine`, `read`, `score`, `other`, the whole `search`, and the exact index's search as the reference; whether all settings returned the same results; and one closing line that names the pool. The docstring explains every column.
- **The script is a tool, not a verdict. Change it as you need:** more settings, more sizes (`--sizes`), another clock. It runs here only on a Mac, where codemem keeps FAISS on one thread and numpy uses Apple's library, so we cannot see what OpenBLAS does. You can.

**The goals.** This is done when all of these hold on your PC:

1. **The step and the pool are named,** with the table that shows it.
2. **With the fix, a compact search on all cores is no slower than on one core** at 100,000, 200,000, 500,000 and 1,000,000 vectors (your one-core numbers: about 22, 26, 59 and 115 ms; within 2 ms).
3. **Results do not change:** the same ids and scores as before the fix (the script prints a fingerprint of the results; it must be equal on `main` and on the fix).
4. **Builds are not slower:** "from rows" of `scripts/bench_search_scale.py` stays where it was on all cores (3.99 s at 100,000; 36.41 s at 1,000,000).
5. **The suite passes** on the fix (`uv run pytest -q`).

**Who changes the code.** You may. Make a branch of your own from `andre/compact-threads`, change the search path of `CompactVectorStore` as the table tells you, and iterate until the goals hold. The limits: nothing that changes what a search returns, the saved file, or how an index is built; no new setting a user has to know; no thread count taken from the user's hands by force on Linux (a limit inside one search call is fine). Our session is preparing both candidate fixes on this branch as separate commits; if they are there when you start, measure them first. Post the tables before and after and the diff. Andre reviews and merges.

## Checked

- The script ran end to end on a Mac at 20,000 vectors (5 s). The per-thread behaviour of `faiss.omp_set_num_threads` was checked there with FAISS 1.16.0.
- Not checked: anything on Linux; which suspect it is; that OpenBLAS's threshold for this product is what its source says on your build.

## Left

- The candidate fixes as further commits on `andre/compact-threads` (within the hour). The Mac's own step table.

## Blocked on, or needed from others

- **Track A:** the script's output from your PC, when the ruff group has ended and before or beside the hard tier, whichever does not hold the hard tier up; then the fix, by the goals above.

## Next

- Andre's session: the candidate fixes; reading your table as soon as it is posted.
