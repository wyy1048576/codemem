# Track A, evaluation: status

**Owner:** Andrew. **Plan:** `docs/plan/track-a-evals.md` on `main`.
**Updated:** 2026-11-27 09:10 UTC, by Andrew (with Claude Code).

| | |
|---|---|
| Now | Fair tasks with L1 and L2: pandas 17, playwright 28, duckdb 41, kubernetes 20. ruff: group 1 running, 20 valid of 21 checked, not screened yet (it keeps its recipe; the disk is handled by an archive on D: and compaction). The commit to run is codemem `463171c`. Andre's points a to e on the task supply are decided (09:02 UTC). Full list: log entry of 09:10 UTC |
| Done | **Both setups run end to end.** On `main`: `cmeval generate` (#20), the grader (#21), the proxy (#22), review fixes and ripgrep (#23), the runner with step counts and score (#24), the `tool` setup with codemem in the container (#25, `77c6aa8`). Images rebuilt and validated again under the corrected rules. Decisions on the prompt frame, the tools and ripgrep are made. **The pilot batch is done (2026-11-25): 36 runs on both repos and both setups, 0 discarded, token counts equal on all; 5 of 6 pass conditions of §2.2 met; 0 of 18 `tool` runs called codemem at `light`, 4 of 5 at `strong`** |
| Behind | **The hard tier: no repo has a validated hard-tier task.** Medium tier short for pandas (3 of 6) and kubernetes (2 of 6). No check run yet |
| Next | 1. Andre's thread script on the quiet PC when ruff group 1 ends. 2. Screen of the ruff tasks, and the test of the text-only pre-screen on 112 screened tasks. 3. Hard tier: `-large.jsonl` candidates of pandas, duckdb, playwright, then the rest; stop at 4 fair a repo. 4. Medium tier for pandas and kubernetes. 5. vscode, home-assistant, trino. 6. The check run (24 Sonnet runs), when Andrew agrees |
| Machines | All builds and runs on the PC. Its disk file is 192 GB (guard limit 300); valid images go to the archive on D: (9 TB free) |
| Blocked on | nothing |
| Needs from other tracks | C: the thread script for the compact index (Andre, due 09:30 UTC). Nothing else |
| Gives to other tracks | For B: codemem's tool descriptions are paid on every turn (entry of 2026-11-25 09:34, point 3). Recipe traps and validation faults that every new recipe will meet (entries of 07:20 and 2026-11-25 09:34). The `cm3-full` hit files (for B1) |
| Dates | Nov 27, 20:00 UTC: codemem locked. Nov 30, 23:59: results frozen. Dec 1, 14:00: the presentation. Dec 7 or 8: the paper |
