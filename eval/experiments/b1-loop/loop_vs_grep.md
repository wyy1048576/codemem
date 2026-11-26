# Loop vs grep: where Track B stands (2026-11-26)

**Current focus of Track B: codemem's search loop against a grep agent, end to end.** This note collects the
algorithms, the results so far, the case study of duckdb-25101 and the evidence that grep is helped by what the
model remembers about the repos. Nothing here builds the repo or runs tests: "edited" means the final diff touches
a gold function, not that the task is fixed.

Tables show only the **one-shot** search and **our loop** (plus grep), by decision of 2026-11-26. The other
retrieval arms (whole-issue, revise, diagnose, one-hop) are in their own notes (`*_results.md`) and are dropped
from here on.

## 1. The algorithms

**One-shot** (`aug_retriever.py`, `mode="oneshot"`). One Sonnet 5.5 call reads the issue and writes an
`intent`, a `symptom` and up to 12 `anchors` (words that must occur verbatim in the issue). codemem fuses, by RRF
(k = 60), dense search on intent + symptom (code and usage vectors, jina-code-embeddings-0.5b), BM25 on the
anchors and BM25 / dense on the whole issue. The top 50 is the result.

**Our loop** (`aug_retriever.py`, `mode="loop"`; end to end in `e2e_loop.py`).
- Round 1 *is* the one-shot search: the same Sonnet call and the same top N (checked in the code:
  `aug_retriever.py:203-204`, `e2e_loop.py:93-94`). So the loop never starts below one-shot.
- Each round Sonnet sees the issue, its earlier queries and notes, and up to N results it has not seen before.
  It says whether the code that must change is among them (`found`), picks results, and writes the next query:
  intent, symptom, anchors (verbatim from the issue or a result already shown) and up to 3 `look_in` paths.
- Rounds 2+ (`_round_fused`): dense intent + symptom on code and usage (pool 100), all anchors joined into one
  BM25 query, and BM25 / dense lists restricted to each `look_in` path, fused by RRF. Results already shown are
  never shown again.
- Results are 500-character previews (`loop`) or the chunk's full source cut at 4,000 characters (`loop-full`,
  retrieval only). The end-to-end loop uses previews.
- End to end, when Sonnet says found, a fix call (`system_fix.txt`) gets the full code of the picks (up to 8
  chunks, 60,000 characters) and returns exact edits. Edits apply only if each `old` text occurs once in its
  file. If it cannot fix, its explanation and next query go into the next round. Cap: 10 rounds or $3.
- `LOOP_N` (env, default 50) sets N; outputs go to `<LOOP_TAG>.summary.json` / `.diff` (added for the n sweep).

**Grep agent** (`e2e_run.py ... grep`). Headless Claude Code (`claude -p`, Sonnet 5.5, medium effort) with Read,
Edit, Write, Grep, Glob; no shell, no build; budget $5. A fresh copy of the repo at the base commit, git history
removed (`e2e_all.py`). Two more arms exist for one task only (25101): `codemem` (Read, Edit, Write + codemem's
`search_code`, `get_chunk`) and `codemem+grep` (both tool sets).

**One-hop expansion** (`hop_retriever.py`, dropped). Add callers and callees from codemem's call graph to each
result of a saved top 50, ranked by cosine to the issue, 15 per result at ranks 1-5, 10 at 6-20, 5 at 21-50.
Result: of the 20 one-shot misses not one call away, it recovers none; of the 7 that are one call away it adds all 7,
but 6 of them sit in files the top 50 already has, and it adds about 125 functions (3,300 lines) per task.
The loop recovers more for less (`hop_results.md`). **Decision: use the loop, not the one-hop rule.**

## 2. Retrieval only: the loop against one-shot (50 tasks)

From `loopfull_results.md` (25 DuckDB + 25 pandas tasks, gold functions at IoU 0.5, max 5 rounds):

| Arm | DuckDB function MRR | DuckDB tasks with every gold function in the top 10 | pandas function MRR | pandas tasks with every gold function in the top 10 |
|---|---:|---:|---:|---:|
| one-shot | 0.298 | 8 | 0.395 | 9 |
| loop (full code, `loop-full`) | **0.711** | **16** | **0.764** | **14** |

loop-full vs one-shot, function MRR: +0.414 (p 0.002) on DuckDB, +0.368 (p 0.003) on pandas. In 42 of 50
tasks Sonnet said found; in 37 of those a pick was gold.

## 3. End to end: the loop with a fix against grep (21 tasks)

`e2e_all.py`, `e2e_score.py --common`: the 21 tasks (7 DuckDB, 14 pandas, 36 gold functions) where both arms
finished. One run each, Sonnet 5.5.

