# Track B: hybrid_v2 (one cached conversation) pushed with the 35-task runs: 23-25% cheaper, edits still below grep

- **Track:** B
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-27 10:13 UTC
- **Work package:** B1, end to end without tests
- **Branch, commits, pull request:** PR #45, `wilson/loop-vs-grep-e2e` at `22aef0f`
  (`eval/experiments/b1-loop/e2e_hybrid2.py`, `hybrid.md` sections 3-4, `out/e2e-b45/`, `analysis/`)

## Done

**hybrid_v2** (`e2e_hybrid2.py`, arm `hybrid_v2`, prompt `system_hybrid_v2.txt`): after the step-1 `hybrid_first`
call, one `claude -p --resume` conversation with the prompt cache on, each step appending only its results. grep
shows code (5 lines of context, merged per function, numbered `S.N`); `open` (path + lines, symbol or result) replaces
read; repeated greps are trimmed, then refused; a `done` action, a review step after an edit without `done`.

Also pushed: the e2e-b45 runs of the entry of 04:50 (grep, codemem only, hybrid) and the `hybrid_gc`, `hybrid_done`,
`hybrid_v2a` switches in `e2e_hybrid.py` (smoke runs only), and the analysis scripts.

e2e-b45, 35 tasks, 72 gold functions, one run each, Sonnet 5.5:

| Level | Arm | Cost | Steps (by kind) | Input tokens | Output tokens | Cost per 1k tokens | Gold functions edited (of 72) | Tasks with a gold function edited (of 35) |
|---|---|---:|---|---:|---:|---:|---:|---:|
| L1 | grep agent | $2.08 | 297 turns | 2,292k | 71k | $0.0009 | 50 | 33 |
| L1 | hybrid | $3.04 | 20 codemem, 66 grep, 41 read | 931k | 82k | $0.0030 | 45 | 33 |
| L1 | hybrid_v2 | $2.34 | 20 codemem, 38 grep, 20 open, 2 review, 2 retry | 1,259k | 81k | $0.0017 | 47 | 33 |
| L2 | grep agent | $2.26 | 309 turns | 2,687k | 79k | $0.0008 | 47 | 33 |
| L2 | hybrid | $4.21 | 30 codemem, 65 grep, 47 read | 1,397k | 109k | $0.0028 | 42 | 31 |
| L2 | hybrid_v2 | $3.16 | 29 codemem, 52 grep, 35 open, 3 review, 2 retry | 2,508k | 109k | $0.0012 | 41 | 30 |

Input tokens include cache writes and reads (79-80% of hybrid_v2's input is cache reads). A retry is an edit that
did not apply and was shown again. Mean seconds per task: grep 22, hybrid 39, hybrid_v2 27.

- Cost: 23-25% below the hybrid; still above grep.
- Edits: about the hybrid's (better in 5 runs, worse in 5); grep is better in 9, worse in 1.
- Fixes spanning 2+ gold functions (110): grep 64, hybrid_v2 56. Only 5 of 70 runs reached a review step:
  Sonnet nearly always marks its first edit `done`. Codemem is a first-step tool (46 first steps, 3 later).

## Checked

`VAGUE_SET=e2e-b45 python score_vague8.py`, `analysis/cost_split.py`, `analysis/v2_stats.py`. No tests (no Docker
or NVIDIA GPU here). One run per arm and task.

## Left

Why hybrid_v2 still edits fewer gold functions than grep (being investigated now). Repeat runs.

## Blocked on, or needed from others

A: grading saved diffs (unchanged).

## Next

Wilson, with Claude Code: diagnose the gap, then fix the loop (for example a forced review step after the first edit).
