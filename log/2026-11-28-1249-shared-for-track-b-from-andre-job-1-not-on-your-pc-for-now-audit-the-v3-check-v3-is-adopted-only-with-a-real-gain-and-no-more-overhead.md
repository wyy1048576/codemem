# For track B, from Andre: job 1 does not run on your PC. For now, audit the v3 check and say whether you agree: v3 is adopted only with a meaningful gain and no more overhead

- **Track:** shared: from the lead, for track B. Answers your entries of 12:15 and 12:30 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 12:49 UTC
- **Work package:** B8 (job 1); the decision on PR #85 (v3)
- **Branch, commits, pull request:** the data of the v3 check: branch `andre/v3-check-data`, folder `v3-check/` (our entry of 06:55 UTC)

## Done

**1. Job 1 does not run on your PC** (Andre). Install nothing for it: no WSL, no Docker, no Arc route.

- **Wilson himself is looking into FarmShare,** a shared GPU cluster. If that does not work out, the last resort is Nebius, the GPU that Andre rents.
- **Check on FarmShare first:** the runner needs Docker containers with a GPU inside them. Shared clusters do not always allow Docker.
- **When the machine is settled, Andre posts how job 1 runs there.** Until then, nothing on job 1.
- PR #90's branch (`andre/eval-vector-backend`, now `64344a9`) has `main` merged in, and a switch for a machine whose containers cannot get a GPU (`CMEVAL_CODEMEM_DEVICE=cpu`, commit `331b767`). Whether it is used is decided with the machine.

**2. For now: audit the v3 check, and answer agree or dispute** (Andre). The entry of 06:55 UTC says what to check and what a dispute needs. It takes no heavy runs: one command recomputes every table, and `transcripts/` has every session.

**3. Andre's rule for PR #85: v3 replaces v2 only with a meaningful gain, and no more overhead.**

- **The gain must be larger than the run-to-run variation,** on the setup the evaluation runs (the tool plus the 20 lines), with no loss of quality.
- **If there is no such gain, or v3's overhead is higher, v3 is not adopted.** Its known overhead: 485 more input tokens in every request, and longer search arguments.

**4. Job 2 (an evaluation of v3) waits for the outcome of your audit.** Nothing runs for it now.

## Left

- Track B: the audit and your answer.
- Andre: the machine for job 1.

## Blocked on, or needed from others

- **Track B:** your answer on the v3 check, agree or dispute, with your findings.

## Next

- Andre decides on PR #85 after your answer, by the rule of point 3.
