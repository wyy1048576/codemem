# To all tracks: `main` is locked and final at `463171c`. Track A: begin when you are ready, and report after the first one or two repos. Track B: two separate jobs

- **Track:** shared: from the lead, to all tracks. This is the entry that says "begin" (announced at 01:00 UTC)
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 01:20 UTC
- **Work package:** the freeze of `codemem-final`; A12 (the runs); B8
- **Branch, commits, pull request:** `main` at `e7586b4` (#86, the run plan's §12, docs only). codemem's own files are those of `463171c`

## Done

**1. `main` is locked and final. The hash is `463171c`.** There are no more delays.

- No index and no block is made again. The runs keep their codemem checkout at `463171c`.
- `codemem-final` is what our entry of 00:40 UTC says in point 2: the MCP tool, the tool descriptions of #26, the 20 results at the start, no hooks.
- **PRs #45, #73 and #85 are not in the lock,** and nothing of them is merged before the runs.

**2. Track A: begin whenever you are ready.**

- The check run goes on from its fourth run. The three records of 00:56 to 01:06 UTC stay, as your entry of 01:09 UTC says.
- **Report as soon as the first one or two repos are done. Do not wait for the full report.** Andre wants to assess the results and the savings early, and to see that everything runs smoothly:
  - **the results:** tasks solved in each setup;
  - **the savings:** tokens, time and turns of `codemem` against `grep`, pair by pair, for each model and level;
  - **anything out of the ordinary:** discarded or flagged runs, runs that ended at a limit, a check that failed, the load on the two accounts.
- In practice that is your first look after the Haiku half of the check run and the check run's report (pandas and playwright), and the same again after the first repo or two of Haiku's repetition 1.
- Then on in the order of `docs/plan/runs.md` §7.

**3. Track B: two jobs, and they are separate.**

- **Job 1, which is yours to do: the comparison of the exact and the compact index on kubernetes** (our entry of 00:56 UTC; `docs/plan/runs.md` §12, on `main` since #86). Its three conditions stand: your agent at its highest setting, exactly as track A runs, and a question in this log before any assumption. It comes first. We still wait for your post on whether your machine can do it.
- **Job 2, which you may propose: a small evaluation of PR #85** (the query that the agent fills in with `intent`, `symptom`, `anchors` and `locations`; the new wording; `k` up to 10; no hooks). PR #85 is not merged and is not part of the lock. Andre invites a **plan** for an evaluation on 1 or 2 repos, not the full load. **Post the plan here and wait for our go-ahead before any run.** It should say:
  - **which repos and tasks:** 1 or 2 repos of the run sample. The memory probe (our entry of 22:43 UTC) shows where the models do not place the tasks from memory; duckdb and kubernetes have the most room;
  - **the two arms:** codemem at `463171c`, as locked, against the same with #85, and everything else the same. Say which of #85's changes each arm holds, so that a difference can be put down to one of them: the new wording and the new inputs are two things;
  - **the models and levels,** the number of runs, and the hours on your machine;
  - **what is measured:** tasks solved, turns, tokens and time; how often the agent fills each new input; and what the longer description costs on every turn (it grows from 483 to 1,352 characters);
  - **the pipeline:** track A's, as for job 1, or what differs.
- **Job 2 does not delay job 1.** Item 1, your 112 runs, goes on as you posted.
- Our review of #85 follows in its own entry.

## Checked

`git diff --stat 463171c origin/main -- . ':(exclude)eval' ':(exclude)docs'` prints nothing at `e7586b4`.

## Left

Nothing for the lock.

## Blocked on, or needed from others

- **Track A:** the early reports of point 2.
- **Track B:** the post on feasibility for job 1; the plan for job 2 if you want to make one.

## Next

Track A: the check run goes on. The lead: reads the early reports, and reviews #85.
