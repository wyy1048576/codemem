# Track B, item 1 results (late): Claude Code with codemem 463171c over MCP against grep only, Haiku, 14 tasks at L1 and L2; and a third arm, a fuller tool description with no hooks. codemem ties grep on functions edited and costs more in most pairs

- **Track:** B. Item 1 of the entries of 12:40 and 12:55 UTC, with the checks of 13:15
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-28 00:40 UTC
- **Work package:** B1, B8
- **Branch, commits, pull request:** codemem `463171c` (arm `tool`); `wilson/mcp-detailed-wording` at `9b880bb`, off `463171c` (arm `detailed`; prompts only, pushed, no pull request). Harness, scores and every stream: `log/2026-11-28-0040-b-data/` (`run_item1.py`, `score_item1.py`, `score-haiku.json`, `item1-haiku-records.zip`)

## Done

**Late:** results were due 22:00 UTC, at the latest 23:00. Started 23:16 UTC (entry of 23:20).

**Changes from the plan of 12:55, by Wilson's decision:**
- **Haiku only.** Sonnet was dropped after its grep runs (28, kept in the records, not reported). So item 1's Sonnet half is not done.
- **A third arm, `detailed`.** No hook anywhere: not after the agent chose grep, not after each turn. The MCP tool and the server instructions alone say, in detail, when to call `search_code` instead of Grep (first, when the task describes behaviour and the file is not known; when the names to grep are guesses; before a second variant of a grep; for code spread over several files) and when to grep instead (an exact name, path or string from the task or from code already read), what a search costs, and how to use one. The aim is to get the search where it saves turns without the extra turns a hook costs.

**Setup.** Claude Code 2.1.314, `-p`, `claude-haiku-5-5`, stream-json, `--setting-sources ""`, `--strict-mcp-config`, `--permission-mode acceptEdits`, `--max-budget-usd 5`. Built-in tools in every arm: Read, Edit, Write, Grep, Glob; **no shell**. Same prompt in every arm (fix the issue; nothing can be built or run). Prompt cache on (one conversation). Tasks: the 14 vague-prompt tasks of PR #45 (6 pandas, 8 playwright), L1 and L2. One run per cell, 84 runs.

| Arm | What the agent has besides the built-in tools |
|---|---|
| `grep` | nothing |
| `tool` | codemem `463171c` over MCP, all its tools, wording `light`, registered with `alwaysLoad` as `codemem init` does |
| `detailed` | the same server with steering `detailed` (`wilson/mcp-detailed-wording`) |

**Totals, Haiku, 14 tasks per level.** Cost in USD as Claude Code reports it. Seconds without the first search's wait for the model (below). Tokens of the answering model: new input, written to the cache, read from the cache, output. Gold functions edited: the final diff touches a line inside a function the real fix changed (27 per level). Tasks with a gold function edited: of 14.

| Level | Arm | Cost | Seconds | Turns | New input | Cache write | Cache read | Output | `search_code` calls | `get_chunk` calls | Gold functions edited | Tasks with a gold function edited |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| L1 | grep | 0.207 | 895 | 174 | 276 | 368,251 | 3,546,710 | 155,102 | 0 | 0 | 17 | 12 |
| L1 | tool | 0.131 | 699 | 168 | 252 | 291,250 | 2,340,933 | 98,112 | 12 | 0 | 17 | 12 |
| L1 | detailed | 0.137 | 750 | 181 | 282 | 294,203 | 2,631,599 | 104,113 | 4 | 4 | 18 | 12 |
| L2 | grep | 0.139 | 627 | 174 | 272 | 307,431 | 2,528,845 | 104,251 | 0 | 0 | 16 | 11 |
| L2 | tool | 0.182 | 813 | 206 | 296 | 385,747 | 3,968,580 | 130,764 | 12 | 0 | 15 | 11 |
| L2 | detailed | 0.153 | 699 | 210 | 326 | 332,062 | 3,570,271 | 101,242 | 9 | 5 | 16 | 13 |

**Pairs by task and level** (28 per comparison): the first arm lower / equal / higher than the second.

| Measure | tool vs grep | detailed vs grep | detailed vs tool |
|---|---|---|---|
| Cost | 11 / 0 / 17 | 10 / 0 / 18 | 13 / 0 / 15 |
| Turns | 10 / 6 / 12 | 7 / 6 / 15 | 9 / 3 / 16 |
| Seconds | 10 / 1 / 17 | 9 / 0 / 19 | 10 / 3 / 15 |
| Cache read | 14 / 0 / 14 | 7 / 0 / 21 | 13 / 0 / 15 |
| Gold functions edited | 3 / 23 / 2 | 2 / 23 / 3 | 2 / 22 / 4 |

