# Diagnosis prompt (v2): DuckDB and pandas, dev results

**Dev, not a test.** The v2 prompt (`system_oneshot_v2.txt`, sha `91a33faed09f`, see `frozen_v2.json`) was written after
reading these repos' fixes. A frozen run on an unseen repo is the real check.

Arms, on the same index and search settings as before (runs `duckdb-arc-diag`, `pandas-arc-diag`):
- whole: whole issue only. Identical to the earlier runs on 25/25 tasks per repo.
- oneshot: v1 one-shot (cached answers). Identical to the earlier runs on 25/25 tasks per repo.
- diagnose-base: v2's own intent, symptom and anchors in the same six lists as one-shot. No suspect lists.
- diagnose: diagnose-base plus "diagnosis + suspects" (code, usage) and BM25 on suspects, each at weight 0.5.
  The diagnosis was "none" on 2 pandas tasks, which then get no suspect lists.

Sonnet: 50 new v2 calls, $0.71 at list price.

## Function level

| Arm | DuckDB MRR | DuckDB all gold in top 10 | DuckDB none in top 50 | pandas MRR | pandas all gold in top 10 | pandas none in top 50 |
|---|---:|---:|---:|---:|---:|---:|
| whole | 0.254 | 4 | 9 | 0.335 | 8 | 9 |
| oneshot | 0.298 | 8 | 4 | 0.395 | 9 | 6 |
| diagnose-base | 0.315 | 9 | 6 | 0.369 | 9 | 5 |
| diagnose | 0.337 | 10 | 5 | 0.405 | 8 | 5 |

Diagnose vs one-shot, function MRR: DuckDB +0.039 (95% CI 0.002 to 0.092, Holm p 0.22, 10 better / 3 worse / 11 same);
pandas +0.010 (CI -0.093 to 0.117, 4 / 5 / 14). Pandas recall@10 fell from 0.511 to 0.424; recall@50 rose from 0.707 to 0.772.
At function level, diagnose lost one task one-shot found (duckdb-23952).

## Per gold file, by cause (70 gold files)

| Cause | whole | oneshot | revise | diagnose-base | diagnose |
|---|---:|---:|---:|---:|---:|
| A | 6 | 2 | 2 | 2 | 2 |
| B | 7 | 6 | 6 | 5 | 5 |
| C | 2 | 0 | 1 | 1 | 0 |
| D | 4 | 4 | 4 | 4 | 4 |
| E | 6 | 6 | 7 | 6 | 6 |
| Total missed | 25 | 18 | 20 | 18 | 17 |

Diagnose vs one-shot: recovered 1 gold file (B: pandas-71334 `core/arrays/_mixins.py`, rank 18), lost none.

The cause B checks:
- duckdb-25101 `physical_top_n.cpp`: still outside the top 50 in every arm. v2 put LIMIT 0 in the diagnosis and
  `PhysicalTopN` among 5 suspects, but its diagnosis still blames the delim join.
- duckdb-24752 `multi_file_function.hpp`: still missed.
- pandas-71334: 1 of 4 files recovered (`_mixins.py`); `arrays/base.py`, `interval.py`, `dtypes/base.py` still missed.
- pandas-66270 `core/base.py`: already found by one-shot (rank 6); diagnose rank 3.

Ranks moved on files that were already found: `timeseries.py` 21 to 6, `contains.cpp` 5 to 6, `create_type_info.cpp` 30 to 19.
