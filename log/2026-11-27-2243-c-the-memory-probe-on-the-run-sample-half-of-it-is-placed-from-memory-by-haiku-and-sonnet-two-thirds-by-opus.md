# Track C: the memory probe on the run sample. Haiku and Sonnet name the right file from memory in half of the sessions, Opus in two thirds

- **Track:** C
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 22:43 UTC
- **Work package:** `docs/plan/runs.md` §11, point 2 (the memory probe)
- **Branch, commits, pull request:** none. The probe is a script on Andre's laptop; its results are in `2026-11-27-2243-c-data/` beside this entry

## Done

**What was run.** The L2 request of each of the 61 run tasks (`eval/tasks/run-sample-v1.jsonl` on `main` at `414e2b1`) went to Haiku 5.5, Sonnet 5.5 and Opus 5.5 with no repository and no tools: one `claude -p` call in an empty folder. The model is told which open-source repository the request is about and that it cannot look at it, and it names up to 3 files and 5 functions where the change has to be made, the most likely first. Three sessions of each task and model, 549 in all.

**The result: sessions in which the first file named is a gold file.**

| Repo (tasks) | Haiku | Sonnet | Opus |
|---|---|---|---|
| pandas (9) | 25 of 27 | 25 of 27 | 23 of 27 |
| ruff (9) | 11 of 27 | 14 of 27 | 15 of 27 |
| duckdb (14) | 9 of 42 | 10 of 42 | 21 of 42 |
| playwright (14) | 19 of 42 | 20 of 42 | 21 of 42 |
| home-assistant (7) | 14 of 21 | 12 of 21 | 18 of 21 |
| kubernetes (8) | 12 of 24 | 13 of 24 | 22 of 24 |
| **all (61)** | **90 of 183 (49%)** | **94 of 183 (51%)** | **120 of 183 (66%)** |

- **A model mostly knows a task's place or does not.** Tasks by how many of their three sessions were right (3, 2, 1, 0): Haiku 24, 7, 4, 26. Sonnet 27, 4, 5, 25. Opus 37, 3, 3, 18.
- **Taking 2 or 3 of 3 as "placed from memory":** Haiku 31 of 61 tasks, Sonnet 31, Opus 40. All three models place 26 tasks, and none of them places 18.
- **Haiku and Sonnet are alike on the file and apart on the function.** The right function by its full name, on the 43 tasks whose record has a gold function: Haiku 50 of 129 sessions, Sonnet 79, Opus 94.
- **A gold file among the three files named:** 109, 111 and 129 of 183 sessions.
- **By tier, right file first:** easy 49, 54 and 72 of 108 sessions; medium 30, 33 and 34 of 60; hard 11, 7 and 14 of 15. The 5 hard-tier tasks are not harder to place from memory than the others.

**What it says about the runs.**

- With the L2 request alone, Haiku and Sonnet already name the right file in about half of the sample, and Opus in two thirds. A search can save little there. The room for codemem is in the rest: the tasks a model never placed are 26 for Haiku, 25 for Sonnet and 18 for Opus.
- **duckdb holds most of that room for Haiku and Sonnet:** 9 and 10 of its 14 tasks were never placed. pandas holds none of it for them.
- **The six tasks of the check run:** the three of pandas (68278, 68945, 68090) were placed by every model in every session. The three of playwright were mostly not: 42204 by Opus only, 43316 and 42260 by no model in 2 or 3 sessions. So a gain in the check run, if there is one, should show on its playwright tasks, not on its pandas tasks.
- The probe is at L2 only. At L0 and L1 the request says more, so the shares there are probably higher. They were not measured.

**The data, for a split of the run pairs by task and model.**

- `2026-11-27-2243-c-data/memory-probe-by-task.jsonl`: one row per task and model (183 rows): `sessions` (3), `right_file_first` (0 to 3), `right_file_among_three`, `right_function_full` (null when the task's record has no gold function), `first_files` (the first file of each session), `gold_files`, `tier`.
- `2026-11-27-2243-c-data/memory-probe-sessions.jsonl`: one row per session (549 rows) with the model's whole answer.

## Checked

- All 549 sessions finished with a usable answer. Each was answered by the model asked for, with no tools and no MCP server, and with nothing of our project in its first request (the gate of the sessions of Nov 26).
- **How steady one session is:** session 1 against the session of Nov 26, on the 40 tasks probed on both days with the same request: the same verdict in 34 of 40 for Haiku, 36 for Sonnet and 38 for Opus. That is why each task now has three sessions.
- A file counts as right only when its path equals a gold file's path (a leading repo name is dropped).
- The 122 L1 and L2 prompts of the 61 run tasks were searched for the gold files' paths and names and for the gold functions' names: no prompt names a gold file, and where a file's stem appears it is the ordinary word of the request ("sas7bdat", "clock", "describe").
- Not checked: L0 and L1 on this sample; the function for ruff and kubernetes (their task records hold no gold function).
- Cost: 1.84 million tokens, of which 1.43 million were cache reads, on Andre's subscription from his laptop. No seat of the PC was used.

## Left

- vscode and trino, when they join the sample: the probe is run again, and sessions already made are skipped.
- The scripts (`closed.py`, `closed_sample.py`, `closed_sample_report.py`) are on Andre's laptop. They go on a branch when the analysis wants them in the repo.

## Blocked on, or needed from others

Nothing.

## Next

Track C: the entry on the lock at 00:30 UTC.
