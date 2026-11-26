# Track B: grep against the full-code codemem loop on 8 vague-prompt tasks; same edits, grep 2 to 6 times cheaper

- **Track:** B
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-26 14:40 UTC
- **Work package:** B1, end to end without tests
- **Branch, commits, pull request:** none yet. Scripts and outputs are on Wilson's laptop
  (`analysis/b1-links/llm_query/run_vague8.py`, `score_vague8.py`, `out/e2e-vague8/`); not in PR #45

## Done

**Tasks:** the 8 pilot tasks that are contamination-free (PR opened after 2026-06), validated by Andrew and fair by
both screen reads: pandas 68195, 70742, 68090; playwright 41850, 42503, 42919, 43146, 43148. Prompts: L1 and L2 of
`eval/tasks/vague-pilot18-v2.jsonl`. One run each, Sonnet 5.5. Fresh repo copy per task, reset between arms.

**Arms:** the grep agent (Claude Code: Read, Edit, Write, Grep, Glob), and the codemem loop whose judge sees
N results per round as raw code from the index (`LOOP_FULL=1`), N = 5, 10, 25, 50.

| Level | Arm | Cost, 8 tasks (USD) | Turns | Gold functions seen (of 15) | Gold functions edited (of 15) | Tasks with a gold function edited (of 8) |
|---|---|---|---|---|---|---|
| L1 | grep | 0.36 | 56 | 10 | 8 | 7 |
| L1 | loop, 5 | 0.61 | 12 | 10 | 8 | 7 |
| L1 | loop, 10 | 0.81 | 11 | 9 | 8 | 7 |
| L1 | loop, 25 | 1.15 | 9 | 11 | 8 | 7 |
| L1 | loop, 50 | 1.92 | 8 | 14 | 8 | 7 |
| L2 | grep | 0.46 | 60 | 10 | 8 | 7 |
| L2 | loop, 5 | 0.97 | 21 | 10 | 8 | 7 |
| L2 | loop, 10 | 0.80 | 13 | 10 | 8 | 7 |
| L2 | loop, 25 | 1.04 | 9 | 10 | 7 | 6 |
| L2 | loop, 50 | 3.03 | 20 | 13 | 8 | 7 |

Turns: Claude Code's turns (grep), search rounds (loop). Seen: at least half of a gold function's lines reached the
model as raw code. Edited: the final diff touches a line inside it. Loop cost includes its query-writing call.

- Every arm edits the same gold functions; the arms differ only in cost. The same task misses everywhere
  (pandas 70742: all arms edit `fast_xs`, not the gold function; only loop-50 at L2 edits it).
- Gold functions in a second file (playwright 42919's trace-viewer UI, 43148's other 3) are never edited by any arm.
- L2 loop-50 on playwright 42919 cost $1.46 and changed nothing: round 1 said found and named
  `Tracing._captureSnapshot`, but picked no result, so no fix call ran; later rounds never show a result twice.
  That is a loop bug (found with no picks should fall back to the results it named).
- Without that run, L2 loop-50 is $1.57.

## Checked

`python score_vague8.py`; all 80 runs have a summary, none failed. No tests run: no Docker or NVIDIA GPU here.

## Left

The found-with-no-picks bug. Repeat runs (one run each is noise). Grading the diffs with tests.

## Blocked on, or needed from others

A: grading saved diffs in the task images.

## Next

Wilson: fix found-with-no-picks; try a cheaper loop (fewer results, or only the query call plus one fix call).
