# Track A, for Andre and Wilson: the replay at 5 to 50 results; half of the agents' first searches were keywords only; 5 codemem tests fail on Linux; prompts version 3; the hard-tier candidates

- **Track:** A. Answers Andre's entries of 09:54 (points 1 and 2), 11:32 (run 1, first part), 13:52 (step 2), 15:44 and 15:48, and Wilson's request to grade a saved diff
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-26 19:25 UTC
- **Work package:** A1, A5, A9; it serves decisions of tracks B and C
- **Branch, commits, pull request:** `main` at `029dada`: #55 (vague prompts version 3), #56 (`cmeval e2e grade`, `cmeval e2e turns`), #57 (hard-tier candidates, `generate.tier`), #58 (`cmeval e2e replay`). Data: `log/2026-11-26-1925-a-data/replay-1.md` and `replay-1.json` on this branch

## Done

**1. The replay (Andre, 09:54, point 1).** The real first `search_code` call of the main agent in each run with codemem, asked again on the task's own index through the MCP server, at 5, 10, 20, 30 and 50 results. 62 runs (Haiku; pandas 34, playwright 28; L0 21, L1 19, L2 22), codemem `041124e`, the 20 pilot tasks. Full tables per repo and level: `replay-1.md`.

| | In the run | k=5 | k=10 | k=20 | k=30 | k=50 |
|---|---|---|---|---|---|---|
| A gold file is among the results | 55% | 60% | 66% | 77% | 84% | 89% |
| Every gold file is | 32% | 34% | 37% | 50% | 53% | 58% |
| A gold function is (51 runs with function gold) | 47% | 43% | 49% | 63% | 67% | 76% |
| Characters of the output | 4,813 | 2,316 | 4,476 | 8,749 | 12,911 | 21,096 |

| A gold file is among the results | k=10 | k=20 | k=30 | k=50 |
|---|---|---|---|---|
| L0 (21 runs) | 76% | 81% | 86% | 86% |
| L1 (19 runs) | 53% | 68% | 84% | 89% |
| L2 (22 runs) | 68% | 82% | 82% | 91% |
| pandas (34) | 71% | 85% | 85% | 94% |
| playwright (28) | 61% | 68% | 82% | 82% |

- From 10 to 20 results: 11 points more for a gold file (66 to 77%), 13 for every gold file, 14 for a gold function, for 4,300 more characters. The gain is largest at L1, where the query has no names (53 to 68%, and 84% at 30).
- Rank of the first gold file at k=50: rank 1 in 25 runs, 2 to 5 in 12, 6 to 10 in 4, 11 to 20 in 7, 21 to 30 in 4, 31 to 50 in 3, not found in 7.
- The same task is in several runs, so these are 62 queries on 20 tasks, not 62 independent tasks.

**2. A finding that matters more than the number of results: in 31 of the 62 runs the first search was answered from keywords only,** with the note that the model is still loading. The agent makes one `search_code` call in turn 1 to 3 and then greps, so in half of our `tool` runs the agent never got a result from the vectors. Compare "in the run" (55%) with k=10 (66%) above: the replay at the run's own number of results, with the model loaded, finds a gold file in 7 more runs. **Before the check run the runner will wait until codemem reports ready before the agent starts** (your note of 14:17, point 7, says this is ours). All runs so far with the `tool` setup have this fault; none is a result.

**3. The cost of a result in our runs (Andre, 09:54, point 2).** Means over the 62 runs:

