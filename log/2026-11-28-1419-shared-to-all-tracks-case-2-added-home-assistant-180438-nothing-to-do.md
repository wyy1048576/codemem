# To all tracks: case 2 is in `case-studies.md`, home-assistant 180438. Nothing to do: keep it in mind when you analyse results

- **Track:** shared: from track C, to tracks A and B. No answer is needed
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 14:19 UTC
- **Work package:** the analysis of the results
- **Branch, commits, pull request:** `case-studies.md` on this branch (`worklog`)

## Done

**Case 2: home-assistant 180438** (Haiku, repetition 1). Track A suggested it at 14:15 UTC.

- codemem's 20 lines put the function to change first at every level. Yet codemem failed all three runs, and grep solved two.
- **The cause is the fix, not the finding.** grep's solved runs removed the port swap (11 lines). codemem's runs, and grep's at L0, added an HTTPS probe (80 to 85 lines), which the hidden tests fail.
- **This one task is the whole gap in solved tasks on home-assistant:** 21 against 19 with it, 19 against 19 without it.
- **A lean to watch:** codemem's changes outside tests were larger on home-assistant (larger in 12 of 18 pairs, p 0.24), but not on pandas.

## Left

- None.

## Blocked on, or needed from others

- None.

## Next

- Track C adds cases as the runs go on.
