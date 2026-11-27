# Track A: the table for duckdb and kubernetes (41 and 20 fair, all with L1 and L2); ruff is stopped by disk; what happened to the PC

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-27 05:40 UTC
- **Work package:** A1, A2, A9
- **Branch, commits, pull request:** `main` at `8a8dbee`: #62 (screen reads of duckdb and kubernetes), #63 (an archive for task images, no crash dumps), #64 (vague prompts for duckdb and kubernetes)

## Done

**1. Fair tasks per repo, in the tiers of `docs/plan/runs.md`** (easy tier = today's labels `easy` and `medium`; medium tier = today's label `hard`). Two reads per valid task under `screen-rules-v1.md`, a third where they disagree.

| Repo | Validated | Valid | Fair, label `easy` | Fair, label `medium` | Easy tier (wanted 6, stop at 8) | Medium tier (wanted 4, stop at 6) | Hard tier | Fair tasks with L1 and L2 |
|---|---|---|---|---|---|---|---|---|
| pandas | 100 | 92 | 9 | 5 | 14 | **3** | 15 candidates, not validated | 17 of 17 |
| playwright | 60 | 49 | 11 | 9 | 20 | 8 | 27 candidates, not validated | 28 of 28 |
| duckdb | 60 | 58 | 15 | 15 | 30 | 11 | 19 candidates, not validated | 41 of 41 |
| kubernetes | 58 | 54 | 13 | 5 | 18 | **2** | 4 candidates, not validated | 20 of 20 |
| ruff | 7 of 60 | 7 | screen not started | | | | 48 candidates | 0 |

- **Kept share per label** (Andre's question whether the screen removes more of the larger fixes): duckdb easy 15 of 17, medium 15 of 23, hard 11 of 18; kubernetes easy 13 of 18, medium 5 of 21, hard 2 of 15. Yes for kubernetes, as for pandas; less so for duckdb and playwright.
- **Warnings.** The medium tier is short for pandas (3) and kubernetes (2); neither has candidates with the label `hard` left to validate (pandas 8, kubernetes 0). By the plan's rule they run more easy-tier tasks. kubernetes cannot reach a hard tier (4 candidates).
- Agreement of reads 1 and 2: duckdb and kubernetes 108 of 112 (kappa 0.93); pandas and playwright 135 of 141 (0.90).
- Prompts: `eval/tasks/vague-b7-v3.jsonl` (pandas, playwright) and `eval/tasks/vague-b10a-v3.jsonl` (duckdb, kubernetes), both under `vague-rules-v3.md`, each reviewed by a second reader against issue, fix and tests.

**2. ruff is stopped, by disk.** A ruff task image is 16.5 GB, because every task compiles the whole workspace in its own layer. 7 of the 60 candidates are validated (all valid). The recipe is being changed so that the compiled output of a reference commit is a layer that the tasks share; the same for the Go build cache of kubernetes. ruff runs again after that, so its table is about a day late.

**3. What happened to the PC** (for the methods section, and so that nobody is surprised):
- The drive that holds Docker's data filled twice on Nov 26. Cause one: the virtual disk file grows with every image build and does not shrink when images are removed. Cause two: duckdb's `unittest` crashed in a validation container and WSL wrote three crash dumps of 47 GB each.
- Repaired: the disk file is compacted, the dumps are deleted, every container of the pipeline now runs with `--ulimit core=1:1` (no dump), and finished task images go to an archive on a second drive (`cmeval images save|load|list`) and come back as the validated image itself, not a rebuild.
- No record was lost. The validations of duckdb and kubernetes had ended before the stop.

## Checked

- The table: `cmeval e2e screen-table` on `eval/tasks/screen/b7.jsonl` and `b10a.jsonl`, tiers from `generate.tier`.
- The archive: one image saved, removed and loaded on the PC; the loaded image id equals the saved one.
- Not checked: no hard-tier candidate is built yet.

## Left

- **Runs 3 and 4 of Andre's entry of Nov 26, 11:32 UTC, are still not done.** The PC was either busy or stopped. They go first when it runs again; they need a quiet machine.
- ruff 60 with the new recipe; admission of vscode, home-assistant, trino; hard-tier validation.
- Andrew's decisions on the entry of Nov 26, 13:52 UTC (queue order, stop rule, check run).

## Blocked on, or needed from others

- Nothing from tracks B and C.

## Next

- Track A: the ruff recipe, then the PC queue; runs 3 and 4 before it.
