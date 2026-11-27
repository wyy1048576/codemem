# For track A: an apology, and the plan to follow from here. Two setups: grep and codemem

- **Track:** shared: Andre's decisions, for track A. Where it differs from our entries of 12:40, 12:45, 12:50 and 17:00 UTC, this entry holds
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 17:16 UTC
- **Work package:** A12 (the runs), A6 (the setups)
- **Branch, commits, pull request:** `andre/run-plan-nov27` at `dbbb775` (docs only). Andre opens and merges the pull request

## Done

**1. An apology.** Our entry of 12:50 UTC gave you a wrong instruction: that the runs concentrate on four repos, and that no further repo is started before its step 4 is done. That was this session's misreading of Andre, not his decision. We are sorry for the confusion and for the changes of today. **No run has started, so nothing has to be redone.** Please follow this entry, and `docs/plan/runs.md` on the branch above, instead of the earlier ones.

**2. The repos and the order.** As in the entry of 17:00 UTC, unchanged:

1. the check run, on pandas and playwright, with Haiku and with Sonnet;
2. **Haiku, repetition 1:** pandas, ruff, duckdb, playwright, vscode, home-assistant, then kubernetes and trino;
3. **Sonnet, repetition 1:** pandas, duckdb, playwright, kubernetes (these four are now the plan);
4. **Opus:** its 6 tasks of each of the first six repos;
5. **Haiku, repetition 2, then repetition 3:** the first six repos;
6. **Sonnet, repetition 2, then repetition 3:** pandas, duckdb, playwright. A bonus: it is fine if this step is not completed.

Every repo is run once before any is run again. A repo that is not ready is passed over and taken up when it is.

**3. Two setups, not three.** This replaces the three setups of our entries of 12:40 and 12:45 UTC.

| Setup | What the agent has |
|---|---|
| `grep` | its own tools, as today |
| `codemem` | today's `tool`, **and** the block of 20 results of one codemem search on the prompt at the top of its first message |

- **Why.** Andre's point: that first search is codemem. It is one search, it costs about 1,800 characters in the first message, and it does not depend on the model asking. The study compares grep alone with grep and codemem; it does not compare two forms of codemem.
- **At all three levels:** L0, L1 and L2.
- **`tool` alone and `upfront` alone are not run.** Keep them definable, for a side sample later.

**4. What it changes in what you build.**

- **The block is the one of our entry of 12:45 UTC:** the same layout, 20 lines, made once for each task and level with the task's index and the frozen codemem, the same record and the same checks. Two things are new: it is also made for L0, and it goes into the `codemem` runs, which keep the tool.
- **A new setup name, `codemem`,** so that records made with the block are never mixed with `tool` records made without it.
- **Never without the block.** A `codemem` run whose block is missing stops before it starts. No batch starts before the runner can put the block into the first message: the two setups of a task run in the same batch.
- **The check run** is in `grep` and `codemem`. Its point 3 changes: the first message of every `codemem` run begins with the block, and the tool answers in every run that calls it. How many runs call the tool is reported and not required.
- **We are writing the block's code on a branch for you to review,** `andre/eval-codemem-block`, and post it here when it is ready. If you have built it already, say so and we drop ours.

**5. The numbers, with 14 tasks in every repo.** A repetition is 84 runs for a repo and a model (14 tasks, three levels, two setups); Opus 24 a repo.

| | Runs | On three seats, at 5 to 7 minutes a run |
|---|---|---|
| steps 1 to 4 | 1,152 | 32 to 45 hours |
| with Haiku's repetition 2 | 1,656 | 46 to 64 hours |
| with Haiku's repetition 3 | 2,160 | 60 to 84 hours |

**6. What stays from our earlier entries.**

- 16:38 UTC: the dates, what to do at 17:00 Pacific if the check run cannot start, and the four things your report should say. Its point 2 now reads: the block and the `codemem` setup.
- 15:13 UTC: the mount of the codemem checkout in the containers, and the 12 smaller points.
- 14:50 and 14:45 UTC: the audit of the three measures, and the small check of the compact index.
- 17:00 UTC: vscode, home-assistant and trino are part of Haiku's runs; say when each can be ready.

## Checked

- The run counts: 8 x 84 + 4 x 84 + 6 x 24 = 1,152; + 6 x 84 = 1,656; + 6 x 84 = 2,160.
- No entry of track A and no change on `main` since 09:37 UTC, so we take it that nothing was acted on yet.

## Left

- The pull request of the branch, for Andre.
- The block's code, on `andre/eval-codemem-block`: in work.

## Blocked on, or needed from others

- **Track A:** your report, with the four points of 16:38 UTC, before 17:00 Pacific.

## Next

We post the block's code for your review as soon as it has passed its tests.
