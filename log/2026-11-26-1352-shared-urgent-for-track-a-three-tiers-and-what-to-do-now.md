# URGENT, for track A, from Andre: read this before your next step. The difficulty tiers have changed, a second collection has to start now, and four entries of today were missed

- **Track:** shared, for track A. Andre tells Andrew directly as well
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 13:52 UTC
- **Work package:** A1, A2, A9 (which tasks are run, and in what order)
- **Branch, commits, pull request:** `andre/run-plan` (`dd5880a`): the page `docs/plan/runs.md`. Andre opens the pull request

## Done

**Track A's session: please stop at the next safe point and read this.** It changes what you
check and collect next. Your entry of 13:20 UTC still asks for the lock date, so several of our
entries did not reach you.

**1. What to read, in this order.**

1. **09:56:** codemem's design is locked on **Friday Nov 27 at noon Pacific (20:00 UTC)**.
2. **10:37:** all of track C is on `main`: run `uv sync` (FAISS 1.16.0), and say if it fails.
3. **11:20:** three new defaults, and one line in `eval/src/cmeval/e2e_run.py`.
4. **11:32:** four runs on the PC, for when it has room.
5. **13:46:** the project's goals and the runs. **Its levels and counts are replaced by point 2
   below.**
6. **The page to work from:** `docs/plan/runs.md` on the branch `andre/run-plan`. It is up to
   date with this entry.

**2. There are three tiers now, and they are not the labels in the task files** (Andre, after
the entry of 13:46).

| Tier | The real fix changes | The label in today's task files | Tasks per repo |
|---|---|---|---|
| **easy** | at most two files and 100 lines | `easy` and `medium` | 6: three of each label |
| **medium** | three to five files, or 101 to 200 lines | `hard` | 4 |
| **hard** | 6 to 15 files, or 201 to 600 lines | none: not collected yet | 4 |

- **Why:** no task on `main` has a fix of more than 5 code files or 200 lines, because the
  collector stops there (`max_code_files`, `max_code_lines`). Requests that touch many files are
  what codemem is meant for. There is no fourth level: what the entry of 13:46 called "large" is
  the hard tier.
- **Every repo that is run gets a hard tier.** A repo with fewer than 4 fair hard tasks runs
  more medium ones instead, so that medium and hard together are 8.
- **Please keep today's label of each task as it is and add the tier as a new label.** Then the
  tables written so far keep their meaning.
- **Your counts of 13:20, in tiers:** pandas has 14 fair easy tasks and 3 medium; playwright 20
  and 8. Neither has a hard task yet.

**Who runs what, per repo,** always in both setups:

| Model | Tasks | Prompts | Repetitions |
|---|---|---|---|
| Sonnet | all 14 | L0, L1, L2 | 3 |
| Haiku | 6: numbers 1 and 2 of each tier | L0, L1, L2 | 1 |
| Opus | 6: number 1 of easy, number 1 of medium, the 4 hard ones | L0, L2 | 1 |
| Open models (a rented GPU, started by Andre: nothing of the PC) | the 6 easy ones; 3 medium as a probe | L0, L1; the probe at L0 | 3; the probe 1 |

**3. What to do now, in this order.**

1. **`git pull` and `uv sync`.** Post whether it worked.
2. **Start the second collection, for the hard tier:** the same collection again with
   `max_code_files = 15` and `max_code_lines = 600`, nothing else changed, for the eight repos
   of the ranking: pandas, ruff, duckdb, playwright, vscode, home-assistant, kubernetes, trino.
   It needs no container, so it can run beside everything else.
3. **Change the order of the admission queue to the ranking:** ruff, duckdb (admitted), vscode,
   home-assistant, then kubernetes and trino. airflow and vllm are the reserve: they are built
   only if a repo above them cannot be.
4. **Check candidates per repo only until:** 8 fair tasks in the easy tier (4 of each label), 6
   in the medium tier, 4 in the hard tier. Then stop that tier.
5. **Prepare the check run** (§6 of the page): 24 Sonnet runs on pandas and one more repo, with
   the locked codemem. No full batch starts before it has passed.
6. **Post:** whether `uv sync` works; the table of fair tasks per repo and tier; the check run's
   five points and the first Sonnet numbers.

**4. What does not change:** the screen and its rules, the vague prompts, the runner, and every
task you have validated and screened.

## Checked

- The counts in tiers are your own of 13:20, added up. The limits of the collector are read from
  `eval/configs/fresh-*.toml` on `main`, and what they removed from `eval/tasks/fresh-*.meta.json`:
  458 fixes in the eight repos (pandas 19, trino 8, kubernetes 17, duckdb 22, playwright 35,
  home-assistant 49, ruff 55, vscode 253).
- Not checked: how many of those are within 15 files and 600 lines, and how many will be valid
  and fair.

## Left

- Nothing on our side for this entry.

## Blocked on, or needed from others

- **Andrew:** the six steps of point 3. Steps 1 and 2 first.

## Next

- Track C's session: its last branches, the note for track A's agents, the audit of pull
  request #45.
