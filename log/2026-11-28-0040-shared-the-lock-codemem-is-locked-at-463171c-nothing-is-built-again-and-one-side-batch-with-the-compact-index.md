# The lock: codemem is locked at `463171c`. Nothing is built again. For track A: one side batch with the compact index on kubernetes

- **Track:** shared: from the lead, to all tracks
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 00:40 UTC
- **Work package:** the freeze of `codemem-final` (`docs/plan/overview.md`); A12 (the runs)
- **Branch, commits, pull request:** `main` at `722ded5`. codemem's own files are those of `463171c`

## Done

**1. The lock hash is `463171c`.**

- Since `463171c`, `main` changed only in `docs/` and `eval/`. So the indexes and the blocks made with `463171c` stay valid: **no index and no block is made again.**
- Keep the codemem checkout of the runs at `463171c`. The eval's own code runs from `main`'s tip, as before.
- **A later merge to `main` does not move the lock.** The runs stay on `463171c` until a new lock is posted in this log.

**2. What `codemem-final` is.** Three parts, all on `main` already:

- **The search and the MCP tool** of `463171c`: `search_code` (10 results a call), `get_chunk`, `index_status`.
- **The tool descriptions of #26** (wording `light`, codemem's default): "Use it first on a new task, and again whenever you lose the trail ... Once you have an exact identifier or string, use grep."
- **One search made for the agent at the start:** the 20 best results of a codemem search on the prompt at the top of the first message (the block of #77).
- **No hooks, and no change of wording.** This is the `codemem` setup of `docs/plan/runs.md` §1, compared with `grep`.

**3. What is not in the lock.**

- **PR #73, the search-dedup switch** (track B). Andre's decision: it is a proposal, ready to merge once reviewed, on hold, and not part of the first runs. We measure its cost and its gain and post them.
- **`andre/start-search-hook`:** the search at the start as a part of codemem for people who install it. The runs do not need it: the runner makes the block itself.
- **Track C's two thread fixes** for the compact index.

**4. For track A: one side batch with the compact index (Andre's request).** The runs use the exact index (`CODEMEM_ENV` in `e2e_index.py`), so they say nothing about the compact one. Andre wants both measured on real runs.

- **What:** kubernetes, its 8 run tasks, the `codemem` setup with `CODEMEM_VECTOR_BACKEND=compact`, Haiku once and Sonnet once, at L0, L1 and L2. That is 48 runs. The index of each task is built as the compact one, and the block is made on it.
- **Compared with:** the `codemem` runs of the same tasks from the plan, which use the exact index. `grep` is not run again.
- **When:** after Haiku's repetition 1 and Sonnet's repetition 1 on kubernetes, when the PC allows. It does not come before the first passes.
- **Please record** the index named in each run's `identity.codemem`, and the memory of the search index for both forms (`index_status`).
- Track B is asked for the same comparison in its own setup (a separate entry).

**5. One question.** How long does it take on the PC to build all the indexes and blocks again (62 tasks, 186 blocks)? We want the number for the day a new lock comes.

## Checked

- `git diff --stat 463171c origin/main -- . ':(exclude)eval' ':(exclude)docs'` prints nothing at `722ded5`.
- The three parts of point 2 were read in the code: the tool descriptions at `463171c` (`prompts.py`, from #26, commit `041124e`), the setup `codemem` in `e2e_run.py` (the tool and the block), and `CONFIG_PATHSPECS`, which removes every agent config file in the container, so no hook runs.

## Left

Nothing for the lock.

## Blocked on, or needed from others

- **Track A:** the check run and its report; the answer to point 5; the side batch of point 4 when its turn comes.

## Next

Track A: the check run. The lead: reads its report, and measures PR #73.
