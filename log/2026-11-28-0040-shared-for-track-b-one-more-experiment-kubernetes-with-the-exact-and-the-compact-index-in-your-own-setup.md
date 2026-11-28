# For track B: one more experiment (Andre's request). kubernetes with the exact index and with the compact index, in your own setup

- **Track:** shared: from the lead, for track B
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 00:40 UTC
- **Work package:** B8; the compact index of track C (`docs/plan/track-c-memory.md`)
- **Branch, commits, pull request:** none. codemem `463171c`, the commit of the lock (entry of 00:40 UTC)

## Done

**Why.** The runs on track A's PC use the exact index, so they say nothing about the compact one. Andre wants both indexes measured on real agent runs, to show that the compact one works. Track A runs this comparison in its own pipeline after its first passes (entry of 00:40 UTC, point 4). Yours is a second measurement, made independently.

**What to run.**

- **Repo and tasks:** kubernetes only, the 8 run tasks of `eval/tasks/run-sample-v1.jsonl` on `main`: `kubernetes__kubernetes-` 140607, 140926, 142138, 142215, 141618, 142340, 141057, 140916. L0 is the issue; L1 and L2 are in `eval/tasks/vague-b10a-v3.jsonl`.
- **The setup** is the `codemem` setup of `docs/plan/runs.md` §1: codemem `463171c` as the MCP tool, wording `light`, no hooks, and the 20 best results of one `codemem search -k 20` on the prompt at the top of the first message. The text of those 21 lines is `block_text` in `eval/src/cmeval/e2e_block.py`.
- **Two arms that differ only in the index:** `CODEMEM_VECTOR_BACKEND=faiss` (the exact one) and `CODEMEM_VECTOR_BACKEND=compact`. The search at the start of each arm is made on that arm's index. Both arms run in your setup, because your runs cannot be set beside track A's.
- **Models and levels, as the plan has them for kubernetes:** Haiku once and Sonnet once, at L0, L1 and L2. That is 8 x 3 x 2 x 2 = 96 runs. The plan has no Opus and no repetitions on kubernetes.
- **The two arms of a task take turns,** and which goes first changes from task to task.

**What to report.**

- **For each arm and model:** the runs, the gold function edited, turns, tokens by class, seconds. Keep each run's diff, so that track A can grade them with the hidden tests later.
- **The 20 results at the start, compact against exact,** for every task and level: the same 20 in the same order, or which differ. This is the direct check, the same query on both indexes.
- **Each index:** the seconds of its build, its size on disk, and the memory of the search index (`codemem status`).
- **The checks of our entry of 13:15 UTC:** every search by meaning, the model loaded before the first search, and the others.

**First, within the hour: can your machine do it?** kubernetes has to be indexed at 8 base commits, in both forms. Please post whether the index builds there, how long the first one took, and when the 96 runs could end. If it cannot end before Nov 30, say so: the comparison then stays with track A alone.

**Order.** Item 1 goes on. You choose when the kubernetes index is built, so that it does not disturb item 1's timings; say which order you chose.

## Checked

The 8 task ids and the prompt file were read from `main` at `722ded5`. `CODEMEM_VECTOR_BACKEND` takes `auto`, `faiss` and `compact` (`src/codemem/config.py` at `463171c`).

## Left

Our review of `6146896` (D4 and D5) is running and comes in its own entry. PR #73 is on hold as a proposal by Andre's decision (entry of 00:40 UTC, point 3).

## Blocked on, or needed from others

- **Track B:** the answer on feasibility within the hour.

## Next

Track B: the feasibility answer, then the runs.
