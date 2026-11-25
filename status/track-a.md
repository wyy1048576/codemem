# Track A, evaluation: status

**Owner:** Andrew. **Plan:** `docs/plan/track-a-evals.md` on `main`.
**Updated:** 2026-11-25 09:00 UTC, by Andrew (with Claude Code).

| | |
|---|---|
| Now | the runner: the agent inside the task's container. Then bring-up runs with Haiku in the `grep` setup |
| Done | **pandas and playwright admitted** (10 of 10 and 8 of 10 valid; `cmeval generate`, `e5c8ec0`). **The grader is on `main`** (`a2c3655`) and is right on all 18 valid tasks: the real fix passes, an empty change fails. **The recording proxy** is on `main` (`0d3ff1b`) and agrees with `modelUsage` on a real run. Claude Code ran once inside a task container by hand: not root, clean settings, no internet, the model API through the proxy |
| Behind | about two days against the run sheet (§14.3). The first end-to-end test is aimed at Nov 25 or 26 |
| Next | 1. The runner and bring-up runs. 2. 60 candidates validated per repo, and the task file. 3. The `tool` setup: codemem inside the container. 4. Recipes for ruff, kubernetes, duckdb |
| Machines | pandas and playwright: the PC. The Mac builds nothing at present: its Docker cannot pull images. Free disk on the PC: 867 GB of the virtual disk, 454 GB real |
| Blocked on | nothing |
| Needs from other tracks | **Andre: two decisions before the main batch** (the prompt frame, and which of Claude Code's own tools stay on): see the log entry of 2026-11-25 09:00. B: the `codemem-today` tag (`3d9f42b` is used until then). The team: a Java repo in place of kafka, no date |
| Gives to other tracks | the `cm3-full` hit files (for B1); the checked facts in the log entries of 2026-11-22 |
| Dates | Nov 25 evening: `codemem-final` frozen; tasks for the first two repos. Nov 26: the full runs start (at risk by about one day). Nov 30, 23:59: results frozen. Dec 1, 14:00: the presentation. Dec 7: the paper |
