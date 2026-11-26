# B1 search loop: codemem loop vs a grep agent, end to end without tests

Track B experiments on Wilson's laptop (Windows, Intel Arc 140V GPU through `arc_embedder.py`).
The scripts were written against a local copy of `main` at `7c24558` (`analysis/codemem-7c24558`) and use
absolute Windows paths in places; they are here to be read and rerun, not yet cleaned up for other machines.

**Start with [`loop_vs_grep.md`](loop_vs_grep.md):** Track B's current focus (loop vs grep), the algorithms, the
21-task results, the n = 10 / 25 / 50 sweep, the duckdb-25101 case study and the grep "memory" test.

**Nothing in this folder builds the repo or runs tests.** An arm "edits a gold function" when its final diff
touches a line of a function that the real fix changed. That is not "fixed": the hidden tests were not run.

## The arms

| Arm | Script | What the model gets |
|---|---|---|
| grep | `e2e_run.py ... grep` | Claude Code (`claude -p`, Sonnet 5.5, medium effort) with Read, Edit, Write, Grep, Glob; no shell, no build. Budget $5 |
| loop-N | `e2e_loop.py` (`LOOP_N`, default 50) | Round 1: codemem's one-shot top N for an LLM-written query. Each round Sonnet judges N new results (500-character previews; results shown before are never shown again). When it says found, a fix call gets the full code of the picks (up to 8 chunks) and returns exact edits. Cap: 10 search rounds or $3 |

All Sonnet calls are Sonnet 5.5 (`llm.py`). Prompts: `system_loop.txt`, `system_fix.txt`.

## Result 1: the 3 fair pandas pilot tasks (2026-11-26)

> **Updated later the same day:** `score_pilot3.py` now counts only raw code as seen (not previews), adds the
> one-shot query call to the loops' cost, and covers the full-code arms (`full5`, `full10`, `full25`).
> `out/e2e-pilot3/score.json` is from that version; the table below is from the first one. The new table is in
> [`loop_vs_grep.md`](loop_vs_grep.md), section 4b.

Tasks: pandas 68195 (easy), 68945 (easy), 68090 (hard) from `eval/tasks/fresh-v1.jsonl`: valid on Andrew's
PC and fair by both screen reads (`eval/tasks/screen/pilot18.jsonl`). pandas 70742 is left out while its screen
is reopened. One run per arm and task. Drivers: `run_pilot3.py` (grep, loop-50), `run_pilot3_n.py`
(loop-10, loop-25). Scorer: `score_pilot3.py`. Outputs: `out/e2e-pilot3/<task>/<arm>.*`, scores in
`out/e2e-pilot3/score.json`.

| Arm | Cost (USD) | Turns | Gold functions seen | Gold functions edited | Tasks with a change |
|---|---|---|---|---|---|
| grep | 0.14 | 22 | 3 / 6 | 4 / 6 | 3 / 3 |
| loop-50 | 0.75 | 13 | 6 / 6 | 2 / 6 | 2 / 3 |
| loop-25 | 0.28 | 4 | 6 / 6 | 2 / 6 | 3 / 3 |
| loop-10 | 0.27 | 4 | 5 / 6 | 3 / 6 | 3 / 3 |

- **Cost:** `total_cost_usd` of Claude Code (grep), or the sum of the Sonnet calls' costs (loops), over the 3 tasks.
- **Turns:** Claude Code's `num_turns` (grep); search rounds (loops).
- **Gold functions:** the functions in the task's gold labels (`gold.functions`), 6 over the 3 tasks.
- **Seen:** at least half of the function's lines were shown to the model: lines returned by Read, or printed by
  Grep in content mode (grep); result previews and fix code shown to Sonnet (loops). Grep reads short windows,
  so it can edit a function it has not "seen" (68195: 3 of 36 lines read; 68945 `to_datetime`: 127 of 446).
- **Edited:** the final diff changes or inserts at a line inside the function's span at the base commit.

Per task (cost / turns / gold functions edited):

| Task | grep | loop-50 | loop-25 | loop-10 |
|---|---|---|---|---|
| 68195 | 0.019 / 4 / 1 of 1 | 0.071 / 1 / 1 of 1 | 0.057 / 1 / 1 of 1 | 0.041 / 1 / 1 of 1 |
| 68945 | 0.061 / 10 / 2 of 2 | 0.079 / 1 / 1 of 2 | 0.144 / 2 / 0 of 2 | 0.053 / 1 / 1 of 2 |
| 68090 | 0.063 / 8 / 1 of 3 | 0.601 / 11 / 0 of 3 (no change) | 0.077 / 1 / 1 of 3 | 0.173 / 2 / 1 of 3 |

What the logs show:
- In every loop arm, round 1 already had the right function within its first 10 results. Results 11 to 50 added
  nothing on these tasks.
- 68090: loop-50 and loop-25 showed the fix call the same code (`BaseGrouper.indices`, lines 673-696). loop-25's
  fix applied; loop-50's said "could not fix". Its next 9 rounds saw only results 51 and later (seen results are
  not shown again), judged nothing found, and hit the cap: 80% of loop-50's cost. loop-10's first fix also failed,
  but round 2 still had good results left, picked the whole `BaseGrouper` class and applied a fix.
- 68945: loop-25 fixed `_maybe_cache`, not the gold `_convert_and_box_cache`. That may be a valid fix; only the
  hidden tests can tell.
- 68195: grep and loop-25 also edited the test file; a grader puts the real test files back.
- loop-25 on 68945 failed once on a Windows file lock when saving the index (`PermissionError` on a rename in
  `store._atomic_write`); the rerun is the one scored.

**Not enough to rank the arms:** 3 tasks, one run each, and no tests. The gap between the loops comes from one
task each. Next: 3 to 5 runs per arm and task, and grading of the saved diffs with the task images.

## Earlier: 21 tasks, grep vs loop-50 (from an earlier session)

`e2e_all.py` and `e2e_score.py` on 21 tasks (14 pandas, 7 duckdb) of the retrieval eval's samples. Outputs:
`out/e2e-all/`; the one-call `hop-feed` arm reads `out/hop_feed.jsonl`. Result as reported then: grep $1.58,
21 gold functions seen, 17 edited; loop-50 $5.59, 33 seen, 10 edited, no change on 7 of 21 tasks.

## Other files

The retrieval-only experiments of the same work (one-shot, revise, diagnose, loop, loopfull, hop) and their result
notes: `*_results.md`, `*.toml`, `per_gold_file*.{py,json,md}`. They use `cmeval run` on the retrieval eval.
The LLM answer cache (`out/cache/`) and run logs are not included.
