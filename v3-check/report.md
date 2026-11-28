# v3 (PR #85, `4902671`) against v2 (`main`, `463171c`): an independent check with Haiku and Sonnet

<!-- answer: start -->
**Answer (337 sessions kept; Haiku and Sonnet; 17 pandas and 6 vLLM tasks at L2; the agent locates, it does not edit).**
1. **With the 20 lines, which is what the evaluation runs, v3 does not beat v2, with either model.** Haiku pandas (34 pairs): turns -5%, tokens -1%, cost +2%, seconds +8% (p 0.54 to 0.95). Haiku vLLM (12 pairs): tokens +30%, cost +33% as the harness counts, -7% and +7% counting first attempts (p 0.08 to 0.54). Sonnet pandas (25 pairs): turns +10%, tokens +19%, cost +8%, seconds +14% (p 0.10 to 0.67; two runs of `v2` differ by +25% in tokens). Sonnet vLLM: tokens +4%. Quality the same everywhere. None of it is larger than the noise; with Sonnet it leans against v3, and Sonnet never called search_code with the lines in either arm (0 of 61 sessions), so all it gets from v3 is longer definitions.
2. **As a tool alone, v3 is not better beyond the noise either.** Haiku: tokens -20% (pandas) and -18% (vLLM), cost -15% and -5%, but `v3-tool` used more tokens than `v2-tool` in 21 of 34 pandas pairs, and two runs of `v2-tool` differ by +68% (pandas) and 2.1 times (vLLM) (p 0.21 or more); right file first 29 against 32 of 34. Sonnet pandas: `v3-tool` used more tokens in 14 of 17 pairs (+33%, p 0.01; cost +16%, p 0.22), because it searched in 9 sessions against 3, for the same quality: the one gap with a small p (one of many comparisons), and it goes against v3.
3. **What v3 changes for certain:** 485 more input tokens in every request (codemem's tool definitions 3,405 against 2,144 characters, instructions 825 against 611); Haiku fills intent, symptom and anchors in almost every call (locations in about a third), so a call's arguments are about 5 times longer, while Sonnet mostly fills only anchors; in 3 of Haiku's 92 v3 sessions the first call left out the required `query`.
4. **The PR's own gain** (about -20% in cost as a tool, Haiku, 5 tasks, one or two runs) is the size of the run-to-run noise measured here; it does not show with the 20 lines, and it turns around with Sonnet.
<!-- answer: end -->

## What was compared, and how

- **The question.** Does PR #85 ("v3": new tool wording, at most 10 results, four optional inputs the agent fills
  in, no hooks) do better than `main` ("v2")? Two comparisons: the tool against the tool (what the PR's own tests
  measured), and v3 against v2 with the 20 search results at the top of the first message, which is what the
  evaluation runs.
- **Five arms.** `grep`: the agent's own tools only (Read and read-only shell commands). `v2-tool`, `v3-tool`:
  codemem at that commit as the MCP tool. `v2`, `v3`: the tool plus the same 20 lines (one `codemem search -k 20` on
  the request, made at `463171c` as the evaluation makes them).
- **Sessions.** Claude Code headless in the review harness (`.cache/review/compare/bin/compare.py`, its gates
  unchanged; driver `blockv3.py`). The agent may read and search but not edit; it answers with up to 3 files and 5
  functions; at most 25 turns; L2 requests. Each session has its own copy of the task's repository and index. One
  session at a time; the arms take turns and their order changes from task to task. Haiku: `grep` once and each
  codemem arm twice per task (the second run measures the noise). Sonnet: each arm once, and `v2` and `v3` a second
  time on 8 pandas tasks (stage 4, which the cap of 340 sessions cut there).
- **Tasks.** 17 pandas tasks (each at its own commit, with its own index) and 6 vLLM tasks on the vLLM checkout
  `e9acf48` with the real index (144,729 vectors); each vLLM session ran in a copy of the checkout with an empty `.git`
  marker, as the pandas tasks do, and on its own copy of the index.
- **The run.** 340 sessions from 02:15 to 06:04 UTC on Nov 28: 337 kept, 3 discarded by the harness and run again (see
  the tables). $5.43 at list prices (Haiku $0.79, Sonnet $4.61). Subscription status "allowed" throughout (7-day use
  0.36 to 0.38); no session overlapped another model process.
- **Measures.** Quality: the answer's first file is a file of the fix (right file first); a function of the fix is
  named (right function, the harness's full-name rule). Turns: model turns. Seconds: from the first model request to
  the end of the last (the agent's own time; the server's start is not in it). Tokens: all processed, and by class.
  Cost: `total_cost_usd`, Claude Code's estimate at list prices (the sessions ran on the subscription).

## Checks made before the first session

- **v3 opens our indexes without rebuilding them.** On pandas task 70205 and on the vLLM index, v3's server (and
  v2's, for comparison) came up ready with the same chunks and vectors as before (vLLM: 102,224 chunks; 109,562 +
  35,167 = 144,729 vectors), nothing stale, nothing embedded. On the vLLM index, which an older codemem built, both
  commits make the same small update: one setting added (`vector_backend: faiss`) and two 207-byte sidecar files
  rewritten. v3 does exactly what v2 does there.
- **A plain search is the same at both commits.** Three real queries (the first queries of earlier sessions), with
  only `query`, on one copy of the index: byte-identical results at `463171c` and `4902671`, on pandas (task 70205)
  and on vLLM.
- **The 20 lines.** Made again at `463171c` for all 23 tasks; for the 17 pandas tasks they are identical to the
  lines blocks F and G used.
- **One dry start per arm** (the harness's fake API: no model call), on a pandas task, and three on a vLLM task:
  the first request held the arm's own tool texts (v2: 2,144 characters of codemem tool definitions; v3: 3,405, with
  the four new inputs), no hook, no foreign text, an empty git section, and the 20 lines in `v2` and `v3` only.

## Results

