# For track A: an audit of the three measures (tokens, cost, time) before the runs start, with the evidence in the log

- **Track:** shared: from Andre, for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 14:50 UTC
- **Work package:** A4 (the integrity checks), §4.5 and §5 of track A's plan
- **Branch, commits, pull request:** none

## Done

**Why Andre asks.** The comparison of grep against codemem in tokens, cost and time is the project's result, and the pipeline that measures it is one of its contributions. We cannot see the PC, so we ask you to audit your own measurement and post the evidence: for each point below, what the records show. The aim is one thing: **no measure may lean towards one setup for a reason that is not the setup.** Your plan already guards most of this (§4.5, §5); what we ask is the proof from records, and three additions that today's work brought up.

**When.** With the check run at the latest, because its 48 runs are the first evidence. Anything that can be answered from the pilot's records, earlier.

## The audit, point by point

### Tokens

1. **Which of the six numbers of §5.4 does a run record today?** Processed tokens and the four classes are in `run.json`. Tokens read by tool, tokens before the first edit and peak context: built, or not yet? Say which tables can be made from the runs as they are.
2. **The classes by model, and the two kinds of cache write.** Claude Code writes its cache at the one-hour rate (in our sessions and in track B's every cache write was `ephemeral_1h`), which costs twice the input price, not 1.25 times. Confirm that the per-request `usage` in the proxy log keeps `cache_creation.ephemeral_1h_input_tokens` and `ephemeral_5m_input_tokens`, and Claude Code's side calls to another model apart from the main model's.
3. **Processed tokens lean towards the setup with fewer turns.** This is the addition that matters most. In our sessions and in track B's, 77 to 87% of a run's tokens are cache re-reads, which cost a tenth or a twentieth of the input price. New text entering the conversation (a tool result) is 12% of the tokens and more than half of the cost. So a setup that saves turns saves many cheap tokens, and a setup that returns longer results adds few, dear ones. codemem does both. A table of processed tokens alone would overstate what codemem saves. **Please report the four classes beside the sum in every table,** and see point 5.
4. **Cache luck.** Your plan says the sum does not depend on whether the first request found the prompt cached. For the classes it does. Show, from the check run, the cache write of the first request of each run by setup: how often is the standing prompt written and how often read, for `grep`, `tool` and `upfront`? (`grep` and `upfront` share a prompt; `tool` has four more tool definitions.)

### Cost

5. **A cost column from one fixed price table, never from `total_cost_usd`.** The agent's own dollar figure depends on the version of Claude Code: on our Mac, version 2.1.285 priced Sonnet's cache reads at $0.20 a million, and track B's 2.1.314 at $0.10. Please add cost at list prices, computed by us: each class of each model times one price, with the price table written in the output. It is the measure a reader will ask for, and the classes make it exact.
6. **The Claude Code binary and the model ids are the same in every run of the experiment.** Show the distinct values of `harness_version`, the binary's hash and the model ids over all runs, and make the score say so when there is more than one.

### Time

7. **What is outside the clock, reported beside it.** The wait for codemem (`codemem_warm_s`), the index copy and, for `upfront`, the search that made the block are not in `agent_s`. That is right for comparing the agent's work, and it has to be stated: please report them per setup beside the wall time, so that the paper can say what a session of codemem costs before the agent starts.
8. **Other work on the PC while a timed batch runs.** Image builds, validation of the hard tier and our own thread measurement all run on the same machine. They slow a run by an amount that has nothing to do with its setup. Either keep heavy jobs off while a timed batch runs, or record the machine's load at the start and end of every run so that such runs can be marked.
9. **Seats.** Record which seat ran each run. Do the setups of one task run on the same seat, turn about? A seat near its limit answers more slowly: show the number of 429 answers and retries per run, by setup.
10. **Where the time goes.** Wall time includes the tests the agent starts and waits for; in the pilot those were the long runs. Report model time (`duration_api_ms`) beside wall time, and the time before the first edit if it is recorded, so that a difference in wall time can be told from a difference in test waiting.

### Both, and the comparison itself

11. **Runs that are thrown away.** Only a setup with codemem can fail the codemem checks (the warm-up, a first search from keywords only). Show the number of discarded runs by setup and reason. If `tool` runs are redone more often than `grep` runs, say so in the table.
12. **Runs that end at a limit.** The number that ended at the turn or the time limit, by setup and model. They count as not completed, with their tokens and time, in every setup alike: confirm it from the score.
13. **Missing values.** `e2e_score` leaves a run without a value out of that mean. Show how many runs lack tokens or time, by setup, and that a pair is only made where both sides have the value.
14. **One difference.** For one task of the check run, post the first request of its `grep`, `tool` and `upfront` runs side by side (sizes of the system prompt, the tool list and the first message). The only differences must be codemem's four tools and its instructions in `tool`, and the block in `upfront`.

## What we do on our side

We are reading the measurement code on `main` (`eval/src/cmeval`: the proxy, the runner's clocks, the score and its pairs) for anything that could lean, and post what we find here.

## Checked

Points 2, 3 and 5 rest on our own session records and on track B's 35-task records (the numbers are in our entries of today, 11:45 and 12:40 UTC). The rest are questions, not findings.

## Left

Our reading of the code.

## Blocked on, or needed from others

**Track A:** the audit with the check run. It must not delay the start; where an answer needs the check run's records, post it right after.

## Next

Andre's session: the code reading, then the comparison of your answers with it.
