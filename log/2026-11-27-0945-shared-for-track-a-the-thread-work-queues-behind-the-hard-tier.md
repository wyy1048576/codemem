# For track A, from Andre: the thread work queues behind the hard tier. It changes the order of our two entries of 09:25 and 09:35 UTC, nothing else

- **Track:** shared: from track C's session, for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 09:45 UTC
- **Work package:** A1 (the task supply) first; C2 after it
- **Branch, commits, pull request:** none

## Done

**Andre's order for tonight: the hard tier first, and nothing beside it that competes for the PC.** You said it yourself at 09:02 UTC: the real gap is the hard tier. The thread work is ours, it does not touch the runs, and it can wait. Andrew is likely asleep until the morning, so this is written so that you can follow it without asking.

**What that means for your list of 09:10 UTC:**

- **Step 3 (our thread script) moves behind step 6 (the hard tier).** Do not hold the start of a hard-tier build for it, and do not time anything while a build runs: both would be slower, and the timings would mean nothing.
- **The one exception:** if at some moment no build is running and none is waiting to start (a gap between groups, or the builds are done and the screen reads go on without the PC), the script's first run fits there. It takes 3 to 4 minutes and only measures.
- **The fix and parts 2 and 3** (our entries of 09:25 and 09:35 UTC) come after the hard-tier candidates of pandas, duckdb and playwright are built and validated. Reading the code and writing the change may go on beside the builds, as long as nothing of it is timed or run in a container meanwhile.
- **If the night ends before any of it:** one line in your next entry, and it waits for the runs to be under way. That is fine.

**One suggestion for the same night, yours to take or leave.** The check run and the first runs need each chosen task's index built with `463171c`. The easy and medium tasks of pandas, playwright, duckdb and kubernetes are chosen already. If their indexes can be built beside the hard-tier builds without slowing them (they need the model and the vector cache, not Docker's disk), the runs can start as soon as Andrew says go, with no index build in front of them. If it would slow the builds, leave it: the hard tier is first.

## Checked

- Nothing new was measured for this entry.

## Left

- On our side: the remaining commits on `andre/compact-threads` (the `--check` flag, the plan's paragraph, two candidate fixes). They wait for you there.

## Blocked on, or needed from others

- Nothing. The decisions that are Andrew's (the check run, more pandas candidates) stay his.

## Next

- Track A: the hard tier; then the thread work, in the order above.
