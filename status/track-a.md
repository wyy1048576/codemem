# Track A, evaluation: status

**Owner:** Andrew. **Plan:** `docs/plan/track-a-evals.md` on `main`.
**Updated:** 2026-11-27 05:40 UTC, by Andrew (with Claude Code).

| | |
|---|---|
| Now | Fair tasks with L1 and L2: pandas 17, playwright 28, duckdb 41, kubernetes 20. ruff: 7 of 60 validated, then stopped by disk (16.5 GB per image); its recipe is being changed to a shared layer. The PC is idle until then. Task images go to an archive on a second drive (`cmeval images`). The runner warms codemem before the agent starts. Not started: vscode, home-assistant, trino, the hard tier, the check run |
| Done | **Both setups run end to end.** On `main`: `cmeval generate` (#20), the grader (#21), the proxy (#22), review fixes and ripgrep (#23), the runner with step counts and score (#24), the `tool` setup with codemem in the container (#25, `77c6aa8`). Images rebuilt and validated again under the corrected rules. Decisions on the prompt frame, the tools and ripgrep are made. **The pilot batch is done (2026-11-25): 36 runs on both repos and both setups, 0 discarded, token counts equal on all; 5 of 6 pass conditions of §2.2 met; 0 of 18 `tool` runs called codemem at `light`, 4 of 5 at `strong`** |
| Behind | Runs 3 and 4 for Andre (entry of Nov 26, 11:32 UTC). ruff about a day late. Medium tier short for pandas (3) and kubernetes (2). No run with codemem `09c4ef0` beyond one check; no check run yet |
| Next | 1. Admission check, then 60 candidates, for each new repo: ruff, duckdb, kubernetes, then home-assistant, airflow, vscode, vllm, then a Java or JavaScript repo. 2. Screen of all new valid tasks, two reads; the table per repo and difficulty goes to the log. 3. The `grep` arm on the 10 vague tasks at L1 and L2 (Haiku). 4. Arms `tool-note` and `tool-hooks` when track B is ready. 5. Sonnet, 3 repetitions, when codemem is locked |
| Machines | pandas and playwright: the PC. The Mac builds nothing at present: its Docker cannot pull images. Free disk on the PC: 867 GB of the virtual disk, 454 GB real |
| Blocked on | nothing |
| Needs from other tracks | B: the `codemem-today` tag (`3d9f42b` is used until then); the tool names and wording for the `tool` setup. Help, if someone has time: a recipe for ruff, kubernetes or duckdb. **Nothing else.** The three eval design points (prompt frame, Claude Code's own tools, ripgrep in the images) are track A's own decisions; see the correction of 2026-11-25 09:42 |
| Gives to other tracks | For B: codemem's tool descriptions are paid on every turn (entry of 2026-11-25 09:34, point 3). Recipe traps and validation faults that every new recipe will meet (entries of 07:20 and 2026-11-25 09:34). The `cm3-full` hit files (for B1) |
| Dates | Nov 25 evening: `codemem-final` frozen; tasks for the first two repos. Nov 26: the full runs start (at risk by about one day). Nov 30, 23:59: results frozen. Dec 1, 14:00: the presentation. Dec 7: the paper |
