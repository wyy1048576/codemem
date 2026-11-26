# Track A: your entries since 09:54 UTC are read (late, our fault); `uv sync` works on the PC and the Mac; the grep arm on the vague tasks; what runs now

- **Track:** A. Answers the shared entries of 09:54, 09:56, 10:37, 11:20, 11:32, 13:46, 13:52, 13:53, 14:17, 14:24, 15:44, 15:48, 16:11, and Wilson's of 13:07 to 14:40
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-26 19:00 UTC
- **Work package:** A1, A2, A5, A9
- **Branch, commits, pull request:** `main` at `09c4ef0`. Ours since the last entry: #46 (vague prompts for the 45 fair tasks), #47 (rebuild of task images, per-test grader check), #48 (step counts version 3)

## Done

**0. We missed your entries.** Our session pulled the log at 13:20 UTC and did not read what was new. So the entries from 09:54 on reached us only at 18:45 UTC. They are all read now. The lock date (Fri Nov 27, 20:00 UTC) is noted; please ignore our question about it in the entry of 13:20.

**1. `uv sync`: works.**
- PC (Linux, x86-64, WSL 2): `uv sync` on `main` at `09c4ef0` installs FAISS 1.16.0; `import faiss` gives 1.16.0.
- Mac: Apple silicon on macOS 26.5, so the new FAISS has a build for it.
- The codemem commit of our runs so far is `041124e` (all Haiku runs, also today's). No run with `8d86da8` or `09c4ef0` yet: there was no check run.

**2. Andre's measurements, state.**
- Entry of 11:32, runs 1 and 2 (tests on Linux, index sizes): started at 18:50 UTC, beside two validations. The result follows in its own entry.
- Runs 3 and 4 (cost against size, the same results on real indexes): these are timings, so they need a quiet machine. The PC queue is held: when the two running validations end, runs 3 and 4 go first, then the queue goes on.
- Entry of 09:54, points 1 and 2 (the replay at 5, 10, 20, 30 and 50 results, and the size of a search result in our runs): the tool is being written; it runs on the PC after runs 3 and 4.

**3. What track A has, in your tiers** (today's labels kept; easy tier = labels `easy` and `medium`, medium tier = label `hard`):

| Repo | Validated | Valid | Fair, label `easy` | Fair, label `medium` | Fair, label `hard` (medium tier) | Hard tier | Fair tasks with L1 and L2 |
|---|---|---|---|---|---|---|---|
| pandas | 100 | 92 | 9 | 5 | 3 | not collected | 17 of 17 |
| playwright | 60 | 49 | 11 | 9 | 8 | not collected | 28 of 28 |
| duckdb | 39 of 60 so far | 37 | screen not started | | | not collected | 0 |
| kubernetes | 28 of 60 so far | 26 | screen not started | | | not collected | 0 |
| ruff | admitted (8 of 10) | | | | | not collected | 0 |

- **Warning: pandas has 3 fair tasks in the medium tier, against 4 wanted and 6 to stop at.** Only 8 more candidates with the label `hard` exist. 197 pandas candidates are not validated; Andrew decides if they are.
- All five required languages have an admitted repo: pandas, playwright, duckdb (9 of 10), kubernetes (10 of 10), ruff (8 of 10). Not checked yet: home-assistant, vscode, trino, airflow, vllm.
- **The second collection (15 files, 600 lines) for the eight repos has started** (no container). The tier becomes a new label beside today's.

**4. The grep arm on the 10 vague pilot tasks** (Haiku, 1 run each, codemem `041124e`; behaviour, not a result):

| Level | Arm | Completed of 10 | codemem called | Median turns | Median tokens (M) |
|---|---|---|---|---|---|
| L0 | `grep` (Nov 25) | 6 | 0 | 15 | 0.69 |
| L0 | `tool` | 7 | 4 | 21.5 | 1.12 |
| L0 | `tool`, thinking summaries off | 7 | 5 | 13.5 | 0.66 |
| L1 | `grep` | 8 | 0 | 26 | 1.32 |
| L1 | `tool` | 8 | 9 | 21 | 1.23 |
| L2 | `grep` | 8 | 0 | 26 | 1.21 |
| L2 | `tool` | 7 | 10 | 19.5 | 0.94 |

Completion is the same in both arms. With codemem the median run is 5 to 6 turns shorter at L1 and L2. The gold file is opened by turn 2 or 3 in every cell. Two of the 10 tasks are unfair by the new screen (playwright 42672, pandas 70742).

**5. Your other points.**
- **The 13 prompt corrections (15:44, 15:48):** a review against the issues and tests is in work; we take the rows into a file of our own (`vague-b7-v3`), with the reason per row and the credit, and post what we took. The four rule sentences are reviewed with them.
- **Full records of every run:** nothing is pruned, and task images go first when disk is short (they do already). `cmeval e2e turns`, one row per turn, is in work.
- **Wilson, grading a saved diff:** `cmeval e2e grade RECIPE --tasks FILE --id TASK --patch DIFF` is in work. It needs the task's image on the PC; images of valid tasks are removed after validation now and built again with `cmeval generate --rebuild`.
- **Step counts are version 3 now** (#48): old runs must be counted again (`cmeval e2e recount`) before their counts are compared.
- **The line in `e2e_run.py` (11:20) and the pins (14:17):** read; they are on `main`. No comment.

## Checked

- `uv sync` and the FAISS version: run on the PC at 18:45 UTC.
- The table of point 4: `run.json` of 70 runs on the PC, counted again with step counts version 3.
- Not checked: the full test suite on Linux (run 1 is in progress).

## Left

- **Decisions that are Andrew's, as owner of the eval, before we act on the entry of 13:52:** the new order of the admission queue (vscode and home-assistant before kubernetes and trino; airflow and vllm as reserve), the stop rule per tier, and the check run of 24 Sonnet runs. He has the entry. Until he answers, the queue keeps its order: ruff 60, then the admission checks.
- Runs 3 and 4, the replay, the screen of duckdb and kubernetes.

## Blocked on, or needed from others

- **Disk on the PC:** 160 GB free on the drive that holds Docker's data. Images are removed after validation and built again when needed; a trial on 3 playwright images gave the same result for every test. A larger disk is Andrew's decision.
- **Andre:** nothing.

## Next

- Track A: the result of runs 1 and 2; then runs 3 and 4 and the replay; the table for duckdb and kubernetes after their screen.
