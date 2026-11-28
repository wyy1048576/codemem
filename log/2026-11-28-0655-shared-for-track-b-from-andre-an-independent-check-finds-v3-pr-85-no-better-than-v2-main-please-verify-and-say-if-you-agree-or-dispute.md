# For track B, from Andre: an independent check finds v3 (PR #85) no better than v2 (`main`). Please verify it and say whether you agree or dispute it

- **Track:** shared: from the lead, for track B. On your entries of 00:40 UTC (PR #85) and 01:15 UTC (its quick test against `main`), and our review of PR #85 (01:45 UTC)
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 06:55 UTC
- **Work package:** track B, the decision on PR #85
- **Branch, commits, pull request:** all data on branch `andre/v3-check-data` (`1d366fd`, data only, never to be merged), folder `v3-check/`. Compared: PR #85 at `4902671` ("v3") against `main`'s codemem `463171c` ("v2")

## Done

**Andre's finding: v3 performs no better than the v2 that is on `main`.**

- **Your quick test of 01:15 UTC is not representative.** It ran 5 tasks with Haiku, one or two runs each, with the tool alone. The gap it found is the size of the run-to-run variation measured here.
- **What decides it is the metrics, and whether a gain is worth the effort.** Replacing v2 on `main` means a new lock of codemem, the evaluation's setup checked again, and the runs measured again. That is a significant amount of engineering and evaluation effort.
- **So the bar is:** v3 better than v2 on the setup the evaluation runs, by more than the run-to-run variation, with no loss of quality.

**What we ran.**

- **337 sessions on the Mac,** Nov 28, 02:15 to 06:04 UTC, one at a time, the setups taking turns in an order that changes from task to task.
- **Tasks:** 17 pandas tasks and 6 vLLM tasks, all at L2. vLLM ran on its real index of 144,729 vectors, one copy per session.
- **Models:** `claude-haiku-5-5` and `claude-sonnet-5-5`.
- **What the agent does:** Claude Code headless (`claude -p`) reads and searches but does not edit, then names the files and functions it would change. It is scored on two things:
  - the right file first (the first file it names is a file of the fix);
  - the right function (it names a function of the fix in full).
- **Five setups:**
  - `grep`: the agent's own tools only.
  - `v2-tool` and `v3-tool`: codemem at that commit as the MCP tool.
  - `v2` and `v3`: the tool plus the same 20 lines at the top of the first message. **`v2` is what the evaluation runs.**
  - The 20 lines come from one `codemem search -k 20` per task at `463171c`, made as the evaluation makes them, and are the same text in `v2` and `v3`.
- **Repetitions:**
  - Haiku ran `grep` once and each codemem setup twice per task; the second run measures the run-to-run variation.
  - Sonnet ran each setup once, and `v2` and `v3` a second time on 7 and 8 pandas tasks.

**1. With the 20 lines, which is what the evaluation runs: v3 against v2.**

Each figure is the sum of v3 over the sum of v2, on the same tasks and runs. The last two columns are the run-to-run variation, in tokens: an arm's second run over its first, on the same tasks.

| | Pairs | Turns | Tokens | Cost | Seconds | Right file, right function | v2 run twice | v3 run twice |
|---|---|---|---|---|---|---|---|---|
| Haiku, pandas | 34 | 0.95 | 0.99 | 1.02 | 1.08 | same | 1.27 | 0.85 |
| Haiku, vLLM | 12 | 1.12 | 1.30 | 1.33 | 1.31 | same | 0.82 | 0.53 |
| Sonnet, pandas | 25 | 1.10 | 1.19 | 1.08 | 1.14 | same | 1.25 | 1.01 |
| Sonnet, vLLM | 6 | 1.00 | 1.04 | 1.02 | 0.98 | same | not measured | not measured |

- **No gap is larger than the variation.** A permutation test within each task gives p from 0.08 to 1.00.
- **Haiku on vLLM:** one long v3 session (25 turns, 973,000 tokens) carries most of the gap. It is the rerun of a session the harness set aside. Counting the first attempts instead gives 0.93 in tokens and 1.07 in cost.
- **Sonnet never called `search_code` with the 20 lines,** in either arm: 0 of 61 sessions. So all it got from v3 was the longer tool texts.

**2. The tool alone, which is what your quick test measured: v3-tool against v2-tool.**

| | Pairs | Turns | Tokens | Cost | Seconds | v3-tool used more tokens in | v2-tool run twice (tokens) |
|---|---|---|---|---|---|---|---|
| Haiku, pandas | 34 | 0.88 | 0.80 | 0.85 | 0.90 | 21 of 34 pairs | 1.68 |
| Haiku, vLLM | 12 | 0.88 | 0.82 | 0.95 | 1.00 | 6 of 12 | 2.08 |
| Sonnet, pandas | 17 | 1.12 | 1.33 | 1.16 | 1.10 | 14 of 17 (p 0.01) | not measured |
| Sonnet, vLLM | 6 | 1.03 | 1.12 | 1.07 | 1.07 | 3 of 6 | not measured |

- **Haiku:** v3-tool's lower totals come from a few pairs. It used more tokens than v2-tool in most pairs, two runs of v2-tool differ by 1.68 and 2.08, and p is 0.21 or more. Right file first: 29 of 34 for v3-tool against 32 of 34 for v2-tool.
- **Sonnet, pandas:** the one gap with a small p, and it goes against v3. Sonnet searched in 9 sessions with v3-tool against 3 with v2-tool, for the same quality.

**3. For scale: the same sessions do find real gaps where they exist.** v2 against `grep`:

| | Pairs | Turns | Tokens | Cost | Seconds |
|---|---|---|---|---|---|
| Haiku, pandas | 34 | 0.80 (p 0.01) | 0.95 | 0.94 | 0.79 (p 0.01) |
| Sonnet, pandas | 24 | 0.69 (p 0.00) | 0.78 | 0.75 (p 0.03) | 0.69 (p 0.01) |

So the check can see a gap of 20 to 30%. Between v3 and v2 it finds none.

**4. What v3 changes for certain.**

- **485 more input tokens in every request.** codemem's tool definitions grow from 2,144 to 3,405 characters, and its server instructions from 611 to 825.
- **Haiku fills the new fields.** It fills `intent`, `symptom` and `anchors` in almost every call and `locations` in about a third, so its search arguments are about 5 times longer. Sonnet mostly fills only `anchors`.
- **Some calls fail.** In 3 of Haiku's 92 v3 sessions, the first call left out the required `query` and failed validation.

**Why the quick test of 01:15 UTC is not representative.**

1. Its gap, about 20% lower cost for the tool alone with Haiku, is the size of the variation between two runs of one setup measured here.
2. It measured the tool alone. With the 20 lines, which is what the evaluation runs, the gap disappears.
3. It was Haiku only. With Sonnet the gap turns against v3.
4. It ran 5 tasks with one or two runs each, so no measure of the variation stood next to the gap.

## Checked

- **The tables recompute from the branch alone.** `python3 v3-check/bin/blockv3_report.py --print` reproduces all 116 table rows of `v3-check/report.md` exactly, with no codemem checkout needed.
- **Before the first session:**
  - v3's server opened the pandas and vLLM indexes without rebuilding them: the same chunks and vectors, nothing stale.
  - Three real plain queries gave byte-identical results at `463171c` and `4902671`, on pandas and on vLLM.
  - The 20 lines, made again at `463171c`, were identical to the saved ones.
  - One dry start per arm showed the right tool texts, no hook, and the lines only in `v2` and `v3`.
- **The source each arm ran:** every session's `runs/<session>/mcp.json` names it in `PYTHONPATH` (`compare-main` is `463171c`, `compare-pr85` is `4902671`).

**What this does not show.**

- The agent locates code and does not edit it. Fix runs were not measured.
- The requests are L2 only, and the tasks are pandas and vLLM only.
- Sonnet's run-to-run variation exists only for `v2` and `v3`, on 7 and 8 pandas tasks.
- A second run can reuse the prompt cache of the first, which lowers its cost but not its tokens. That is why the variation is given in tokens. Between arms, run 1 is paired with run 1 and run 2 with run 2.
- Seconds exclude the server's start.
- The harness ran again the 3 sessions whose first call left out `query`. The report gives both counts.

**The data, on branch `andre/v3-check-data`, folder `v3-check/`:**

- `README.md`: the map of the folder and the two commands.
- `report.md`: the full result, with every table and one worked example (task 71129).
- `brief.md`: the design, written before the first session.
- `sessions.csv`: one row per kept session.
- `transcripts/`: each session in readable form, with every turn, tool call, result and answer.
- `runs/`: each session's record, Claude Code's event stream, the proxy log with every request's `usage`, the first message, the exact command and the server config.
- `v3/`: the 20 lines of each task, the checks made before the first session, and codemem's server instructions at both commits.
- `bin/`: the harness and the report scripts.
- Removed before publishing: local paths, the subscription's usage fields, and the rate-limit headers and request ids.

## Left

- Andre's decision on PR #85, after your answer.

## Blocked on, or needed from others

**Track B: please verify this and answer here, agree or dispute.**

1. **Recompute** the tables from the branch with one command, and read any sessions you doubt in `transcripts/`.
2. **Check the method:**
   - the arms and their sources;
   - the scoring of right file and right function;
   - the pairing by task and run;
   - the variation measure;
   - the rule that ran the 3 failed sessions again.
3. **Say whether you agree** that v3 is no better than v2 on these measures.
4. **If you dispute it, come back with findings that would change the decision.** Either:
   - an error in our method or data, with the evidence; or
   - a measurement on the setup the evaluation runs (the tool plus the 20 lines), with Haiku and Sonnet. It needs at least two runs per arm and task, so that the variation stands next to the gap; tasks fixed before the runs; tokens, turns, cost, seconds and quality; and on which measure v3 is better, and by how much against the variation.
5. **Please answer this before any runs for your job 2** (an evaluation of v3 on 1 or 2 repos), since this entry is about whether that effort is worth it. Job 1, the exact and the compact index on kubernetes, is not affected.

## Next

- Andre decides on PR #85 when your answer is in.
