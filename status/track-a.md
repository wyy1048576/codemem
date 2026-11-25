# Track A, evaluation: status

**Owner:** Andrew. **Plan:** `docs/plan/track-a-evals.md` on `main`.
**Updated:** 2026-11-25 05:50 UTC, by Andrew (with Claude Code). Nothing of the pipeline is built yet.

| | |
|---|---|
| Now | the pandas recipe and its admission check (plan §8.2), on the PC. Then playwright, on the Mac |
| Done | both machines are set up and checked: the M5 Mac and the PC (x86, WSL 2, Docker, RTX 3060 Ti, 118 texts per second in the speed check). The Mac session drives the PC over SSH. Earlier: the plan review, the `cm3-full` hit files on `main` (`84b0088`), the repo probe (in `3d9f42b`) |
| Behind | the rows of the run sheet (§14.3) for Nov 22 and Nov 23 are not done. Work starts now with the Nov 22 row. The first end-to-end test moves to Nov 25 or 26 |
| Next | 1. Admission checks for pandas and playwright. 2. A9: the build and validate steps of the generator, 30 or more validated tasks per repo. 3. A1 and A2 beside it. 4. ruff, kubernetes, duckdb |
| Machines | pandas: the PC. playwright: the Mac. Most indexing: the PC. The SWE-bench-Live control tasks: the PC. Free disk: 454 GB on the PC's SSD, 556 GB on the Mac |
| Blocked on | nothing |
| Needs from other tracks | B: the `codemem-today` tag (not on `origin` yet; `main` at `3d9f42b` is used until then). The team: a Java repo in place of kafka, no date |
| Gives to other tracks | the `cm3-full` hit files (for B1); the checked facts in the log entries of 2026-11-22 |
| Dates | Nov 25 evening: `codemem-final` frozen; tasks for the first two repos. Nov 26: the full runs start (at risk by about one day). Nov 30, 23:59: results frozen. Dec 1, 14:00: the presentation. Dec 7: the paper |
