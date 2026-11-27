# Track A: where we are, the full to-do list, and what runs now

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-27 09:10 UTC
- **Work package:** A1 (the task supply), and the runs
- **Branch, commits, pull request:** none. `main` at `8a8dbee` for the eval; codemem `463171c` to run

## Done

**Running now on the PC**
- Ruff group 1 (`val.sh ruff 2 --sample 60`): 21 tasks checked, 20 valid, 1 invalid (27429: no test went from failing to passing). It stops at about 15 new tasks, in about 15 minutes.
- The disk guard. The disk file stays at 192 GB (limit 300). New builds reuse the space of the 92 pandas images, which are now in the archive on D:.

**The list, in order**

| # | Step | State |
|---|---|---|
| 1 | Andre's four runs on the PC | Done. Runs 3 and 4 posted 06:20 UTC; both checks PASS |
| 2 | Ruff, group 1 | Ends soon. 20 valid; by run tier: 13 easy, 7 medium |
| 3 | Andre's thread script for the compact index | Waits for the script (due 09:30 UTC). Runs on the quiet PC when the ruff group ends |
| 4 | Screen of the 20 valid ruff tasks (two reads, third on a disagreement) | Next. Needs no PC |
| 5 | Test of the text-only pre-screen (point b): the 112 screened duckdb and kubernetes tasks, read again without the test lists | Next, beside step 4. Needs no PC |
| 6 | Hard tier (point c): build the `-large.jsonl` candidates whole; pandas, duckdb, playwright first; screen; stop at 4 fair a repo | After step 3 |
| 7 | Medium tier where it is short: pandas (3 of 6), kubernetes (2 of 6) | After step 6. More pandas candidates need Andrew's go |
| 8 | Admission checks of vscode, home-assistant, trino; then their candidates | After step 7 |
| 9 | Check run: 24 Sonnet runs on `463171c`, indexes built again with it | Waits for Andrew |

**Fair tasks per run tier now** (need 8 easy, 6 medium, 4 hard, with spares)

| Repo | easy | medium | hard |
|---|---|---|---|
| pandas | 14 | 3 | 0 |
| playwright | 20 | 8 | 0 |
| duckdb | 30 | 11 | 0 |
| kubernetes | 18 | 2 | 0 |
| ruff | 13 valid, not screened | 7 valid, not screened | 0 |

**Decided today:** points a to e of Andre's entry of 08:45 UTC (our answer of 09:02 UTC). The commit to run is `463171c`; the PC's run checkout is on it.

## Checked

- Counts from `val-ruff.log` and `diskguard.log` on the PC, and from `eval/tasks/screen/`.

## Left

- Steps 3 to 9 above.

## Blocked on, or needed from others

- Andre: the thread script and its location in this log, by 09:30 UTC.
- Andrew: the check run (step 9), more pandas candidates (step 7).

## Next

- Track A: stop ruff group 1, run Andre's script, start steps 4 and 5.
