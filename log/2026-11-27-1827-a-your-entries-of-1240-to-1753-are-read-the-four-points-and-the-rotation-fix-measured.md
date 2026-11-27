# Track A, for Andre: your entries of 12:40 to 17:53 UTC are read. Where the four points stand, and the rotation fix measured

- **Track:** A, for the lead and track C. A first answer to the entries of 12:40, 12:45, 14:45, 14:50, 15:13, 16:38, 17:00, 17:16 and 17:53 UTC. The full report of 16:38 UTC follows before 01:00 UTC
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-27 18:27 UTC
- **Work package:** A12 (the runs), A6 (the setups), A4 (the integrity checks), C2 (the compact index)
- **Branch, commits, pull request:** `main` at `c03262b` (ours since 09:37 UTC: #67 to #72). In work: `eval-codemem-setup`, built on `andre/eval-codemem-block` at `f79208b`. Measured, not changed: `andre/compact-threads` at `33f9d0e`, `andre/compact-threads-fix-rotation` at `cca0b31`

## Done

**0. Why you heard nothing.** Our session did not pull this log between 12:45 and 18:20 UTC. It worked (the hard-tier screens, the prompts, the indexes, your thread measurement) and posted nothing. Nothing in your entries was acted on before 18:20 UTC. All of them are read now. No run has started.

**1. The four points of 16:38 UTC, as they stand now.**

| # | Point | State |
|---|---|---|
| 1 | The mount of the codemem checkout | **Our PC is affected. Not fixed yet; the fix is in work.** Details in part 2 |
| 2 | The block and the `codemem` setup | We built none of our own; yours is the one. In review now. `cmeval e2e block` works on the PC with a real index (part 3) |
| 3 | Fair tasks, prompts, indexes | Ready for five repos (part 4) |
| 4 | Can the check run start at 01:00 UTC | **Yes, if the mount fix and your branch pass their real checks by then.** Our estimate for both: 23:00 UTC. One limit: the PC has one seat today (part 5) |

**2. The mount (15:13 UTC, point 1).**

- **The PC mounts a full checkout.** The program is `~/codemem-project/codemem-c/.venv/bin/codemem`, a worktree of this repo at `463171c`. `eval/tasks/e2e/*.jsonl` is in it. `CMEVAL_HOME` is `~/.cmeval`, outside the checkout, and it is not mounted as a whole.
- **The fix, in work:** mount only the environment and the package source (an allowlist), and a proof inside the container before each run that mounts codemem. A run that fails the proof does not start. The proof goes into the run's record. Your point 5 (the first setup moves from task to task) is in the same branch.
- **The look back.** 171 kept runs in 19 run ids (63 `grep`, 108 `tool`), read from each run's `stream.jsonl`:
  - tool calls of the agent that name a path under the checkout, `/home/ripst` or `~/.cmeval`: **0**;
  - tool results that show a line of a task file (`test_patch`, `tasks/e2e/`): **0**;
  - commands that search from `/`: 19 (10 in `grep` runs, 9 in `tool` runs). All search by file name (`find / -name ...`), none by content.
- So the hole was open and no run used it. Agents do search from `/`, so it has to be closed.

**3. Your branch `andre/eval-codemem-block`.**

- An independent review of the diff is in work.
- On the PC, at `f79208b` with codemem `463171c`: `cmeval e2e block pandas --id pandas-dev__pandas-68278` made the blocks of L0 (10.6 s) and L2 (6.7 s). Each has 20 results, `embedded: true`, and a timing key `embed_query:jinaai/jina-code-embeddings-0.5b`. The L2 block puts `NDFrame.ewm` first and the online mean's functions in the first ten.
- Not done yet: one real `codemem` run in the container, for `opens_with_text` (your check 1). It comes with the mount fix, on the merged code.
- Your two questions. A column for the agent's own calls: yes, we add it to the score. The mount: the fix covers `codemem` and `tool`.

**4. Tasks that are ready** (fair by the screen, with L1 and L2, index built with `463171c`). Sample: `eval/tasks/run-sample-v1.jsonl`, seed `runs-v1`.

| Repo | Fair: easy / medium / hard tier | In the run sample |
|---|---|---|
| pandas | 14 / 3 / 0 (hard: 0 of 15 valid) | 6 + 3 + 0 = 9 |
| ruff | 10 / 3 / 0 | 6 + 3 + 0 = 9 |
| duckdb | 30 / 11 / 4 | 6 + 4 + 4 = 14 |
| playwright | 20 / 8 / 2 | 6 + 6 + 2 = 14 |
| kubernetes | 18 / 2 / 0 | 6 + 2 + 0 = 8 |

- All indexes of these tasks are built with `463171c` (ended 14:21 UTC, no failure).
- **playwright's two hard tasks, 43342 and 43482, are two fixes of one issue with one hidden test.** Their L1 and L2 are being written now. Whether both run is Andrew's decision; our default is to run 43342 only.
- The blocks of all sample tasks (54 tasks, three levels) take about 25 minutes. They are made after the merge.

**5. The check run.**

- The run that was armed for 21:00 UTC (Sonnet, `grep` and `tool`) is disarmed. It followed the plan of this morning.
- The new one is armed after the merge, for 01:00 UTC: the six tasks (pandas 68278, 68945, 68090; playwright 42204, 43316, 42260), L0 and L2, `grep` and `codemem`, Haiku and Sonnet: 48 runs.
- **Seats: the PC has one login token, so one seat.** At 5 to 7 minutes a run, 48 runs take 4 to 6 hours on it. Your hours assume three seats. Andrew is asked for more.

**6. vscode, home-assistant and trino (17:00 UTC).**

- Their admission checks started at 18:25 UTC on the PC. They stop at 00:40 UTC at the latest, so that they do not load the timed runs.
- After admission each repo needs: validation of its candidates (image builds, hours of CPU), two screen reads, the prompts, the indexes.
- **The conflict:** validation builds load the PC, and from 01:00 UTC the PC runs timed batches without a gap (your point 8 of 14:50 UTC). Either the builds run beside the batches and every run records the machine's load, or these repos cannot be built before the freeze. This is a decision for Andrew; we bring it to him with the admission results.
- With builds beside the batches, our estimate is: home-assistant and vscode ready on Sat Nov 28, late UTC; trino on Sun Nov 29. Without, not before the freeze.

**7. The rotation fix, measured on the quiet PC** (14:21 to 14:54 UTC, no build, no run; 16 cores; full output in `log/2026-11-27-1827-a-data/threads-2.log`). Against your five goals of 09:25 UTC:

| Goal | Result |
|---|---|
| 1. The step and the pool are named | Met (our entry of 09:37 UTC): numpy's OpenBLAS threads; the time sits in the two FAISS steps after the one-row product |
| 2. All cores no slower than one core, within 2 ms | **Not met by 2 to 3 ms.** The fix takes the overhead from +34 to +52 ms down to +4 to +5 ms (table below) |
| 3. The same results | Met: the fingerprints of the compact and the exact index are equal on the base and on the fix, at all four sizes, in every configuration |
| 4. Builds are not slower | Met at 100,000 (3.96 s against 3.99 s). At 1,000,000: 37.22 s against 36.41 s (+2%), one run each |
| 5. The suite passes | Met: 737 passed, 2 skipped, 4 deselected |

A compact search, median ms of 50 searches:

| Vectors | Base, one core | Base, all cores | Fix, one core | Fix, all cores | Fix, all cores, run again |
|---|---|---|---|---|---|
| 100,000 | 22.56 | 74.89 | 22.86 | 27.31 | 26.00 |
| 200,000 | 25.57 | 68.94 | 26.33 | 31.48 | 29.92 |
| 500,000 | 59.26 | 95.61 | 59.42 | 63.57 | 64.51 |
| 1,000,000 | 115.11 | 149.35 | 116.21 | 120.55 | 120.66 |

- **What is left is FAISS's own threads, not numpy's.** On the base, configuration b (BLAS on one thread, FAISS on all) already cost +4.4 to +5.4 ms. On the fix, configuration g (the FAISS calls of a compact search on one thread, your fix (ii)) leaves -1.1 to +0.9 ms. So fix (i) and fix (ii) together would meet goal 2.
- The script's `--check` passed, and its verdict on the fix is "threads: not shown".
- The disk: on the fix, first-time queries cost -1.3 to +1.6 ms. The operating system keeps the index file in memory here.

## Checked

- The look back: a script over every `stream.jsonl` under `~/.cmeval/e2e/runs`, set-aside attempts left out. The one command that named `/home` listed `/home/agent/.npm`, the agent's own folder.
- The two blocks: read on the PC (the fields and the first lines of the text).
- The thread numbers: copied from the log file in the data folder. One measurement of each branch.
- Not checked: any run with a block; the mount fix (not written yet); your parts 2 and 3 of the thread work (the CPU limit of a container, the guard), not started.

## Left

- The mount fix, the review of your branch, one real `codemem` run, the merge.
- The blocks of all sample tasks, and the check run at 01:00 UTC.
- The audit of 14:50 UTC and your points 2 to 13 of 15:13 UTC: point 5 is in the fix branch; the others come with the check run's records or after it.
- The replay with the compact index (14:45 UTC, part 1): not started. It needs no seat and can run beside a batch.

## Blocked on, or needed from others

- **Andre:** nothing to do now. For the thread work: do you want fix (ii) on top of fix (i)? The numbers say it meets goal 2.
- **Andrew:** the seats; the merge of the block branch; the builds beside the batches.

## Next

Track A: the mount fix and the merge, then the full report of 16:38 UTC before 01:00 UTC.
