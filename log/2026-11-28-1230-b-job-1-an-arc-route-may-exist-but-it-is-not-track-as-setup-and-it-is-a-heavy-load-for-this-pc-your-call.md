# Track B: job 1 on this PC. A route through its Intel Arc GPU may exist, but it is not track A's setup, it is unproven, and it would hold the PC for a day and a half. Your call; we wait

- **Track:** B. Follows our entry of 12:15 UTC (this PC has no NVIDIA GPU and no Docker)
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-28 12:30 UTC
- **Work package:** B8; `docs/plan/runs.md` §12
- **Branch, commits, pull request:** none. Read: PR #90, `andre/eval-vector-backend` at `a6653cb`

## Done

**What running job 1 on the Arc would take.** Nothing of this is done; every point is a change from track A's setup.

1. **A Linux host inside the PC.** The runner mounts the host's codemem `.venv` into a Linux container, so the eval would run in WSL2, with Docker in WSL2. Neither is installed (an admin install and a restart).
2. **The Arc inside the container,** through WSL2's `/dev/dxg` and PyTorch's XPU build. Not tried in this pipeline; it may not work.
3. **Changes to the eval and to codemem's setup,** which your entry of 00:56 UTC asks us not to make ourselves: the runner's GPU device (`nvidia.com/gpu=all` in `e2e_run.py`), XPU torch in codemem's environment, and an embedder plugin for the Arc in place of CUDA float16.

**Whether the result would still answer §12.** Probably: both arms on one machine, the same embedder, only the index differs, and §12 already keeps these numbers apart from track A's. But it is not "exactly as track A runs".

**Estimated time, one step after another.** Not measured on this PC; the index is the least certain, since we have no chunk count for kubernetes.

| Step | Estimate | From |
|---|---|---|
| WSL2, Docker, the Arc in a container, the changes above | 2 to 4 h, may fail | first time |
| 8 kubernetes images (about 9 GB each) | 3 to 4 h | about 15 min each on track A's 16 cores; this PC has 8 |
| 8 indexes in both forms, each form's build timed from an empty cache | 4 to 8 h | pandas (37,489 chunks) took 28 min on the Arc |
| 96 runs and their grading | 13 to 19 h | track A's mean of about 5 to 6 min a run; kubernetes and Sonnet run longer |
| **Total** | **about 22 to 35 h** | the freeze is about 67 h away |

**Our concern: it is a heavy load for this PC.** It is a laptop (8 logical cores, 31.5 GB of memory, the GPU shares memory). Builds and timed runs cannot overlap (your entry of 07:05 UTC), so the PC would be busy for a day and a half with nothing else beside it, including the work for job 2 and our answer to your entry of 06:55 UTC. Disk is not the problem (361 GB free).

## Checked

The runner's GPU and mount code on `a6653cb`; this PC's GPU, cores, memory and disk.

## Left

Job 1, as you decide.

## Blocked on, or needed from others

**Andre, one of:**
1. **Job 1 on another machine** with an NVIDIA GPU and Docker (ours has none);
2. **the Arc route on this PC,** approving the changes in points 1 to 3, knowing it may fail at point 2 and holds the PC for about 22 to 35 h;
3. **a smaller job 1** that you name (for example fewer tasks or one model), on either route;
4. **job 1 dropped.**

We do nothing on job 1 until you answer.

## Next

Wilson, with Claude Code: the answer to your entry of 06:55 UTC.
