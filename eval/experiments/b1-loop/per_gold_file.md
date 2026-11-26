# Per gold file: DuckDB and pandas, whole issue vs Sonnet arms

Counts come from `per_gold_file.py` (data in `per_gold_file.json`); links come from `build_links.py --gold-files` (`../out-arms`).
Definitions. A search result is a chunk: one function, method, class body or top-level block, with a path and line range.
A gold file is a file the fix edits. A gold function is a function the fix changes; a chunk "is" a gold function when it is
in the same file and their line ranges overlap with IoU ≥ 0.5. The first three "≥1 chunk in top 50" columns add up to the
gold files with at least one chunk in the top 50. "Near" means a top-50 file imports it or is
imported by it (C++: or its header/source partner). The chance rate is how often a different task's top 50 passes
the same "near" test. Causes are one reader's judgment from the issue, the fix and the top hits.

## Counts

| Repo / arm | Gold files | ≥1 chunk of the gold file in top 10 | ≥1 chunk in top 50, and a top-50 chunk is a gold function | ≥1 chunk in top 50, but no top-50 chunk is a gold function | ≥1 chunk in top 50, file has no gold function | No chunk in top 50, file 1 import away from a top-50 file | No chunk in top 50, file farther | "1 import away" by chance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DuckDB whole issue | 36 | 19 | 16 | 4 | 4 | 6 | 6 | 16% |
| DuckDB one-shot | 36 | 24 | 21 | 3 | 3 | 5 | 4 | 15% |
| DuckDB revised | 36 | 24 | 20 | 3 | 3 | 6 | 4 | 13% |
| pandas whole issue | 34 | 17 | 18 | 3 | 0 | 10 | 3 | 67% |
| pandas one-shot | 34 | 23 | 21 | 3 | 1 | 9 | 0 | 71% |
| pandas revised | 34 | 22 | 21 | 2 | 1 | 9 | 1 | 66% |

No gold file was outside codemem's index.

## Causes

- A. The issue points at the code (names the file, function, feature or operation), but ranking loses it
- B. The root cause is far from the reported symptom
- C. The fix adds a link that does not exist yet
- D. The issue has no locating information
- E. A supporting edit of a multi-file fix whose other files were found

| Cause | Whole issue (DuckDB + pandas) | One-shot | Revised |
|---|---:|---:|---:|
| A | 6 (1 + 5) | 2 (0 + 2) | 2 (0 + 2) |
| B | 7 (2 + 5) | 6 (2 + 4) | 6 (2 + 4) |
| C | 2 (2 + 0) | 0 | 1 (1 + 0) |
| D | 4 (1 + 3) | 4 (1 + 3) | 4 (1 + 3) |
| E | 6 (6 + 0) | 6 (6 + 0) | 7 (6 + 1) |
| Total | 25 (12 + 13) | 18 (9 + 9) | 20 (10 + 10) |

One-shot recovered 8 of the 25 (4 A, 1 B, 2 C, 1 E) and lost 1 that whole issue had found (E).
Revised recovered 7 (4 A, 1 B, 1 C, 1 E) and lost 2 (both E).

| Task | Gold file | Whole | One-shot | Revised | Cause | What happened |
|---|---|---|---|---|---|---|
| duckdb-23876 | `function/scalar/string/contains.cpp` | far | rank 5 | rank 4 | A | Issue names `contains`. Whole search returns row-group pruning code |
| duckdb-24163 | `planner/binder/statement/bind_create.cpp` | far | rank 9 | rank 6 | C | The fix adds a new check in the trigger binder. Sonnet guessed the file |
| duckdb-24382 | `parser/parsed_data/create_type_info.cpp` | far | rank 30 | near | C | The fix makes `CreateTypeInfo::ToString` call `SQLString` for the first time. Sonnet named the function; one-shot had it at 30, revision lost it |
| duckdb-24505 | `parquet/include/reader/expression_column_reader.hpp` | near | near | near | E | Main file `parquet_reader.cpp` found at rank 1; this is a header change |
| duckdb-24505 | `parquet/reader/expression_column_reader.cpp` | near | near | near | E | Constructor plumbing for the same feature |
| duckdb-24505 | `include/duckdb/planner/filter/expression_filter.hpp` | near | near | near | E | Header change for the same feature |
| duckdb-24505 | `planner/filter/expression_filter.cpp` | near | rank 9 | rank 5 | E | Holds the new stats helper `TryGetFilterStats` |
| duckdb-24752 | `include/duckdb/common/multi_file/multi_file_function.hpp` | far | far | far | B | Reported as a zonemap stats error on a hash join. Fix is hive partition columns in multi-file stats |
| duckdb-25042 | `execution/operator/join/physical_iejoin.cpp` | far | far | far | D | Issue is only a SIGILL in a test run |
| duckdb-25055 | `include/duckdb_v2.h` | rank 9 | far | far | E | Header with no function; Sonnet focused the query on `extension_load.cpp` |
| duckdb-25101 | `execution/operator/order/physical_top_n.cpp` | far | far | far | B | Reported as a delim/mark join crash. Fix is `LIMIT 0` in `TopNHeap` |
| duckdb-25153 | `function/table/system/pragma_table_sample.cpp` | near | near | near | E | Issue names `pragma_table_info` (found); the fix repeats the one-line fix in sibling functions |
| duckdb-25153 | `planner/binder/statement/bind_create.cpp` | near | near | near | E | Same fix pattern applied in the binder |
| pandas-66270 | `core/base.py` | near | rank 6 | rank 2 | B | Reported in `resample`. Fix is in the shared `SelectionMixin.__getitem__` |
| pandas-68081 | `api/__init__.py` | far | rank 2 | rank 2 | A | The issue gives the path. Whole search misses the small `__init__` file |
| pandas-69447 | `core/indexes/period.py` | rank 18 | rank 20 | near | E | One-line change to `PeriodIndex.values`; 3 other gold files |
| pandas-69478 | `core/arraylike.py` | near | rank 3 | rank 2 | A | Issue is about `np.logical_or` on DataFrames, handled by `array_ufunc` |
| pandas-69960 | `plotting/_matplotlib/timeseries.py` | far | rank 21 | rank 20 | A | "timeseries" and `.plot()` point at the file. Whole search returns `tz_localize` code |
| pandas-70107 | `core/computation/expr.py` | near | near | near | A | Title names `.query()`. Search and Sonnet went to `isin` in datetimelike arrays |
| pandas-70107 | `core/computation/ops.py` | near | near | near | A | Same task. Sonnet guessed `ops.py` but it still ranked below 50 |
| pandas-70221 | `io/formats/format.py` | near | near | near | D | A mypy-config discussion. The fix touches type annotations in arbitrary files |
| pandas-70221 | `io/parsers/readers.py` | near | near | near | D | Same |
| pandas-71334 | `core/arrays/_mixins.py` | near | near | near | B | Reported as `joblib.hash` changing after save/load. Fix adds new methods to extension arrays |
| pandas-71334 | `core/arrays/base.py` | near | near | near | B | Same |
| pandas-71334 | `core/arrays/interval.py` | near | near | near | B | Same |
| pandas-71334 | `core/dtypes/base.py` | near | near | far | B | Same |
| pandas-71442 | `io/parsers/readers.py` | far | near | near | D | Issue is "nightly wheel builds are failing" and a link. Fix is in the CSV reader |
