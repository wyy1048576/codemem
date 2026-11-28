# For track B: Andre's go-ahead for job 1. Pull the branch of PR #90 and run kubernetes at L0, L1 and L2, with the compact index and with the exact one

- **Track:** shared: from the lead, for track B
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 01:42 UTC
- **Work package:** B8; `docs/plan/runs.md` §12
- **Branch, commits, pull request:** `andre/eval-vector-backend` at `a6653cb`, now PR #90 (https://github.com/wyy1048576/codemem/pull/90). **It is open on purpose and will not be merged:** run the eval from this branch. codemem stays at `463171c`

## Done

**Andre's go-ahead: start job 1 now.**

1. **Pull the branch of PR #90** (`git fetch origin andre/eval-vector-backend`) and run the eval from it. It is `main`'s eval plus the switch `CMEVAL_CODEMEM_VECTOR_BACKEND`. The codemem checkout that the runs use stays at `463171c`.
2. **Run kubernetes at L0, L1 and L2 with the compact index,** and the same with the exact index, so that the two can be compared on your machine: the 8 run tasks, Haiku once and Sonnet once, 96 runs in all (`docs/plan/runs.md` §12). The exact commands for both arms are in our entry of 01:35 UTC.
3. **The three conditions stand:** your agent at its highest setting, exactly as track A runs, and a question in this log before any assumption.

**You do not have to wait for an answer from us before you start. But two posts come early, and one rule stops the runs.**

- **Post, as soon as you know it: every difference between your machine or setup and track A's** (the system, Docker, the GPU inside the container, the Claude Code version, anything you had to change to make a step run).
- **Post the five checks of the first run of the compact arm** (our entry of 01:35 UTC, "What the first real run of the compact arm must show") before the other runs go on.
- **Stop and ask here, and do not work around it, if** a command of the entry of 01:35 UTC does not run as written, one of the five checks fails, a step of track A's pipeline cannot run on your machine (the images, the GPU in the container, the grader), or a difference touches what is measured. Runs made in another way do not count.
- **If your machine cannot do it at all, say so at once.** Do not put your own harness in its place.

**Job 2 (the plan for v3 against v2) is not part of this go-ahead.** It still needs its plan and our answer first.

## Checked

PR #90's head is `a6653cb`, the commit of our entry of 01:35 UTC.

## Left

Nothing on our side.

## Blocked on, or needed from others

- **Track B:** the two posts above, then the runs and their report.
- **Track A:** nothing; an answer here if track B's agent asks how a step of the pipeline is run.

## Next

Track B: job 1.
