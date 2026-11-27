# Track A, for Andre: points a to e are taken, with three changes. Ruff costs time but is not the bottleneck now; the hard tier is

- **Track:** A, for track C. Answers the entry of 2026-11-27 08:45 UTC
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-27 09:02 UTC
- **Work package:** A1 (the task supply)
- **Branch, commits, pull request:** none

## Done

**Andrew's decisions on points a to e.** A second review session read your entry against the plan and our records first.

- **a. Taken.** A tier stops at 8 fair tasks (easy), 6 (medium) and 4 (hard). Note: the hard tier has no spares at 4. We check candidates in the seeded order, so the stop does not bias the arms. The paper gives each fair share as a share of the candidates checked. Our old warnings "early below 25, short below 20" are dropped. The floor of 12 stays.
- **b. Taken for ruff only, after a test.** We read the 112 screened duckdb and kubernetes tasks again without the test lists, and count the tasks that change from fair to unfair. We use the pre-screen only if that count is near zero. A candidate is not built only when both reads say unfair with high confidence. The paper reports this filter and its counts. The 18 valid ruff tasks get the full screen first.
- **c. Taken.** The hard tier first, then medium, then easy.
- **d. Taken, but no deletion.** The images of the tasks we do not choose leave Docker, and their compressed files stay in the archive on D: (about 4 GB each, 9 TB free). Reasons: spares, a possible version 2 of the screen rules, the search measures (they use all valid tasks), and the exact image that was validated. We compact the disk file after the removal.
- **e. Taken, in a new order.** The PC is not idle: ruff runs now, with its old recipe. The shared layer was measured and dropped (it saves 10 to 15%). The hard-tier candidates come after the ruff group. The check run waits for Andrew.

**The commit to run is `463171c`.** We move the PC's run checkout to it before any run.

**Ruff: what the PC shows.**

- Yes, each candidate compiles. To validate a task, we must build its image and run its tests before and after the fix. For ruff, that means a compile of the Rust workspace in each image: 798 s on average over 17 builds, 2 at a time, so about 7 minutes per task.
- The disk problem was real at 02:48 UTC. The disk file grew from 154 to 245 GB in 75 minutes, and the guard stopped the job. The fix: a compaction, then the 92 old pandas images went from Docker to the archive (75 saved, 0 failed). New builds now reuse that space. The disk file stayed at 192 GB from 06:23 to 09:00 UTC, through 12 ruff builds.
- Ruff now: 19 checked, 18 valid (by label: 6 easy, 6 medium, 7 hard). In the run tiers that is 12 easy and 6 medium. The group stops at about 15 new tasks (soon). Then the two screen reads follow; they need no PC.
- **The real gap is the hard tier.** No repo has a validated hard-tier task yet. Point c puts it first after ruff.

## Checked

- Build times, counts and disk sizes from `val-ruff.log`, `diskguard.log` and `ruff-g1.log` on the PC.

## Left

- Track A: the screen of the ruff tasks; the test of the text-only pre-screen; the hard-tier candidates.

## Blocked on, or needed from others

- Nothing.

## Next

- Track A, as above.
