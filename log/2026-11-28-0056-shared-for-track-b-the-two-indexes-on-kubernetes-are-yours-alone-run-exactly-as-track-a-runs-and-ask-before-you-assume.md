# For track B: the comparison of the two indexes on kubernetes is yours alone. Run it exactly as track A runs, with your agent at its highest setting, and ask before you assume

- **Track:** shared: from the lead, for track B. It replaces our entry of 00:41 UTC wherever that one says "in your own setup"
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 00:56 UTC
- **Work package:** B8; the compact index of track C (`docs/plan/runs.md` §12, on the branch `andre/run-plan-compact-index` until it is merged)
- **Branch, commits, pull request:** none yet. codemem `463171c`, the commit of the lock (entry of 00:56 UTC)

## Done

**Andre's decision.** The comparison of the exact and the compact index on kubernetes runs on track B's machine only. Track A's PC is not touched and runs no such batch. So this result rests on your runs alone, and it goes into the paper as track C's evidence that the compact index works in real agent runs.

**Three things Andre asks of this work.**

1. **Your agent at its highest setting:** the most capable model you have, at maximum effort, for the whole of it.
2. **Exactly as track A runs.** Not your own harness.
3. **With any issue or question, ask in this log and wait for the answer.** Do not assume, and do not work around a step that does not run. A wrong assumption here costs all three tracks.

**What "exactly as track A runs" means.**

- **The eval's own code** (`cmeval`, from `main`): the kubernetes recipe and its images, `cmeval e2e index`, `cmeval e2e block`, the runner with its proxy, its limits (150 turns, 50 minutes) and its checks, and the grader with the hidden tests. Change no default and skip no check.
- **codemem `463171c`** from a checkout pinned at that commit, in its own `uv sync` environment.
- **The setup `codemem`** (`docs/plan/runs.md` §1): the MCP tool, wording `light`, no hooks, and the block of 20 results at the top of the first message, made by `cmeval e2e block`.
- **The tasks and prompts of `main`:** the 8 kubernetes run tasks of `eval/tasks/run-sample-v1.jsonl`, at L0, L1 and L2 (`eval/tasks/vague-b10a-v3.jsonl`).
- **Haiku once and Sonnet once.** 8 x 3 x 2 models x 2 indexes = 96 runs.
- **The two arms differ only in the index:** the exact one (`CODEMEM_VECTOR_BACKEND=faiss`, what the runner sets today) and the compact one (`CODEMEM_VECTOR_BACKEND=compact`). Each task's index is built in both forms, and each arm's block is made on its own index.

**The switch for the index comes from us.** The runner sets the exact index in a constant (`CODEMEM_ENV` in `e2e_index.py`). Please do not patch the eval yourself: we write the switch that lets a batch name the index, with tests, and post the branch here. Until then, prepare what does not depend on it.

**Before the first run, two posts in this log.**

1. **Within the hour: can your machine do it at all?** Docker with Linux containers, the builds of the kubernetes images of the recipe, the GPU inside a container (the runner refuses a codemem setup without it), and the index of kubernetes at 8 base commits in both forms. Say what works, what does not, and how long the first image and the first index took. If it cannot be done, say so. Do not put your own harness in its place.
2. **Before any run that counts: every difference between your machine or setup and track A's** (the system, Docker, the GPU, the Claude Code version, anything you had to change to make a step run). Then wait for our go-ahead. No run made before it counts.

**What to report at the end:** as in our entry of 00:41 UTC: tasks solved, tokens, time and turns for each arm and model; the 20 results at the start, compact against exact, for every task and level; and for each index the seconds of its build, its size on disk and the memory of the search index.

**Order.** Item 1 runs on. This comes next. Do not run both at the same time if that would disturb the timings of either; say which order you chose.

## Checked

The 8 task ids and the prompt file are those of our entry of 00:41 UTC, read from `main` at `722ded5`.

## Left

- From us: the switch for the index, on a branch; and our review of `6146896` (D4 and D5), in its own entry.

## Blocked on, or needed from others

- **Track B:** the post on feasibility within the hour.
- **Track A:** nothing; an answer in the log if track B's agent asks how a step of the pipeline is run.

## Next

Track B: the feasibility post. The lead: the switch for the index.
