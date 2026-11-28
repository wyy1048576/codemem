# Track A, report: home-assistant's hard task is done for Haiku, repetition 1 (6 runs, all solved). home-assistant is complete: 54 runs. The check runs of the preparation step are on the release

- **Track:** A, for the lead. Adds to our report of 14:15 UTC
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 15:06 UTC
- **Work package:** A12 (the runs)
- **Branch, commits, pull request:** none. Release `run-records`: `haiku-rep1-homeassistant-large.tgz`, `haiku-rep1-homeassistant-large-marks.tsv`, `prep-check-runs.tgz`

## Done

**Task 175759 (hard tier) at L0, L1 and L2 in both setups: 6 runs, 0 discarded, none at a limit, all 6 solved.** Eval `739fbe3`, the old preparation step, as your rule of 12:54 UTC says.

| Level | grep: turns, tokens, seconds | codemem: turns, tokens, seconds | codemem minus grep: tokens, seconds | Cost as reported, USD |
|---|---|---|---|---|
| L0 | 19, 1,033,206, 182 | 22, 1,367,996, 157 | +334,790 (+32%), -25 | 0.022 / 0.028 |
| L1 | 26, 1,486,821, 225 | 33, 2,290,886, 213 | +804,065 (+54%), -12 | 0.031 / 0.044 |
| L2 | 24, 1,362,375, 172 | 20, 1,155,541, 129 | -206,834 (-15%), -43 | 0.028 / 0.024 |

- `codemem` opened a fix file at turn 1 at every level, `grep` at turn 2. The agent made no `search_code` call of its own.
- **home-assistant with all 9 tasks:** 54 runs, 0 discarded; solved `grep` 24 of 27, `codemem` 22 of 27; processed tokens 17,470,105 against 19,253,024 (+10%); agent seconds 3,422 against 3,530 (+3%).
- **Marks:** every one of the 6 runs had image builds beside it, and 5 had the other run stream. Our two check pairs of the preparation step (14:05 to 14:22 UTC) ran beside the first of them; the marks count them as other runs.

**The check runs of the preparation step are on the release as `prep-check-runs.tgz`** (8 records, marked as checks in the notes): `prepcheck-*` with `da25c74` (3 finished runs and the run that was lost), `prepcheck3-*` with the fix `a2a0932` (4 finished runs).

## Checked

- Both archives searched after unpacking: no login token, no name, no address.
- The 6 records: all ended `finished`; the proxy's token count equals the agent's; block in the first message and mount proof ok in the 3 `codemem` runs.

## Left

- Stream 2 is in playwright now (old step, since we treat playwright as begun). Stream 1 is in ruff L1.

## Blocked on, or needed from others

- None new. Open from 14:28 UTC: playwright (begun or not), and the step for repetitions 2 and 3.

## Next

- Andrew, with Claude Code: the hours of the drive, posted before the Mac goes off; the ruff report after it.
