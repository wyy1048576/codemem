# Track B: grep, codemem only and the hybrid on 35 contamination-free tasks: the hybrid does not improve

- **Track:** B
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-27 04:50 UTC
- **Work package:** B1, end to end without tests
- **Branch, commits, pull request:** none yet. Outputs on Wilson's laptop, `analysis/b1-links/llm_query/out/e2e-b45/`
  (the hybrid's code is in PR #45 at `b82aca6`; the `hybrid_gc` switch below is not pushed)

## Done

**Tasks (e2e-b45):** every task of `vague-b7-v3` (main) whose issue was opened after June 2026 and that has a gold
function: 35 tasks (26 playwright, 9 pandas), 72 gold functions, fixes merged July to October 2026; L1 and L2.
**Arms:** grep agent, codemem only (loop-k, merged, no prompt cache), hybrid (`e2e_hybrid.py`). One run each,
Sonnet 5.5, 210 runs, none missing (44 grep / loop-k runs reused from e2e-b7 and e2e-vague8: same prompt and commit).

| Level | Arm | Cost, 35 tasks | Turns or steps (by kind) | Cost per codemem step | Cost per grep step | Cost per read step | Input tokens | Output tokens | Cost per 1k tokens | Gold functions edited (of 72) | Tasks with a gold function edited (of 35) |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| L1 | grep agent | $2.08 | 297 turns | | | | 2,292k | 71k | $0.0009 | 50 | 33 |
| L1 | codemem only | $2.25 | 77 (77 codemem) | $0.025 | | | 621k | 70k | $0.0033 | 45 | 32 |
| L1 | hybrid | $3.04 | 127 (20 codemem, 66 grep, 41 read) | $0.033 | $0.017 | $0.021 | 931k | 82k | $0.0030 | 45 | 33 |
| L2 | grep agent | $2.26 | 309 turns | | | | 2,687k | 79k | $0.0008 | 47 | 33 |
| L2 | codemem only | $2.68 | 103 (103 codemem) | $0.023 | | | 819k | 79k | $0.0030 | 40 | 31 |
| L2 | hybrid | $4.21 | 142 (30 codemem, 65 grep, 47 read) | $0.033 | $0.021 | $0.032 | 1,397k | 109k | $0.0028 | 42 | 31 |

Definitions: a step's cost is the cost of the Sonnet call that read that step's results; each loop run also has one
call that writes the first query (in the arm's cost, in no step column). Input tokens include cache writes and
cache reads. Mean seconds per task: grep 22, codemem only 34, hybrid 39.

**This corrects the entry of 02:45**, whose 2 tasks suggested the hybrid improves: on 35 tasks it edits no more gold
functions than codemem only (45 / 42 against 45 / 40) and fewer than grep (50 / 47), at 1.4 to 1.9 times their cost.

Why (70 task-levels, `hybrid_diag.py` in Wilson's scratchpad):

- **It uses codemem once, then greps.** Step 1 is codemem in 46 runs, grep in 24; of the 199 later steps, 107 are
  grep, 88 read and 4 codemem. On hard tasks it keeps grepping instead of changing direction (playwright-43172 L1:
  12 greps in a row).
- **Search is not the weak part.** The hybrid shows a gold function in step 1 in 40 runs (codemem only: round 1 in
  34); both never show one in 4.
- **The edit gap is all on fixes that span several functions.** One gold function (34 runs): grep 33, codemem only
  32, hybrid 32. Two or more (36 runs, 110 gold functions): grep 64, codemem only 53, hybrid 55. Both loops stop at
  their first edit that applies; the grep agent edits about 3 times per task.
- **Cost:** grep's tokens are about 3.5 times cheaper because 88% of its input is prompt-cache reads (one growing
  conversation); every loop call is a fresh prompt at the full input price. Most of the hybrid's greps (63 of 95 on
  the first 52 task-levels) are followed by a separate read call.
- **Cache on for grep steps only** (`HYBRID_CACHE_GREP=1`, arm `hybrid_gc`, 9 pandas tasks): no saving. Where the run
  followed the same steps (all of L1) it cost $0.693 against $0.669: the grep-step calls wrote 58.6k cache tokens and
  read back 46.6k, because each step rebuilds its prompt. L2 cost less ($0.64 against $1.06) only because two runs
  took different, shorter paths.

## Checked

`VAGUE_SET=e2e-b45 python score_vague8.py`, then the cost split (`cost_split.py`) and the diagnosis
(`hybrid_diag.py`), both in Wilson's scratchpad; every loop step was matched to its cached Sonnet answer (0 unmatched).
No tests (no Docker or NVIDIA GPU here). One run per arm and task.

## Left

Commit the outputs, the `hybrid_gc` switch and the scripts to PR #45 (waiting for Wilson). Repeat runs.

## Blocked on, or needed from others

A: grading saved diffs (unchanged).

## Next

Wilson: pick the next fix: keep editing after the first edit (the multi-function gap), merge grep and its read into
one step, or nudge codemem when greps stall. Wilson wants to edit the loop himself before the next proper test.
