# Hybrid: grep or codemem search, Sonnet's choice at each step

Wilson, with Claude Code, 2026-11-26. Script: [`e2e_hybrid.py`](e2e_hybrid.py). Prompts:
[`system_hybrid_first.txt`](system_hybrid_first.txt) (step 1) and [`system_hybrid.txt`](system_hybrid.txt) (every
later step), schemas `schema_hybrid_first.json` and `schema_hybrid.json`. Sonnet calls: [`llm.py`](llm.py).

**Nothing here was graded with tests.** "Edited a gold function" means the final diff touches a line inside a
function that the real fix changed.

## 1. The algorithm

"codemem search" here means loop-k as in [`loop_k.md`](loop_k.md): merged judge and fix, one fresh Sonnet call per
step, prompt cache off, results shown as raw code, a result shown once is not shown again. The hybrid adds grep
as a second tool and lets Sonnet choose the tool at every step.

```
step 1 call (hybrid_first):  issue  ->  tool (codemem | grep)
                                        codemem: structured query (intent, symptom, anchors) + k in {3, 5, 10}
                                        grep:    regex + optional path + ignore case
step s = 1 .. 15:
  run the tool chosen for this step
    codemem, step 1:   loop-k's first round (AugRetriever._retrieve on the structured query)
    codemem, later:    one free-text query: its code, usage and BM25 lists, plus code and BM25 lists limited to each
                       look_in path, fused with RRF; top k not shown before, as raw code
    grep:              git grep -n -I -E; at most 40 matching lines (8 per file), each with its enclosing function
    read:              no new results; only the picks, in full
  one call (hybrid) sees: issue, earlier steps (tool, input, notes, picks, edit attempts), the full code of
                          everything picked so far, this step's results
  it returns one action:  edit | read | codemem (query, look_in, k) | grep (pattern, path, ignore case)
  edit:  applied only if every `old` text occurs exactly once in its file; then stop
         if it does not apply, the next step is a read with this step's results in the edited files added to the picks
cap: 15 steps (HYBRID_MAX_STEPS) or $3
```

Choices and why:

- **k is 3, 5 or 10, never 1 or 2.** A step that wants one or two results should use grep.
- **Only step 1 is structured.** Its intent / symptom / anchors query feeds loop-k's first round unchanged. Every
  later codemem step takes one free-text query (plus `look_in`): it is searched by meaning and by its words, so the
  model does not have to split it into fields. `look_in` stays because the folder limit moved a gold function from
  rank 59 to rank 1 in a check on playwright-42503.
- **A picked grep line pins its enclosing function** (or 25 lines on each side, outside any function), shown in full
  in every later step. `read` exists so that grep can be followed by reading the function before editing.
- **When to use which tool** is only in the prompts: grep when an exact string the code contains is known
  (identifier, option, error message, or a name seen in code whose definition or callers are wanted); codemem when
  the names are not known, several related functions are wanted in full, no precise folder or file is known, or the
  search has to change direction ("if you have no direct clue where to look, use codemem"). k: 3 or 5 when the
  query and the issue describe the code well enough that it should rank near the top, otherwise 10.

Run: `python run_vague8.py L1|L2 hybrid [TASK_IDS]` (arm `hybrid`), score with `score_vague8.py`.

## 2. Preliminary result: 2 tasks, one run each

Steps are tool runs (codemem searches, greps and reads). Sonnet calls are steps plus the step-1 call. For the grep
agent, turns are Claude Code's turns and the tool calls are counted by name.

| Task (level) | Arm | Cost (USD) | Turns or steps | Tool runs by kind | Sonnet calls | Gold functions edited |
|---|---|---:|---:|---|---:|---|
| playwright-42503 (L2) | grep agent | 0.093 | 11 turns | 7 Grep, 1 Read, 2 Edit | 11 turns | 1 of 1 |
| playwright-42503 (L2) | codemem only (loop-k) | 0.130 | 5 rounds | 5 codemem (k 5, 5, 5, 10, 5) | 6 | 1 of 1 |
| playwright-42503 (L2) | hybrid | 0.085 | 2 steps | 2 codemem (k 10, 5), 0 grep, 0 read | 3 | 1 of 1 |
| pandas-69779 (L1) | grep agent | 0.065 | 11 turns | 5 Grep, 2 Read, 3 Edit | 11 turns | 2 of 3 |
| pandas-69779 (L1) | codemem only (loop-k) | 0.036 | 1 round | 1 codemem (k 5) | 2 | 2 of 3 |
| pandas-69779 (L1) | hybrid | 0.038 | 1 step | 1 codemem (k 5), 0 grep, 0 read | 2 | 2 of 3 |

- On both tasks the hybrid edits the same gold functions as the other two arms and costs less than grep
  ($0.123 against $0.158 in total). On playwright-42503 it needs 2 steps where loop-k needed 5 rounds: its second,
  free-text query with `look_in` on both playwright packages found `runDaemonForContext` at once.
- Both runs used codemem only, so they do not test grep inside the hybrid. An earlier smoke run on pandas-71129
  (L1, with an older wording of the prompts, not kept) used 3 greps and 1 read and edited the gold function for
  $0.064 (grep agent $0.034).
- Two tasks and one run each: this is a direction, not a measurement.

## 3. 35 contamination-free tasks (e2e-b45), 2026-11-27

