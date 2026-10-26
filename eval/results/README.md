# Results

Final runs that the team reports from. Each folder holds the metrics of one run, not the hit
texts (those stay in `CMEVAL_HOME/runs/<run id>/`, outside git).

| Folder | What it is |
|---|---|
| `2026-10-23-dev50-final/` | First full dev run: 50 SWE-bench Verified tasks, 6 systems. The grep systems ran at `c6b2933`; the 3 codemem systems come from run `2026-10-23-dev50` (codemem `d5c2013`), merged with `cmeval merge`. Dev split: the numbers guide development and are not final results. |
| `2026-10-23-b4b/` | The update vs. rebuild check (Decision 5) at the codemem code of the dev run: PASS. |
| `2026-10-25-fresh-dev-grep-b/` | The grep baselines (grep, grep-fn, grep-fn-plus) on the 399 fresh dev tasks (`tasks/fresh-v1.jsonl`), at `3743a30`. The report is made with `--where gold_all_python=true` (364 tasks; the 35 others are in its last section). No codemem systems yet: they join with `cmeval merge` after the codemem changes land. Dev split. |
| `2026-10-23-repo-stats/` | `cmeval repo-stats --functions` on the 16 candidate repos for fresh tasks (`configs/fresh-candidates.toml`), merges from 2026-07-01 to 2026-10-22. `stats.md` has the tables; `stats.json` has all numbers. Used to choose the repos for F4. |

Files in a run folder:

- `report.md`: the report (`cmeval report`): main tables with 95% bootstrap intervals, paired tests
  against grep-fn-plus (primary: function MRR and tokens to the first right function, Holm over 6
  tests), group tables, the IoU check, latency, and task counts.
- `summary.csv`: the mean of each metric for each system, level, and IoU.
- `scores.jsonl.gz`: one row for each task, system, level, IoU, and metric (gzip).
- `meta.json`, `score-meta.json`: inputs, code commits, machine, token counter, and the merged parts.
- `index.jsonl`: build and update cost for each task.

To make the report again from these files, unpack `scores.jsonl.gz` next to the other files and run
`cmeval report <folder>`. The tasks file must be the run's (`tasks/swebv-dev50.jsonl` or
`tasks/fresh-v1.jsonl`) with the same sha256 (`--tasks tasks/<file>.jsonl` on another machine).
For the fresh run, add `--where gold_all_python=true`.
