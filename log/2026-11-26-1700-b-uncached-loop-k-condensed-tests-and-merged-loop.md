# Track B: one call per round (merged10) cuts loop-10's cost by a fifth with the same edits; condensing tests does not help

- **Track:** B
- **Who:** Wilson, with Claude Code (the full10t and merged10 arms were asked for by Wilson's forked session)
- **When:** 2026-11-26 17:00 UTC
- **Work package:** B1, end to end without tests
- **Branch, commits, pull request:** none. On Wilson's laptop, `analysis/b1-links/llm_query/`: `llm.py`
  (`LLM_NO_PROMPT_CACHE`, `LLM_LOG` usage log), `e2e_loop.py` (`LOOP_CONDENSE_TESTS`), `e2e_loopk.py`
  (`LOOP_FIXED_K`, retry after an edit that does not apply), `run_vague8.py`, `score_vague8.py`

## Done

Same 8 contamination-free vague-prompt tasks as the entries of 14:40 and 16:10. One run each, Sonnet 5.5.

- **loopk_nc**: loop-k with prompt caching off (`DISABLE_PROMPT_CACHING` for the CLI). Input is billed at $2 per
  million tokens instead of $4 for a cache write.
- **full10t**: loop-10 whose judge sees a result the index flags as a test in about 500 characters (header, a
  "tests:" line when it calls at most 5 non-test chunks, up to 3 lines with a query word). The fix call is unchanged.
- **merged10**: 10 results per round as raw code, the first query from the same one-shot call as loop-10, and one
  call per round that sees the new results and the full code of earlier picks and either edits or searches again.
  After an edit that does not apply, the next round shows the same code with the error and no new results.

| Level | Arm | Cost, 8 tasks (USD) | Mean seconds per task | Rounds | Gold functions edited (of 15) | Tasks with a gold function edited (of 8) |
|---|---|---|---|---|---|---|
| L1 | grep | 0.36 | 17 | 56 (turns) | 8 | 7 |
| L1 | loop-k | 0.39 | 26 | 13 | 8 | 7 |
| L1 | loop-k, no prompt cache | 0.44 | 34 | 16 | 8 | 7 |
| L2 | grep | 0.46 | 22 | 60 (turns) | 8 | 7 |
| L2 | loop-10 | 0.80 | 27 | 13 | 8 | 7 |
| L2 | loop-10, tests condensed | 0.79 | 37 | 14 | 7 | 6 |
| L2 | merged, 10 per round | 0.64 | 26 | 13 | 8 | 7 |
| L2 | loop-k | 0.52 | 27 | 16 | 7 | 7 |
| L2 | loop-k, no prompt cache | 0.48 | 31 | 18 | 7 | 7 |

- merged10: same edits, rounds and time as loop-10 for 20% less. No edit failed to apply. Its first applied edit
  missed every gold function in 1 run (pandas 70742, where every arm edits `fast_xs`), as for loop-10.
- full10t: cheaper where round 1 was mostly tests (playwright 42919, $0.046 against $0.102), no cheaper overall;
  pandas 68090 lost its gold edit. Rounds whose input did not change replay loop-10's cached answers (8 of 30 calls).
- No prompt cache: input $2.00 per million tokens against $2.76 effective with caching, but this run took more
  rounds on pandas 70742 and 68090, so the totals moved by less than run-to-run noise.
- One L1 run (playwright 41850, loop-k no cache) searched 10 rounds without finding `fetch.ts` and was rerun: another
  session was rebuilding the shared repo copies (`~/e2e-copies`) at the same time. The rerun edited it in round 2.

## Checked

`python score_vague8.py`; per-call token use from `out/e2e-vague8/*-calls.jsonl`. No tests: no Docker or NVIDIA GPU.

## Left

Repeat runs: single runs differ by more than these changes. Only one session at a time should use `~/e2e-copies`.

## Blocked on, or needed from others

A: grading saved diffs in the task images.

## Next

Wilson: merged + chosen k + no prompt cache in one arm; repeat runs (3 per task) before drawing conclusions.
