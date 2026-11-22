# The next-phase plan is written, and the work log is set up

- **Track:** shared
- **Who:** Andre, with Claude Code
- **When:** 2026-11-22 22:34 UTC
- **Work package:** none: planning
- **Branch, commits, pull request:** `main`. The plan is in commits e5c9eab and 8dc3a2f. Today's later edits and the new files named below are in Andre's working tree, for him to commit

## Done

- **The plan:** `docs/plan/overview.md`, and one file per track: `track-a-evals.md`,
  `track-b-retrieval.md`, `track-c-memory.md`.
- **Dates:** Dec 1, the solution and the results, presented. Dec 8, the paper on arXiv. What does
  not fit has no date (overview §8.3).
- **Owners:** track A is Andrew's, track B is Wilson's, track C is Andre's.
- **Rules for people and agents:** `CONTRIBUTING.md`, with `AGENTS.md` and `CLAUDE.md` pointing
  to it.
- **This log:** the `worklog` branch, checked out at `.worklog/`.
- **Track A starts small:** a pilot on two or three repos in different languages, on the codemem
  that exists today with its local embedding model (track A §2.2 and §2.3). The embedding model is
  swapped by configuration. Qwen3-Embedding-8B through Nebius comes later.
- **Keys:** Claude runs on our subscriptions. API keys are for embeddings and for the open models
  of the small-model study only.

## Checked

- Nothing in the plan is built or run, except a small pilot of one-bit vector codes (track C §5).
- Facts marked "checked Nov 22" in the plan were read on their pages that day. Facts marked
  "reported" came from research passes and have not been re-read.
- The log commands of `CONTRIBUTING.md` §4 were rehearsed in a throwaway copy, with two clones
  writing at the same time: the second push was refused, rebased and then went through.

## Left

- Whether a hosted provider serves the 9B and 14B open models is not confirmed (overview §12,
  decision 8).
- Three behaviours of Claude Code under a subscription are to be checked on the first day
  (track A §4.3).

## Blocked on, or needed from others

Nothing.

## Next

- Andrew: propose the pilot repos (track A §2.2), then A1 and A2.
- Wilson: tag `codemem-today`, then B1.
- Andre: C1, and agree the vector store interface with Wilson by Nov 25.
