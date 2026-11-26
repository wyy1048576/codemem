# For track A: the five failures on Linux have a cause. A branch with the fix (tests, docs, one script) and two commands to run on the PC

- **Track:** shared: from track C's session, for track A. Answers your entry of 19:25 UTC, point 4
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 21:20 UTC
- **Work package:** C2 (the compact index), on track C's side
- **Branch, commits, pull request:** `andre/compact-linux` (pushed, tip `bc76bd0`, merged with `main` `e6f2d30`). No pull request yet: Andre opens it

## Done

**The cause, in one paragraph.** Before a vector is coded, the compact index rotates it: one float32 matrix product, done by numpy's maths library (BLAS). A BLAS does not promise a row the same last bits in calls of different sizes. FAISS then stores per-vector correction numbers that differ in their last bits, so an index patched edit by edit and one built once hold different bytes, and copies of one vector coded in two calls do not tie exactly. The five tests compared exactly those things. **The byte you saw differ, number 124, is a digit of the checksum** that the file's first line holds as text: it says the data differs, not where.

- **FAISS is not the cause** on the Mac: on 1 to 16 threads, and with one add against many small adds, it gives identical codes from identical inputs.
- **Reproduced on the Mac by changing only the batch sizes.** Apple's library rounds by call for calls of 8 to 15 rows at 32 numbers, sizes the tests did not use. With a rotation that rounds by call, exactly your five tests fail there, and `test_ties...[4]` passes, as on your PC.
- **What only your PC can show:** that OpenBLAS is what does it there. `test_ties...[1]` failed on your PC with all its rows in one call, so OpenBLAS must also round by a row's position in a call, probably from splitting the call across its threads.

**What is wrong for a user: nothing we know of.** Scores are read from the stored vectors, not from the codes. A saved file is checked against its own checksum. Nothing in the product compares a patched index with a rebuilt one. The one effect is which of two candidates whose estimates differ in the last bit is kept at the cut. Your runs are on the exact index and are not touched, as you wrote.

**The branch changes no behaviour.**

1. The three tests that hold two indexes to the same bytes use a rotation that every BLAS multiplies exactly (a signed permutation), so they test what they were written for: the bookkeeping and the cut through ties.
2. `docs/architecture.md` §5 and four comments in `src/codemem/store.py` no longer promise equal bytes: codes are equal up to the rotation's rounding.
3. A new script, `scripts/diagnose_compact_store.py`: each stage of the coding path by call size, position and thread count, in four child processes (BLAS on 1 thread or the default, FAISS on 1 or 16 threads). 15 seconds on the Mac.

## Checked

- Mac, FAISS 1.16.0: `tests/test_compact_store.py` 94 passed; the diagnostic runs.
- Not checked: Linux. That is the request below.

## Left

- A change that would remove the dependence (rotating in float64) is proposed for after the runs: it changes how vectors are coded, and it is still not exact.

## Blocked on, or needed from others

**Track A, two commands on the PC, when it suits the queue** (neither is a timing; both take under a minute):

```bash
git fetch origin && git checkout origin/andre/compact-linux && uv sync
uv run pytest -q tests/test_compact_store.py
uv run python scripts/diagnose_compact_store.py > diagnose.txt 2>&1
```

- **Expected from the tests:** all pass (94 on the Mac).
- **Expected from the diagnostic:** "stage 2, rotation" lists call sizes whose rows differ, or more than one distinct result for the same vector in one call; "stage 3, FAISS encode" says equal. **If stage 3 shows a difference, the cause on x86 is another one and this branch is not enough: say so.**
- Please post `diagnose.txt` (it is short). The full log of the five failures is then no longer needed.

## Next

- Andre: the pull request, after your result.
