# Track A, report: home-assistant is done for Haiku, repetition 1 (48 runs of 8 tasks, none discarded). The hard task runs now. Every run has its marks

- **Track:** A, for the lead. The second report of repetition 1 (the first: pandas, 08:32 UTC)
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 14:15 UTC
- **Work package:** A12 (the runs)
- **Branch, commits, pull request:** none. Records: release `run-records`, files `haiku-rep1-homeassistant.tgz`, `haiku-rep1-homeassistant-marks.tsv`, `pressure-to-1405.log`

## Done

**The 8 easy and medium tasks of home-assistant ran at L0, L1 and L2 in both setups: 48 runs, 0 discarded, 0 flagged, none at a limit.** Eval `739fbe3`, codemem `463171c`, the old preparation step (`chown`) in all 48. One repo of one repetition is not a result.

| Level | Solved, grep | Solved, codemem | Turns, grep / codemem | Processed tokens, grep / codemem | Agent seconds, grep / codemem | Cost as reported, USD |
|---|---|---|---|---|---|---|
| L0 | 6 of 8 | 7 of 8 | 66 / 81 | 2,894,372 / 3,955,213 (+37%) | 685 / 1,003 (+46%) | 0.072 / 0.098 |
| L1 | 8 of 8 | 7 of 8 | 108 / 92 | 5,337,115 / 4,720,729 (-12%) | 1,024 / 886 (-13%) | 0.116 / 0.106 |
| L2 | 7 of 8 | 5 of 8 | 113 / 110 | 5,356,216 / 5,762,659 (+8%) | 1,134 / 1,142 (+1%) | 0.113 / 0.129 |
| **All** | **21 of 24** | **19 of 24** | **287 / 283** | **13,587,703 / 14,438,601 (+6%)** | **2,843 / 3,031 (+7%)** | **0.301 / 0.333** |

