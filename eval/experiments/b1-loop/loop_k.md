# Loop-k: Track B's chosen search loop (merged judge and fix, prompt cache off)

Wilson, with Claude Code, 2026-11-26. Script: [`e2e_loopk.py`](e2e_loopk.py). Prompts:
[`system_oneshot_k.txt`](system_oneshot_k.txt), [`system_loopk.txt`](system_loopk.txt) (schemas
`schema_oneshot_k.json`, `schema_loopk.json`). Sonnet calls: [`llm.py`](llm.py).

**Nothing here was graded with tests.** "Edited a gold function" means the final diff touches a line inside a
function that the real fix changed. The diffs are saved so that Track A can grade them (section 2).

## 0. The result in one table

14 vague-prompt tasks (8 pilot tasks and 6 b7 tasks, pandas and playwright, all opened after June 2026, valid, fair
by the screen). One run per arm, task and level, Sonnet 5.5 (medium effort) everywhere.

| Prompt level | Arm | Cost, 14 tasks (USD) | Gold functions edited (of 27) | Tasks with a gold function edited (of 14) |
|---|---|---|---|---|
| L1 | grep agent | 0.81 | 14 | 11 |
| L1 | **loop-k (merged, no prompt cache)** | **0.94** | **14** | **11** |
| L2 | grep agent | 1.04 | 16 | 12 |
| L2 | **loop-k (merged, no prompt cache)** | **1.08** | **14** | **12** |

Loop-k now costs about what grep costs (4% to 16% more) and edits the same tasks. The first codemem loop
(50 previews per round, separate fix call) cost about 4 times grep on the same kind of task (`loop_vs_grep.md`).
Grep is still faster: 17 to 32 s per task against 31 to 47 s.

## 1. The algorithm

```
first call (oneshot_k):  issue  ->  query (intent, symptom, anchors) + k in {1, 2, 3, 5, 10}
round r = 1 .. 10:
    results  = codemem top k for the query, leaving out every result shown before
    one call (loopk) sees:
        the issue
        its notes, picks and edit attempts of earlier rounds (short text)
        the full source of the results it picked earlier (up to 8 chunks, 60k characters)
        the k new results, each as raw code from the index (a chunk over 20k characters is cut;
        a class that long is shown as its skeleton, since its methods are results of their own)
    it returns either
        action = edit:   exact edits {path, old, new} on code it can see   -> apply all or nothing
        action = search: notes, picks, the next query and the next k
    edits applied             -> stop
    edits did not apply       -> next round shows the same code again with the error, no new results
stop at 10 rounds or $3
```

- **Sonnet picks k.** The first call picks k from how specific the issue is (1 to 3 when it names a function,
  option or exact string; 5 or 10 when it only describes behaviour). Each round picks the next k from how direct
  the next step is. In practice it picked 2, 3 or 5 almost every time, sometimes 1, and never 10.
- **One call per round.** The same call judges the results and writes the fix. There is no separate fix call
  that re-reads the issue, the notes and the code.
- **Picks stay visible.** Results it picked come back in full in every later round, so it can edit code it saw
  earlier. Results it did not pick are never shown again.
- **Prompt cache off.** `claude -p` writes each call's input to the prompt cache at the cache-write rate, about
  twice the plain input rate. Each loop call is a new conversation, so nothing reads that cache back except the
  shared system prompt. `e2e_loopk.py` turns caching off (`LLM_NO_PROMPT_CACHE=1`, which sets
  `DISABLE_PROMPT_CACHING` for the CLI); `LLM_NO_PROMPT_CACHE=0` turns it back on.
- **Logging.** With `LLM_LOG=FILE`, `llm.py` writes one JSON line per Sonnet call: input, system and output size,
  cost, and the token usage of fresh calls (`out/*/calls.jsonl`, `out/e2e-vague8/*-calls.jsonl`).

## 2. How to run it, and how to grade it

**Run one task** (needs codemem installed and an index of the repo copy under `CODEMEM_HOME`; Wilson's runs used
`arc_embedder.py` on an Intel Arc GPU, see `README.md`):

```
CODEMEM_HOME=~/.codemem-e2e python e2e_loopk.py TASKS.jsonl TASK_ID REPO_COPY OUT_DIR
```

`TASKS.jsonl` is a task file whose `query` is the prompt to use (for vague prompts, `out/e2e-b7/tasks-L1.jsonl`
and the like: the task of `eval/tasks/e2e/<repo>.jsonl` with `query` replaced by the vague prompt and the issue kept
in `query_L0`). `REPO_COPY` is a checkout of the task's base commit. It writes `OUT_DIR/loopk.diff` and
`OUT_DIR/loopk.summary.json` (rounds, the k of each round, cost, seconds, the full history).

