# Track A, evaluation: status

**Owner:** Andrew. **Plan:** `docs/plan/track-a-evals.md` on `main`.
**Updated:** 2026-11-25 09:42 UTC, by Andrew (with Claude Code).

| | |
|---|---|
| Now | a bring-up batch on the 18 valid tasks (Haiku, `grep`). Rebuilding the step counts (searches, file views, gold file seen). Then the review fixes (#23) and the runner are merged |
| Done | **The pipeline runs end to end in the `grep` setup.** On `main`: `cmeval generate` (#20), the grader (#21, right on 18 of 18), the recording proxy (#22). pandas and playwright admitted. The runner works on real tasks (branch `e2e-runner`): the first run gave equal token counts from the proxy and from `modelUsage` |
| Behind | about two days against the run sheet (§14.3). The first end-to-end test is aimed at Nov 25 or 26 |
| Next | 1. Merge #23 and the runner; validate and grade again under the new rules. 2. The `tool` setup: codemem inside the container. 3. 60 candidates validated per repo. 4. The first end-to-end test of §2.2 (1 of 6 conditions met). 5. Recipes for ruff, kubernetes, duckdb |
| Machines | pandas and playwright: the PC. The Mac builds nothing at present: its Docker cannot pull images. Free disk on the PC: 867 GB of the virtual disk, 454 GB real |
| Blocked on | nothing |
| Needs from other tracks | B: the `codemem-today` tag (`3d9f42b` is used until then); the tool names and wording for the `tool` setup. Help, if someone has time: a recipe for ruff, kubernetes or duckdb. **Nothing else.** The three eval design points (prompt frame, Claude Code's own tools, ripgrep in the images) are track A's own decisions; see the correction of 2026-11-25 09:42 |
| Gives to other tracks | For B: codemem's tool descriptions are paid on every turn (entry of 2026-11-25 09:34, point 3). Recipe traps and validation faults that every new recipe will meet (entries of 07:20 and 2026-11-25 09:34). The `cm3-full` hit files (for B1) |
| Dates | Nov 25 evening: `codemem-final` frozen; tasks for the first two repos. Nov 26: the full runs start (at risk by about one day). Nov 30, 23:59: results frozen. Dec 1, 14:00: the presentation. Dec 7: the paper |