- **The cost column is `total_cost_usd`.** The score now has the cost from your price table beside it (#93, on `main`); on the 78 records checked the two are equal.
- **Seconds: read them with the marks.** 47 of the 48 runs had image builds, the other run stream, or both beside them.
- **Tasks where the setups differ:**
  - 180438: `grep` solved it at L1 and L2, `codemem` at no level (11 to 17 turns each).
  - 184035: `codemem` did not solve it at L2; all other runs of it are solved.
  - 184675: at L0 only `codemem` solved it (`grep` stopped after 4 turns with an empty change); at L1 both; at L2 neither.
- **The agent's own searches:** `search_code` was called in 5 of the 24 `codemem` runs (L0 0, L1 3, L2 2), one call each. The block was in the first message of all 24.
- **First fix file opened at turn 1:** `grep` 3 of 24, `codemem` 13 of 24 (L0 2 against 6, L1 1 against 3, L2 0 against 4). In 2 `grep` runs at L0 (180391, 180560) the record shows no opened fix file although the run is solved. We have not read these two streams yet; it may be the known gap of the record (a file changed through a script).
- **Checks over the 48 records:** all ended `finished`; the proxy's token count equals the agent's in 48 of 48; mount proof ok in 24 of 24; no search fell back; host load at the start of a run 4.2 to 56.8.
- **Seat:** all 48 runs on seat 2: 98 agent minutes, 0.63 USD as reported. No usage limit. Seat 1 is at 18% of its week (12:31 UTC).

**The full tables, pair by pair:**

### haiku-homeassistant-L0: 16 records, 0 discarded

| Task | grep: solved, turns, tokens, s | codemem: solved, turns, tokens, s | codemem minus grep: turns, tokens, s | searches by the agent | first gold file opened at turn (grep, codemem) |
|---|---|---|---|---|---|
| core-180391 | yes, 8, 329,608, 41 | yes, 7, 311,483, 54 | -1, -18,125, +13 | 0 | None, 1 |
| core-180438 | no, 9, 405,158, 161 | no, 15, 809,401, 311 | +6, +404,243, +149 | 0 | 2, 1 |
| core-180560 | yes, 5, 195,101, 78 | yes, 8, 372,575, 116 | +3, +177,474, +37 | 0 | None, 1 |
| core-181276 | yes, 13, 534,642, 72 | yes, 18, 844,749, 157 | +5, +310,107, +85 | 0 | 2, 2 |
| core-182765 | yes, 7, 323,774, 76 | yes, 5, 238,748, 38 | -2, -85,026, -38 | 0 | 1, 1 |
| core-183382 | yes, 8, 335,392, 89 | yes, 7, 315,484, 126 | -1, -19,908, +37 | 0 | 2, 1 |
| core-184035 | yes, 12, 606,975, 138 | yes, 12, 634,072, 116 | +0, +27,097, -21 | 0 | 1, 1 |
| core-184675 | no, 4, 163,722, 30 | yes, 9, 428,701, 86 | +5, +264,979, +56 | 0 | 2, 2 |
| **8 pairs** | 6 solved, 66, 2,894,372, 685 | 7 solved, 81, 3,955,213, 1003 | +15, +1,060,841 (+37%), +318 (+46%) | | |

Cost as Claude Code reports it, USD: grep 0.072, codemem 0.098.

### haiku-homeassistant-L1: 16 records, 0 discarded

| Task | grep: solved, turns, tokens, s | codemem: solved, turns, tokens, s | codemem minus grep: turns, tokens, s | searches by the agent | first gold file opened at turn (grep, codemem) |
|---|---|---|---|---|---|
| core-180391 | yes, 10, 412,347, 40 | yes, 7, 306,131, 37 | -3, -106,216, -3 | 0 | 1, 1 |
| core-180438 | yes, 17, 890,824, 217 | no, 11, 622,289, 278 | -6, -268,535, +61 | 0 | 2, 3 |
| core-180560 | yes, 8, 333,440, 96 | yes, 9, 393,456, 92 | +1, +60,016, -4 | 0 | 2, 2 |
| core-181276 | yes, 16, 703,301, 127 | yes, 16, 769,638, 114 | +0, +66,337, -14 | 0 | 2, 2 |
| core-182765 | yes, 13, 639,685, 204 | yes, 10, 496,853, 62 | -3, -142,832, -142 | 0 | 2, 1 |
| core-183382 | yes, 10, 457,938, 77 | yes, 11, 569,090, 85 | +1, +111,152, +8 | 1 | 3, 2 |
| core-184035 | yes, 24, 1,467,251, 196 | yes, 12, 663,588, 96 | -12, -803,663, -100 | 1 | 2, 1 |
| core-184675 | yes, 10, 432,329, 67 | yes, 16, 899,684, 123 | +6, +467,355, +57 | 1 | 3, 2 |
| **8 pairs** | 8 solved, 108, 5,337,115, 1024 | 7 solved, 92, 4,720,729, 886 | -16, -616,386 (-12%), -138 (-13%) | | |

Cost as Claude Code reports it, USD: grep 0.116, codemem 0.106.

### haiku-homeassistant-L2: 16 records, 0 discarded

| Task | grep: solved, turns, tokens, s | codemem: solved, turns, tokens, s | codemem minus grep: turns, tokens, s | searches by the agent | first gold file opened at turn (grep, codemem) |
|---|---|---|---|---|---|
| core-180391 | yes, 9, 362,210, 48 | yes, 8, 361,638, 39 | -1, -572, -9 | 0 | 2, 1 |
| core-180438 | yes, 17, 863,152, 267 | no, 17, 945,855, 323 | +0, +82,703, +57 | 0 | 3, 1 |
| core-180560 | yes, 12, 506,392, 114 | yes, 12, 567,667, 109 | +0, +61,275, -6 | 0 | 3, 2 |
| core-181276 | yes, 18, 834,791, 149 | yes, 17, 786,993, 185 | -1, -47,798, +36 | 0 | 3, 2 |
| core-182765 | yes, 13, 651,172, 100 | yes, 9, 479,141, 62 | -4, -172,031, -38 | 0 | 2, 1 |
| core-183382 | yes, 12, 556,060, 78 | yes, 14, 677,778, 109 | +2, +121,718, +31 | 0 | 3, 1 |
| core-184035 | yes, 22, 1,161,387, 269 | no, 18, 1,199,507, 193 | -4, +38,120, -77 | 1 | 3, 2 |
| core-184675 | no, 10, 421,052, 108 | no, 15, 744,080, 122 | +5, +323,028, +15 | 1 | 3, 2 |
| **8 pairs** | 7 solved, 113, 5,356,216, 1134 | 5 solved, 110, 5,762,659, 1142 | -3, +406,443 (+8%), +8 (+1%) | | |

Cost as Claude Code reports it, USD: grep 0.113, codemem 0.129.

## Checked

- The archive has no login token, no name and no address (searched after unpacking). It has one folder `1.discarded-1/` without a record (181276, `grep`, L1): the attempt that was stopped in preparation when the stream moved to its runner at 09:36 UTC.
- `case-studies.md` read. No home-assistant case is in it yet. 180438 may be one: `codemem` fails it at all three levels.

## Left

- The hard task 175759 (`homeassistant-large`, 6 runs): it started at 14:01 UTC with the old step, as your rule of 12:54 UTC says. Its records come in their own archive.
- The check run's build times in the marks file (still owed).

## Blocked on, or needed from others

- None.

## Next

- Andrew, with Claude Code: the entry on the fix of the preparation step and your questions of 12:54 and 13:15 UTC; then the ruff report (ruff is at L1; about 20:00 UTC).
