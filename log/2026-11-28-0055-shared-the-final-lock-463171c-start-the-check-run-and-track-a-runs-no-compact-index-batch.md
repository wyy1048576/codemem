# The final lock: `463171c`. Track A, please start the check run. One correction: track A runs no batch with the compact index

- **Track:** shared: from the lead, to all tracks
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 00:55 UTC
- **Work package:** the freeze of `codemem-final` (`docs/plan/overview.md`); A12 (the runs)
- **Branch, commits, pull request:** `main` at `722ded5`. codemem's own files are those of `463171c`

## Done

**1. The lock is final: `463171c`.** This is the entry announced at 00:43 UTC.

- Since `463171c`, `main` changed only in `docs/` and `eval/`. **No index and no block is made again.**
- Keep the codemem checkout of the runs at `463171c`. A later merge to `main` does not move the lock: the runs stay on `463171c` until a new lock is posted here.
- **Track A: please start the check run now, by 01:15 UTC (17:15 Pacific) at the latest.**

**2. Points 1, 2, 3 and 5 of our entry of 00:40 UTC stand as written:** the hash, what `codemem-final` is (the MCP tool, the tool descriptions of #26, the 20 results at the start, no hooks), what is not in the lock, and the question of how long a full rebuild takes on the PC.

**3. Point 4 of that entry is withdrawn.** Andre's decision: **track A runs no batch with the compact index.** The PC and its runs stay on the exact index, as they are, and nothing is asked of track A for it.

- The comparison of the exact and the compact index on kubernetes is run by track B on its own machine, with track A's pipeline as it is. Its instructions come in a separate entry.
- If track B's agent asks you how a step of the pipeline is run, please answer it in the log.

## Checked

`git diff --stat 463171c origin/main -- . ':(exclude)eval' ':(exclude)docs'` prints nothing at `722ded5`.

## Left

Nothing for the lock.

## Blocked on, or needed from others

- **Track A:** the check run and its report.

## Next

Track A: the check run. The lead: the instructions for track B's comparison of the two indexes.
