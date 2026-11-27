# For track A: the thread work, updated. On a Mac the same slowdown turned out to be the disk cache, not threads, so the cause on your PC is open again. The script now tells the two apart, and both candidate fixes are on branches

- **Track:** shared: from track C's session, for track A. It adds to our entries of 09:25, 09:35 and 09:45 UTC and replaces nothing in them except one reading, named below
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 10:00 UTC
- **Work package:** C2 (the compact index)
- **Branch, commits, pull request:** `andre/compact-threads` (`33f9d0e`): the script with one setting per hypothesis, a `--check` flag, and the plan's paragraph. `andre/compact-threads-fix-rotation` (`cca0b31`) and `andre/compact-threads-fix-faiss` (`d36f176`): the two candidate fixes, each one commit on top of it. No pull request; nothing is merged

## Done

**The correction first.** Our entry of 09:25 UTC read your table of run 3 as a thread effect. **That is not established.** On the Mac the first measurements looked exactly like yours (23 ms on 8 threads against 7 on one, at 100,000 vectors), and they were wrong:

- The extra time was all in one step: reading the candidates' rows from SQLite. That step has no threads.
- The slow run was always the one that came first at its size, whatever its thread count. Alternating 8 threads and 1 thread at 500,000 vectors gave 48.7 and 24.3 ms, then 24.5 and 39.0, then 24.5 and 24.2.
- So it was the operating system's file cache: a search whose rows are not in memory reads them from the disk. That Mac is short of memory and pushes the index file's pages out.
- **With every query's rows read once before timing, 8 threads equal 1 thread** (within 0.3 ms at 500,000 vectors; the FAISS steps are the same on 1 and 8 threads, 17.9 against 18.0 ms and 4.4 against 4.5 ms). So the Mac does not show a thread overhead at all.

**Why this matters for your numbers.** `scripts/bench_search_scale.py` times each query the first time it is asked, so cold reads of the rows can be in its "search ms". A cold read costs tens of milliseconds, the size of what you measured (34 to 58 ms). We do not know which it is on your PC: threads, as we first read it, or the disk. Your machine has memory to spare, which speaks against the disk; two thread pools and WSL 2 speak for threads. **Only your PC can say, and one run of the new script says it.**

**The suspects now, in the order to rule them out:**

| Suspect | The script's settings that test it | It is the one if |
|---|---|---|
| 0. Cold reads of the rows (new) | `i` and `j`: queries asked for the first time, on all cores and on one, against `a` and `d`, whose rows were read before timing | the first-time queries are slow by tens of ms and the warmed ones are not, whatever the threads |
| 1. OpenBLAS threads the one-row rotation | `b` (BLAS on 1, FAISS on all), `h` (the query rotated without the BLAS) | `b` and `h` are as fast as `d`, and the time sits in `rotate` or in the step after it |
| 2. FAISS opens a parallel region for one query | `c` (FAISS on 1, BLAS on all), `g` (the search's FAISS calls on one thread) | `c` and `g` are as fast as `d` |
| 3. The two pools together | `e` and `f`: waiting threads of OpenMP, and of OpenBLAS, made passive | only `e` or `f`, or only `b` and `c` together, remove it |
| 4. Something of WSL 2 | all of them | none removes it |

`a` is both pools on all cores, `d` both on one, and `k` is `a` again at the end, to see whether `a`'s numbers repeat. Every setting runs in a process of its own and prints the variables it was given and the thread counts the libraries report from inside.

**How to run it** (when the order of 09:45 UTC allows: behind the hard tier, on a quiet PC):

```bash
git fetch origin && git checkout origin/andre/compact-threads && uv sync
uv run python scripts/time_compact_search.py --work <a folder on the Linux disk, not /mnt/c, with 2 GB free> --keep-indexes
```

- About 4 to 5.5 minutes on your PC by our estimate (your searches were about three times slower than that Mac's); `--sizes 100000` shortens it.
- It prints, per setting, the median and the 10th and 90th percentile of each step (`rotate`, `coarse`, `fine`, `read`, `score`, `other`, the whole `search`, and the exact search), whether every setting returned the same ids and scores, the time to build the compact index on all cores and on one, and a closing verdict of three: threads (and which pool), the disk, or neither. Send back everything it prints.
- Not run by us: setting `f`, since that Mac's numpy does not use OpenBLAS. If it fails on your PC, say so and go on without it.

**If the verdict is threads: the fix is already written, as two branches.** Check out the one the verdict names and run the script again with the same `--work`:

```bash
git checkout origin/andre/compact-threads-fix-rotation     # suspect 1: a single query is rotated by numpy's own loop, not the BLAS
git checkout origin/andre/compact-threads-fix-faiss        # suspect 2: a search's FAISS calls run on one OpenMP thread, and the count is restored after
uv run python scripts/time_compact_search.py --work <the same folder> --keep-indexes --check
```

- Each is one small commit in `src/codemem/store.py` with its test; `tests/test_compact_store.py` passes on each (95 tests, on the Mac). Settings `g` and `h` of the script try the same two changes at run time, so the first run already shows what each would give.
- The fingerprints of the results must equal those of the first run, and `--check` must exit with status 0.
- If both are needed, apply both. If neither is the right change, write your own; the limits and the five goals of 09:25 UTC stand.

**If the verdict is the disk:** nothing in codemem is slower with more cores, and no fix of the search is called for. What changes is the bench: it should read each query's rows once before it times them, or report first-time and repeated searches apart. Say so and we change it. Your run 3 numbers then need a second look, and so does the size at which the compact index starts to win.

**If the verdict is neither:** post the tables. Then run 3's difference came from something that one run does not show, and `k` against `a` says whether it repeats.

## Checked

- On the Mac (M1, 8 cores, FAISS 1.16.0, numpy on Apple's library): the script runs end to end; all settings return the same ids and scores for 50 of 50 queries; `--check` passes; `faiss.omp_set_num_threads` changes the calling thread's count only.
- Not checked: anything of OpenBLAS, GNU OpenMP or WSL 2; setting `f`; the two fixes' effect on speed, since the Mac has no overhead to remove.

## Left

- Parts 2 and 3 of the entry of 09:35 UTC are unchanged. The `--check` flag of part 3 is on the branch now. The plan's paragraph (`docs/plan/track-c-memory.md` §4.2) lists the three parts with their state, and says that the cause on the PC is not established.

## Blocked on, or needed from others

- **Track A:** the script's output from the PC, in the order of 09:45 UTC. Nothing before the hard tier.

## Next

- Andre's session reads the output when it is posted and takes the branch the verdict names to a pull request, or changes the bench if it is the disk.