| | |
|---|---|
| The first `search_code` result, as the model got it | 4,930 characters, about 2,200 tokens (estimated from the growth of the next request's input) |
| Turns after it | 24.6 |
| Share of the later requests' input that is read from the cache | 97.2% |
| Tokens of the result sent again over the rest of the run | about 54,000, almost all as cache reads |

So 10 more results cost about 2,000 tokens once, and about 50,000 cached tokens over a run of 25 turns.

**4. Run 1 of the entry of 11:32, first two parts: 5 codemem tests fail on Linux x86-64** (`main` at `09c4ef0`, `uv sync` clean, FAISS 1.16.0, Python as `uv` chose it; two validations were building beside it).

```
uv run pytest -q
FAILED tests/test_compact_store.py::test_ties_at_the_candidate_cut_are_all_kept[1]
FAILED tests/test_compact_store.py::test_an_index_patched_step_by_step_is_the_index_rebuilt_from_the_rows[1]
FAILED tests/test_compact_store.py::test_an_index_patched_step_by_step_is_the_index_rebuilt_from_the_rows[4]
FAILED tests/test_compact_store.py::test_an_upsert_that_fails_part_of_the_way_leaves_the_index_as_it_was[1]
FAILED tests/test_compact_store.py::test_an_upsert_that_fails_part_of_the_way_leaves_the_index_as_it_was[4]
5 failed, 724 passed, 2 skipped, 4 deselected in 630.39s

CODEMEM_TEST_VECTOR_BACKEND=compact uv run pytest -q
(the same five)
5 failed, 721 passed, 5 skipped, 4 deselected in 524.41s
```

The last failure, at `tests/test_compact_store.py:923`:

```
>       assert vs._ids.tolist() == final and vs.to_bytes() == once.to_bytes()
E         At index 124 diff: b'2' != b'0'
```

So an index that was patched step by step is not byte-equal to the one built once, on this machine. The full log is on the PC (`~/.cmeval/logs/andre-12.log`); say if you want it here. `check_faiss_calls.py` and run 2 are still running; runs 3 and 4 follow when the PC is quiet. On the PC every repo is on the exact index, so this does not touch the eval's runs.

**5. Vague prompts version 3 is on `main`** (#55): `eval/tasks/vague-b7-v3.jsonl`, rules `vague-rules-v3.md`. All 13 rows of Andre's review are taken: 12 as proposed, playwright 43172 L1 with one more phrase changed (it copied the error text "Unsupported locator method"). Our review found 4 more rows with the same faults (playwright 41942 L1, 43316 L2; pandas 71232 L1, 69015 L1). The four rule sentences are in, each with a limit (for example: a behaviour that only the tests show stays out of L2). `vague-b7-v3.changes.md` has old text, new text and reason per row. **This replaces the branch `andre/vague-prompts-v3`, which has files of the same names: please do not merge it.** The README names the file of 45. The meta file lists, per task, the L2 words that are in a gold file's path: 24 of 45 tasks by the plain rule, not 15.

**6. The second collection, for the hard tier, is on `main`** (#57): fixes of 6 to 15 code files or 201 to 600 lines. `generate.tier(patch)` gives the tier; today's label stays. Task files `eval/tasks/fresh-*-v1-large.jsonl` and `eval/tasks/e2e/<recipe>-large.jsonl`.

| Repo | New tasks | In the pool (a test that a suite runs, no raised dependency) |
|---|---|---|
| pandas | 19 | 15 |
| ruff | 48 | 48 (45 with an issue in the ty tracker) |
| duckdb | 20 | 19 |
| playwright | 31 | 27 |
| vscode | 199 | 187 |
| home-assistant | 43 | 25 |
| kubernetes | 8 | 4 |
| trino | 5 | 5 |

**Warning: kubernetes and trino cannot reach 4 fair hard tasks,** also if every task is valid and fair. pandas will be short at its keep rate (15 × 0.9 × 0.18 is about 2). duckdb and home-assistant are at risk. None is built or validated yet.

**7. Two commands for you** (#56).
- **Wilson:** `cmeval e2e grade RECIPE --tasks FILE --id TASK --patch DIFF` grades a saved diff in the task's image with the run's grader. `--patch DIR` takes `<task id>.patch` files and your layout `<task id>/<arm>.diff`. The diff must be a git diff with `a/` and `b/` prefixes against the base commit. It runs on the PC; the task's image must exist (`cmeval generate RECIPE --tasks FILE --id TASK --rebuild`). Checked on two finished runs: it gives their verdicts. All 111 diffs of `origin/wilson/loop-vs-grep-e2e` pass the format check; 25 are empty. Say which to grade and we run them.
- **Andre:** `cmeval e2e turns RUN_ID --id TASK [--with RUN_ID2]`: one row per turn (seconds, the four token classes, tools, command or query, kinds of action, gold surfaced, opened, edited), two runs side by side with `--with`. The sums equal `run.json`. The runner prunes nothing: a run done again is moved to `<rep>.discarded-<n>`.

## Checked

- The replay: in the 31 runs answered from keywords, a keyword search in the replay gives the run's own list; in the other 31, the replay at the run's number of results gives the run's list. The indexes were built with another codemem commit than the program (the check says so), with the same lists.
- Not checked: the replay with `09c4ef0` (plain-text results, other preview sizes would change the character counts).

## Left

- `check_faiss_calls.py`, run 2, runs 3 and 4.
- The wait for a loaded model in the runner.
- The decisions of Andrew on the entry of 13:52 (queue order, stop rule, check run).

## Blocked on, or needed from others

- **Andre:** whether you want the full log of the five failures.
- **Wilson, Andre:** the number of results is yours to set; the table is above.

## Next

- Track A: the wait for a loaded model; runs 2 to 4; the screen of duckdb and kubernetes.
