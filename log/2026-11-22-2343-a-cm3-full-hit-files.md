# The cm3-full hit files of the three main runs are on main

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-22 23:43 UTC
- **Work package:** none. A request from track B, for B1
- **Branch, commits, pull request:** pull request #18, merged into `main` as `84b0088`

## Done

Track B asked for the ranked results of `cm3-full` from the October runs. They are now in git:

- `eval/results/2026-10-26-py100/cm3-full.jsonl.gz` (100 tasks)
- `eval/results/2026-10-26-cpp68/cm3-full.jsonl.gz` (68 tasks)
- `eval/results/2026-10-26-ts50/cm3-full.jsonl.gz` (50 tasks)

Each file is the run's hit file as `cmeval run` wrote it, gzipped. One row for each task:
`task_id`, `commit`, `search_ms` and `hits`. A hit has `path`, `start_line`, `end_line`,
`symbol`, `score`, `text` (the card codemem returned) and `extra` (the rank in each of the
three signals, and the kind). `eval/results/README.md` describes the file.

To grade a hit, join on `task_id` with the task file of the run (`eval/tasks/fresh-v1-py100.jsonl`,
`fresh-cpp-v1-68.jsonl`, `fresh-ts-v1-50.jsonl`): its `gold` field has the right files, classes
and functions. The per-task scores are in `scores.jsonl.gz` in the same folder.

## Checked

- Each file unpacks to the same sha256 as the file in `CMEVAL_HOME/runs` on Andrew's Mac.
- The files hold paths and short code previews from public repos. A scan found no keys and no
  local paths.
- No code changed, so no tests were run.

## Left

- The files hold the 50 results of each task: the runs used k = 50. A result ranked below 50 is
  not in them.
- The hit files of the three grep systems are not in git. Say so here if B1 needs them.

## Blocked on, or needed from others

Nothing.

## Next

Wilson: B1 from these files. Andrew: step 1 of the pilot.
