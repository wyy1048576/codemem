# Track A: answer on 20 search results; validation of 160 candidates runs; recipes for seven more repos are written

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-26 09:50 UTC
- **Work package:** A1, A2, A9 (tasks and the pipeline)
- **Branch, commits, pull request:** none yet; branches `e2e-screen`, `e2e-collect` and one per recipe are local until their checks pass

## Done

**Answer to Andre's entry of 07:58 UTC (20 results).** Track A's position:
- No new arm in the run matrix. The number of results is a codemem setting. Tracks B and C fix
  it before the lock, on dev tasks. The matrix is already several hundred runs.
- Track A offers a measurement without model usage: the real first `search_code` query of each
  `tool` run we have, run again at 10, 20 and 30 results on that task's own index, measured as
  "a gold file is in the results". These are agent queries, which the vLLM table did not have.
  Say if you want it; it needs about an hour of work and no agent run.
- One cost to weigh for track B: the result of a call stays in the context and is sent again
  on every later turn. 2,500 more tokens in turn 1 of a 20-turn run are about 50,000 processed
  tokens, most of them as cache reads.
- No Haiku probe: 10 tasks cannot show a change in completion.

**Validation of more candidates (started 09:21 UTC, PC).** pandas 100 and playwright 60, drawn
with a fixed seed, 3 : 4 : 3 over easy, medium, hard. After 28 minutes: pandas 19 valid of 19,
playwright 12 valid of 15. The table per repo and difficulty follows after the screen.

**The screen is now a pipeline step** (branch `e2e-screen`, in review): packets for the readers,
stored reads in `eval/tasks/screen/`, the table Andre asked for, and `cmeval e2e score --screen`,
which takes unfair tasks out of the completion score only.

**Recipes are written for home-assistant, airflow, vscode and vllm** (not built yet); ruff,
duckdb and kubernetes are in work. Candidates are collected for kubernetes (111 tasks, 86 with
tests) and ruff (65 tasks with an issue in ruff's tracker, 230 when issues in `astral-sh/ty`
count; ty's code is in the ruff repo. Decided: they count, with a tag, and results are split
by it).

**Two findings about tasks.**
- The collector keeps only code files in `patch` and `test_patch`. Snapshot files, fixture data
  and files such as `strings.json` are lost (home-assistant: 208 of 618 tasks lose a file). A
  task with a lost file can come out invalid, not wrongly valid. A re-split from the real commit
  is in work. The retrieval eval is not affected: gold labels are code files.
- pandas 70742 is reopened for the screen. The issue names pandas 2.3.3 as the reference; on
  2.3.3 two of the four hidden test cases fail too. Two fresh reads with that fact will decide.
  If it is unfair, pandas keeps 3 of the 10 pilot tasks.

## Checked

- The validation counts are from the PC's log and records at 09:49 UTC.
- The 2.3.3 fact: the four cases of the hidden test, run on pandas 2.3.3 on the Mac.
- Not checked: no new recipe has built an image yet.

## Left

- Admission checks on the PC for each new recipe, then 60 candidates for each repo that passes.
- The screen of all new valid tasks, two reads each.

## Blocked on, or needed from others

- **Andre, Wilson:** the date on which codemem's design is locked. Results freeze on Nov 30.
- **Andre:** say if you want the replay at 10, 20 and 30 results.

## Next

- Track A: the list above, through the night. The next entry has the table per repo and difficulty.
