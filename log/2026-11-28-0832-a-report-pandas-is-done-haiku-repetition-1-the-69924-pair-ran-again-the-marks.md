# Track A, report: pandas is done for Haiku, repetition 1 (54 runs, none discarded). The 69924 pair ran again. Every run has its marks

- **Track:** A, for the lead. The early report that you asked for after the first repo, and the answer to your entry of 07:05 UTC
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 08:32 UTC
- **Work package:** A12 (the runs), A4 (the integrity checks)
- **Branch, commits, pull request:** none. Records: release `run-records`, files `haiku-rep1-pandas.tgz`, `haiku-rep1-pandas-marks.tsv`, `pressure-to-0830.log`

## Done

**1. pandas, Haiku, repetition 1: 54 runs of 54** (9 tasks, L0, L1 and L2, `grep` and `codemem`). 12 of them are the check run's records. Eval `722ded5` and `739fbe3` (no change in `eval/src` between them), codemem `463171c`, seat `claude-token`.

**One repo of one repetition is not a result.** The differences below are smaller than the difference between two runs of the same task that you measured (1.27 in tokens for pandas).

| | `grep` | `codemem` | `codemem` against `grep` |
|---|---|---|---|
| Solved, of 27 | 20 | 20 | the same |
| Turns | 465 | 420 | -10% |
| Processed tokens | 23,428,263 | 23,266,145 | -0.7% |
| Agent seconds | 6,819 | 5,322 | -22% (read point 3 first) |
| Cost as Claude Code reports it, USD | 0.479 | 0.517 | +8% |
| First file of the fix opened at turn 1, of 27 | 3 | 16 | |

- **By pair:** `codemem` used fewer tokens in 17 of 27 pairs and fewer seconds in 16 of 27.
- **One task carries most of the tokens on `codemem`'s side:** pandas 70734, +802,150 at L1 and +1,430,838 at L2. Neither setup solved it at any level.
- **Solved:** the setups differ in 2 of 27 pairs. `grep` alone solved 67897 at L0; `codemem` alone solved 68945 at L1. At L2 they agree on every task.
- **By level, tokens:** L0 -11%, L1 +3%, L2 +6%. **Seconds:** L0 -32%, L1 -34%, L2 +5%.
- **The agent called `search_code` in 12 of the 27 `codemem` runs,** one time each: 2 at L0, 4 at L1, 6 at L2. It never called `get_chunk`.

**2. The checks, over the 54 records.**

- Discarded 0, flagged 0. All ended `finished`: no turn limit, no time limit, no usage limit.
- The proxy's token count equals the agent's in 54 of 54.
- All 27 `codemem` runs have the block in the first message and a passing mount proof. No search fell back, none was keywords only.
- Seat `claude-token`: 16% of its weekly limit at 08:28 UTC. It was at 11% before the check run and 13% after it. Seat `claude-token-2` (home-assistant): 1% of its 5-hour limit.

**3. The marks (your entry of 07:05 UTC, point 2).** `haiku-rep1-pandas-marks.tsv` has one line for each run folder: the start of the agent's seconds, the number of samples of `pressure.log` in them, the highest and the mean number of cores in use, the highest number of build jobs, the seconds in which the other stream's agent ran, the seconds in which the other stream prepared a run (its chown of `/testbed`, heavy on the disk), and the marks in words.

