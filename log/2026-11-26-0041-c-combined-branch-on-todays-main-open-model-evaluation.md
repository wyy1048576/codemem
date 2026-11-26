# Track C: the combined branch is on today's `main`; the open-model evaluation is Andre's and starts after track C is merged

- **Track:** C. Point 2 is for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 00:41 UTC
- **Work package:** C2 to C5, C8, C9 (the branches); A6 and A11 (who does them)
- **Branch, commits, pull request:** `andre/track-c-all` at `3b37d70`, pushed. No pull request yet. Andre opens them

## Done

**1. `andre/track-c-all` has `main` at `1a7e4d1` (#29) merged in.** #29 changes only files under
`eval/`, and no file of it is touched by track C. Each of the seven branches still merges with
`main` without a conflict. The commands of the entry of 2026-11-25 23:43 now check out this tip.

**2. A decision of the team meeting of Nov 25, with Andre's order for it.** The evaluation with
open models is Andre's: the harness and the runs (in the plan, the open-harness part of A6, and
A11).
- **When:** after track C is merged. Track A's task generation and the runs that start on Nov 26
  come first.
- **How it starts:** with a survey of ready-made agent loops that take any model. The plan's §4.6
  is the starting list. Nothing is chosen.
- **Models:** mostly 7 to 13 billion parameters, at most about 30 (Qwen, Llama). The list is
  proposed here before any run.
- **State:** nothing is built. One untested file exists on a local branch, on hold.

Track A: please do not build the open harness in parallel. If part of it exists already, say so
here.

**3. Measured for C3 (one copy on disk): what the saved search index costs and buys.** On the
real pandas index (49,770 vectors):

| | |
|---|---|
| the index folder | 321 MB |
| of it, `index.db` | 231 MB: vectors 94, chunk rows 61, the keyword index 18, calls 5; the rest is SQLite's own indexes and page overhead |
| of it, the saved search index (`vec_*.faiss`) | 90 MB: a second copy of the vectors |
| a start that reads the saved file | 0.17 s |
| a start that builds the search index from the rows | 0.66 s |

So dropping the saved file of the exact index would make an index folder 28% smaller, and a start
0.5 s longer per 50,000 vectors. The model's own load (7 s on the PC's GPU) runs beside it.
**Nothing is changed.** Andre decides.

## Checked

- `andre/track-c-all` at `3b37d70`: 619 tests pass (the default setting; an M1).
- The two start times: best of 5, on an M1 with an index build and a test run going on beside
  them. The file sizes are exact.
- Not checked: the compact and the exact run of the suite on this tip (they passed on `9713c8b`,
  and the merge brought no file of `src/` or `tests/`).

## Left

- The pull requests (Andre). Their texts and links are ready.
- The vLLM index: the build is running again (about 145,000 vectors). Then the search-index check
  on it.

## Blocked on, or needed from others

- **Andrew:** the check on the PC (entry of 2026-11-25 23:43) is still wanted before
  `andre/compact-default` is merged. Nothing of track C has run on Linux or x86.

## Next

- Track C's session: the vLLM check; the memory, disk and time report on a quiet machine.
