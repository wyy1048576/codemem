# Track A: home-assistant has 7 fair tasks with prompts, its recipe is fixed, and the check run stays armed for 01:00 UTC

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-27 22:21 UTC
- **Work package:** A9 (tasks), A12 (the runs)
- **Branch, commits, pull request:** `main` at `414e2b1`. Merged since 19:35 UTC: #80 (screen of home-assistant), #81 (home-assistant recipe), #82 (prompts of home-assistant, run sample)

## Done

**1. home-assistant: the first screen.**

| Label | Valid | Fair |
|---|---|---|
| easy | 11 | 5 |
| medium | 13 | 1 |
| hard | 9 | 1 |
| all | 33 | 7 |

- Rules version 1, two reads of each task, a third read for 2. Reads 1 and 2 agree on 31 of 33 (kappa 0.82). File `eval/tasks/screen/ha1.jsonl`.
- Frequent reasons for unfair: the issue offers two fixes and the tests need one; an exact key, version or message; a new name that the tests import.
- In the tiers of the run plan: **6 easy, 1 medium, 0 hard.** The run sample (`run-sample-v1.jsonl`, same seed) now holds these 7. The rows of the other five repos did not change.
- L1 and L2 for the 7: `eval/tasks/vague-ha1-v3.jsonl`, rules version 3, one writer and one review (4 ok, 3 corrected). No "Done when" line.

**2. A fault of our home-assistant recipe, fixed (#81).**

- 18 of the first 57 candidates failed in the dependency step: `surepy` pins `rich<11`, `pytest-codspeed` needs `rich>=13.8.1`.
- The repo's CI passes because uv reads `[tool.uv] override-dependencies` of `pyproject.toml` at the repo root. Our step ran with only the requirement files.
- Fix: `pyproject.toml` is one of the files of the dependency step. Two of the 18 were tried with it and are valid.
- Cost: every home-assistant image has a new fingerprint. The 7 fair tasks are validated again now; the 16 other install failures follow.

**3. The disk of the PC.**

- The WSL disk file grows with every build round and shrinks only when WSL is shut down. Four compactions today.
- A second guard now stops only the image builds (at 280 GB). The first guard (300 GB) stops everything. So a build cannot stop a run.
- A vscode build beside two home-assistant builds fills about 47 GB in 21 minutes. **vscode and trino builds wait until the check run is under way.** vscode admission so far: 6 valid of 6 with the recipe of #79. trino: 1 valid of 1.

## Checked

- The run sample: `diff` of the rows of the other repos before and after: no change. 957 tests pass.
- 182220 keeps the name of an inner backup archive in L1 and L2. The fix must match it and the hidden tests use it. At the base commit a text search finds the name only in one comment of a test file.
- After each compaction: the check run is armed again (last time 22:15:39 UTC), both guards run, and the sessions stay alive with the SSH connection closed.

## Left

- home-assistant is short in the medium and hard tiers (1 and 0). In validation now: the hard-tier file (43 candidates) and 41 new candidates of a second seeded sample.
- Indexes and blocks of the 7 home-assistant tasks: in work (codemem `463171c`).
- vscode and trino: admission, then a sample, a screen, prompts. They will not be ready for Haiku's first repetition tonight.

## Blocked on, or needed from others

- **Andre:** the lock hash at 00:30 UTC in this log. If it is not `463171c`, we build the indexes and blocks of the six check tasks again before 01:00 UTC.
- **Andre and Wilson:** a login token each for the rotation, if you agree (Andrew has the message).

## Next

1. 00:30 UTC: read the lock hash. 01:00 UTC: the check run (48 runs), then its report.
2. If it passes: Haiku's repetition 1 on pandas, ruff, duckdb, playwright, kubernetes, and home-assistant when its 7 tasks are valid again and indexed.
