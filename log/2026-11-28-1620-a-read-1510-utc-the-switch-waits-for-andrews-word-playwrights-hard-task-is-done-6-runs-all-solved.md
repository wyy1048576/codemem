# Track A: we read the entry of 15:10 UTC; the switch waits for Andrew's word; playwright's hard task is done (6 runs, all solved)

- **Track:** A. Answers the lead's entry of 15:10 UTC
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 16:20 UTC
- **Work package:** A12 (the runs)
- **Branch, commits, pull request:** none. Runs: eval `739fbe3`, codemem `463171c`

## Done

**1. We read the entry of 15:10 UTC and follow it.** The unit is a repo, a model and a repetition.

- **The switch is not written yet.** Andrew decides for track A and has not answered. He has our recommendation (yes) and your entry.
- **The first unit that it concerns is Haiku's duckdb** (stream 1, after ruff, about 22:30 UTC). The switch is one line on the PC and takes effect for a unit that has no record yet. If Andrew does not answer before duckdb starts, duckdb begins on the old step and keeps it for repetition 1.
- **Not ready yet: a choice by model and repetition.** The record of the checkout is per recipe today. That covers duckdb, kubernetes and vscode for every model. It does not cover Opus on pandas, ruff, home-assistant and playwright, or Haiku's repetitions 2 and 3. We add the model and the repetition to that choice before those steps go into a queue (not before Nov 29, 09:00 UTC). We do not change the runner while Andrew's laptop is off (see 4).

**2. In every report we name the method of each repetition**, from `prep_steps_s` and `cmeval_commit` of the records. All records so far: old step, eval `739fbe3`.

**3. playwright's hard task (43342) is done for Haiku, repetition 1: 6 runs, all solved, none discarded, none at a limit.** Old step. Stream 2, 14:59 to 16:18 UTC.

| Level | grep: turns, tokens, s | codemem: turns, tokens, s | first fix file opened at turn (grep, codemem) |
|---|---|---|---|
| L0 | 20, 1,086,056, 419 | 40, 2,928,423, 918 | 2, 1 |
| L1 | 33, 2,077,656, 473 | 28, 1,921,418, 248 | 3, 1 |
| L2 | 35, 1,981,585, 330 | 36, 2,532,064, 514 | 4, 1 |

- The codemem agent made no search of its own in the 3 runs. The block was in the first message in 3 of 3.
- One task, one repetition: not a result. Its records go on the release with the report of playwright.
- Load at the start of a run: 7.8 to 18.4 (the vscode validation builds beside it, and stream 1 runs ruff).

**4. State at 16:20 UTC.**

- Stream 1: ruff, part a, level L1. One codemem run ended at the turn limit (ruff 26747, L1, 10.9 million tokens). It counts as not completed.
- Stream 2: playwright's 13 tasks since 16:18 UTC, old step.
- Builds: the vscode validation has 25 valid and 0 invalid.
- No guard has fired. The disk file is at 370 GB.
- **Andrew drives today. His laptop is off for about 6 hours.** In that time the PC goes on alone (two runners, the watchdog, the guards), and nobody of track A reads this log. We post the hours when he closes the laptop.

## Left

- The switch line, after Andrew's word.
- The model and the repetition in the choice of the checkout.
- The reports of ruff and of playwright.

## Blocked on, or needed from others

- None.

## Next

- Watch both streams. Report ruff (about 22:30 UTC) and playwright when they end.
