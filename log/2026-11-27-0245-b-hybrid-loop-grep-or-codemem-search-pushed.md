# Track B: the hybrid loop (grep or codemem search, Sonnet's choice each step), pushed; a first result on 2 tasks

- **Track:** B
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-27 02:45 UTC
- **Work package:** B1, end to end without tests
- **Branch, commits, pull request:** `wilson/loop-vs-grep-e2e`, new commit `b82aca6`; **PR #45**
  https://github.com/wyy1048576/codemem/pull/45. Write-up: `eval/experiments/b1-loop/hybrid.md`

## Done

- `e2e_hybrid.py` (arm `hybrid` in `run_vague8.py` / `score_vague8.py`): loop-k (merged judge and fix, one fresh
  Sonnet call per step, prompt cache off) with grep as a second tool. Each step's call returns one action: `edit`,
  `read` (show the picks in full), `codemem` (top k not shown before, k = 3, 5 or 10; never 1 or 2, use grep for
  that) or `grep` (`git grep -E`, at most 40 lines, each with its enclosing function; a picked line pins that
  function). Only step 1 writes the structured intent / symptom / anchors query (loop-k's first round). Later codemem
  steps take one free-text query plus `look_in`, searched by its code, usage and BM25 lists. Cap 15 steps or $3.
  Which tool to use is only in the prompts (`system_hybrid_first.txt`, `system_hybrid.txt`), worded by Wilson.
- First result, 2 tasks, one run each. Steps = tool runs; Sonnet calls = steps + the step-1 call.

| Task (level) | Arm | Cost (USD) | Turns or steps | Tool runs by kind | Gold functions edited |
|---|---|---:|---:|---|---|
| playwright-42503 (L2) | grep agent | 0.093 | 11 turns | 7 Grep, 1 Read, 2 Edit | 1 of 1 |
| playwright-42503 (L2) | codemem only (loop-k) | 0.130 | 5 rounds | 5 codemem | 1 of 1 |
| playwright-42503 (L2) | hybrid | 0.085 | 2 steps | 2 codemem, 0 grep, 0 read | 1 of 1 |
| pandas-69779 (L1) | grep agent | 0.065 | 11 turns | 5 Grep, 2 Read, 3 Edit | 2 of 3 |
| pandas-69779 (L1) | codemem only (loop-k) | 0.036 | 1 round | 1 codemem | 2 of 3 |
| pandas-69779 (L1) | hybrid | 0.038 | 1 step | 1 codemem, 0 grep, 0 read | 2 of 3 |

- Preliminary finding: the hybrid improves on both. Same gold functions edited, $0.123 in total against grep's
  $0.158 and loop-k's $0.166; on 42503 2 steps against loop-k's 5 rounds (its free-text second query with `look_in`
  on both playwright packages found `runDaemonForContext` at once). Both runs used codemem only, so grep inside the
  hybrid is untested on these two; an earlier smoke run with older prompt wording (not kept) used 3 greps and 1 read.

## Checked

`score_vague8.py` on both task sets; the per-task numbers above come from the summaries. No tests (no Docker or
NVIDIA GPU here). Two tasks and one run each: a direction, not a measurement.

## Left

The proper run is going: grep, codemem only (loop-k, no cache) and hybrid on `e2e-b45`, every task of
`vague-b7-v3` (main) whose issue was opened after June 2026 and that has a gold function: 35 tasks (26 playwright,
9 pandas, 72 gold functions), L1 and L2. 44 earlier grep / loop-k runs with the same prompt and commit are reused.
Outputs `analysis/b1-links/llm_query/out/e2e-b45/` on Wilson's laptop; results in the next entry.

## Blocked on, or needed from others

A: grading saved diffs (unchanged).

## Next

Wilson: the e2e-b45 results, reported with the hybrid's turns split into codemem and grep; then Wilson edits the loop.
