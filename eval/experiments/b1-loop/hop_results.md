# One-hop call-graph expansion: DuckDB + pandas (50 tasks, 80 gold functions)

`hop_retriever.py` / `hop.toml` / `run_hop.py`, runs `duckdb-arc-hop`, `pandas-arc-hop`, scored by `hop_score.py`
(`hop_score.json`). No Sonnet calls. Each arm's saved top 50 (from the `arc-loopfull` runs) is expanded with
codemem call-graph neighbours (callers + callees, `edges` table) at the task's commit, ranked by cosine between
the neighbour's code vector and the whole issue's query vector. Budget: ranks 1-5 take 15 each, 6-20 take 10,
21-50 take 5 (375 picks max). Neighbours already in the top 50 are skipped; repeats count once.

| Arm | Gold functions not in top 50 | ... a caller/callee of a top-50 result (no budget) | ... added by the budget | Distinct functions added per task (median) |
|---|---:|---:|---:|---:|
| whole | 36 | 9 | 8 | 142 |
| oneshot | 27 | 7 | 7 | 124 |
| loop | 22 | 2 | 2 | 123 |
| loop-full | 21 | 1 | 1 | 125 |

Gold files one import away (the earlier "one hop" test, per_gold_file_loopfull.json):

| Arm | Gold files one import away | ... a call neighbour lies in the file (no budget) | ... an added function lies in the file | ... an added function is gold |
|---|---:|---:|---:|---:|
| whole | 16 | 8 | 7 | 0 of 10 |
| oneshot | 14 | 8 | 6 | 1 of 10 |
| loop | 12 | 7 | 2 | 0 of 7 |
| loop-full | 12 | 5 | 3 | 0 of 9 |

oneshot: 6 of the 7 added gold functions are in files already in the top 50; only pandas-71442 `_read_csv_chunks`
is a new file. 2 of the 7 have cosine below 0.4 (0.33, 0.28), so a 0.4 cut would keep 5.