| Arm | $ per task | Gold functions seen | Gold functions edited | Recall (seen or edited) | Tasks with a code change |
|---|---:|---:|---:|---:|---:|
| loop with fix, 50 results per round | $0.27 | 33 | 10 | 33/36 (92%) | 14/21 |
| grep agent | $0.08 | 21 | 17 | 24/36 (67%) | 21/21 |

- **Seen:** at least half of a gold function's lines were shown to the model (loop: previews and fix code; grep:
  lines returned by Read, or printed by Grep in content mode). Grep reads short windows, so it can edit a
  function it never "saw"; the edit column is the fairer comparison.
- **Edited:** the final diff changes or inserts at a line inside the gold function's span at the base commit.
- The loop **finds more but fixes less**: on 7 of 21 tasks it hit its cap without applying a fix.
- These 21 are the easier tasks: the one-shot top 50 alone shows 75% of their gold functions (66% over all 50).

## 4. Results per round: n = 10, 25, 50 (21 tasks)

`e2e_topn.py` reruns the loop on the same 21 tasks with `LOOP_N` 10 and 25 (fresh copy of the repo per run, one
run each); n = 50 is the run of section 3. `e2e_topn_score.py` scores the four arms (`e2e_topn_score.json`).
20 of the 21 tasks have scored gold functions (pandas-68081 has none).

| Arm | $ per task | Recall (gold functions seen or edited) | Tasks whose diff edits ≥1 gold function | … every gold function | … every gold file | Tasks with no change | Median rounds |
|---|---:|---:|---:|---:|---:|---:|---:|
| loop, n=10 | $0.20 | 30/36 (83%) | 11/20 | 9/20 | 13/21 | 7 | 2 |
| loop, n=25 | $0.24 | 31/36 (86%) | 9/20 | 8/20 | 10/21 | 9 | 1 |
| loop, n=50 | $0.27 | 33/36 (92%) | 10/20 | 9/20 | 12/21 | 7 | 1 |
| grep agent | $0.08 | 24/36 (67%) | 15/20 | 12/20 | 15/21 | 0 | — |

- **n barely matters.** Fewer results per round saves a little ($0.27 → $0.20) and loses a little recall; the
  edit columns move by one or two tasks, within the noise of one run. No n closes the gap to grep on edits.
- **The loop's gap is in deciding and fixing, not in finding.** With n = 50, all 7 tasks with no change ran
  the full 10 rounds, and together they cost $4.24 of the arm's $5.59 (76%). In 5 of them Sonnet said found and
  the fix call answered "could not fix" (23825, 23876, 68575, 68947, 69478); in 2 it never said found
  (23952, 69447). In all 7, every gold function had already been shown to Sonnet. After a "could not fix",
  the results it saw are never shown again, so the next rounds search what is left and find nothing (the same
  pattern as pandas-68090 in the pilot). Grep edited a gold function in 4 of these 7.
- The 3 fair pandas pilot tasks (README, result 1) pointed the other way (n = 10 and 25 much cheaper than 50),
  but there one task carried the whole gap.
- Cost accounting: loop costs are the judge and fix calls; the one-shot query call (about $0.01) is not
  counted, except in the two pandas-70107 n = 10 / 25 runs, which used a newer `e2e_loop.py` (same previews)
  that adds it ($0.0125 each). Grep's cost is Claude Code's `total_cost_usd`.

## 5. Case study: duckdb-25101 (LIMIT 0 in a TopN under a LEFT_DELIM_JOIN)

Outputs: `out/e2e-25101/`. Gold: `TopNHeap::Sink` and two helpers in `src/execution/operator/order/physical_top_n.cpp`.

| Arm | Cost | Turns / rounds | Outcome |
|---|---:|---:|---|
| grep agent | $0.10 | 7 turns | edited `physical_top_n.cpp` |
| codemem agent (search_code, get_chunk) | $0.26 | 15 turns | edited `physical_top_n.cpp` |
| codemem + grep agent | $0.26 | 17 turns | edited `physical_top_n.cpp` (1 codemem search, 6 greps) |
| loop with fix (n=50, previews) | $0.77 | 10 rounds | fixed in round 10, at the cap |
| loop, retrieval only (`loop-full`, 5 rounds) | $0.58 | 5 rounds | never said found |

**Why grep wins here.** Its first search was `limit == 0` (three spellings). Five lines came back, one of them
`physical_top_n.cpp:580`; it read the file and fixed it.

**Why the loop loses.** Sonnet chose the wrong suspect, not codemem's index:
1. *The issue steers it.* The title and plans name LEFT_DELIM_JOIN, MARK and DELIM_SCAN. Round 1's top 50 had 26
   delim-join results and none from `physical_top_n.cpp`. Each round Sonnet read 50 results about delim joins and
   dug deeper (Reset, SupportsReuse, ColumnDataCollection, ResetMarkJoinInfo). TopN came up only as a side note;
   `physical_top_n.cpp` was never a `look_in` path.
