# Results

Final runs that the team reports from. Each folder holds the metrics of one run, not the hit
texts (those stay in `CMEVAL_HOME/runs/<run id>/`, outside git).

| Folder | What it is |
|---|---|
| `2026-10-23-dev50-final/` | First full dev run: 50 SWE-bench Verified tasks, 6 systems. The grep systems ran at `c6b2933`; the 3 codemem systems come from run `2026-10-23-dev50` (codemem `d5c2013`), merged with `cmeval merge`. Dev split: the numbers guide development and are not final results. |
| `2026-10-23-b4b/` | The update vs. rebuild check (Decision 5) at the codemem code of the dev run: PASS. |
| `2026-10-23-repo-stats/` | `cmeval repo-stats --functions` on the 16 candidate repos for fresh tasks (`configs/fresh-candidates.toml`), merges from 2026-07-01 to 2026-10-22. `stats.md` has the tables; `stats.json` has all numbers. Used to choose the repos for F4. |
| `2026-10-24-subset-v2/` | codemem v2 (`configs/codemem-v2.toml` at codemem `31c0f99`, before the v2 weights existed, so every system is unweighted) on 13 dev tasks of four small repos (requests, pytest, seaborn, flask), on an M1. Indicative only; see `docs/decisions.md` §5. |
| `2026-10-24-subset-weights/` | The search-time weightings v2's defaults were chosen from (`configs/codemem-v2-weights.toml`, codemem `18d3b77`), same 13 tasks. |
| `2026-10-24-subset-b4/` | The update vs. rebuild check for codemem v2 on those 13 tasks: PASS (update at `31c0f99`, rebuild at `18d3b77`). |
| `2026-10-25-subset-v3/` | codemem v3 (`configs/codemem-v3.toml` at codemem `96bc2bc`) on the same 13 tasks, on an M1: the v3 default (neutral weights, BM25 queries without stopwords) and five variants. Indicative only; see `docs/decisions.md` §4, which also compares it with v2, the MVP and the grep baselines task by task. |
| `2026-10-25-subset-v3-b4/` | The update vs. rebuild check for codemem v3 on those 13 tasks: PASS, both at codemem `96bc2bc` (13/13 tasks with the same top 10 for all six systems, metric differences 0.0000). |
| `2026-10-25-fresh-dev-grep-b/` | The grep baselines (grep, grep-fn, grep-fn-plus) on the 399 fresh dev tasks (`tasks/fresh-v1.jsonl`), at `3743a30`. The report is made with `--where gold_all_python=true` (364 tasks; the 35 others are in its last section). No codemem systems yet: they join with `cmeval merge` after the codemem changes land. Dev split. |
| `2026-10-26-py100/` | The main Python comparison (F5 B4): grep, grep-fn, grep-fn-plus and `cm3-full` (`configs/main-python.toml`) on the Python sample `tasks/fresh-v1-py100.jsonl` (100 all-Python fresh dev tasks from pandas, transformers, home-assistant and airflow), at `aed438d`, update mode, Mac M5. Primary tests: `cm3-full` vs. grep-fn-plus, Holm over 2. The report is rebuilt byte for byte from these files at `aed438d`. pandas built from the vector cache (warm). |
| `2026-10-26-cpp68/` | The main C++ comparison (F7 B4): grep, grep-fn, grep-fn-plus (`types = ["c", "cpp", "cuda"]`) and `cm3-full` (`configs/main-cpp.toml`) on the C++ sample `tasks/fresh-cpp-v1-68.jsonl` (25 duckdb, 25 Godot, 18 llama.cpp all-C++ fresh dev tasks), at `7c24558`, update mode, Mac M5. Report with `--where gold_all_cpp=true`, rebuilt byte for byte from these files. duckdb and Godot built from the vector cache (warm; their cold builds are in the Decision 5 check). |
| `2026-10-26-ts50/` | The main TypeScript comparison (F7 B4): grep, grep-fn, grep-fn-plus (`types = ["ts"]`) and `cm3-full` (`configs/main-typescript.toml`) on the TypeScript sample `tasks/fresh-ts-v1-50.jsonl` (25 vscode, 25 playwright all-TypeScript fresh dev tasks), at `7c24558`, update mode, Mac M5. Report with `--where gold_all_typescript=true`, rebuilt byte for byte from these files. Both repos built from the vector cache (warm; their cold builds are in the Decision 5 check). |

Files in a run folder:

- `report.md`: the report (`cmeval report`): main tables with 95% bootstrap intervals, paired tests
  against grep-fn-plus (primary: function MRR and tokens to the first right function for the primary systems of the run's codemem version, Holm over all primary tests: 6 for the MVP runs, 2 for cm3-full), group tables, the IoU check, latency, and task counts.
- `summary.csv`: the mean of each metric for each system, level, and IoU.
- `scores.jsonl.gz`: one row for each task, system, level, IoU, and metric (gzip).
- `meta.json`, `score-meta.json`: inputs, code commits, machine, token counter, and the merged parts.
- `index.jsonl`: build and update cost for each task.

To make the report again from these files, unpack `scores.jsonl.gz` next to the other files and run
`cmeval report <folder>`. The tasks file must be the run's (`tasks/swebv-dev50.jsonl` or
`tasks/fresh-v1.jsonl`) with the same sha256 (`--tasks tasks/<file>.jsonl` on another machine).
For the fresh run, add `--where gold_all_python=true`. The primary systems follow the run's codemem
version, so `2026-10-23-dev50-final` (MVP) needs no flags. Runs that were reported with their own
`--baseline` or `--primary` (the subset runs) need the same flags again: their `report.md` names the
baseline in its header and the primary systems in "Primary metrics".
