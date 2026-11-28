# Track A: stream 1 stood still for 40 minutes. ruff's 9 images are 155 GB, and their load brought the PC's disk file close to its guard. ruff now runs in two parts. Nothing is lost

- **Track:** A, for the lead. A fault of our launcher, told at once
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 09:10 UTC
- **Work package:** A12 (the runs)
- **Branch, commits, pull request:** none

## Done

**1. What happened.**

- After the pandas 69924 pair, stream 1 began to load the images of ruff's 9 run tasks at 08:29 UTC. Our launcher loads all images of a repo before its first batch.
- A ruff image is 16.5 to 18 GB in Docker (the compiled Rust code is in it). The 9 are 155 GB. We had not looked at that sum.
- The file of the PC's Linux disk grew from 293 GB to 385 GB in 33 minutes. It does not shrink again without a stop of everything. Its guard is at 420 GB: there it stops both run streams, because drive C: has about 100 GB left.
- At 09:01 UTC the builds' own guard (380 GB) stopped the image builds. That is how we saw it.
- At 09:03 UTC we stopped stream 1 by hand, with 8 of the 9 images loaded. **No run was active in stream 1, and stream 2 (home-assistant) went on without a break.**

**2. What we did.**

- **ruff runs in two parts:** first the 8 tasks whose images are loaded (L0, L1, L2), then their images leave Docker, then the ninth task (27700). The run ids stay `haiku-ruff-L0`, `-L1`, `-L2`. Both setups of a task are in the same batch, as before.
- Stream 1 started again at 09:09 UTC and is in ruff L0. It lost 40 minutes (08:29 to 09:09 UTC) and no run.
- The builds started again at 09:09 UTC; their guard is now at 415 GB. Builds cannot make the disk file grow: they write to the build daemon's fixed file. Only 2 of duckdb's 10 missing images are still to build.
- We removed the 6 playwright images from the run daemon to free room inside the disk file. **3 of them were not in the archive before** (tasks of the check run); they are saved now.

**3. What changes for the plan.** Nothing in the sample or the method. For the order: within ruff, the ninth task runs after the other eight at all three levels, not level by level with them.

**4. The disk from here.** The file stays at 385 GB; 337 GB are in use, and 135 GB of that are ruff's images, which go when part one is done. No other repo of the sample is near that size (kubernetes: 8 images of about 9 GB). vscode would be (14 images of 12.5 GB): we said at 08:06 UTC that it would run in two halves, and this confirms why.

## Checked

- The 8 loaded images have the ids of their archive records (`docker image inspect` against the record, one by one).
- Stream 1's log shows `8 in Docker already ... 0 failed` and the batch `haiku-ruff-L0` with 8 tasks; its first run is in preparation at 09:10 UTC.

## Left

- A watcher now also fires when the disk file reaches 404 GB.
- For Haiku's repetitions 2 and 3, the launcher needs the same two parts for ruff. Noted on our side.

## Blocked on, or needed from others

- Nothing new. Still open: your answer on the preparation step (our entry of 08:06 UTC, draft pull request #92).

## Next

- The reports on home-assistant and ruff.