**Tasks:** every task of `vague-b7-v3` (main) whose issue was opened after June 2026 and that has a gold function:
35 tasks (26 playwright, 9 pandas), 72 gold functions, fixes merged July to October 2026; L1 and L2 prompts.
Built by [`analysis/build_b45.py`](analysis/build_b45.py); outputs in `out/e2e-b45/`. One run per arm and task,
Sonnet 5.5. 44 grep / loop-k runs were reused from e2e-b7 and e2e-vague8 (same prompt and commit).

**This corrects section 2:** on 35 tasks the hybrid does not improve. Per-step costs and tokens:
[`analysis/cost_split.py`](analysis/cost_split.py); diagnosis: [`analysis/hybrid_diag.py`](analysis/hybrid_diag.py).

- It uses codemem once, then greps: step 1 is codemem in 46 of 70 runs; of the 199 later steps, 107 are grep, 88
  read and 4 codemem.
- Search is not the weak part: a gold function is shown in step 1 in 40 runs (loop-k round 1: 34).
- The gap is on fixes that span several functions. One gold function (34 runs): grep 33, loop-k 32, hybrid 32
  edited. Two or more (36 runs, 110 gold functions): grep 64, loop-k 53, hybrid 55. Both loops stop at their first
  edit that applies.
- Cost: every loop call is a fresh prompt at the full input price, while 88% of the grep agent's input is prompt-
  cache reads. `hybrid_gc` (cache on only for the calls that read grep results, `HYBRID_CACHE_GREP=1`) saved
  nothing: each step rebuilds its prompt, so cache writes exceeded cache reads.

## 4. hybrid_v2: one cached conversation ([`e2e_hybrid2.py`](e2e_hybrid2.py), arm `hybrid_v2`)

Prompt: [`system_hybrid_v2.txt`](system_hybrid_v2.txt). Step 1 is unchanged (the `hybrid_first` call). After it:

- **One conversation, cache on (F, E).** Each step is a `claude -p --resume` turn that appends only that step's
  results; nothing earlier is re-sent. Cost per call = difference of the session's cumulative `total_cost_usd`.
- **grep shows code (C).** 5 lines of context, blocks merged within a function, results numbered `S.N`. Over 40
  matching lines it shows only the lines and counts per file.
- **`open` replaces `read` (B).** Up to 3 targets: path + lines, path + symbol, or an earlier result `S.N`.
- **Repeated greps (A).** A grep whose alternatives overlap an earlier one (Jaccard at least 0.5) or that finds no new
  lines shows only its new lines and a note; from the second repeat on, grep is refused and dropped from the next
  schema. After 3 greps in a row a note says to switch to codemem.
- **Stopping (D).** A `done` action and a `done` flag on edits. After an applied edit without `done`, a review step
  shows the diff with the edited functions in full; after a failed edit, a retry step.
- **Tool guidance (G):** exact string: grep; known file or function: open; no clue or stuck: codemem; edit once
  the code in view confirms the fix; after an edit, check callers and sibling code paths.

Gold functions edited (of 72), tasks with a gold function edited (of 35). Steps are counted by kind; a retry is an
edit that did not apply and was shown again. Input tokens include cache writes and reads. A step's cost is the
cost of the Sonnet call that read its results; the step-1 call is in the total only.

| Level | Arm | Cost | Steps (by kind) | Cost per codemem / grep / read or open step | Input tokens | Output tokens | Cost per 1k tokens | Gold functions edited | Tasks hit |
|---|---|---:|---|---|---:|---:|---:|---:|---:|
| L1 | grep agent | $2.08 | 297 turns | | 2,292k | 71k | $0.0009 | 50 | 33 |
| L1 | codemem only | $2.25 | 77 codemem | $0.025 / - / - | 621k | 70k | $0.0033 | 45 | 32 |
| L1 | hybrid | $3.04 | 20 codemem, 66 grep, 41 read | $0.033 / $0.017 / $0.021 | 931k | 82k | $0.0030 | 45 | 33 |
| L1 | hybrid_v2 | $2.34 | 20 codemem, 38 grep, 20 open, 2 review, 2 retry | $0.036 / $0.020 / $0.021 | 1,259k | 81k | $0.0017 | 47 | 33 |
| L2 | grep agent | $2.26 | 309 turns | | 2,687k | 79k | $0.0008 | 47 | 33 |
| L2 | codemem only | $2.68 | 103 codemem | $0.023 / - / - | 819k | 79k | $0.0030 | 40 | 31 |
| L2 | hybrid | $4.21 | 30 codemem, 65 grep, 47 read | $0.033 / $0.021 / $0.032 | 1,397k | 109k | $0.0028 | 42 | 31 |
| L2 | hybrid_v2 | $3.16 | 29 codemem, 52 grep, 35 open, 3 review, 2 retry | $0.037 / $0.018 / $0.021 | 2,508k | 109k | $0.0012 | 41 | 30 |

- hybrid_v2 costs 23-25% less than the hybrid (79-80% of its input is cache reads) and takes 27 s per task
  (hybrid 39, grep 22). It edits about as many gold functions as the hybrid (better in 5 runs, worse in 5) and
  fewer than grep (grep better in 9 runs, worse in 1).
- The multi-function gap is unchanged: 56 of 110 against grep's 64. Only 5 of 70 runs reached a review step:
  Sonnet almost always sends its first edit with `done: true`. Codemem stays a first-step tool (46 first steps, 3
  later). Counts: [`analysis/v2_stats.py`](analysis/v2_stats.py).
- Other arms in the code, single smoke runs only: `hybrid_gc`, `hybrid_done` (stop only on `done`, review after
  each edit) and `hybrid_v2a` (`HYBRID_V2=1` in `e2e_hybrid.py`: rebuilt prompt with a keep list).
