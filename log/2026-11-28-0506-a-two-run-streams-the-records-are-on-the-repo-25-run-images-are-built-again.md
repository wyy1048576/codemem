# Track A: two run streams from 05:03 UTC; the check run's records are on the repo; 25 run images are built again

- **Track:** A, for the lead and the team
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 05:06 UTC
- **Work package:** A12 (the runs), A9 (tasks)
- **Branch, commits, pull request:** none. Release `run-records` on the repo

## Done

**1. Andrew's decision: two streams of runs at the same time, one per seat.** One stream needs about 32 hours for the rest of Haiku's repetition 1; the plan does not fit in the 75 hours to the freeze that way. The timings get somewhat noisier; he accepts that.

| Stream | Seat first | Steps, in order | Since |
|---|---|---|---|
| 1 | `claude-token` | pandas, ruff, duckdb-large, duckdb | 05:02:43 UTC (pandas began at 04:16 UTC in one stream) |
| 2 | `claude-token-2` | home-assistant, home-assistant hard, playwright hard, playwright, kubernetes | 04:55:33 UTC |

- The two runs of a pair (`grep` and `codemem` of one task) are back to back in the same stream, as before. A step is never in both streams.
- A stream takes the other seat when its own is at a limit.
- Each run has its own proxy port, container name and index copy, so two streams do not share anything but the PC and the GPU.

**2. The check run's records are on the repo: release `run-records`** (Andrew chose the repo). `gh release download run-records -R wyy1048576/codemem` gives `check-run-haiku-half.tgz` (24 runs) and `check-run-sonnet-half.tgz` (24 runs). Release files, not commits, so a clone does not grow. Later batches go to the same release, one archive per finished repo. The records hold the account's limit headers, request ids and the PC's host name; no token, no email.

**3. Images of 25 run tasks are in neither Docker nor the archive: playwright 7, duckdb 10, kubernetes 8.** They are tasks of the first batches, built before the archive existed, and removed later to free the disk. The tasks are valid; only the images are gone. They are built again on the build daemon without a new validation (`cmeval generate --rebuild`), in this order: kubernetes (2 of 8 done, about 15 minutes each), playwright, duckdb. A stream that reaches a step whose images are missing waits and looks again every 5 minutes; it does not stop. The steps are ordered so that the waiting is short: stream 2 began with home-assistant, stream 1 takes duckdb last.

**4. One fault of mine, and its fix: builds took all 16 cores for 90 seconds beside a timed run.** The first kubernetes builds on the new build daemon started at 04:41 UTC with no CPU limit. From 04:42 to 04:43:30 UTC the load was 15 to 38. I stopped them. The build daemon and everything it starts is now in one group with a hard CPU limit (first 4 cores, 6 since 04:56 UTC; tested: a busy build was held at exactly the limit).

- **The run it touched:** pandas 69924, `codemem`, L0 (04:40 to 04:45 UTC, 303 s). Its pair partner (`grep`, 439 s) ran after it, with builds at the limit. I leave the pair in; the record shows the load. Say if you want it run again.
- **The load value in a record now means less.** The load average counts build processes that wait at their limit, so records show a load of 15 to 45 while 8 of the 16 cores are in use. `~/.cmeval/logs/pressure.log` on the PC has the cores really in use, every 30 seconds, with the number of build jobs. The analysis should mark runs from that log, not from the load in the record. I will add it to the archives.

**5. Two more set-aside folders, with no agent time in them.** `haiku-pandas-L0`: pandas 71232 `grep` and pandas 69779 `grep`, each `1.discarded-1`. I stopped stream 1 twice right after a run had ended, to change its step list; the next run was in its preparation. Both were run again at once.

## Checked

- Both streams write runs (pandas 9 of 18 at L0 at 05:04 UTC; home-assistant is loading its 8 images from the archive).
- The release lists both files with the sizes of the local archives.
- The CPU limit: `cpu.max` of the group, and a test build with 8 busy processes held at 399% of one core.

## Left

- The 23 other images. The new home-assistant and ruff candidates come after them in the build queue.

## Blocked on, or needed from others

- **Andre:** the three points of the entry of 04:45 UTC (price table, runs at a limit, the side batch with bodies).

## Next

A report when pandas and home-assistant are done, about 4 to 5 hours from now.
