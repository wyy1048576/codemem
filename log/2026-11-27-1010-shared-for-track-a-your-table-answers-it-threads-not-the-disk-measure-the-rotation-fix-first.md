# For track A: your table of 09:37 UTC answers it. On your PC it is threads, numpy's BLAS, and not the disk. Measure the rotation fix first

- **Track:** shared: from track C's session, for track A. Our entry of 10:00 UTC crossed yours of 09:37; this one puts the two together
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 10:10 UTC
- **Work package:** C2 (the compact index)
- **Branch, commits, pull request:** `andre/compact-threads-fix-rotation` (`cca0b31`), the candidate your table points to

## Done

**Thank you for the run in the gap.** We wrote the entry of 10:00 UTC before we had read yours, and it asks a question you had already answered:

- **It is not the disk on your PC.** Your `read` column is flat in all four settings (2.6 to 3.1 ms). On the Mac the whole effect sat in that column. So suspect 0 of the 10:00 entry is ruled out for you, and your run 3 numbers stand as a thread effect.
- **The pool is numpy's BLAS,** as your closing line says: with it on one thread, FAISS on 16 costs 2 ms. With it on 16, the two FAISS steps slow down (`fine` from 16 to 55 ms at 100,000 vectors with both pools on 16; from 40 to 61 ms at 500,000 with FAISS on 1).
- **Your reading fits:** the time is not in the product itself (`rotate` is at most 4.7 ms) but in what follows it, as if OpenBLAS's 16 worker threads stayed busy after the one-row product and took the processors from FAISS.

**So, when the hard tier allows, in this order:**

1. **`andre/compact-threads-fix-rotation` first.** It rotates a single query with numpy's own loop, so a search never wakes numpy's BLAS threads at all. If your reading is right, that removes the whole effect. Run the script on that branch with the same `--work` folder and `--check`; the goals of 09:25 UTC decide.
2. **The new script on `andre/compact-threads` tests your reading directly,** in the same run: setting `h` applies that change at run time, and setting `f` leaves the product on 16 threads but makes OpenBLAS's waiting threads passive. If `f` alone removes the effect, the busy waiting is the cause, as you wrote.
3. `andre/compact-threads-fix-faiss` is then not needed, unless `c` and `g` say otherwise on the new run.

**One more thing your table shows, for after this:** on one thread `fine` takes 16 ms at 100,000 vectors and 40 ms at 500,000 on your PC. On the Mac the same step takes about 4 ms at 500,000. So FAISS's ranking by 4-bit codes is far slower on your processor than on Apple's, whatever the threads, and it is most of a compact search there. It is why the compact index only draws level with the exact one at 100,000 vectors on your PC even on one thread. We note it; nothing is asked of you for it now.

## Checked

- Your full log (`log/2026-11-27-0937-a-data/threads-1.log`): the four tables, the `read` column, the thread counts each child reported.

## Left

- Unchanged: the fix measured by the five goals of 09:25 UTC; parts 2 and 3 of 09:35 UTC; all of it behind the hard tier (09:45 UTC).

## Blocked on, or needed from others

- Nothing new.

## Next

- Track A: the hard tier; then the rotation fix on the PC.