**Run many** with [`run_vague8.py`](run_vague8.py): `python run_vague8.py L1|L2 ARMS TASK_IDS`, with
`VAGUE_SET=e2e-b7` for the b7 tasks. It makes a fresh copy of the repo per task from `~/.cmeval/repos/<repo>.git`
into `~/e2e-copies/<repo>`. Only one process at a time may use `~/e2e-copies` (section 6). Score with
`score_vague8.py` (same `VAGUE_SET`).

**Grade the saved diffs** with Track A's grader (`cmeval e2e grade`, PR #56). Every arm's diff is saved as
`out/<set>/<level>/<task id>/<arm>.diff`, which is the `--patch DIR` layout:

```
cmeval e2e grade pandas     --tasks tasks/e2e/pandas.jsonl     --patch <this folder>/out/e2e-b7/L2
cmeval e2e grade playwright --tasks tasks/e2e/playwright.jsonl --patch <this folder>/out/e2e-b7/L2
```

(and the same for `L1`, and for `out/e2e-vague8/L1` and `L2`). The chosen loop's diffs are `loopk_nc.diff`; grep's
are `grep.diff`. A run that changed nothing has an empty diff, which the grader refuses; count it as not completed.

## 3. Why this design: what each step changed

All numbers are from runs on this laptop, one run each. Section numbers of `loop_vs_grep.md` give the earlier
detail.

1. **More results per round showed more gold code but did not fix more** (21 tasks, `loop_vs_grep.md`). Loop-50
   saw 92% of gold functions against grep's 67%, but edited fewer. The loop's no-change runs had all seen every
   gold function; then the fix call said "could not fix", and results are never shown twice.
2. **Raw code instead of 500-character previews did not help either** (3 pandas tasks, n = 5 / 10 / 25). All 6 gold
   functions were seen at n = 10 and 25, at most 3 of 6 edited against grep's 4, at about twice the cost. The
   bottleneck is the decision to edit, not the search.
3. **Why grep was cheap.** On the 8 L2 tasks grep sent 539k input tokens, 7 times the loop's, but 89% of them were
   cache reads (about $0.10 per million tokens): each turn re-sends the conversation, and the cache serves it.
   Grep read only 85k characters of code. Loop-10 read 274k characters as whole chunks (two thirds of them test
   files on one task), and paid the cache-write premium on almost all of its input: $0.58 of its $0.80.
4. **Sonnet picking k halved the cost** (8 tasks). In round 1 the gold function was result 1 or 2 on about half
   the tasks, so reading 10 whole results was mostly waste. Loop-k with one call per round: L1 $0.39, L2 $0.52,
   against loop-10's $0.81 and $0.80, with the same edits (8 / 8 and 7 / 8 of 15).
5. **Merging judge and fix saves about a fifth.** At a fixed n = 10 (`merged10`, L2, 8 tasks): $0.64 against
   loop-10's $0.80, same edits, rounds and time; no edit failed to apply. With Sonnet picking k (6 b7 tasks), the
   split version (judge call, then a fix call) cost about 30% to 75% more, edited as many or fewer gold functions
   and stopped at the 10-round cap in 7 of its 24 runs, against 3 of 24 for merged.
6. **Prompt cache off cuts the price of each call** to $2 per million input tokens against $2.76 effective with
   caching (the shared system prompt was the only part read back). Like for like, the same calls would have cost
   18% less. On the 6 b7 tasks merged loop-k cost $0.74 / $0.77 with caching and $0.50 / $0.60 without.
7. **Things that did not help:** condensing test results to about 500 characters in the judge's view (`full10t`,
   L2: $0.79 against $0.80, one gold edit fewer, slower).

### Per-set results

**8 pilot tasks** (`out/e2e-vague8/`; pandas 68195, 70742, 68090; playwright 41850, 42503, 42919, 43146, 43148;
L1 / L2 of `eval/tasks/vague-pilot18-v2.jsonl`):

| Level | Arm | Cost, 8 tasks (USD) | Mean seconds | Rounds or turns | Gold functions edited (of 15) | Tasks with a gold function edited (of 8) |
|---|---|---|---|---|---|---|
| L1 | grep | 0.36 | 17 | 56 turns | 8 | 7 |
| L1 | loop-10, separate fix | 0.81 | 26 | 11 | 8 | 7 |
| L1 | loop-k merged, cache on | 0.39 | 26 | 13 | 8 | 7 |
| L1 | loop-k merged, cache off | 0.44 | 34 | 16 | 8 | 7 |
| L2 | grep | 0.46 | 22 | 60 turns | 8 | 7 |
| L2 | loop-10, separate fix | 0.80 | 27 | 13 | 8 | 7 |
| L2 | loop-10, tests condensed | 0.79 | 37 | 14 | 7 | 6 |
| L2 | merged, n = 10 | 0.64 | 26 | 13 | 8 | 7 |
| L2 | loop-k merged, cache on | 0.52 | 27 | 16 | 7 | 7 |
| L2 | loop-k merged, cache off | 0.48 | 31 | 18 | 7 | 7 |

