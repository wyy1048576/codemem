# Track B: loop-k (Sonnet picks k, edits in any round) costs about what grep costs on the 8 vague-prompt tasks

- **Track:** B
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-26 16:10 UTC
- **Work package:** B1, end to end without tests
- **Branch, commits, pull request:** none. On Wilson's laptop: `analysis/b1-links/llm_query/e2e_loopk.py`,
  `system_loopk.txt`, `schema_loopk.json`, `system_oneshot_k.txt`, `schema_oneshot_k.json`; outputs `out/e2e-vague8/<L>/<task>/loopk.*`

## Done

**Loop-k.** The query-writing call also picks k, the number of results shown, from {1, 2, 3, 5, 10}. Each round is one
Sonnet call that sees the k new results as raw code, its earlier notes and the full source of results it picked
earlier, and either returns edits (applied if each old text occurs once) or the next query with the next k. No
separate judge and fix calls.

Same 8 tasks as the entry of 14:40, one run each, Sonnet 5.5:

| Level | Arm | Cost, 8 tasks (USD) | Mean seconds per task | Rounds | Gold functions edited (of 15) | Tasks with a gold function edited (of 8) |
|---|---|---|---|---|---|---|
| L1 | grep | 0.36 | 17 | 56 (turns) | 8 | 7 |
| L1 | loop, 10 | 0.81 | 26 | 11 | 8 | 7 |
| L1 | loop-k | 0.39 | 26 | 13 | 8 | 7 |
| L2 | grep | 0.46 | 22 | 60 (turns) | 8 | 7 |
| L2 | loop, 10 | 0.80 | 27 | 13 | 8 | 7 |
| L2 | loop-k | 0.52 | 27 | 16 | 7 | 7 |

- Sonnet chose k = 1 to 5, never 10. Every run applied an edit; no edit failed to apply.
- L2 playwright 43148: loop-k edited 1 of 5 gold functions, grep and loop-10 2.
- Token use of the loop-k calls (new: `llm.py` logs usage with `LLM_LOG`): $0.60 of $0.91 is the premium rate for
  writing the input to the prompt cache, which no later call reads (each `claude -p` call is a new conversation).

## Checked

`python score_vague8.py`. No tests: no Docker or NVIDIA GPU here.

## Left

Repeat runs; grading with tests; not caching the loop's inputs; leaving test files out of the results.

## Blocked on, or needed from others

A: grading saved diffs in the task images.

## Next

Wilson: stop the cache-write premium on the loop's calls, then rerun loop-k.
