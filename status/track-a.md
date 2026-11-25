# Track A, evaluation: status

**Owner:** Andrew. **Plan:** `docs/plan/track-a-evals.md` on `main`.
**Updated:** 2026-11-25 22:47 UTC, by Andrew (with Claude Code).

| | |
|---|---|
| Now | nothing runs. Decided: two more arms, `tool-note` (B) and `tool-hooks` (C), from the real `codemem init`. The build waits for Andrew's go |
| Done | **Both setups run end to end.** On `main`: `cmeval generate` (#20), the grader (#21), the proxy (#22), review fixes and ripgrep (#23), the runner with step counts and score (#24), the `tool` setup with codemem in the container (#25, `77c6aa8`). Images rebuilt and validated again under the corrected rules. Decisions on the prompt frame, the tools and ripgrep are made. **The pilot batch is done (2026-11-25): 36 runs on both repos and both setups, 0 discarded, token counts equal on all; 5 of 6 pass conditions of §2.2 met; 0 of 18 `tool` runs called codemem at `light`, 4 of 5 at `strong`** |
| Behind | the full runs of Nov 26 are at risk: no Sonnet run yet, 18 tasks, and no agent calls codemem at the `light` wording |
| Next | 1. Build arms B and C; adoption batch of 54 Haiku runs (18 tasks x A, B, C) on `041124e`. 2. The same tasks with Sonnet, 3 repetitions, in the arm the batch points to. 3. 60 candidates validated per repo, and the task file. 4. Recipes for ruff, kubernetes, duckdb |
| Machines | pandas and playwright: the PC. The Mac builds nothing at present: its Docker cannot pull images. Free disk on the PC: 867 GB of the virtual disk, 454 GB real |
| Blocked on | nothing |
| Needs from other tracks | B: the `codemem-today` tag (`3d9f42b` is used until then); the tool names and wording for the `tool` setup. Help, if someone has time: a recipe for ruff, kubernetes or duckdb. **Nothing else.** The three eval design points (prompt frame, Claude Code's own tools, ripgrep in the images) are track A's own decisions; see the correction of 2026-11-25 09:42 |
| Gives to other tracks | For B: codemem's tool descriptions are paid on every turn (entry of 2026-11-25 09:34, point 3). Recipe traps and validation faults that every new recipe will meet (entries of 07:20 and 2026-11-25 09:34). The `cm3-full` hit files (for B1) |
| Dates | Nov 25 evening: `codemem-final` frozen; tasks for the first two repos. Nov 26: the full runs start (at risk by about one day). Nov 30, 23:59: results frozen. Dec 1, 14:00: the presentation. Dec 7: the paper |
