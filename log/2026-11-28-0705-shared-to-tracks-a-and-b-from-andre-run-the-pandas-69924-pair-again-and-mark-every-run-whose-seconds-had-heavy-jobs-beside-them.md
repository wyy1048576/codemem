# To tracks A and B, from Andre: run the pandas 69924 pair at L0 again, and mark every run whose seconds had heavy jobs beside them

- **Track:** shared: from the lead, to tracks A and B. On track A's entry of 05:06 UTC, point 4
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 07:05 UTC
- **Work package:** A12 (the runs), A4 (the integrity checks); track B, job 1
- **Branch, commits, pull request:** none

## Done

**1. For track A: run the pair of pandas 69924 at L0 again** (Andre).

Builds took all 16 cores for 90 seconds during its `codemem` run (04:42 to 04:43:30 UTC), and its `grep` run had capped builds beside it. So the pair's seconds cannot be trusted.

- Run both setups again, back to back in one stream like any pair (Haiku, repetition 1, L0), at whatever point suits the stream.
- **The new pair counts for every measure:** tokens, turns, solved and seconds. This is decided now, before its result is known.
- Keep the first pair as a set-aside, with its reason. Nothing is discarded.
- Say in your next report when the pair ran again.

**2. For both tracks: in the analysis, a run's seconds are compared only together with a note of what else ran on the machine.** Load does not change tokens, turns or the solve rate, but it does change seconds.

- **Track A:**
  - Mark every run that had builds or another heavy job beside it. Use `pressure.log`, which records the cores in use every 30 seconds and the number of builds.
  - Keep that log with the archives.
- **Track B, for job 1 on your machine:** the same applies to your runs.
  - Keep heavy jobs away from a timed run.
  - Where one did run, log it so that the run can be marked.
  - The load at the start and end of a run is not enough on its own: track A found that the load average also counts build processes waiting at their CPU limit.

## Left

- Track A: the pair run again.

## Blocked on, or needed from others

- **Track A:** the new pair, and the marks from `pressure.log` with each archive.
- **Track B:** please note this for job 1.

## Next

- None from this entry.
