# Track B: on 6 more vague-prompt tasks, merged loop-k without prompt cache matches grep's cost and edits; split loop-k is worse

- **Track:** B
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-26 18:30 UTC
- **Work package:** B1, end to end without tests
- **Branch, commits, pull request:** none. On Wilson's laptop, `analysis/b1-links/llm_query/`: `e2e_loop.py`
  (`LOOP_CHOOSE_K`), `system_loop_k.txt`, `schema_loop_k.json`, `run_vague8.py` / `score_vague8.py` (`VAGUE_SET`);
  outputs `out/e2e-b7/`

## Done

**Tasks:** 6 new tasks from `eval/tasks/vague-b7-v3.jsonl` on main (valid, fair by the b7 screen), one per repo and
difficulty, picked at random (seed 20261126) among those with gold functions and not in the earlier 8: pandas 71129
(easy), 69779 (medium), 67897 (hard); playwright 41988 (easy), 43174 (medium), 42792 (hard). L1 and L2 prompts (v3).

**Arms:** grep; loop-k where Sonnet picks k from {1, 2, 3, 5, 10}, either merged (one call per round edits or
searches) or split (a judge call, then a fix call), each with the prompt cache on or off. One run each, Sonnet 5.5.

| Level | Arm | Cost, 6 tasks (USD) | Without playwright 41988 | Mean seconds | Gold functions edited (of 12) | Tasks with a gold function edited (of 6) | Runs stopped at 10 rounds |
|---|---|---|---|---|---|---|---|
| L1 | grep | 0.45 | 0.29 | 26 | 6 | 4 | |
| L1 | loop-k merged | 0.74 | 0.32 | 32 | 6 | 4 | 1 |
| L1 | loop-k merged, no cache | 0.50 | 0.21 | 44 | 6 | 4 | 0 |
| L1 | loop-k split | 1.01 | 0.63 | 52 | 5 | 3 | 2 |
| L1 | loop-k split, no cache | 0.65 | 0.29 | 50 | 6 | 4 | 1 |
| L2 | grep | 0.58 | 0.32 | 32 | 8 | 5 | |
| L2 | loop-k merged | 0.77 | 0.48 | 45 | 6 | 4 | 1 |
| L2 | loop-k merged, no cache | 0.60 | 0.39 | 47 | 7 | 5 | 1 |
| L2 | loop-k split | 0.99 | 0.65 | 54 | 6 | 4 | 1 |
| L2 | loop-k split, no cache | 1.05 | 0.76 | 70 | 4 | 3 | 3 |

- Merged beats split in cost and edits at both levels, and stops at the cap less often (3 of its 24 runs, against 7 of
  24; corrected at 19:10, first written as 2 of 12 and 7 of 12).
- Merged without prompt cache is the best loop: within $0.05 of grep at L1 and $0.02 at L2, with the same edits at L1
  and one fewer at L2 (7 against 8).
- Playwright 41988 (an accessibility snapshot drops a button's name; gold: a plugin's `exit` in
  `ariaSnapshotDistiller.ts`) stopped 7 of 8 loop runs at 10 rounds ($0.21 to $0.42 each). The loops found the file
  but edited `removeRedundantNames`' `enter`. Grep took 14 and 18 turns and edited the gold function only at L2.
- Over all 14 tasks (these 6 and the earlier 8), cost / gold functions edited: L1 grep $0.81 / 14, merged loop-k
  $1.13 / 14, merged no cache $0.94 / 14; L2 grep $1.04 / 16, merged $1.29 / 13, merged no cache $1.08 / 14.
- The split arms on the earlier 8 tasks did not run: the batch stopped at its one-hour limit.

## Checked

`VAGUE_SET=e2e-b7 python score_vague8.py`. No tests: no Docker or NVIDIA GPU here.

## Left

Repeat runs; a better way out of a 10-round loop on hard tasks (41988); the split arms on the earlier 8.

## Blocked on, or needed from others

A: grading saved diffs in the task images.

## Next

Wilson: make merged loop-k without prompt cache the default loop arm; look at why 41988 loops.