| | Runs | Builds beside | Other stream beside (share of the agent's seconds) | Before `pressure.log` |
|---|---|---|---|---|
| L0, `grep` | 9 | 5 | 44% | 3 |
| L0, `codemem` | 9 | 5 | 15% | 3 |
| L1, `grep` | 9 | 9 | 93% | 0 |
| L1, `codemem` | 9 | 9 | 97% | 0 |
| L2, `grep` | 9 | 6 | 61% | 3 |
| L2, `codemem` | 9 | 6 | 67% | 3 |

- **So the seconds of pandas were not measured under one condition.** The 12 check-run records ran in one stream; L1 ran with builds and the other stream beside every run. The two setups of a pair ran back to back, so a pair saw about the same load, but the levels did not.
- `pressure.log` starts at 04:16 UTC and has the cores in use from 04:50 UTC. For the 12 check-run records (00:56 to 03:22 UTC) the marks say `before pressure.log`. Whether image builds ran beside them, and when, we take from the build logs and add to the file; that is not done yet.
- The load average in a record (`host_load_start`, up to 74) counts build processes that wait at their CPU limit. Use the cores in use.

**4. pandas 69924 at L0 ran again** (your entry of 07:05 UTC, point 1), in stream 1, as one batch of two runs, right after pandas L2.

| | `grep` | `codemem` |
|---|---|---|
| First pair, set aside (04:40 to 04:53 UTC) | solved, 18 turns, 961,914 tokens, 439 s | solved, 19 turns, 1,110,229 tokens, 303 s |
| New pair, counts (08:15 to 08:28 UTC) | solved, 22 turns, 1,209,530 tokens, 310 s | solved, 19 turns, 1,144,743 tokens, 311 s |

- The new pair is in the tables of point 1. The first pair is in `grep/1.discarded-1/` and `codemem/1.discarded-1/` with its whole record and a `SET-ASIDE.txt` that gives the reason and your entry. It is in the archive.
- **The new pair's marks:** builds beside both runs (duckdb, at the limit of 6 cores; cores in use at most 10.4 and 9.2 of 16), and the other stream beside both (home-assistant: its agent for 30 and 40 s, its preparation for 250 and 150 s). No run had all cores busy.
- Our report script counted set-aside folders as records until today. We corrected it before this report: the first pair is listed apart and is in no sum.

**5. The tables by task.**

**L0**

| Task | grep: solved, turns, tokens, s | codemem: solved, turns, tokens, s | codemem minus grep: turns, tokens, s | searches by the agent | first gold file opened at turn (grep, codemem) |
|---|---|---|---|---|---|
| pandas-67025 | yes, 13, 578,040, 288 | yes, 9, 454,302, 64 | -4, -123,738, -224 | 0 | 3, 1 |
| pandas-67897 | yes, 34, 1,986,682, 549 | no, 22, 1,221,673, 330 | -12, -765,009, -219 | 1 | 2, 1 |
| pandas-68090 | yes, 11, 519,304, 223 | yes, 13, 713,843, 217 | +2, +194,539, -6 | 1 | 2, 1 |
| pandas-68278 | yes, 9, 374,647, 137 | yes, 7, 309,824, 233 | -2, -64,823, +96 | 0 | 1, 1 |
| pandas-68945 | no, 11, 476,344, 46 | no, 11, 505,833, 57 | +0, +29,489, +12 | 0 | 2, 1 |
| pandas-69779 | no, 34, 1,705,454, 802 | no, 28, 1,530,799, 357 | -6, -174,655, -446 | 0 | 6, 8 |
| pandas-69924 | yes, 22, 1,209,530, 310 | yes, 19, 1,144,743, 311 | -3, -64,787, +1 | 0 | 2, 1 |
| pandas-70734 | no, 13, 654,830, 76 | no, 12, 615,030, 57 | -1, -39,800, -19 | 0 | 1, 2 |
| pandas-71232 | yes, 3, 118,467, 14 | yes, 6, 254,750, 30 | +3, +136,283, +16 | 0 | None, None |
| **9 pairs** | 6 solved, 150, 7,623,298, 2446 | 5 solved, 127, 6,750,797, 1657 | -23, -872,501 (-11%), -789 (-32%) | | |

Cost as Claude Code reports it, USD: grep 0.164, codemem 0.159.

**L1**

| Task | grep: solved, turns, tokens, s | codemem: solved, turns, tokens, s | codemem minus grep: turns, tokens, s | searches by the agent | first gold file opened at turn (grep, codemem) |
|---|---|---|---|---|---|
| pandas-67025 | yes, 19, 872,974, 95 | yes, 10, 513,104, 73 | -9, -359,870, -21 | 0 | 3, 1 |
| pandas-67897 | yes, 34, 1,922,907, 954 | yes, 26, 1,478,586, 202 | -8, -444,321, -752 | 0 | 2, 1 |
| pandas-68090 | yes, 15, 705,916, 330 | yes, 16, 858,862, 191 | +1, +152,946, -139 | 1 | 2, 2 |
| pandas-68278 | yes, 11, 476,541, 314 | yes, 12, 550,114, 171 | +1, +73,573, -144 | 0 | 2, 1 |
| pandas-68945 | no, 13, 516,104, 52 | yes, 15, 698,981, 131 | +2, +182,877, +79 | 0 | 5, 1 |
| pandas-69779 | yes, 13, 582,319, 145 | yes, 11, 559,372, 289 | -2, -22,947, +145 | 1 | 3, 2 |
| pandas-69924 | yes, 24, 1,384,844, 410 | yes, 21, 1,370,862, 385 | -3, -13,982, -25 | 1 | 2, 3 |
| pandas-70734 | no, 12, 542,711, 64 | no, 22, 1,344,861, 126 | +10, +802,150, +62 | 1 | 3, 4 |
| pandas-71232 | yes, 7, 274,288, 33 | yes, 3, 122,250, 18 | -4, -152,038, -16 | 0 | 2, 1 |
| **9 pairs** | 7 solved, 148, 7,278,604, 2396 | 8 solved, 136, 7,496,992, 1586 | -12, +218,388 (+3%), -810 (-34%) | | |

Cost as Claude Code reports it, USD: grep 0.143, codemem 0.165.

**L2**

| Task | grep: solved, turns, tokens, s | codemem: solved, turns, tokens, s | codemem minus grep: turns, tokens, s | searches by the agent | first gold file opened at turn (grep, codemem) |
|---|---|---|---|---|---|
| pandas-67025 | yes, 13, 570,567, 111 | yes, 11, 568,603, 79 | -2, -1,964, -32 | 0 | 2, 1 |
| pandas-67897 | yes, 30, 1,619,386, 392 | yes, 31, 1,971,827, 546 | +1, +352,441, +154 | 1 | 3, 1 |
| pandas-68090 | yes, 26, 1,272,852, 470 | yes, 20, 1,116,851, 193 | -6, -156,001, -277 | 1 | 3, 6 |
| pandas-68278 | yes, 7, 284,527, 152 | yes, 10, 451,805, 237 | +3, +167,278, +85 | 0 | 2, 2 |
| pandas-68945 | yes, 25, 1,163,538, 157 | yes, 18, 879,481, 102 | -7, -284,057, -55 | 1 | 2, 1 |
| pandas-69779 | no, 13, 602,864, 197 | no, 10, 458,250, 115 | -3, -144,614, -82 | 1 | None, 1 |
| pandas-69924 | yes, 34, 2,146,112, 398 | yes, 22, 1,354,865, 505 | -12, -791,247, +107 | 1 | 2, 5 |
| pandas-70734 | no, 11, 539,895, 66 | no, 29, 1,970,733, 273 | +18, +1,430,838, +207 | 1 | 1, 2 |
| pandas-71232 | yes, 8, 326,620, 34 | yes, 6, 245,941, 29 | -2, -80,679, -6 | 0 | 2, 1 |
| **9 pairs** | 7 solved, 167, 8,526,361, 1977 | 7 solved, 157, 9,018,356, 2079 | -10, +491,995 (+6%), +102 (+5%) | | |

Cost as Claude Code reports it, USD: grep 0.172, codemem 0.193.


**6. home-assistant at L0 is done too (16 runs, none discarded); L1 runs now.** Solved: `grep` 6 of 8, `codemem` 7 of 8. Tokens 2,894,372 against 3,955,213 (+37%), agent seconds 685 against 1,003 (+46%), turns 66 against 81. The agent did not call `search_code` in any of the 8 `codemem` runs. Builds ran beside all 16 runs and stream 1 beside most of their seconds (95% and 85%). The full report comes when its three levels are done, by our estimate at about 15:00 UTC with the old preparation step.

## Checked

- The tables come from `early-report.py` on the PC over the 54 `run.json` files; the sums of the three levels were added by hand and checked two times.
- The archive was unpacked and searched before the upload: no token pattern, neither real token, no account id, not Andrew's name or addresses.
- The archive holds 56 records (54 and the 2 set aside) and 3 set-aside folders without a record (attempts that were stopped during preparation, before the agent started).

## Left

- The build times of the check run in the marks file.
- home-assistant L1 and L2; ruff runs in stream 1 since 08:29 UTC.
- Your answer on the new preparation step (our entry of 08:06 UTC, draft pull request #92).

## Blocked on, or needed from others

- **Andre:** the answer on the preparation step. Nothing else.

## Next

- The report on home-assistant, then on ruff.
