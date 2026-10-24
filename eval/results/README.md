# Results

Final runs that the team reports from. Each folder holds the metrics of one run, not the hit
texts (those stay in `CMEVAL_HOME/runs/<run id>/`, outside git).

| Folder | What it is |
|---|---|
| `2026-10-23-dev50-final/` | First full dev run: 50 SWE-bench Verified tasks, 6 systems. The grep systems ran at `c6b2933`; the 3 codemem systems come from run `2026-10-23-dev50` (codemem `d5c2013`), merged with `cmeval merge`. Dev split: the numbers guide development and are not final results. |
| `2026-10-23-b4b/` | The update vs. rebuild check (Decision 5) at the codemem code of the dev run: PASS. |
| `2026-10-24-subset-v2/` | codemem v2 (`configs/codemem-v2.toml` at codemem `31c0f99`, before the v2 weights existed, so every system is unweighted) on 13 dev tasks of four small repos (requests, pytest, seaborn, flask), on an M1. Indicative only; see `docs/baseline-v2-diff.md` §5.3. |
| `2026-10-24-subset-weights/` | The search-time weightings v2's defaults were chosen from (`configs/codemem-v2-weights.toml`, codemem `18d3b77`), same 13 tasks. |
| `2026-10-24-subset-b4/` | The update vs. rebuild check for codemem v2 on those 13 tasks: PASS (update at `31c0f99`, rebuild at `18d3b77`). |

Files in a run folder:

- `report.md`: the report (`cmeval report`): main tables with 95% bootstrap intervals, paired tests
  against grep-fn-plus (primary: function MRR and tokens to the first right function, Holm over 6
  tests), group tables, the IoU check, latency, and task counts.
- `summary.csv`: the mean of each metric for each system, level, and IoU.
- `scores.jsonl.gz`: one row for each task, system, level, IoU, and metric (gzip).
- `meta.json`, `score-meta.json`: inputs, code commits, machine, token counter, and the merged parts.
- `index.jsonl`: build and update cost for each task.

To make the report again from these files, unpack `scores.jsonl.gz` next to the other files and run
`cmeval report <folder>`. The tasks file must be `tasks/swebv-dev50.jsonl` with the same sha256
(`--tasks tasks/swebv-dev50.jsonl` on another machine).
