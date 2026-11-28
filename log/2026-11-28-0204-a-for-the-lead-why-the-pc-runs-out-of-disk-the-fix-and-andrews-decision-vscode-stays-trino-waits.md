# Track A, for the lead: why the PC runs out of disk, the fix we take, and Andrew's decision: vscode stays, trino waits

- **Track:** A, for the lead. Answers Andre's questions to Andrew in the chat (about 01:55 UTC)
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 02:04 UTC
- **Work package:** A9 (tasks), A12 (the runs)
- **Branch, commits, pull request:** none. `main` at `739fbe3` (#88, #89 since our last entry)

## Done

**1. Where the space goes. It is the task images, not the indexes.**

- **Each task has its own image:** the repo at the task's commit with its whole test environment. One image: duckdb 0.8 GB, pandas 3.3, playwright 4.2, home-assistant 1.3 to 5.7, trino 6.6, ruff about 10, vscode about 12.
- **Far more images are built than tasks are run.** About 1 in 4 valid tasks passes the fairness screen, and about 1 in 10 of the hard tier. For the 64 run tasks we built and validated about 450 images. The archive of finished images is about 300 GB, compressed.
- **A build writes more than it keeps.** A vscode build writes its 12 GB image and about as much again in build cache. One vscode build beside two home-assistant builds wrote 47 GB in 21 minutes.
- **The WSL disk file only grows.** Space that is freed comes back only when WSL is shut down and the file is compacted, and that ends every job. So builds beside runs fill the disk, and no compaction is possible during a run. Six compactions on Nov 27.
- **The disks:** the SSD (2 TB, NVMe) holds the WSL disk file and has 280 GB free. The 10 TB disk is a hard disk; it holds the archive only.

**The indexes, as you asked.** Yes, the runs use the exact index, as the lock says. They are not the problem:

| | Size |
|---|---|
| All indexes, 137 tasks | 104 GB |
| Of them, the 64 run tasks | about 46 GB |
| The other 73 tasks | 58 GB, being moved to the hard disk now |

- One home-assistant index folder is 1.5 GB: `index.db` 836 MB, the two vector files 335 MB, and a copy of the source 350 MB. duckdb: 963 MB, of which the vector files are 210 MB.
- **So the vectors are about a fifth of an index folder.** The compact form can only shrink that part: at most about 20 GB over all 137 tasks. It does not change the picture.

**2. The fix we take, in the gap after the check run.** Checked with three independent advisers (Opus 5.5, Fable 5.2, Fable 5.1), who all chose it.

- **The runs change nothing:** the same Docker daemon on the SSD. Every run stays comparable.
- **Builds and validation get a second Docker daemon,** whose storage is one fixed file of 120 GB on the SSD. Builds use the same blocks again, so they cannot grow the disk file past that. A full file fails a build, never a run.
- Not taken: Docker on the hard disk (it would put the timed runs on a slow disk), and builds on the hard disk (several times slower, and tests in validation would time out).
- **For the methods:** disk pressure is logged during the runs, and each run is marked when a build ran beside it. The check run has no build beside it.
- If its test does not pass within 45 minutes, nothing changes and builds stay in the gaps between batches.

**3. Andrew's decision on the two repos that are not ready.**

- **vscode stays.** It is the repo where an index should show most, and it has the largest pool for the hard tier. It is the costliest: about 60 builds of 13 to 15 minutes for a sample. With the second daemon it can build beside the runs.
- **trino waits, and is dropped if the builds do not run ahead.** It adds a sixth language, 64 candidates, 17 minutes a build, 1 valid so far. Without it the table has 6 repos and 5 languages; with vscode, 7 repos.
- **Build order from now:** home-assistant (53 candidates queued), the hard tier of ruff (48 candidates, none built yet), vscode, the hard tier of kubernetes (8 candidates), then trino if time is left.
- If you want another order, or trino before something else, say so here.

**4. home-assistant has its first hard-tier task.** 1 fair of 16 in the first wave (#88), with prompts (#89). It runs 9 tasks: 6 easy, 2 medium, 1 hard. The sample has 64 run tasks now.

## Checked

- The disk types and the free space were read on the PC (`Get-PhysicalDisk`, `Get-Volume`). The index sizes were read from the index folders.
- The check run: 11 of 48 runs done at 02:02 UTC, none discarded or flagged.

## Left

The early report after the Haiku half of the check run.

## Blocked on, or needed from others

- **Andre:** nothing needed. Your word here if the build order or the trino decision should be different.

## Next

The early report. Then the second daemon in the gap after the check run.
