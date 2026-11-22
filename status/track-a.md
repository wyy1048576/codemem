# Track A, evaluation: status

**Owner:** Andrew. **Plan:** `docs/plan/track-a-evals.md` on `main`.
**Updated:** 2026-11-22 23:43 UTC, by Andrew (with Claude Code). Nothing is built yet.

| | |
|---|---|
| Now | the pilot repos are proposed in pull request #17, which waits for Andre's review |
| Done | the plan checked against the code, the run logs and the primary pages; the pilot proposal (plan §2.5 in the pull request); difficulty counts for our 3,788 tasks; candidate Go and Rust repos for our own task sets |
| Next | 1. Step 1 of the pilot: index pandas and playwright with the local model, and run the update-against-rebuild check. 2. A1: the pipeline skeleton, first on the localization tier. 3. A2: the recording proxy and the cross-check, against `modelUsage` |
| Blocked on | nothing for step 1. The graded pilot needs an x86 machine with Docker: Andrew's home PC (Windows, 16 cores, 64 GB, Docker through WSL 2). He sets it up on Mon Nov 23. Rule 5 of plan §2.2 is checked there first |
| Needs from other tracks | B: `codemem-today` tagged, Nov 23. Andre: review of pull request #17 |
| Gives to other tracks | the `cm3-full` hit files of the three October runs, on `main` since `84b0088` (for B1); the checked facts in `log/2026-11-22-2318-a-plan-review-and-pilot-proposal.md` (public task dates, Claude Code token fields, Nebius limits, October index cost). The pipeline's first version is due Nov 25 |
| Dates | Nov 25: the pipeline's first version. Dec 1: results on the dev tasks. Dec 8: the paper on arXiv |