<!-- note: start -->
Tables written 2026-11-28 06:05 UTC: final: stages 1 to 3 complete, stage 4 stopped at the cap of 340 sessions (337 kept, 3 discarded and run again). 337 finished sessions.
<!-- note: end -->

<!-- s1: start -->
### Stage 1: Haiku, pandas (17 tasks, L2): grep once, each codemem arm twice

153 sessions. Right file first: the answer's first file is a file of the fix. Right function: a function of the fix named (the harness's full-name rule).

| Arm | Sessions | Right file first | Right function | Turns: median / sum | Seconds: median / sum | Tokens, all: median / sum | Cost $: median / sum | search_code calls per session |
|---|---|---|---|---|---|---|---|---|
| `grep` | 17 | 16 | 14 of 16 | 5 / 88 | 14.6 / 248 | 67,590 / 1,271,271 | 0.0029 / 0.0535 | 0.00 |
| `v2-tool` | 34 | 32 | 28 of 32 | 4.0 / 176 | 8.2 / 457 | 57,780 / 3,369,423 | 0.0027 / 0.1311 | 1.94 |
| `v3-tool` | 34 | 29 | 29 of 32 | 4.0 / 155 | 9.6 / 413 | 60,062 / 2,683,376 | 0.0028 / 0.1113 | 1.62 |
| `v2` | 34 | 30 | 29 of 32 | 3.5 / 140 | 9.6 / 390 | 53,164 / 2,425,340 | 0.0025 / 0.1008 | 1.26 |
| `v3` | 34 | 31 | 29 of 32 | 3.0 / 133 | 9.4 / 421 | 49,190 / 2,404,172 | 0.0024 / 0.1025 | 1.03 |

Tokens by class (new input, cache write, cache read, output):

| Arm | New input: median / sum | Cache write: median / sum | Cache read: median / sum | Output: median / sum |
|---|---|---|---|---|
| `grep` | 10 / 180 | 5,902 / 119,259 | 58,634 / 1,114,791 | 2,083 / 37,041 |
| `v2-tool` | 8 / 352 | 7,498 / 335,592 | 50,280 / 2,964,929 | 1,206 / 68,550 |
| `v3-tool` | 8 / 310 | 7,794 / 281,689 | 53,796 / 2,338,332 | 1,544 / 63,045 |
| `v2` | 7 / 280 | 6,436 / 250,958 | 46,264 / 2,115,181 | 1,430 / 58,921 |
| `v3` | 6 / 266 | 6,342 / 241,965 | 40,278 / 2,095,714 | 1,435 / 66,227 |

