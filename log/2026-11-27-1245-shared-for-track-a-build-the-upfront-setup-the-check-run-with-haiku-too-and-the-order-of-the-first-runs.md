# For track A: build the `upfront` setup of the plan, run the check run with Haiku too, and a new order for the first runs

- **Track:** shared: from track C's session, for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 12:45 UTC. It belongs to the announcement of 12:40 UTC
- **Work package:** A6 (the setup `upfront`), and the run plan (`docs/plan/runs.md` §4, §6, §7)
- **Branch, commits, pull request:** none: a request for the runner and for the order of the runs. The commit of codemem to run stays `463171c`

## Done

**Why we ask.** We measured, with real Claude Code sessions on this Mac, where each model stands with
codemem (17 pandas tasks at their own base commits, vague prompts, the agent names the functions to change
and edits nothing; one session per cell; details in our entry of Nov 26, 21:50 UTC):

| Model | Called `search_code` by itself (setup `tool`) | Results placed in the first message, against `grep` |
|---|---|---|
| Haiku | in turn 1, in 68 of 68 sessions | fewer turns in 13 of 17 tasks, more in 3 |
| Sonnet | 3 of 17 | fewer turns in 12 of 17, more in 1 |
| Opus | 0 of 6 | fewer turns in 3 of 6, more in 1 |

The same right answers in every setup. Track B's own runs say the same of the tool: given the choice at
every step, Sonnet used codemem at step 1 in 46 of 70 runs and in 3 of 133 later steps. So codemem is a
first-step tool, and whether its results reach the agent depends on the model asking. The plan's setup
`upfront` (`docs/plan/track-a-evals.md` §4.1, hypothesis H4 of the overview) is the one that takes the asking
out. With Sonnet as the main model and only `grep` and `tool` in the grid, the `tool` runs would mostly equal
the `grep` runs.

A second measurement, with no tools and no repository at all (369 one-call sessions): each model was asked
to name the file to change. Right file named first, at L2: pandas 15, 15, 14 of 17 (Haiku, Sonnet, Opus);
playwright 10, 10, 12 of 28; kubernetes 10, 13, 17 of 20; duckdb 7, 12, 22 of 41. The models know pandas by
heart and duckdb far less. We will run this probe on the final sample too (it needs nothing from you but the
list of sampled tasks and their prompts).

## Needed from track A

**1. The setup `upfront`** (its slot is in `SETUPS` of `e2e_run.py`, not built). It is `grep` plus one
block of text at the top of the first message. No codemem server, no codemem tool.

- **The block:** one codemem search on the prompt text of the run's level (L0: the issue; L1; L2), with the
  task's own index and the locked codemem, 20 results, no filters. One line per result, in rank order:
  `path:start_line`, two spaces, the qualified name. Above them the line
  `Possibly relevant code, from a search by meaning (it may be wrong):`. Then an empty line, then the prompt
  exactly as `grep` gets it.
- **The example** (pandas 68195, L2; the function of the fix is line 14 of the 20):

```
Possibly relevant code, from a search by meaning (it may be wrong):
pandas/tests/arithmetic/test_numeric.py:48  adjust_negative_zero
pandas/tests/series/methods/test_interpolate.py:329  TestSeriesInterpolateData.test_interpolate_invalid_nonpositive_limit
...
pandas/core/reshape/merge.py:2599  _AsOfMerge._validate_tolerance
...
```

- **Made once, before the runs,** for each task and level, on the host, and saved; every repetition and
  every model then gets the same block. What worked for us:
  `codemem search "<prompt text>" --repo <the repo at the base commit> --index-dir <a copy of the task's index> -k 20 --json`
  (fields `path`, `start_line`, `qualname` of each result). Your replay client does the same against a warm
  server.
- **It must be a search by meaning:** the JSON's `timings` must hold a key that starts with `embed_query:`.
  A block made while the model was loading is a keyword answer and must be made again.
- **Record for each run:** the block's text (or its hash and file), the search's seconds, and the place of
  the first line in a gold file and of the first gold function among the 20 (or none).
- **Check for each run:** the block is in the first request; no `mcp__` tool is loaded (as for `grep`).
- **Where it runs:** at L1 and at L2, for the models and tasks of point 3.
- **No fourth setup.** We tested the block with the `tool` server still offered (34 sessions). It changed
  nothing measurable: Haiku still searched at turn 1 in 12 of 17 sessions, and Sonnet never called the tool and
  paid for its descriptions (more tokens than `upfront` in 14 of 17 tasks).

**2. The check run (§6 of the run plan) with Haiku as well as Sonnet,** 24 runs each. Rule 3, "`search_code`
is called in at least 5 of the 6 `tool` runs at L2", is asked of Haiku. For Sonnet and Opus the count is
reported and not required: we measured 3 of 17 and 0 of 6. The check run then also gives minutes per run for
both models, and how many runs ended at the turn or time limit; please post both.

**3. The order after the check run,** in place of §7's steps 2 to 5 (Andre's decision):

1. repetition 1 of Haiku and of Sonnet on every task that is ready: L0, L1, L2 in `grep` and `tool`, and
   `upfront` at L1 and L2 as soon as it is built;
2. Opus as planned (6 tasks, L0 and L2);
3. repetitions 2 and 3 of Haiku;
4. repetitions 2 and 3 of Sonnet, with the time that is left.

The hard tier joins when its tasks are ready, as §7 says. Nothing here changes the tasks, the prompts, the
limits of a run or the grading.

## Checked

The session counts were recounted from the raw records on this Mac. The block's layout is the one our
`upfront` sessions used. Not checked: anything in a container; `upfront` at L0; a fix made by the agent
(our sessions locate only).

## Left

The memory probe on the final sample.

## Blocked on, or needed from others

Track A: points 1 to 3. The runs start at 01:00 UTC on Nov 28. If `upfront` is not built by then, start with
`grep` and `tool` and add `upfront` to the same tasks afterwards: it needs no change to them.

## Next

Andre: the plan's text (`docs/plan/runs.md` §4, §6, §7) follows as a pull request.
