# For track B, from Andre: whatever machine job 1 runs on, it runs `main`'s codemem (`463171c`), never PR #85

- **Track:** shared: from the lead, for track B. Adds to our entries of 12:49 and 13:27 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 13:36 UTC
- **Work package:** B8 (job 1)
- **Branch, commits, pull request:** codemem `463171c` (the lock, "v2"); the eval from PR #90's branch

## Done

**Andre: job 1 uses `main`'s search, not v3.**

- The codemem checkout that builds the indexes and serves the runs is at `463171c`: the lock, the codemem of track A's runs.
- **Not PR #85 (v3), not `wilson/no-hooks`, and no other codemem branch, in either arm.**
- **The reason:** as few variations as possible. The only thing that differs between the two arms is the search index, exact or compact (`docs/plan/runs.md` §12).
- **Record it:** every record of job 1 must show codemem `463171c` (`identity.codemem.commit`). Post it with the five checks of the first compact run.

## Left

- None.

## Blocked on, or needed from others

- None.

## Next

- Unchanged: your answer on the v3 check, then job 1 when the machine is settled.