Pairs on the same task. Each cell: B lower / equal / higher than A, then in brackets the sum of B over the sum of A. p: a permutation test within each task (the arm labels of the task's sessions shuffled, 5,000 times; two-sided), so it measures the gap against the spread between runs. Noise rows: the second run of an arm against its first, on the same task.

| Pairs on the same task: B against A | Pairs | Turns: B lower / equal / higher (sum B / sum A) | Tokens | Cost | Seconds (within 5% = equal) | Right file first: B better / same / worse | Right function | p: turns, tokens, cost, seconds, file, function |
|---|---|---|---|---|---|---|---|---|
| `v3-tool` against `v2-tool` | 34 | 12 / 12 / 10 (0.88) | 13 / 0 / 21 (0.80) | 14 / 0 / 20 (0.85) | 11 / 5 / 18 (0.90) | 0 / 31 / 3 | 2 / 29 / 1 | 0.27, 0.21, 0.24, 0.46, 0.17, 1.00 |
| `v3` against `v2` | 34 | 13 / 10 / 11 (0.95) | 15 / 0 / 19 (0.99) | 16 / 0 / 18 (1.02) | 13 / 3 / 18 (1.08) | 2 / 31 / 1 | 1 / 30 / 1 | 0.66, 0.95, 0.89, 0.54, 1.00, 1.00 |
| `v2` against `v2-tool` | 34 | 18 / 7 / 9 (0.80) | 21 / 0 / 13 (0.72) | 21 / 0 / 13 (0.77) | 17 / 3 / 14 (0.85) | 1 / 30 / 3 | 2 / 29 / 1 | 0.06, 0.09, 0.06, 0.19, 0.58, 1.00 |
| `v3` against `v3-tool` | 34 | 18 / 8 / 8 (0.86) | 19 / 0 / 15 (0.90) | 22 / 0 / 12 (0.92) | 18 / 3 / 13 (1.02) | 2 / 32 / 0 | 1 / 30 / 1 | 0.08, 0.35, 0.48, 0.90, 0.49, 1.00 |
| `v2-tool` against `grep` | 34 | 18 / 8 / 8 (1.00) | 18 / 0 / 16 (1.33) | 16 / 0 / 18 (1.22) | 21 / 4 / 9 (0.92) | 2 / 30 / 2 | 2 / 28 / 2 | 1.00, 0.30, 0.34, 0.64, 1.00, 1.00 |
| `v3-tool` against `grep` | 34 | 17 / 11 / 6 (0.88) | 15 / 0 / 19 (1.06) | 15 / 0 / 19 (1.04) | 20 / 7 / 7 (0.83) | 0 / 31 / 3 | 2 / 29 / 1 | 0.19, 0.65, 0.67, 0.08, 0.43, 1.00 |
| `v2` against `grep` | 34 | 18 / 11 / 5 (0.80) | 18 / 0 / 16 (0.95) | 18 / 0 / 16 (0.94) | 25 / 3 / 6 (0.79) | 1 / 30 / 3 | 2 / 29 / 1 | 0.01, 0.72, 0.57, 0.01, 0.56, 1.00 |
| `v3` against `grep` | 34 | 22 / 4 / 8 (0.76) | 22 / 0 / 12 (0.95) | 18 / 0 / 16 (0.96) | 21 / 3 / 10 (0.85) | 0 / 33 / 1 | 1 / 31 / 0 | 0.03, 0.77, 0.81, 0.33, 1.00, 1.00 |
| noise: `v2-tool` run 2 against run 1 | 17 | 4 / 5 / 8 (1.29) | 7 / 0 / 10 (1.68) | 5 / 0 / 12 (1.54) | 6 / 1 / 10 (1.45) | 0 / 17 / 0 | 0 / 16 / 0 | |
| noise: `v3-tool` run 2 against run 1 | 17 | 10 / 2 / 5 (0.99) | 12 / 0 / 5 (0.99) | 12 / 0 / 5 (0.90) | 9 / 3 / 5 (0.96) | 1 / 16 / 0 | 1 / 15 / 0 | |
| noise: `v2` run 2 against run 1 | 17 | 3 / 8 / 6 (1.19) | 5 / 0 / 12 (1.27) | 11 / 0 / 6 (1.06) | 8 / 2 / 7 (1.08) | 1 / 15 / 1 | 0 / 15 / 1 | |
| noise: `v3` run 2 against run 1 | 17 | 5 / 3 / 9 (0.93) | 6 / 0 / 11 (0.85) | 10 / 0 / 7 (0.72) | 9 / 1 / 7 (0.70) | 1 / 16 / 0 | 1 / 15 / 0 | |

Discarded by the harness and run again: `v3-tool` 1 (the first search_code call left out `query`: a validation error, the server alive). compare.py reads such a call as a server that died, so its rule replaces these sessions by new runs. Counted with their first attempts instead:

| Pairs on the same task: B against A | Pairs | Turns: B lower / equal / higher (sum B / sum A) | Tokens | Cost | Seconds (within 5% = equal) | Right file first: B better / same / worse | Right function | p: turns, tokens, cost, seconds, file, function |
|---|---|---|---|---|---|---|---|---|
| `v3-tool` against `v2-tool`, first attempts | 34 | 12 / 12 / 10 (0.89) | 13 / 0 / 21 (0.81) | 14 / 0 / 20 (0.86) | 11 / 5 / 18 (0.91) | 0 / 31 / 3 | 2 / 29 / 1 | 0.32, 0.24, 0.26, 0.49, 0.17, 1.00 |
| `v3` against `v2`, first attempts | 34 | 13 / 10 / 11 (0.95) | 15 / 0 / 19 (0.99) | 16 / 0 / 18 (1.02) | 13 / 3 / 18 (1.08) | 2 / 31 / 1 | 1 / 30 / 1 | 0.66, 0.95, 0.89, 0.54, 1.00, 1.00 |
| `v3-tool` against `grep`, first attempts | 34 | 17 / 10 / 7 (0.89) | 15 / 0 / 19 (1.07) | 15 / 0 / 19 (1.05) | 20 / 7 / 7 (0.84) | 0 / 31 / 3 | 2 / 29 / 1 | 0.24, 0.57, 0.61, 0.09, 0.43, 1.00 |
| `v3` against `grep`, first attempts | 34 | 22 / 4 / 8 (0.76) | 22 / 0 / 12 (0.95) | 18 / 0 / 16 (0.96) | 21 / 3 / 10 (0.85) | 0 / 33 / 1 | 1 / 31 / 0 | 0.03, 0.77, 0.81, 0.33, 1.00, 1.00 |

Use of search_code:

| Arm | Sessions that searched (first call at turn 1) | search_code calls | Calls with intent / symptom / anchors / locations | Median characters of a call's arguments (of its query) | Calls asking k > 10 | Median characters of a result | First search: right file in its results (right function) | First search: median rank of the right file | Calls that failed in these sessions (of them: no `query`) |
|---|---|---|---|---|---|---|---|---|---|
| `v2-tool` | 34 of 34 (34) | 66 | 0 / 0 / 0 / 0 | 108 (82) | 0 | 4,506 | 25 (16) of 34 | 1 | 0 (0) |
| `v3-tool` | 34 of 34 (34) | 55 | 54 / 53 / 51 / 23 | 491 (98) | 0 | 4,486 | 27 (21) of 34 | 1 | 0 (0); and 1 discarded first attempts whose first call had no `query` |
| `v2` | 29 of 34 (29) | 43 | 0 / 0 / 0 / 0 | 107 (79) | 0 | 4,776 | 22 (18) of 29 | 1.0 | 0 (0) |
| `v3` | 30 of 34 (30) | 35 | 35 / 35 / 35 / 20 | 517 (100) | 0 | 4,781 | 26 (20) of 30 | 1.0 | 0 (0) |

What codemem's definitions add to each request:

| Arm | codemem tool definitions, characters (search_code's description) | Server instructions, characters | First request, input tokens: median | More than `grep`, same task: median | More than `v2-tool`, same task: median | Model requests per session: median |
|---|---|---|---|---|---|---|
| `grep` | 0 (0) | - | 10,488 | - | - | 5 |
| `v2-tool` | 2,144 (483) | 611 | 11,523 | 1,035 | - | 4 |
| `v3-tool` | 3,405 (1,352) | 825 | 12,008 | 1,520 | 485 | 4 |
| `v2` | 2,144 (483) | 611 | 12,222 | 1,731 | - | 4 |
| `v3` | 3,405 (1,352) | 825 | 12,707 | 2,216 | 485 | 3 |
<!-- s1: end -->

<!-- s2h: start -->
### Stage 2a: Haiku, vLLM (6 tasks, L2): grep once, each codemem arm twice

54 sessions. Right file first: the answer's first file is a file of the fix. Right function: a function of the fix named (the harness's full-name rule).

| Arm | Sessions | Right file first | Right function | Turns: median / sum | Seconds: median / sum | Tokens, all: median / sum | Cost $: median / sum | search_code calls per session |
|---|---|---|---|---|---|---|---|---|
| `grep` | 6 | 5 | 6 of 6 | 8.5 / 50 | 23.9 / 142 | 140,443 / 890,173 | 0.0057 / 0.0338 | 0.00 |
| `v2-tool` | 12 | 9 | 11 of 12 | 5.0 / 83 | 13.7 / 218 | 82,527 / 1,759,141 | 0.0034 / 0.0569 | 2.17 |
| `v3-tool` | 12 | 10 | 11 of 12 | 5.0 / 73 | 13.7 / 219 | 81,671 / 1,440,167 | 0.0036 / 0.0538 | 2.00 |
| `v2` | 12 | 10 | 10 of 12 | 5.0 / 83 | 15.5 / 261 | 83,472 / 1,833,200 | 0.0033 / 0.0642 | 1.17 |
| `v3` | 12 | 9 | 9 of 12 | 6.0 / 93 | 21.8 / 342 | 107,820 / 2,377,492 | 0.0045 / 0.0851 | 2.33 |

Tokens by class (new input, cache write, cache read, output):

| Arm | New input: median / sum | Cache write: median / sum | Cache read: median / sum | Output: median / sum |
|---|---|---|---|---|
| `grep` | 17 / 100 | 12,246 / 72,796 | 124,242 / 794,715 | 3,686 / 22,562 |
| `v2-tool` | 10 / 166 | 7,906 / 128,675 | 69,222 / 1,600,022 | 1,892 / 30,278 |
| `v3-tool` | 10 / 146 | 8,480 / 121,364 | 70,512 / 1,285,265 | 2,281 / 33,392 |
| `v2` | 10 / 166 | 8,015 / 135,801 | 72,975 / 1,656,318 | 2,262 / 40,915 |
| `v3` | 12 / 186 | 11,134 / 184,735 | 95,230 / 2,139,007 | 3,109 / 53,564 |

Pairs on the same task. Each cell: B lower / equal / higher than A, then in brackets the sum of B over the sum of A. p: a permutation test within each task (the arm labels of the task's sessions shuffled, 5,000 times; two-sided), so it measures the gap against the spread between runs. Noise rows: the second run of an arm against its first, on the same task.

| Pairs on the same task: B against A | Pairs | Turns: B lower / equal / higher (sum B / sum A) | Tokens | Cost | Seconds (within 5% = equal) | Right file first: B better / same / worse | Right function | p: turns, tokens, cost, seconds, file, function |
|---|---|---|---|---|---|---|---|---|
| `v3-tool` against `v2-tool` | 12 | 5 / 2 / 5 (0.88) | 6 / 0 / 6 (0.82) | 6 / 0 / 6 (0.95) | 5 / 0 / 7 (1.00) | 1 / 11 / 0 | 1 / 10 / 1 | 0.75, 0.76, 0.78, 0.98, 1.00, 1.00 |
| `v3` against `v2` | 12 | 2 / 5 / 5 (1.12) | 2 / 0 / 10 (1.30) | 2 / 0 / 10 (1.33) | 2 / 1 / 9 (1.31) | 0 / 11 / 1 | 0 / 11 / 1 | 0.54, 0.47, 0.18, 0.08, 1.00, 1.00 |
| `v2` against `v2-tool` | 12 | 5 / 1 / 6 (1.00) | 5 / 0 / 7 (1.04) | 6 / 0 / 6 (1.13) | 5 / 0 / 7 (1.20) | 1 / 11 / 0 | 0 / 11 / 1 | 1.00, 0.86, 0.65, 0.40, 1.00, 1.00 |
| `v3` against `v3-tool` | 12 | 5 / 1 / 6 (1.27) | 5 / 0 / 7 (1.65) | 4 / 0 / 8 (1.58) | 3 / 2 / 7 (1.56) | 0 / 11 / 1 | 0 / 10 / 2 | 0.30, 0.21, 0.09, 0.05, 1.00, 0.51 |
| `v2-tool` against `grep` | 12 | 11 / 0 / 1 (0.83) | 11 / 0 / 1 (0.99) | 10 / 0 / 2 (0.84) | 11 / 0 / 1 (0.77) | 0 / 11 / 1 | 0 / 11 / 1 | 0.61, 1.00, 0.64, 0.34, 1.00, 1.00 |
| `v3-tool` against `grep` | 12 | 10 / 1 / 1 (0.73) | 8 / 0 / 4 (0.81) | 8 / 0 / 4 (0.80) | 8 / 1 / 3 (0.77) | 0 / 12 / 0 | 0 / 11 / 1 | 0.03, 0.40, 0.32, 0.20, 1.00, 1.00 |
| `v2` against `grep` | 12 | 9 / 1 / 2 (0.83) | 8 / 0 / 4 (1.03) | 7 / 0 / 5 (0.95) | 8 / 1 / 3 (0.92) | 0 / 12 / 0 | 0 / 10 / 2 | 0.35, 0.95, 0.80, 0.56, 1.00, 0.33 |
| `v3` against `grep` | 12 | 8 / 0 / 4 (0.93) | 7 / 0 / 5 (1.34) | 5 / 0 / 7 (1.26) | 5 / 2 / 5 (1.20) | 0 / 11 / 1 | 0 / 9 / 3 | 0.85, 0.77, 0.62, 0.59, 1.00, 0.45 |
| noise: `v2-tool` run 2 against run 1 | 6 | 2 / 1 / 3 (1.44) | 3 / 0 / 3 (2.08) | 3 / 0 / 3 (1.58) | 2 / 0 / 4 (1.42) | 0 / 5 / 1 | 0 / 5 / 1 | |
| noise: `v3-tool` run 2 against run 1 | 6 | 2 / 2 / 2 (0.97) | 3 / 0 / 3 (0.84) | 4 / 0 / 2 (0.84) | 1 / 2 / 3 (0.93) | 0 / 6 / 0 | 1 / 5 / 0 | |
| noise: `v2` run 2 against run 1 | 6 | 1 / 3 / 2 (0.93) | 3 / 0 / 3 (0.82) | 4 / 0 / 2 (0.88) | 3 / 1 / 2 (0.96) | 0 / 6 / 0 | 0 / 6 / 0 | |
| noise: `v3` run 2 against run 1 | 6 | 3 / 1 / 2 (0.72) | 4 / 0 / 2 (0.53) | 5 / 0 / 1 (0.65) | 3 / 0 / 3 (0.82) | 1 / 5 / 0 | 1 / 5 / 0 | |

Discarded by the harness and run again: `v3` 2 (the first search_code call left out `query`: a validation error, the server alive). compare.py reads such a call as a server that died, so its rule replaces these sessions by new runs. Counted with their first attempts instead:

| Pairs on the same task: B against A | Pairs | Turns: B lower / equal / higher (sum B / sum A) | Tokens | Cost | Seconds (within 5% = equal) | Right file first: B better / same / worse | Right function | p: turns, tokens, cost, seconds, file, function |
|---|---|---|---|---|---|---|---|---|
| `v3-tool` against `v2-tool`, first attempts | 12 | 5 / 2 / 5 (0.88) | 6 / 0 / 6 (0.82) | 6 / 0 / 6 (0.95) | 5 / 0 / 7 (1.00) | 1 / 11 / 0 | 1 / 10 / 1 | 0.75, 0.76, 0.78, 0.98, 1.00, 1.00 |
| `v3` against `v2`, first attempts | 12 | 3 / 4 / 5 (0.98) | 3 / 0 / 9 (0.93) | 3 / 0 / 9 (1.07) | 3 / 1 / 8 (1.08) | 0 / 12 / 0 | 0 / 12 / 0 | 0.94, 0.80, 0.68, 0.61, 1.00, 1.00 |
| `v3-tool` against `grep`, first attempts | 12 | 10 / 1 / 1 (0.73) | 8 / 0 / 4 (0.81) | 8 / 0 / 4 (0.80) | 8 / 1 / 3 (0.77) | 0 / 12 / 0 | 0 / 11 / 1 | 0.03, 0.40, 0.32, 0.20, 1.00, 1.00 |
| `v3` against `grep`, first attempts | 12 | 8 / 0 / 4 (0.81) | 7 / 0 / 5 (0.95) | 5 / 0 / 7 (1.02) | 6 / 1 / 5 (0.99) | 0 / 12 / 0 | 0 / 10 / 2 | 0.18, 0.79, 0.88, 0.95, 1.00, 0.33 |

Use of search_code:

| Arm | Sessions that searched (first call at turn 1) | search_code calls | Calls with intent / symptom / anchors / locations | Median characters of a call's arguments (of its query) | Calls asking k > 10 | Median characters of a result | First search: right file in its results (right function) | First search: median rank of the right file | Calls that failed in these sessions (of them: no `query`) |
|---|---|---|---|---|---|---|---|---|---|
| `v2-tool` | 12 of 12 (12) | 26 | 0 / 0 / 0 / 0 | 87 (65) | 0 | 4,463 | 10 (8) of 12 | 1.0 | 0 (0) |
| `v3-tool` | 12 of 12 (12) | 24 | 22 / 21 / 22 / 0 | 430 (82) | 0 | 4,529 | 8 (7) of 12 | 1.0 | 0 (0) |
| `v2` | 10 of 12 (9) | 14 | 0 / 0 / 0 / 0 | 89 (67) | 0 | 4,510 | 9 (6) of 10 | 1 | 0 (0) |
| `v3` | 12 of 12 (10) | 28 | 28 / 27 / 28 / 5 | 492 (95) | 0 | 4,268 | 10 (8) of 12 | 1.0 | 0 (0); and 2 discarded first attempts whose first call had no `query` |

What codemem's definitions add to each request:

| Arm | codemem tool definitions, characters (search_code's description) | Server instructions, characters | First request, input tokens: median | More than `grep`, same task: median | More than `v2-tool`, same task: median | Model requests per session: median |
|---|---|---|---|---|---|---|
| `grep` | 0 (0) | - | 10,482 | - | - | 8 |
| `v2-tool` | 2,144 (483) | 611 | 11,518 | 1,035 | - | 5 |
| `v3-tool` | 3,405 (1,352) | 825 | 12,002 | 1,520 | 485 | 5 |
| `v2` | 2,144 (483) | 611 | 12,314 | 1,835 | - | 5 |
| `v3` | 3,405 (1,352) | 825 | 12,799 | 2,320 | 485 | 6 |
<!-- s2h: end -->

<!-- s2s: start -->
### Stage 2b: Sonnet, vLLM (6 tasks, L2): each arm once

30 sessions. Right file first: the answer's first file is a file of the fix. Right function: a function of the fix named (the harness's full-name rule).

| Arm | Sessions | Right file first | Right function | Turns: median / sum | Seconds: median / sum | Tokens, all: median / sum | Cost $: median / sum | search_code calls per session |
|---|---|---|---|---|---|---|---|---|
| `grep` | 6 | 5 | 5 of 6 | 6.5 / 40 | 14.9 / 91 | 41,164 / 296,126 | 0.0435 / 0.2949 | 0.00 |
| `v2-tool` | 6 | 5 | 5 of 6 | 6.5 / 36 | 14.5 / 76 | 47,574 / 298,839 | 0.0436 / 0.2796 | 0.50 |
| `v3-tool` | 6 | 5 | 5 of 6 | 6.0 / 37 | 14.2 / 81 | 53,755 / 334,201 | 0.0491 / 0.3004 | 0.83 |
| `v2` | 6 | 5 | 6 of 6 | 6.0 / 33 | 15.0 / 86 | 54,471 / 324,436 | 0.0521 / 0.3079 | 0.00 |
| `v3` | 6 | 5 | 5 of 6 | 5.5 / 33 | 14.9 / 85 | 53,306 / 337,567 | 0.0511 / 0.3134 | 0.00 |

Tokens by class (new input, cache write, cache read, output):

| Arm | New input: median / sum | Cache write: median / sum | Cache read: median / sum | Output: median / sum |
|---|---|---|---|---|
| `grep` | 13 / 80 | 5,992 / 42,068 | 33,890 / 246,253 | 1,270 / 7,725 |
| `v2-tool` | 13 / 72 | 6,578 / 42,106 | 40,538 / 250,565 | 1,230 / 6,096 |
| `v3-tool` | 12 / 74 | 7,186 / 42,876 | 45,976 / 284,057 | 1,358 / 7,194 |
| `v2` | 12 / 66 | 6,914 / 43,955 | 46,022 / 272,673 | 1,434 / 7,742 |
| `v3` | 11 / 66 | 7,632 / 46,089 | 44,754 / 284,209 | 1,331 / 7,203 |

Pairs on the same task. Each cell: B lower / equal / higher than A, then in brackets the sum of B over the sum of A. p: a permutation test within each task (the arm labels of the task's sessions shuffled, 5,000 times; two-sided), so it measures the gap against the spread between runs. Noise rows: the second run of an arm against its first, on the same task.

| Pairs on the same task: B against A | Pairs | Turns: B lower / equal / higher (sum B / sum A) | Tokens | Cost | Seconds (within 5% = equal) | Right file first: B better / same / worse | Right function | p: turns, tokens, cost, seconds, file, function |
|---|---|---|---|---|---|---|---|---|
| `v3-tool` against `v2-tool` | 6 | 2 / 3 / 1 (1.03) | 3 / 0 / 3 (1.12) | 3 / 0 / 3 (1.07) | 2 / 1 / 3 (1.07) | 0 / 6 / 0 | 0 / 6 / 0 | 1.00, 0.81, 0.42, 0.60, 1.00, 1.00 |
| `v3` against `v2` | 6 | 2 / 2 / 2 (1.00) | 2 / 0 / 4 (1.04) | 2 / 0 / 4 (1.02) | 2 / 1 / 3 (0.98) | 0 / 6 / 0 | 0 / 5 / 1 | 1.00, 0.67, 0.59, 0.83, 1.00, 1.00 |
| `v2` against `v2-tool` | 6 | 2 / 4 / 0 (0.92) | 2 / 0 / 4 (1.09) | 2 / 0 / 4 (1.10) | 1 / 0 / 5 (1.13) | 0 / 6 / 0 | 1 / 5 / 0 | 0.51, 0.53, 0.57, 0.25, 1.00, 1.00 |
| `v3` against `v3-tool` | 6 | 4 / 1 / 1 (0.89) | 4 / 0 / 2 (1.01) | 2 / 0 / 4 (1.04) | 3 / 1 / 2 (1.04) | 0 / 6 / 0 | 1 / 4 / 1 | 0.50, 0.97, 0.76, 0.94, 1.00, 1.00 |
| `v2-tool` against `grep` | 6 | 3 / 1 / 2 (0.90) | 3 / 0 / 3 (1.01) | 2 / 0 / 4 (0.95) | 4 / 0 / 2 (0.84) | 0 / 6 / 0 | 0 / 6 / 0 | 0.43, 0.93, 0.74, 0.28, 1.00, 1.00 |
| `v3-tool` against `grep` | 6 | 4 / 0 / 2 (0.93) | 3 / 0 / 3 (1.13) | 2 / 0 / 4 (1.02) | 4 / 0 / 2 (0.90) | 0 / 6 / 0 | 0 / 6 / 0 | 0.75, 0.55, 0.94, 0.49, 1.00, 1.00 |
| `v2` against `grep` | 6 | 3 / 1 / 2 (0.82) | 3 / 0 / 3 (1.10) | 3 / 0 / 3 (1.04) | 3 / 0 / 3 (0.95) | 0 / 6 / 0 | 1 / 5 / 0 | 0.31, 0.71, 0.84, 0.81, 1.00, 1.00 |
| `v3` against `grep` | 6 | 3 / 1 / 2 (0.82) | 3 / 0 / 3 (1.14) | 3 / 0 / 3 (1.06) | 3 / 0 / 3 (0.93) | 0 / 6 / 0 | 1 / 4 / 1 | 0.25, 0.59, 0.81, 0.75, 1.00, 1.00 |

Use of search_code:

| Arm | Sessions that searched (first call at turn 1) | search_code calls | Calls with intent / symptom / anchors / locations | Median characters of a call's arguments (of its query) | Calls asking k > 10 | Median characters of a result | First search: right file in its results (right function) | First search: median rank of the right file | Calls that failed in these sessions (of them: no `query`) |
|---|---|---|---|---|---|---|---|---|---|
| `v2-tool` | 3 of 6 (3) | 3 | 0 / 0 / 0 / 0 | 88 (75) | 0 | 4,512 | 2 (2) of 3 | 1.0 | 0 (0) |
| `v3-tool` | 5 of 6 (5) | 5 | 0 / 0 / 5 / 0 | 125 (69) | 0 | 5,038 | 5 (4) of 5 | 1 | 0 (0) |
| `v2` | 0 of 6 (0) | 0 | 0 / 0 / 0 / 0 | - (-) | 0 | - | 0 (0) of 0 | - | 0 (0) |
| `v3` | 0 of 6 (0) | 0 | 0 / 0 / 0 / 0 | - (-) | 0 | - | 0 (0) of 0 | - | 0 (0) |

What codemem's definitions add to each request:

| Arm | codemem tool definitions, characters (search_code's description) | Server instructions, characters | First request, input tokens: median | More than `grep`, same task: median | More than `v2-tool`, same task: median | Model requests per session: median |
|---|---|---|---|---|---|---|
| `grep` | 0 (0) | - | 4,102 | - | - | 6 |
| `v2-tool` | 2,144 (483) | 611 | 5,138 | 1,035 | - | 6 |
| `v3-tool` | 3,405 (1,352) | 825 | 5,622 | 1,520 | 485 | 6 |
| `v2` | 2,144 (483) | 611 | 5,934 | 1,835 | - | 6 |
| `v3` | 3,405 (1,352) | 825 | 6,419 | 2,320 | 485 | 6 |
<!-- s2s: end -->

<!-- s3: start -->
### Stages 3 and 4: Sonnet, pandas (17 tasks, L2): each arm once; `v2` and `v3` a second time on 8 tasks (stage 4, until the cap of 340 sessions)

100 sessions. Right file first: the answer's first file is a file of the fix. Right function: a function of the fix named (the harness's full-name rule).

| Arm | Sessions | Right file first | Right function | Turns: median / sum | Seconds: median / sum | Tokens, all: median / sum | Cost $: median / sum | search_code calls per session |
|---|---|---|---|---|---|---|---|---|
| `grep` | 17 | 15 | 14 of 16 | 4 / 88 | 7.7 / 193 | 22,824 / 632,607 | 0.0268 / 0.6653 | 0.00 |
| `v2-tool` | 17 | 15 | 15 of 16 | 4 / 67 | 8.2 / 146 | 25,142 / 486,976 | 0.0304 / 0.5340 | 0.18 |
| `v3-tool` | 17 | 15 | 15 of 16 | 4 / 75 | 8.4 / 160 | 32,519 / 649,759 | 0.0326 / 0.6171 | 0.53 |
| `v2` | 24 | 22 | 21 of 23 | 3.0 / 77 | 6.4 / 164 | 21,100 / 589,312 | 0.0212 / 0.6069 | 0.00 |
| `v3` | 25 | 21 | 23 of 24 | 3 / 90 | 6.8 / 198 | 23,249 / 751,269 | 0.0237 / 0.6942 | 0.00 |

Tokens by class (new input, cache write, cache read, output):

| Arm | New input: median / sum | Cache write: median / sum | Cache read: median / sum | Output: median / sum |
|---|---|---|---|---|
| `grep` | 8 / 176 | 4,257 / 97,902 | 18,017 / 517,550 | 615 / 16,979 |
| `v2-tool` | 8 / 134 | 4,943 / 86,481 | 20,383 / 389,363 | 635 / 10,998 |
| `v3-tool` | 8 / 150 | 4,769 / 97,406 | 26,924 / 540,293 | 574 / 11,910 |
| `v2` | 6 / 154 | 3,665 / 98,374 | 17,440 / 479,060 | 444 / 11,724 |
| `v3` | 6 / 180 | 3,913 / 106,161 | 19,392 / 630,618 | 482 / 14,310 |

Pairs on the same task. Each cell: B lower / equal / higher than A, then in brackets the sum of B over the sum of A. p: a permutation test within each task (the arm labels of the task's sessions shuffled, 5,000 times; two-sided), so it measures the gap against the spread between runs. Noise rows: the second run of an arm against its first, on the same task.

| Pairs on the same task: B against A | Pairs | Turns: B lower / equal / higher (sum B / sum A) | Tokens | Cost | Seconds (within 5% = equal) | Right file first: B better / same / worse | Right function | p: turns, tokens, cost, seconds, file, function |
|---|---|---|---|---|---|---|---|---|
| `v3-tool` against `v2-tool` | 17 | 3 / 7 / 7 (1.12) | 3 / 0 / 14 (1.33) | 5 / 0 / 12 (1.16) | 6 / 1 / 10 (1.10) | 0 / 17 / 0 | 0 / 16 / 0 | 0.19, 0.01, 0.22, 0.22, 1.00, 1.00 |
| `v3` against `v2` | 25 | 5 / 9 / 11 (1.10) | 7 / 0 / 18 (1.19) | 11 / 0 / 14 (1.08) | 4 / 7 / 14 (1.14) | 0 / 24 / 1 | 1 / 23 / 0 | 0.26, 0.11, 0.67, 0.10, 1.00, 1.00 |
| `v2` against `v2-tool` | 24 | 14 / 6 / 4 (0.85) | 16 / 0 / 8 (0.91) | 19 / 0 / 5 (0.86) | 16 / 1 / 7 (0.85) | 0 / 24 / 0 | 0 / 22 / 1 | 0.06, 0.44, 0.21, 0.07, 1.00, 1.00 |
| `v3` against `v3-tool` | 25 | 11 / 13 / 1 (0.82) | 11 / 0 / 14 (0.77) | 18 / 0 / 7 (0.76) | 16 / 4 / 5 (0.84) | 0 / 24 / 1 | 0 / 24 / 0 | 0.02, 0.05, 0.01, 0.01, 1.00, 1.00 |
| `v2-tool` against `grep` | 17 | 8 / 6 / 3 (0.76) | 8 / 0 / 9 (0.77) | 9 / 0 / 8 (0.80) | 10 / 1 / 6 (0.76) | 0 / 17 / 0 | 1 / 15 / 0 | 0.04, 0.14, 0.12, 0.03, 1.00, 1.00 |
| `v3-tool` against `grep` | 17 | 7 / 4 / 6 (0.85) | 7 / 0 / 10 (1.03) | 8 / 0 / 9 (0.93) | 7 / 1 / 9 (0.83) | 0 / 17 / 0 | 1 / 15 / 0 | 0.22, 0.87, 0.59, 0.15, 1.00, 1.00 |
| `v2` against `grep` | 24 | 17 / 4 / 3 (0.69) | 16 / 0 / 8 (0.78) | 15 / 0 / 9 (0.75) | 16 / 2 / 6 (0.69) | 0 / 24 / 0 | 2 / 20 / 1 | 0.00, 0.07, 0.03, 0.01, 1.00, 1.00 |
| `v3` against `grep` | 25 | 13 / 12 / 0 (0.74) | 11 / 0 / 14 (0.88) | 16 / 0 / 9 (0.77) | 15 / 4 / 6 (0.76) | 0 / 24 / 1 | 2 / 22 / 0 | 0.00, 0.20, 0.02, 0.00, 1.00, 0.33 |
| noise: `v2` run 2 against run 1 | 7 | 1 / 3 / 3 (1.22) | 2 / 0 / 5 (1.25) | 4 / 0 / 3 (0.83) | 4 / 0 / 3 (1.11) | 0 / 7 / 0 | 0 / 6 / 1 | |
| noise: `v3` run 2 against run 1 | 8 | 2 / 6 / 0 (0.93) | 3 / 0 / 5 (1.01) | 7 / 0 / 1 (0.84) | 3 / 3 / 2 (0.97) | 0 / 8 / 0 | 0 / 8 / 0 | |

Use of search_code:

| Arm | Sessions that searched (first call at turn 1) | search_code calls | Calls with intent / symptom / anchors / locations | Median characters of a call's arguments (of its query) | Calls asking k > 10 | Median characters of a result | First search: right file in its results (right function) | First search: median rank of the right file | Calls that failed in these sessions (of them: no `query`) |
|---|---|---|---|---|---|---|---|---|---|
| `v2-tool` | 3 of 17 (3) | 3 | 0 / 0 / 0 / 0 | 120 (74) | 0 | 5,836 | 2 (1) of 3 | 1.0 | 0 (0) |
| `v3-tool` | 9 of 17 (9) | 9 | 1 / 0 / 8 / 0 | 156 (78) | 0 | 5,120 | 8 (5) of 9 | 1.0 | 0 (0) |
| `v2` | 0 of 24 (0) | 0 | 0 / 0 / 0 / 0 | - (-) | 0 | - | 0 (0) of 0 | - | 0 (0) |
| `v3` | 0 of 25 (0) | 0 | 0 / 0 / 0 / 0 | - (-) | 0 | - | 0 (0) of 0 | - | 0 (0) |

What codemem's definitions add to each request:

| Arm | codemem tool definitions, characters (search_code's description) | Server instructions, characters | First request, input tokens: median | More than `grep`, same task: median | More than `v2-tool`, same task: median | Model requests per session: median |
|---|---|---|---|---|---|---|
| `grep` | 0 (0) | - | 4,108 | - | - | 4 |
| `v2-tool` | 2,144 (483) | 611 | 5,143 | 1,035 | - | 4 |
| `v3-tool` | 3,405 (1,352) | 825 | 5,628 | 1,520 | 485 | 4 |
| `v2` | 2,144 (483) | 611 | 5,842 | 1,731 | - | 3 |
| `v3` | 3,405 (1,352) | 825 | 6,327 | 2,216 | 485 | 3 |
<!-- s3: end -->

## Worked example

<!-- example: start -->
**Task 71129, Haiku, `v2` against `v3` (both with the same 20 lines).** The request: "Appending float categories to
integer categories in an HDF5 table now fails with a low-level buffer type error instead of the different-categories
error. Please restore it." The fix is in `IndexCol.validate_metadata` (`pandas/io/pytables.py`). The 20 lines show
`pytables.py` six times in the first seven places, but not that method.

- **`v2`, run 1:** one search, `append categories mismatch error when appending different categories to HDF5 table`
  (with `path_prefix` the file): the method comes 7th. The agent reads on: 4 turns, 67,106 tokens, $0.0034. Run 2: a
  similar query, the method not in the 10 results; 6 turns, 99,226 tokens, $0.0030.
- **`v3`, run 1:** one search whose arguments the new wording asked for: the query, plus `intent` ("Detect when a
  categorical column being appended to an HDF5 table has different categories than the stored table and raise a
  different-categories error before writing the buffer."), `symptom` (the request in other words), `anchors`
  (`different categories`, `categories`, `buffer`, `append`) and `locations` (`pandas/io/pytables.py`, taken from the
  20 lines). The method comes first. 3 turns, 48,919 tokens, $0.0027. Run 2: the same shape of call, the method first
  again; 3 turns, 44,690 tokens, $0.0017.

The opposite also happens. On the easy tasks 67025 and 67897 the agent of `v2` answered from the 20 lines without any
search (2 turns, about 27k tokens), while the agent of `v3` searched first, as v3's wording asks "for your first
search on a task", and used about 40% more tokens. Over the 17 tasks the two effects about cancel (point 1 above).
<!-- example: end -->

## What these sessions do not measure

- **Fix runs.** Here the agent only locates the code and names files and functions; the PR's own tests were fix runs
  (the agent edits until done, scored on the gold functions it edited). Locating is the part of a run where the search
  tool acts, so these sessions test v3's changes with less unrelated noise; but they do not cover a second search when
  the agent loses the trail while editing, which v3's wording also asks for, and a fixed extra per request (v3's longer
  definitions) weighs more in a fix run, which has more requests. Our "right function" is the analogue of the PR's
  "gold functions edited", not the same measure.
- **The hooks.** Neither arm had hooks (the evaluation does not install them either), so the PR's removal of the hooks
  changes nothing here.
- **Other levels, models and repositories.** Only L2; only Haiku and Sonnet; pandas and vLLM. No Opus, no open model.
- **The vLLM checkout is newer than some of the fixes.** `e9acf48` is later than the vLLM tasks' issues, so the code may
  already handle the case (the YAML `false` of task 51573 does); the gold location is still where the change belongs,
  and every arm sees the same code.
- **Sonnet's noise** was measured only for `v2` and `v3`, on 7 and 8 pandas tasks; the tool arms and vLLM have one
  Sonnet run per cell, so their Sonnet gaps stand only against the spread between tasks (the p values).
- **The harness's discard rule.** compare.py reads a first search_code call that fails as a server that died at start
  and runs the session again. Three Haiku sessions of v3 were discarded this way although the server was alive: the
  agent had left out `query`. The main tables count the new runs, as the harness does; each stage that had such a case also
  shows the comparison with the first attempts counted. The rule itself was not changed.
- **Cost** is Claude Code's estimate at list prices; the sessions ran on the subscription. The prompt cache keeps
  entries for an hour: the second run of an arm on a task can read what the first run wrote, which lowers its cost
  (not its token count). This is why the noise rows show second runs cheaper for Sonnet (cost -17% for `v2`, -16% for
  `v3`) with as many tokens or more; between arms, run 1 is paired with run 1 and run 2 with run 2.
