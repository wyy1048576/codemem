# Full-code judge (loop-full): DuckDB and pandas, dev results

**Dev, not a test.** Same loop prompt and settings as `loop` (sha `be4c130c1fdf`, max 5 rounds), but each of the 50
results shows its card header plus the chunk's full source from the index, cut at 4,000 characters
(`aug_retriever.py`, `full_code = true`; cache `out/cache/loopfull-be4c130c1fdf`). The 500-character loop is unchanged.

Runs `duckdb-arc-loopfull`, `pandas-arc-loopfull`. whole, oneshot and loop are identical to the earlier runs on 25/25
tasks per repo. Sonnet: 88 judge calls, $10.30 at list price ($0.12 per call), against $4.71 for the 500-character loop.

## Function level

| Arm | DuckDB MRR | DuckDB tasks with all gold functions in top 10 | DuckDB tasks with no gold function in top 50 | pandas MRR | pandas tasks with all gold functions in top 10 | pandas tasks with no gold function in top 50 |
|---|---:|---:|---:|---:|---:|---:|
| whole | 0.254 | 4 | 9 | 0.335 | 8 | 9 |
| oneshot | 0.298 | 8 | 4 | 0.395 | 9 | 6 |
| diagnose | 0.337 | 10 | 5 | 0.405 | 8 | 5 |
| loop (500 characters) | 0.644 | 15 | 4 | 0.631 | 13 | 4 |
| loop-full | **0.711** | **16** | 4 | **0.764** | **14** | **3** |

loop-full vs loop, function MRR: DuckDB +0.067 (95% CI -0.050 to 0.185, p 0.20, 6 better / 3 worse / 15 same);
pandas +0.132 (CI 0.029 to 0.256, p 0.043, 5 / 0 / 18). vs one-shot: +0.414 (p 0.002) and +0.368 (p 0.003).
Lost vs one-shot and loop: duckdb-24505 at function level (`expression_filter.cpp`, rank 2 in loop, now outside the top 50).

## "found" calls (50 tasks)

| | loop (500 characters) | loop-full |
|---|---:|---:|
| Tasks where Sonnet said found | 43 | 42 |
| ... and a pick was gold | 30 | **37** |
| ... but no pick was gold | 13 | **5** |
| Tasks where Sonnet never said found (ran all 5 rounds) | 7 | 8 |

Of loop's 13 wrong calls:
- The 6 with the gold function among the 50 shown: 4 now right (duckdb-24266, 25153, pandas-69113, 69447);
  duckdb-23939 and pandas-70631 still wrong.
- The 7 without it: 2 now right (pandas-69960, 70107); 3 now keep searching all 5 rounds without finding it
  (duckdb-25101, 25042, 23825); duckdb-24752 and pandas-70742 still wrong.
- New wrong call: pandas-66145.

## Per gold file, by cause (70 gold files)

| Cause | whole | oneshot | diagnose | loop | loop-full |
|---|---:|---:|---:|---:|---:|
| A | 6 | 2 | 2 | 2 | **0** |
| B | 7 | 6 | 5 | 6 | **5** |
| C | 2 | 0 | 0 | 0 | 0 |
| D | 4 | 4 | 4 | 4 | 4 |
| E | 6 | 6 | 6 | 6 | 7 |
| Gold files missed | 25 | 18 | 17 | 18 | **16** |

loop-full vs loop: recovered 3 gold files (A 2, B 1: pandas-71334 `_mixins.py`, rank 14), lost 1 (E: duckdb-24505
`expression_filter.cpp`). duckdb-25101 is still missed: Sonnet no longer stops on the delim join, but 5 rounds of
its own queries never reach `physical_top_n.cpp`.
