# For track A: the priorities of the runs. Haiku first, on a few repos; Haiku's repetitions are the goal; Sonnet's repetitions are a bonus

- **Track:** shared: Andre's decisions, for track A. It narrows the announcement of 12:40 UTC and the request of 12:45 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 13:05 UTC
- **Work package:** the run plan (`docs/plan/runs.md` §4, §5, §7, §8)
- **Branch, commits, pull request:** none yet. The plan's text follows as a pull request (`andre/run-plan-nov27`)

## Done

**Why.** From the start of the runs (Nov 28, 01:00 UTC) to the freeze (Dec 1, 07:59 UTC) there are 79 hours. With three setups and Haiku on every task, the whole plan no longer fits. Andre's worry is time, so here is what counts.

**Andre's decisions.**

1. **The runs concentrate on Haiku, Sonnet and Opus, on a few repos.** The few are the repos of ranks 1 to 4 of the run plan: pandas, ruff, duckdb, playwright. No further repo is started before step 4 below is done.
2. **Haiku carries the presentation.** It is the model that calls codemem at the start of nearly every run. Sonnet and Opus are run to record how often they use it and what `upfront` gives them; more experiments on them come later, with tasks on renamed code.
3. **Haiku's repetitions are the goal.** Andre would be very happy to reach the end of step 4.
4. **Sonnet's repetitions are a bonus.** If time runs out, it is fine that they are not completed. You do not need to ask.
5. **The analysis is not yours to design now.** Which tables and analyses are made from the runs, Andre decides in the next days. Keep recording what every run records today. Suggestions are welcome.

**The order.**

| Step | What | Runs, for a repo with 14 tasks | Where it stands |
|---|---|---|---|
| 1 | the check run, with Haiku and with Sonnet | 48, part of step 2 | must |
| 2 | repetition 1 of Haiku and of Sonnet, repos 1 to 4 | 224 a repo | must |
| 3 | Opus, repos 1 to 4 | 30 a repo | must |
| 4 | repetitions 2 and 3 of Haiku, repos 1 to 4 | 224 a repo | **the goal** |
| 5 | kubernetes, once, with Haiku and Sonnet | 224 | if time is left |
| 6 | repetitions 2 and 3 of Sonnet, repos 1 to 4 | 224 a repo | a bonus |
| 7 | vscode, home-assistant, trino | | if time is left |

- A model's repetition on a repo is 112 runs: `grep` and `tool` at L0, L1 and L2 (14 x 3 x 2 = 84), and `upfront` at L1 and L2 (14 x 2 = 28). Opus: its 6 tasks at L0 and L2 in `grep` and `tool` (24), and `upfront` at L2 (6).
- Through step 4, four full repos are 1,912 runs: 53 to 74 hours on three seats at 5 to 7 minutes a run. A repo with fewer than 14 tasks takes less.
- **Suggestion, yours to take or leave:** inside step 2, run Haiku's repetition of a repo before Sonnet's, so that a batch that is cut short leaves Haiku's table whole.
- The rules of the run plan stay: a repo or a tier that is not ready is passed over and taken up when it is; a batch that is cut short leaves a complete table with fewer repetitions; `upfront` joins a repo's runs on the same tasks as soon as the runner has it.

## Checked

The run counts: 112 = 84 + 28; 224 = 2 x 112; 30 = 24 + 6; 4 x (224 + 30 + 224) = 1,912; 1,912 x 5 / 3 / 60 = 53 hours and 1,912 x 7 / 3 / 60 = 74 hours.

## Left

The plan's text, as a pull request.

## Blocked on, or needed from others

**Track A:** nothing new to build beyond the request of 12:45 UTC. If something in this order does not fit your queue or your sampler, say so here.

## Next

Track A: the check run at 01:00 UTC on Nov 28, then the steps in this order. Andre: the analysis to be made from the runs, in the next days.
