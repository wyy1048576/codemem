# Both repos are tested end to end in both setups; no agent called codemem at the `light` wording

- **Track:** A. Points 2 to 4 of "Done" are for track B
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-25 15:57 UTC
- **Work package:** A1, A2, A3, A4, A9: the first end-to-end test of §2.2
- **Branch, commits, pull request:** `main` at `32cf252`. New since the last entry: #27 (a batch can set codemem's steering level)

## Done

**1. The pilot batch `pilot-haiku-1`.** The 18 valid tasks of pandas (10) and playwright (8), each in `grep` and in `tool`, Haiku, 1 repetition, on the PC. codemem is `9dfe3fe`, wording `light`.

| | `grep` | `tool` |
|---|---|---|
| Runs, discarded, flagged | 18, 0, 0 | 18, 0, 0 |
| Completed | 6 of 18 | 6 of 18, the same 6 tasks |
| Tokens per run, mean / median | 1,164,235 / 1,042,810 | 1,331,969 / 921,840 |
| Seconds per run, mean / median | 258 / 186 | 327 / 172 |
| Content searches per run | 10.7 | 11.8 |
| Runs that called codemem | | **0 of 18** |
| Proxy count equal to `modelUsage` | 18 of 18 | 18 of 18 |

**This is not a codemem result.** No run called codemem, so both columns are the same agent. It is a measure of noise: the two runs of one task differed by up to 8 times in tokens (playwright 42919: 2.14M and 0.25M; pandas 70742: 0.43M and 3.16M). Haiku, one repetition.

**2. Adoption.** The server was connected and the four tools were listed in all 18 `tool` runs (`alwaysLoad`). Haiku searched with `grep` in the shell every time. A probe with `CODEMEM_STEERING=strong` (5 runs): 4 runs called `search_code`, each once, in turn 1, together with a `grep` call, and never again.

**3. What the four codemem calls returned.** Three gave ranked results (3,600 to 6,700 characters); in pandas 70713 the first result is in the file of the real fix. One gave "No results" with the note "the embedding model is still loading". That call had `path_prefix: "/testbed/pandas/core/groupby"`, an absolute path. If the filter expects a path relative to the repo, an agent that passes the absolute one gets nothing and no hint.

**4. The result text reaches the agent as one JSON string** (`{"result":"1. pandas/io/...\\n   def ..."}`, line ends as `\\n`), as seen in Claude Code's stream. Not checked if the model sees it the same way.

**5. The six pass conditions of §2.2.** (1) The grader is right: met, 18 of 18, repeated on the rebuilt images. (2) Every stage for every task in both setups: met. (3) Token counts within 1%: met, equal on all 36 and on 11 probe runs. (4) Tools listed and some runs call them: listed yes; called only at `strong`. (5) Resume and a broken setup: met. An interrupt in the middle of a run leaves nothing running, and the next start does that run again; a codemem program that exits at start gives a discarded run ("mcp server codemem is failed"). (6) Three transcripts read by a person: Andrew, today.

**6. All 20 task images were built again** with ripgrep 15.2.0 and validated under the corrected rules: same verdicts (pandas 10 of 10, playwright 8 of 10).

**7. Other things seen.** No run used a subagent or `Workflow` (tools over 36 runs: Bash 684, Edit 45, Monitor 12, TaskStop 2, Read 1). Long runs come from `Monitor`: the agent starts a wide test run and waits, and each wait sends the whole context again. Haiku used plain `grep`, not `rg`, for almost every search.

## Checked

- Every number above is from the run records on the PC (`~/.cmeval/e2e/runs/pilot-haiku-1`, `probe-strong-1`, `probe-broken-1`, `probe-resume-3`) and `cmeval e2e score`.
- Unit tests: 709 pass on `32cf252`.
- Not checked: subagent token accounting (no run used one). A hard kill (SIGKILL) of the batch leaves the run's container up until the next start.

## Left

- Sonnet runs and three repetitions. The task file of 60 candidates per repo. Recipes for ruff, kubernetes, duckdb.

## Blocked on, or needed from others

- **Wilson (track B):** points 2 to 4. For the adoption check: a batch can now set the level (`CMEVAL_CODEMEM_STEERING=none|light|strong`), and `run.json` records it. The runner removes `.claude/` and `CLAUDE.md`, so the hooks and the agent note of #26 do not reach the agent; say if you want an arm with them. Say in the log when the wording is frozen and at which commit; the `tool` setup then moves to it.
- **Andre (track C):** track A stays with the GPU in the container for now. The embedding server is not needed today.

## Next

- Andrew: read three transcripts; decide the size of the first Sonnet batch.
- Track A's session: the adoption check again when track B names its commit.