The cache-off run on the 8 tasks took 34 rounds against 29 with the cache on, which ate its per-call saving
(section 5). Also on this set: loop-N with n = 5, 25, 50 (`full5`, `full25`, `full50`; $0.61 to $3.03).

**6 b7 tasks** (`out/e2e-b7/`; from `eval/tasks/vague-b7-v3.jsonl`, one per repo and difficulty, picked at random
with seed 20261126: pandas 71129 easy, 69779 medium, 67897 hard; playwright 41988 easy, 43174 medium, 42792 hard):

| Level | Arm | Cost, 6 tasks (USD) | Without playwright 41988 | Mean seconds | Gold functions edited (of 12) | Tasks with a gold function edited (of 6) | Runs stopped at 10 rounds |
|---|---|---|---|---|---|---|---|
| L1 | grep | 0.45 | 0.29 | 26 | 6 | 4 | |
| L1 | loop-k merged, cache on | 0.74 | 0.32 | 32 | 6 | 4 | 1 |
| L1 | **loop-k merged, cache off** | **0.50** | **0.21** | 44 | 6 | 4 | 0 |
| L1 | loop-k split, cache on | 1.01 | 0.63 | 52 | 5 | 3 | 2 |
| L1 | loop-k split, cache off | 0.65 | 0.29 | 50 | 6 | 4 | 1 |
| L2 | grep | 0.58 | 0.32 | 32 | 8 | 5 | |
| L2 | loop-k merged, cache on | 0.77 | 0.48 | 45 | 6 | 4 | 1 |
| L2 | **loop-k merged, cache off** | **0.60** | **0.39** | 47 | 7 | 5 | 1 |
| L2 | loop-k split, cache on | 0.99 | 0.65 | 54 | 6 | 4 | 1 |
| L2 | loop-k split, cache off | 1.05 | 0.76 | 70 | 4 | 3 | 3 |

Arm names in the output folders: `grep`, `loopk` (merged, cache on), `loopk_nc` (merged, cache off: the chosen
loop), `loopks` / `loopks_nc` (split), `full<N>` (loop-N with raw code), `full10t`, `merged10`.

## 4. Where it still fails

- **Playwright 41988** (an accessibility snapshot drops a button's name; gold: a plugin's `exit` in
  `packages/injected/src/ariaSnapshotDistiller.ts`). 7 of 8 loop runs stopped at 10 rounds ($0.21 to $0.42 each).
  The loops found the file and edited `removeRedundantNames`' `enter`, next to the gold code. Grep needed 14 and 18
  turns and edited the gold function only at L2.
- **Pandas 70742.** Every arm, grep included, edits `fast_xs` instead of the gold function (only loop-50 at L2 hit
  it). The task's screen had been reopened; read its results with care.
- **Gold functions in a second file** (playwright 42919's trace-viewer UI, 3 of playwright 43148's 5) are not
  edited by any arm.

## 5. Run-to-run noise, and why small k amplifies it

Every Sonnet call is sampled again, so two runs of the same arm write different queries and pick different k. With
k of 2 or 3, a small difference decides whether the right function is inside the top k or just outside it, and a
miss costs a round. Three causes seen in the logs when the cache-off run took 5 rounds more:

- **k one smaller.** Playwright 41850 L2: k = 3 put `_sendRequest` at result 3 and fixed in round 1; k = 2 needed
  round 2.
- **A dropped anchor.** Anchors must appear verbatim in the issue or in code already shown. Pandas 70742 L1: one run
  had seen code that mentions `fast_xs`, so `fast_xs` stayed an anchor and was result 1; the other run had not, the
  filter dropped the name Sonnet wrote, and it took a round more.
- **Different wording.** Playwright 43148 L2: anchors `cookies` and `/api` pulled `fetch.ts` into the top 3 instead
  of `pathMatches`.

One run per task cannot separate differences of 10% to 20% from this noise. Repeat runs are needed before a
claim smaller than that.

## 6. Caveats

- One run per arm, task and level. No tests: see the top.
- Costs are what `claude -p` reported (Sonnet 5.5). The rates they imply: plain input $2, cache write $4,
  cache read about $0.10, output $10, per million tokens.
- Index time is not counted: a loop's clock starts after codemem has opened the index and brought it up to date.
  The grep agent needs no index.
- `~/e2e-copies` is shared. Another session rebuilt the playwright copy during one run (L1 41850, cache off);
  the index then lacked `fetch.ts` and the run searched 10 rounds for nothing. That run was set aside and run again
  (edited in round 2, $0.045); the tables use the rerun.

## 7. Next

1. Track A: grade the saved diffs (section 2), so "edited" becomes "completed".
2. Fewer wasted rounds: let a symbol name that Sonnet writes pass the anchor filter when the index has it; fetch a
   named file and function directly; a floor of k = 3 in round 1.
3. Repeat runs (3 per task) of grep and loop-k, on more b7 tasks.
4. Why 41988 loops: the edit lands one method away from the gold code.
