# For track A, a suggestion from Andre: build fewer candidates and keep only the chosen tasks' images. And the commit to run is now `463171c`

- **Track:** shared: from track C's session, for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 08:45 UTC
- **Work package:** A1 (the task supply), seen from the runs; C2 for the commit
- **Branch, commits, pull request:** `main` at `463171c` (#65, `andre/compact-linux`, merged by Andre after your check on the PC)

## Done

**1. The commit of codemem to run is `463171c`.** Since `09c4ef0` codemem's code changed in two pull requests: #60 (on macOS OpenMP gets one thread; on every platform the local model runs one call at a time) and #65 (comments in `store.py`, three tests, docs, the diagnostic script). No index has to be built again. Your one check run with `09c4ef0` stays valid as a check of the runner; the runs themselves take `463171c`, or the hash posted at the lock if anything else is merged before it.

**2. The suggestion. It is yours to take or leave: you own the eval.** Andre's concern is time and disk before the runs: a repo needs 14 fair tasks (6 easy, 4 medium, 4 hard) and 2 spares a tier, and today about 60 candidates are built to find them.

Your own tables show where the builds go:

| Repo | Built and validated | Valid | Fair |
|---|---|---|---|
| pandas | 100 | 92 | 17 |
| playwright | 60 | 49 | 28 |
| duckdb | 60 | 58 | 41 |
| kubernetes | 58 | 54 | 20 |

Validation removes few tasks (8 to 18%). The screen removes many (29 to 82%), and more of the larger fixes (kubernetes: fair are 13 of 18 with the label `easy`, 5 of 21 `medium`, 2 of 15 `hard`). So most images are built for tasks that the screen then drops.

- **a. The stop rule of `docs/plan/runs.md` §2, from now on:** check a tier only until it has what the sample needs and 2 spares (8 fair for easy, 6 for medium, 4 for hard), then stop that tier. For ruff that is the difference between 60 images and perhaps 25.
- **b. For a repo whose images are costly (ruff; kubernetes if it is validated again), read before you build.** A first pass of the screen on the text alone: `issue.txt`, `real-fix.patch` and `test.patch`, the same rules, without the two test lists, which need the image. Build only the candidates that pass it. The full screen, with the test lists, then runs on the validated ones as today. A candidate the first pass is unsure about is built.
- **c. Build the tiers that run short first:** hard, then medium, then easy.
- **d. When a repo's tasks are chosen, keep only their images.** The 14 and their spares stay (in Docker, or in your archive); the images of every other candidate are removed, and the virtual disk is compacted after that, since it does not shrink by itself. The records of every candidate stay (validation results, screen reads): they are small, and the paper needs the counts.
- **e. The PC is idle while ruff's recipe is changed** (your status of 05:40 UTC). Two things need no new recipe: the hard-tier candidates of pandas, playwright and duckdb (15, 27 and 19), with points a to c; and the check run of 24 Sonnet runs on `463171c`.

## Checked

- `463171c`: `git diff 09c4ef0 463171c -- src/` shows `__init__.py`, `embedder.py` (#60) and comments in `store.py` (#65). The Mac's suite passed on the branch before the merge (738, and 735 with 3 skipped on each forced index); your PC passed `tests/test_compact_store.py` (94).
- Not checked: how much of a ruff image the new shared layer saves, and whether a text-only first pass agrees with your full screen. A cheap test of the second: run it on the 112 duckdb and kubernetes tasks you have already screened and count the disagreements.

## Left

- Nothing on our side.

## Blocked on, or needed from others

- **Andrew:** whether to take a to e; the three decisions of the entry of Nov 26, 13:52 UTC.

## Next

- Track A: as Andrew decides.
