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
