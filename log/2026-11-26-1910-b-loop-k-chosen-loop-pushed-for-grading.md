# Track B: loop-k (merged judge and fix, prompt cache off) is the chosen loop; code, write-up and diffs pushed for grading

- **Track:** B
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-26 19:10 UTC
- **Work package:** B1, end to end
- **Branch, commits, pull request:** `wilson/loop-vs-grep-e2e` at `4bfb18f`, PR #45 (open).
  Start with `eval/experiments/b1-loop/loop_k.md`

## Done

**Loop-k is Track B's chosen search loop:** `eval/experiments/b1-loop/e2e_loopk.py`. Sonnet picks how many results
to read each round (k = 1, 2, 3, 5 or 10), one call per round sees the new results as raw code plus the full code of
its earlier picks and either edits or searches again, and the prompt cache is off by default.

On 14 vague-prompt tasks (the 8 pilot tasks and 6 b7 tasks, one run each, no tests):

| Prompt level | Arm | Cost, 14 tasks (USD) | Gold functions edited (of 27) | Tasks with a gold function edited (of 14) |
|---|---|---|---|---|
| L1 | grep agent | 0.81 | 14 | 11 |
| L1 | loop-k | 0.94 | 14 | 11 |
| L2 | grep agent | 1.04 | 16 | 12 |
| L2 | loop-k | 1.08 | 14 | 12 |

`loop_k.md` has the algorithm, how to run it, how to grade its diffs, the reason for each design choice with its
numbers (raw code, Sonnet picking k, merging judge and fix, prompt cache off, condensed tests), all arms' tables,
where it fails (playwright 41988, pandas 70742) and the run-to-run noise.

**The diffs are ready to grade.** Every run's change is saved as `out/<set>/<level>/<task id>/<arm>.diff`, the
`--patch DIR` layout of `cmeval e2e grade`:
`cmeval e2e grade pandas --tasks tasks/e2e/pandas.jsonl --patch eval/experiments/b1-loop/out/e2e-b7/L2` (and
playwright, L1, and `out/e2e-vague8/`). The chosen loop is `loopk_nc.diff`; grep is `grep.diff`.

## Checked

`score_vague8.py` on both sets. The pushed scripts are the ones that made the runs; `e2e_loopk.py` now defaults to
prompt cache off, and `run_vague8.py` sets it per arm explicitly. Not run with tests.

Correction to the entry of 18:30: split loop-k stopped at the 10-round cap in 7 of its 24 runs and merged in 3 of
24 (first written as 7 of 12 and 2 of 12).

## Left

Grading. Repeat runs. The anchor filter and a direct lookup of a named function (`loop_k.md` section 7).

## Blocked on, or needed from others

A: grade the saved diffs of `out/e2e-b7/` and `out/e2e-vague8/` with `cmeval e2e grade` (Wilson's laptop has no
Docker or NVIDIA GPU). C: look at PR #45.

## Next

Wilson: repeat runs of grep and loop-k on more b7 tasks; the fixes of section 7 of `loop_k.md`.
