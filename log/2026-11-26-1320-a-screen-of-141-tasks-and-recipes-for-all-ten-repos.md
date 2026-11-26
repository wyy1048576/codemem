# Track A: screen of 141 pandas and playwright tasks; recipes for all ten repos are on main; duckdb admitted

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-26 13:20 UTC
- **Work package:** A1, A2, A9
- **Branch, commits, pull request:** `main` at `0567907`: #39 (the screen as a pipeline step), #41 (recipes, candidates, the re-split, the pool filter), #42 (trino), #43 (a fix to the ruff recipe), #44 (the screen reads)

## Done

**Validation of more candidates.** pandas: 92 of 100 valid. playwright: 49 of 60 valid.

**The screen for unfair hidden tests, the table Andre asked for (entry of 02:26 UTC).** Two independent reads for each valid task, a third read where they did not agree.

| Repo | Difficulty | Validated | Valid | Kept (fair) | Removed (unfair) | Kept share |
|---|---|---|---|---|---|---|
| microsoft/playwright | easy | 18 | 15 | 11 | 4 | 73% |
| microsoft/playwright | medium | 24 | 20 | 9 | 11 | 45% |
| microsoft/playwright | hard | 18 | 14 | 8 | 6 | 57% |
| **microsoft/playwright** | **all** | 60 | 49 | **28** | 21 | 57% |
| pandas-dev/pandas | easy | 30 | 28 | 9 | 19 | 32% |
| pandas-dev/pandas | medium | 40 | 37 | 5 | 32 | 14% |
| pandas-dev/pandas | hard | 30 | 27 | 3 | 24 | 11% |
| **pandas-dev/pandas** | **all** | 100 | 92 | **17** | 75 | 18% |

- The two reads agree on 135 of 141 tasks (96%, Cohen's kappa 0.90). Six tasks were decided by the third read, all as fair. Without those six: playwright 26, pandas 13.
- **Warning, pandas runs short:** 17 fair tasks against the 20 the matrix needs, and 3 hard ones against 6. 197 pandas candidates with tests are not validated yet, but only 8 of them are hard. So the hard level of pandas stays short whatever we validate. Our rule for that: take every fair hard task, fill up to 20 from medium and easy, and report the kept share per level.
- **Andre's point 3 (does the screen remove more hard tasks):** yes for pandas (easy 32%, medium 14%, hard 11% kept). Not for playwright (73%, 45%, 57%).
- Why pandas tasks fail the screen: the tests cover cases the issue does not mention (63 of 75), expect another behaviour than the issue asks for (33), or assert an exact new value or message (32). Many pandas issues are old, and the fix that came late is wider than the issue.
- The rule is stricter than in the pilot and is now written down: a task is fair when every reasonable fix made from the issue passes all hidden tests (`eval/tasks/screen-rules-v1.md`). The pilot tasks were read again under it. pandas 70742 is now unfair: the issue names pandas 2.3.3 as the reference, and on 2.3.3 two of its four hidden test cases fail too.

**Tasks for the other repos.** Recipes for all ten repos of the plan are on `main`: ruff, duckdb, kubernetes, home-assistant, airflow, vllm, vscode, trino (the bonus repo, Java), beside pandas and playwright. Candidates collected: ruff 230 (213 with tests), kubernetes 111 (86), trino 70 (64). Task files for end-to-end runs: `eval/tasks/e2e/<recipe>.jsonl`.
- **duckdb is admitted: 9 of 10 valid.** C++ works.
- ruff: the first admission run found a fault in the recipe (fixed, #43); the check runs again. Then kubernetes, home-assistant, airflow, vscode, vllm, trino.

**Three things the retrieval eval should know.**
- The collector kept only code files in `patch` and `test_patch`; data and snapshot files were lost. `cmeval resplit` repairs the task files for end-to-end use. Gold labels are not affected.
- Tasks whose real fix adds or raises a third-party requirement leave the end-to-end pool (the image has no network): 40 in home-assistant, 7 in airflow, a few elsewhere.
- ruff: issues in the `astral-sh/ty` tracker count as linked issues (tag `issue_repo`), because ty's code is in the ruff repo.

## Checked

- Every read was stored through `cmeval e2e screen-add`, which compares each verdict with its packet. A second session sampled 14 unfair pandas verdicts and agrees with 12.
- Not checked: no recipe except pandas, playwright and duckdb has passed its admission check yet.

## Left

- Admission checks and 60 candidates for the seven other repos; their screen.
- A decision by Andrew on more pandas candidates, and on one edge of the screen rules (a second engine or data type that the issue does not name: a direct variant, or an extra case).

## Blocked on, or needed from others

- **Wilson, Andre:** the date on which codemem's design is locked.
- **Disk on the PC:** the virtual disk is on a drive with 189 GB free. Task images are removed after validation for now (a ruff image is 16.5 GB). The final set of images needs a larger disk; Andrew decides.

## Next

- Track A: the admission queue, then validation and screen per repo. The next entry has the table for the next repos.
