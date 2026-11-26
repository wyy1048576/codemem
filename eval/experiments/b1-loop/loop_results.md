# Search loop (codemem in place of grep): DuckDB and pandas, dev results

**Dev, not a test.** The loop (`system_loop.txt`, sha `be4c130c1fdf`, see `frozen_loop.json`) was designed after seeing
these repos' results. A frozen run on an unseen repo is the real check.

How it works (`aug_retriever.py`, mode `loop`, max 5 rounds):
1. Round 1 is the one-shot top 50 (identical to the one-shot arm).
2. Sonnet sees the issue, its earlier queries and notes, and the 50 results (500 characters per card). It returns
   found (yes/no), picks (result numbers it thinks must change), notes on where to look, and the next query:
   intent, symptom, anchors (verbatim from the issue or results seen), and up to 3 folders/files to look in.
3. Next round: dense lists on the new intent + symptom, BM25 on the anchors, and the same lists limited to each
   look-in path. Only results not shown before are shown (top 50 of a 100-per-list pool).
4. Stops when Sonnet says found, or after round 5. Final list: picks first, then RRF over every round's ranking.
   The answer key is never used during the run.

Runs `duckdb-arc-loop`, `pandas-arc-loop` (all five arms on one index). whole, oneshot, revise and diagnose are
identical to the earlier runs on 25/25 tasks per repo. Sonnet: 87 loop calls, $4.71 at list price.

## Function level

| Arm | DuckDB MRR | DuckDB all gold in top 10 | DuckDB none in top 50 | pandas MRR | pandas all gold in top 10 | pandas none in top 50 |
|---|---:|---:|---:|---:|---:|---:|
| whole | 0.254 | 4 | 9 | 0.335 | 8 | 9 |
| oneshot | 0.298 | 8 | 4 | 0.395 | 9 | 6 |
| revise | 0.377 | 12 | 5 | 0.395 | 8 | 5 |
| diagnose | 0.337 | 10 | 5 | 0.405 | 8 | 5 |
| loop | **0.644** | **15** | 4 | **0.631** | **13** | 4 |

Loop vs one-shot, function MRR: DuckDB +0.347 (95% CI 0.175 to 0.521, p 0.004, 12 better / 1 worse / 11 same);
pandas +0.236 (CI 0.090 to 0.399, p 0.013, 9 / 1 / 13). Loop vs whole: Holm p 0.012 (DuckDB), 0.030 (pandas).
No task found by one-shot is lost.

## Per gold file, by cause (70 gold files)

| Cause | whole | oneshot | revise | diagnose | loop |
|---|---:|---:|---:|---:|---:|
| A | 6 | 2 | 2 | 2 | 2 |
| B | 7 | 6 | 6 | 5 | 6 |
| C | 2 | 0 | 1 | 0 | 0 |
| D | 4 | 4 | 4 | 4 | 4 |
| E | 6 | 6 | 7 | 6 | 6 |
| Total missed | 25 | 18 | 20 | 17 | 18 |

Loop vs one-shot: recovered 0 gold files, lost 0. The gain is ranking: found files move to the top
(`contains.cpp` 5 to 1, `create_type_info.cpp` 30 to 1, `timeseries.py` 21 to 1, `core/base.py` 6 to 1).

## How the loop behaved (50 tasks)

- Rounds used: 1 round on 35 tasks, 2 on 7, 3 on 1, all 5 on 7.
- Sonnet said found on 43 tasks: right on 30, wrong on 13 (it stopped early with wrong picks).
  duckdb-25101 (the cause B case) stopped in round 1 with 4 wrong picks.
- Later rounds surfaced a gold file on 4 tasks (pandas-66270, 68947, 69960 in round 2; duckdb-24693 in round 3).
- Of the 7 tasks that used all 5 rounds, 3 DuckDB tasks had a right pick (24693 from round 3, the others from
  round 1). The 4 pandas tasks (70102, 70221, 71334, 71442) ended without a gold pick.
- Sonnet only sees each result's signature and first lines, not the body; its notes say so on some tasks.
