# Track B: job 1 (kubernetes, the exact and the compact index) acknowledged, late. This PC cannot run it as track A runs: it has no NVIDIA GPU and no Docker. Stopped, as the entry of 01:42 UTC asks

- **Track:** B. Answers the entries of 00:56, 01:29, 01:35 and 01:42 UTC (job 1), and notes those of 06:55 and 07:05 UTC
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-28 12:15 UTC
- **Work package:** B8; `docs/plan/runs.md` §12
- **Branch, commits, pull request:** none. Read: PR #90, `andre/eval-vector-backend` at `a6653cb`

## Done

**Both jobs confirmed.** Job 1: v2 on kubernetes, exact against compact index, 96 runs, from PR #90's branch, exactly as track A runs. Job 2: a plan for v3 against v2 on 1 or 2 repos, posted before any run; it now waits for our answer to your check of 06:55 UTC.

**Late:** the feasibility post was due about 01:56 UTC. Our apology; we missed the entries of 00:56 to 01:42.

**Feasibility: this PC cannot do job 1 as written.** Nothing was installed, changed or run.

| Needed (entry of 00:56 UTC, and the runner) | This PC |
|---|---|
| Docker with Linux containers | Not installed. WSL is not installed either |
| The GPU inside the container: the runner passes `--device nvidia.com/gpu=all` (CDI, `e2e_run.py`) and refuses a codemem setup without it (`CMEVAL_E2E_GPUS=1`) | Intel Arc 140V (16 GB shared). No NVIDIA GPU, no `nvidia-smi`, no CDI spec |
| The index's embeddings in float16 on CUDA (`e2e_index.py`: on the CPU it embeds every text again, hours) | No CUDA. Our own indexes use an Arc plugin embedder (float16 on the GPU through XPU), which is not track A's setup |
| The kubernetes images and 8 indexes in both forms | 361 GB free on C:. 8 logical cores, 31.5 GB memory |

Docker Desktop and WSL could be installed here (an admin install and a restart), but that does not give the container an NVIDIA GPU, so the runner's codemem setup would still refuse to start. Any way round it (no GPU, the CPU, the Arc embedder) is our own setup, which the entry of 01:42 UTC rules out. So we stop here and ask.

**Other differences from track A, for the record:** Windows 11 Home, not Linux; Claude Code 2.1.314.

**The entry of 07:05 UTC (load and seconds) is noted** for any timed run of ours.

**The entry of 06:55 UTC (v3 against v2) is read.** Our answer, agree or dispute, comes in its own entry.

## Checked

`e2e_run.py` and `e2e_index.py` on `a6653cb` for the GPU requirement; `docker`, `wsl`, `nvidia-smi` and the video controller on this PC.

## Left

Job 1, on a machine that can run it.

## Blocked on, or needed from others

**Andre: how job 1 should run, given the above.** For example, on another machine of ours with an NVIDIA GPU and Docker, or with a deviation you name. We do nothing until you answer.

## Next

Wilson, with Claude Code: the answer to the entry of 06:55 UTC.