2. *Each round packs many guesses into one query.* Round 1's anchors did include `TOP_N`, with 11 other words.
   In that BM25 list the gold file was 26th and the gold function 588th; fused with the other lists it fell out
   of the top 50. Grep tests one guess per search, and each search costs almost nothing.

Rank of the gold code for single queries, top 1,000, one signal each (`why25101.py`; "—" = not in the top 1,000):

| Query | BM25: gold file / gold function | Dense (code): gold file / gold function |
|---|---:|---:|
| the loop's own lists, rounds 1-5 (best) | 26 / 588 | 379 / — |
| `limit == 0` (grep's first search) | 339 / — | 192 / — |
| `TOP_N Top: 0` (from the issue's plan) | **2** / 32 | **3** / 42 |
| `TopNHeap Sink limit 0 empty heap` | **1** / 5 | **1** / 2 |
| `ORDER BY with LIMIT 0 crashes in the top-n operator` | 2 / 62 | **1** / 91 |

- codemem is **weaker on code patterns**: BM25 splits `limit == 0` into "limit" and "0", which are everywhere.
- codemem is **stronger on concepts**: once the guess is "LIMIT 0 in TopN", plain English finds the file at rank 1.

## 6. Does grep win because the model remembers the repos?

Hypothesis (Wilson): grep is cheaper partly because Sonnet has seen these repos in training. `grep_memory.py` reads
the 23 finished grep transcripts in `out/e2e-all/` (output `grep_memory.json`). A file or code name counts as
**not in the issue** when neither its path nor its file name (case-insensitive) appears in the issue text.

| What the grep agent's first call did | Runs |
|---|---:|
| Searched inside the exact gold file, a file not in the issue | 9 |
| Searched inside the gold file, which the issue names (e.g. in a traceback) | 3 |
| Searched with code names in neither the issue nor earlier results, and the results listed the gold file | 3 |
| Searched with words from the issue, and the results listed the gold file | 1 |
| Reached the gold file later (4) or never (2), or by another first move (1) | 7 |

- The 9 named-file runs are the solid evidence, e.g. pandas-66270 (`def __getitem__` inside the gold file) and
  pandas-69113 (`def difference`). Nothing in those issues points to the file.
- The 3 code-name runs are weaker: the test counts `BloomFilter` as new even when the issue says "bloom filter".
- This shows Sonnet **remembers the repos' layout**. It does not show it saw the fixes (mid-2026 or later).
- Cost: the 12 runs that found the gold file on the first call without the issue pointing there averaged $0.063;
  the other 11, $0.088; the loop averages $0.27 on the 21 tasks. So memory saves grep a little, but most of the gap
  is what each method shows Sonnet: a grep call returns a few lines, every loop round 50 results.

## 7. What we conclude so far

- The loop is the best retrieval we have (MRR about 0.7-0.76 against 0.3-0.4 for one-shot), and the one-hop rule
  is not worth its cost.
- End to end, grep edits gold code more often at about a third of the loop's cost. The loop shows the right code
  more often but fixes it less often, and when its first hypothesis is wrong it digs deeper instead of switching.
- Most of the loop's cost is tasks where it already saw the gold code and then could not commit to a fix; how
  many results it shows per round (10, 25 or 50) changes little.
- codemem's index can find the code; the weak parts are the hypothesis and the query shape (one fused,
  multi-guess query per round, no exact-text search).

## 8. Next

0. **The fix step**: on "could not fix", let the fix call ask for more code (callers, the rest of the file) or
   let the next round see earlier results again, instead of searching only what is left; and look at why the
   judge never said found on 23952 and 69447 although the gold code was shown.
1. **Narrow probes per round**: let Sonnet send several one-guess searches per round (say 3 × top 10), run each
   anchor as its own BM25 search instead of one joined query, and give the loop an exact-text search.
2. **The renaming control** (contamination): move and rename the repo's files in the test copy so remembered
   paths fail, then rerun grep on the 23 tasks (about $2 at $0.08 a task) and the loop (about $6).
3. 3 to 5 runs per arm and task, and grading of the saved diffs with the hidden tests (needs track A's grader).

## Files added for this note

| File | What it is |
|---|---|
| `loop_vs_grep.md` | this note |
| `e2e_topn.py`, `e2e_topn_score.py`, `e2e_topn_score.json` | the n = 10 / 25 sweep and its scorer (`out/e2e-all/<task>/loop-n10.*`, `loop-n25.*`) |
| `why25101.py` | ranks of the 25101 gold code for the loop's lists and single queries (needs the 25101 index) |
| `grep_memory.py`, `grep_memory.json` | the grep "memory" test of section 6 |
| `out/e2e-25101/` | the four agent / loop runs on duckdb-25101 |
