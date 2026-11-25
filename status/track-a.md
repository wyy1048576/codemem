# Track A, evaluation: status

**Owner:** Andrew. **Plan:** `docs/plan/track-a-evals.md` on `main`.
**Updated:** 2026-11-25 07:20 UTC, by Andrew (with Claude Code).

| | |
|---|---|
| Now | validation of more pandas and playwright tasks (60 candidates each), and the pipeline skeleton (A1) with the recording proxy (A2) |
| Done | **pandas and playwright pass the admission check** (10 of 10 and 8 of 10 valid). `cmeval generate` and both recipes are on `main` (`e5c8ec0`, pull request #20). Both machines are set up; the Mac session drives the PC over SSH |
| Behind | about two days against the run sheet (§14.3). The first end-to-end test is aimed at Nov 25 or 26 |
| Next | 1. The task file with validated tasks for the two repos. 2. A1 and A2, with bring-up runs. 3. Recipes for ruff, kubernetes, duckdb |
| Machines | pandas and playwright: the PC. The Mac builds nothing at present: its Docker cannot pull images. Free disk on the PC: 867 GB of the virtual disk, 454 GB real |
| Blocked on | nothing |
| Needs from other tracks | B: the `codemem-today` tag (not on `origin` yet; `main` at `3d9f42b` is used until then). The team: a Java repo in place of kafka, no date |
| Gives to other tracks | the `cm3-full` hit files (for B1); the checked facts in the log entries of 2026-11-22 |
| Dates | Nov 25 evening: `codemem-final` frozen; tasks for the first two repos. Nov 26: the full runs start (at risk by about one day). Nov 30, 23:59: results frozen. Dec 1, 14:00: the presentation. Dec 7: the paper |
