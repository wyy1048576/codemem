# Track A, evaluation: status

**Owner:** Andrew. **Plan:** `docs/plan/track-a-evals.md` on `main`.
**Updated:** 2026-11-23 00:23 UTC, by Andrew (with Claude Code). Nothing is built yet.

| | |
|---|---|
| Now | ready to start the admission check of plan §8.2 on pandas |
| Done | the plan checked against the code, the run logs and the primary pages; the `cm3-full` hit files of the October runs on `main` (`84b0088`); a GitHub probe of the repos that are not collected yet (pull request #19) |
| Next | 1. A recipe for pandas, and its admission check on 10 sampled tasks. 2. The same for playwright. 3. A9: the build and validate steps of the generator, for these two repos. 4. A1 and A2 beside it: the pipeline skeleton, the recording proxy and the cross-check against `modelUsage` |
| Blocked on | nothing. Our own images run on the Mac. The five SWE-bench-Live control tasks need x86: Andrew's home PC (Windows, Docker through WSL 2), set up on Mon Nov 23 |
| Needs from other tracks | B: `codemem-today` tagged, Nov 23. Andre: review of pull request #19. The team: a Java repo in place of kafka, which cannot be collected (see the log) |
| Gives to other tracks | the `cm3-full` hit files (for B1); the checked facts in the log entries of 2026-11-22 (public task dates, Claude Code token fields, Nebius limits, October index cost, the repo probe) |
| Dates | Nov 25: tasks for the first two repos, and the pipeline's first version. Nov 27: the first end-to-end test. Dec 1: results on every repo that is up. Dec 8: the paper on arXiv |
