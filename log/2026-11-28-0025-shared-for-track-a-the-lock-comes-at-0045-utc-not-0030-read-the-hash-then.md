# For track A: the lock comes at 00:45 UTC (16:45 Pacific), not 00:30. Read the lock hash here then

- **Track:** shared: from the lead, for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 00:25 UTC
- **Work package:** A12 (the runs); the freeze of `codemem-final`
- **Branch, commits, pull request:** none

## Done

**The lock is active from 00:45 UTC (16:45 Pacific) onwards.** Andre asks for 15 more minutes to finalise track B's part and check it. Please read the lock hash in this log at 00:45 UTC, not at 00:30.

- At 2026-11-28 00:25 UTC codemem's own files on `main` (`722ded5`) are still those of `463171c`: only `docs/` and `eval/` changed since.
- If the lock names `463171c`, nothing is built again and the check run can start at 01:00 UTC as armed.
- If it names another commit, the start moves by the time your rebuild of the six check tasks takes. Andre accepts a slight delay.

## Checked

`git diff --stat 463171c origin/main -- . ':(exclude)eval' ':(exclude)docs'` prints nothing at `722ded5`.

## Left

The lock entry, at 00:45 UTC.

## Blocked on, or needed from others

Nothing.

## Next

The lead: the lock entry at 00:45 UTC.
