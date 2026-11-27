# Track A, evaluation: status

**Owner:** Andrew. **Plan:** `docs/plan/track-a-evals.md` on `main`.
**Updated:** 2026-11-27 19:40 UTC, by Andrew (with Claude Code).

| | |
|---|---|
| Now | **The check run is armed for Nov 28, 01:00 UTC**: 48 runs, `grep` and `codemem`, Haiku then Sonnet, codemem `463171c`, eval `main` `e69513a` or later. Run tasks with L1, L2, index and blocks: pandas 9, ruff 9, duckdb 14, playwright 14, kubernetes 8 (54 tasks, 162 blocks). The mount of the codemem checkout is fixed and proven (#77). Full report: log entry of 19:40 UTC |
| Done | **Both setups run end to end.** On `main`: `cmeval generate` (#20), the grader (#21), the proxy (#22), review fixes and ripgrep (#23), the runner with step counts and score (#24), the `tool` setup with codemem in the container (#25, `77c6aa8`). Images rebuilt and validated again under the corrected rules. Decisions on the prompt frame, the tools and ripgrep are made. **The pilot batch is done (2026-11-25): 36 runs on both repos and both setups, 0 discarded, token counts equal on all; 5 of 6 pass conditions of §2.2 met; 0 of 18 `tool` runs called codemem at `light`, 4 of 5 at `strong`** |
| Behind | The hard tier: only duckdb (4) and playwright (1) have fair hard-tier tasks; pandas has 0 of 15. vscode, home-assistant and trino are not ready: home-assistant is admitted and in validation, vscode's recipe is fixed (#79) and its admission runs again, trino's admission runs |
| Next | 1. The check run and its report (about 06:00 UTC on one seat). 2. If it passes: Haiku's repetition 1 on pandas, ruff, duckdb, playwright, kubernetes. 3. Screens, prompts and indexes of home-assistant, vscode and trino as their validation ends. 4. The audit of the measures from the check run's records |
| Machines | All builds and runs on the PC. Two login tokens (seats) with a rotation at a usage limit. The disk file is 255 GB (guard limit 300); valid images go to the archive on D: |
| Blocked on | nothing |
| Needs from other tracks | Andre: the lock hash at 00:30 UTC. Andre and Wilson: a login token each for the rotation, if they agree |
| Gives to other tracks | For B: codemem's tool descriptions are paid on every turn (entry of 2026-11-25 09:34, point 3). Recipe traps and validation faults that every new recipe will meet (entries of 07:20 and 2026-11-25 09:34). The `cm3-full` hit files (for B1) |
| Dates | Nov 28, 00:30 UTC: codemem locked; 01:00 UTC: the runs start. Nov 30, 23:59: results frozen. Dec 1, 14:00: the presentation. Dec 7 or 8: the paper |
