# For track A: the repos are the original ones, and the order of the runs. A correction to the entry of 12:50 UTC

- **Track:** shared: Andre's decisions, for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 17:00 UTC
- **Work package:** A9 (tasks), A12 (the runs)
- **Branch, commits, pull request:** `andre/run-plan-nov27` at `e1db77f` (docs only: `docs/plan/runs.md` §4, §5, §7, §8). Andre opens and merges the pull request

## Done

**1. A correction.** The entry of 12:50 UTC said that the runs concentrate on four repos, and that no further repo is started before its step 4 is done. That was this session's misreading of Andre's words. He meant the repos of the run plan as it was on `main`. They stand:

| Rank | Repo | Haiku | Sonnet | Opus |
|---|---|---|---|---|
| 1 | pandas | three repetitions | once | its 6 tasks |
| 2 | ruff | three repetitions | | its 6 tasks |
| 3 | duckdb | three repetitions | once | its 6 tasks |
| 4 | playwright | three repetitions | once | its 6 tasks |
| 5 | vscode | three repetitions | | its 6 tasks |
| 6 | home-assistant | three repetitions | | its 6 tasks |
| 7 | kubernetes | once | once | |
| 8 | trino | once | | |

**2. The order, from Andre.** It replaces the table of steps of 12:50 UTC.

1. the check run, on pandas and playwright, with Haiku and with Sonnet (48 runs, as before);
2. **Haiku, repetition 1:** ranks 1 to 6 in order, then kubernetes and trino;
3. **Sonnet, repetition 1:** pandas, duckdb, playwright, kubernetes;
4. **Opus:** ranks 1 to 6;
5. **Haiku, repetition 2, then repetition 3:** ranks 1 to 6 in order;
6. **Sonnet, repetition 2, then repetition 3:** pandas, duckdb, playwright. A bonus: it is fine if this step is not completed, and you do not need to ask.

- **Every repo is run once before any is run again.** A repo that becomes ready later starts at step 2, before further repetitions of the others.
- **The hours, with 14 tasks in every repo:** steps 1 to 4 are 1,524 runs, 42 to 59 hours on three seats at 5 to 7 minutes a run. With Haiku's repetition 2 they are 2,028 runs, 56 to 79 of the 79 hours. Repos that are short take less.

**3. Two points that Andre is still checking.** Neither changes anything before step 3, so the start is not affected.

- **Which four repos Sonnet runs.** Proposed: the four above. With no repository and no tools, Sonnet named the right file first in 15 of 17 pandas tasks, 13 of 20 kubernetes tasks, 10 of 28 playwright tasks and 12 of 41 duckdb tasks: a mix of code it knows and code it does not.
- **`upfront` in the first repetition of each model only.** Proposed. A repetition is then 112 runs for a repo the first time and 84 after it.

**4. What it changes for you now.**

- **vscode, home-assistant and trino are part of Haiku's runs again.** They need their admission checks, validation, the screen, the prompts and the indexes. In your next report, say when each can be ready and what it displaces in your queue.
- **They must not delay the check run or the repos that are ready.** The first hours are the same as before: the check run, then Haiku's repetition 1 on pandas, ruff, duckdb and playwright, then kubernetes.
- **Nothing else changes:** the three setups, the check run at 17:00 Pacific, the rule of the entry of 16:38 UTC, and that a repo which is not ready is passed over and taken up when it is.

## Checked

- The run counts: Haiku's repetition 1 on eight repos 8 x 112 = 896; Sonnet's on four 4 x 112 = 448; Opus 6 x 30 = 180; together 1,524; Haiku's repetition 2 on six repos 6 x 84 = 504.
- Sonnet's four numbers: recounted from the probe's raw records.

## Left

The pull request of the branch, for Andre.

## Blocked on, or needed from others

- **Track A:** in your next report, when vscode, home-assistant and trino can be ready.

## Next

Andre confirms the two points of part 3, or changes them, in this log.
