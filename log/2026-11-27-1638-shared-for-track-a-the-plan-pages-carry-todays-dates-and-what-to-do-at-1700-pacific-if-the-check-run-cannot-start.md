# For track A: the plan pages carry today's dates, and what to do at 17:00 Pacific if the check run cannot start

- **Track:** shared: from the lead, for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 16:38 UTC
- **Work package:** A12 (the runs)
- **Branch, commits, pull request:** `andre/run-plan-nov27` at `7ab4342` (three commits, docs only). Andre opens and merges the pull request

## Done

**1. The plan has not changed since the entry of 12:50 UTC.** The order of the runs is the one given there. The branch only writes it into the plan pages:

- `docs/plan/runs.md`: the three setups, the models, the order and the hours, as in the entries of 12:40, 12:45 and 12:50 UTC. Since then its two tables that still counted six repos count the four that are run fully, and it says that all setups of a task take turns and that the first one changes from task to task (point 5 of the entry of 15:13 UTC).
- `docs/plan/overview.md` and `docs/plan/track-a-evals.md`: the dates. They gave a freeze on Nov 25 and runs from Nov 26. They now give what follows.

**2. The dates, as Andre set them.**

| When (Pacific) | What |
|---|---|
| Fri Nov 27, 16:30 | codemem is frozen |
| Fri Nov 27, 17:00 | the runs start, **with the check run** (`runs.md` §6). Its report is read before the batches run unattended overnight |
| Sat Nov 28 and Sun Nov 29 | reserved for running |
| Sat Nov 28, expected | the open harness and the open models are ready. They run on the rented GPU and use nothing of the PC |
| Mon Nov 30, 23:59 | the results are frozen |

**3. At 17:00 Pacific (Nov 28, 01:00 UTC).** From Andre:

- **If the check run cannot start then, or if it does not pass, do not start the overnight batches.** Post where you are and what is missing, and ask Andre here for further instructions.
- **A repo or a tier that is not ready is not that case.** The plan passes it over and takes it up when it is ready (`runs.md` §7), and a repo that is short runs what it has (§3).

**4. So that we can tell where things stand, your next report should say:**

1. the mount of the codemem checkout in `tool` containers (entry of 15:13 UTC, point 1): fixed or not, and how you checked;
2. the `upfront` setup (entry of 12:45 UTC): built or not;
3. the fair tasks of each repo by tier, with their L1 and L2 prompts and their indexes on the frozen codemem;
4. whether the check run can start at 17:00 Pacific.

## Checked

- The three commits merge into `main` without a conflict.
- In the two pages, every replacement was made on a text that occurs once, and no mention of a freeze on Nov 25 or of runs from Nov 26 is left.

## Left

Nothing on our side.

## Blocked on, or needed from others

- **Track A:** the report of point 4, before 17:00 Pacific.

## Next

We read your report when it comes and answer here.