**What it says, with one run per cell:**
- **Neither codemem arm edits more of the fix than grep:** 32 and 34 gold functions against grep's 33 (of 54); 23, 25 and 23 tasks of 28. Every difference is one or two task-levels, inside what two runs of one arm differ by (your 3 of 16).
- **Both cost more than grep in most pairs** (17 and 18 of 28), though `tool` is cheaper in total at L1. These are Haiku sessions of a few cents; the whole 84 runs cost $0.95.
- **The fuller description made Haiku search less, not more:** `search_code` in 12 of 28 runs against 20 of 28 for `tool`. It does what it says: on tasks whose prompt carries an exact string Haiku greps at once (pandas 68195 L2: one grep for the quoted error text, fixed in 10 turns). It did not save turns: more turns than `tool` in 16 of 28 pairs.
- **When Haiku searched, the first result was often right:** `tool` had a gold file in the results in 13 of its 20 searching runs (at place 1 in 7), a gold function in 11. `detailed`: 5 of 12, 5. Next step after a search: Grep in 16 of 24 (`tool`), 7 of 13 (`detailed`), so the agent still greps after a good search.

**The checks of 13:15, with counts.**

1. **Code, by meaning:** 37 searches in 32 of the 56 codemem runs. Every answer listed functions with `path:line`, signature and code, except 1: "No results" in `detailed` L2 playwright 41988, for a `path_prefix` the agent guessed and that does not exist at that commit; its next search, without it, returned code. **No loading note in any result (0 of 37), so no run was dropped.** `codemem status` was saved before each run: ready, the embedding model, chunk count above 0. It names the copy's own commit "base" (each copy is one commit, see 2), not the upstream hash.
2. **The index is the code the agent sees:** each run has its own copy of the repo at the task's base commit (git archive, one commit, no history) and its own index folder. The index is codemem `463171c`'s, built for the repo once (pandas at 71129's commit, 37,489 chunks, 28 min; playwright at 43174's, 1,601 files, 24 min), brought to the task's commit once per task, then copied per run and updated from the run's own copy before the agent starts (exit 0 in 56 of 56).
3. **The arms differ in codemem only:** same model id, Claude Code version, flags, tools, prompt (checked in each stream's init event). No shell in any arm; track A's setups have one.
4. **Cache on:** every run read from the cache. Tokens by kind above.
5. **The answering model:** only `claude-haiku-5-5` in every run's usage; no side calls to another model.
6. **Found, files and functions apart:** above (file in results, function in results, function edited, tasks with a gold file edited are in `score-haiku.json`).
7. **What the agent did with codemem:** above; per run in `score-haiku.json` (calls, turn of the first search, next step).
8. **Two runs per cell: not done.** One run per cell, so no measure of run-to-run noise here; the pairs are given.
9. **Every stream kept** (`item1-haiku-records.zip`: stream, diff, summary, status, MCP config per run). **No request bodies:** no proxy on this machine.

**Deviations.**
- **The embedder** is our Intel Arc plugin (`arc_embedder:ArcEmbedder`, the same model, jina-code-embeddings-0.5b; documents on the GPU in float16, queries on the CPU in float32): a CPU-only index of pandas does not fit the time.
- **The model was not loaded before the agent's clock.** `catchup_budget_ms = 180000` makes the first search wait for it, so no search fell back to keywords, but the wait (about 72 s) fell inside the run. The seconds above subtract the first search's time beyond 1 s; the raw seconds are in the file (`seconds` and `seconds_warm`). Cost and tokens are not affected.
- The grep runs ran at 23:16 to 23:30 UTC, the codemem runs at 23:45 to 00:32.

## Checked

- `score_item1.py` on all 84 Haiku runs; the check counts are from the streams. The `detailed` runs used the branch (`CODEMEM_STEERING=detailed` and its `src` in all 28 MCP configs).
- Not checked: the diffs with tests; a second run per cell; Sonnet; request bodies.

## Left

- Sonnet, if still wanted. A second run per cell.
- Whether to keep the `detailed` wording: on this evidence it does not pay; it is a branch, not a proposal for the lock.

## Blocked on, or needed from others

- **Andre:** whether item 1 needs the Sonnet half now.
- **Track A:** if wanted, grade the 84 diffs in the zip with `cmeval e2e grade`.

## Next

Wilson, with Claude Code: as Andre says.
