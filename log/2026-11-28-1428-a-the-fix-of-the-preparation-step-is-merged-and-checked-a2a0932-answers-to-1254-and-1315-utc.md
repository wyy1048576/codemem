# Track A: the fix of the preparation step is merged and checked (`a2a0932`, #94). Answers to your entries of 12:54, 13:15 and 13:37 UTC. No run uses it yet

- **Track:** A, for the lead. Follows our entry of 13:12 UTC (the fault)
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 14:28 UTC
- **Work package:** A12 (the runs), A4 (the integrity checks)
- **Branch, commits, pull request:** PR #94 merged with squash: `main` = `a2a0932` (equal to the branch at `588f734` that you read, empty diff). Also on `main`: #93 `1b24032` (score only, see the end)

## Done

**1. The fix, as you read it at `588f734`.** The script does not change what git does. It waits until no process of the container is `git` (at most 600 s, else `git_busy` and the old step), copies, compares the sorted names of the copy and the original (else `copy_differs` and the old step), and only then swaps. Tests: 971 passed, 5 skipped.

- **One change against our plan of 13:12 UTC: the clean-up is not put in the foreground.** We measured that it would change the repo in three of the four repos (next point), so the fix only waits.

**2. What git's clean-up does after the commit, measured in containers (4 CPUs, as the runs).** This is also the answer to your question of 13:15 UTC, point 3.

| Repo (one task) | git | Loose objects | What happens after the commit | Background time |
|---|---|---|---|---|
| pandas 69779 | 2.39.5 | 2,705 | nothing: below git's limit of 6,700 | about 10 ms |
| playwright 43316 | 2.39.5 | 3,256 | nothing: below the limit | about 10 ms |
| ruff 27689 | 2.39.5 | 11,052 | the refs are packed; the background part ends at once; the objects stay loose; `.git/gc.log.lock` stays | about 10 ms |
| duckdb 24011 | 2.39.5 | 16,404 | as ruff | as ruff |
| kubernetes 140607 | 2.39.5 | 30,040 | as ruff | as ruff |
| home-assistant 183382 | 2.47.3 | 32,022 | all objects go into one pack, in the background | 10.0 and 10.5 s (two tries) |

- **With the old step the clean-up always ended before the agent's clock.** Only home-assistant has background work: about 10 s, against a `chown` of 228 to 708 s in its 44 records. pandas, the case you named, has none.
- So the clean-up never shared the CPUs with an agent's first seconds, in either setup.
- If the clean-up ran in the foreground (`gc.autoDetach=false`), ruff, duckdb and kubernetes would end packed, which they never were with the old step. That is why the fix leaves git alone.

**3. The comparisons again, with the commit in front of both steps** (your point 5). Old: the real start of the run script of `739fbe3`. New: of the fix. Two containers of the same image, 4 CPUs.

| Task | Objects after the step, both sides | Old step (chown) | New step (wait, copy, check, swap) | Result |
|---|---|---|---|---|
| home-assistant 183382 | 32,024 in 1 pack | 479 s | 44 s | same |
| ruff 27689 | 11,054 loose | 367 s | 8 s | same |
| duckdb 24011 | 16,453 loose | 412 s | 52 s | same |
| kubernetes 140607 | 30,040 loose | 660 s | 33 s | same |

- **Compared, and equal in all four:** every entry of the work tree (name, size, mode, type, link target, modification time, owner; link count of every file); the hash of every file; the count of loose and packed objects; the set of all object ids; `git fsck` (exit 0, no line); the refs; the files of `.git` outside `objects`; `git status`, `git diff`, and the diff against the base commit, as the agent's user.
- **Different, as known:** the link count of a folder, and the entry size of some folders (3 to 13 per repo).
- **Different from run to run with either step, so not compared:** the id of the run's own commit (its time is in it), the time of the folders that this commit changes, and the bytes of the pack (2 KB of 36,710 in home-assistant).
- Scripts and listings: `~/.cmeval/logs/prepcmp3/` on the PC. Window: 13:31 to 14:02 UTC.

**4. Two check pairs with the fix, through `batch.sh` and the new checkout** (home-assistant 183382, L1 and L2, Haiku; own run ids `prepcheck3-haiku-homeassistant-L1` and `-L2`; not runs of the sample). home-assistant is the image where the clean-up really runs in the background.

| Run | Ended | Preparation | `copy_swap` (with the wait) | `sync` | Setup check |
|---|---|---|---|---|---|
| L1, grep | finished, solved | 28.5 s | 25.0 s | 2.2 s | ok |
| L1, codemem | finished, solved | 111.3 s (codemem warm 65.2) | 30.0 s | 1.6 s | ok, block in the first message |
| L2, grep | finished, solved | 35.6 s | 29.1 s | 4.6 s | ok |
| L2, codemem | finished, solved | 92.2 s (codemem warm 37.6) | 26.6 s | 1.3 s | ok, block in the first message |

- **Your two points of 13:37 UTC:** no `git_busy` and no `copy_differs` in any of the four; `copy_swap` is 25 to 30 s, of which about 10 s is the wait for git. So bash takes the finished git processes away at once, and no git process stays in this image.
- In the comparisons of point 3 the wait was 0 to 1 s in the three repos with git 2.39.5.

**5. Your questions of 12:54 UTC.**

1. **Can the difference reach the agent?** Counted over all 149 records of Haiku and Sonnet so far (check run included): 1,807 Bash calls. 7 have `ls -l` in some form. None has `stat`, `du`, `tree`, or `find` with `-printf` or `-ls`.
   - 5 of the 7 list files (the same after both steps; 2 of them "no such file"). 1 lists a folder under `/tmp`.
   - **1 lists a folder of `/testbed`:** playwright 42260, `codemem`, L2: `ls -la packages/injected/lib | head -5`. Two folder lines (`.` and `..`). With the new step their link count would be the real one, not 1. Nothing else of that output would differ.
   - So: yes, it can, in about 1 of 150 runs, as one number in each folder line of a long listing.
2. **What else differs between the checkouts?** For a run: #92 and #94 only (`eval/src/cmeval/e2e_run.py`). `a2a0932` also has #93, which changes the score (`e2e_score.py`, new `prices.py`) and nothing that a run imports. Packages: `uv pip freeze` is equal in both checkouts.
3. **What the old step costs in the repos that began with it** (mean `chown` in the records less the new step: ruff 246 - 8 s, home-assistant 468 - 35 s, pandas 49 - 3 s):

| Where | Runs | Stream hours |
|---|---|---|
| Now: the rest of ruff (L1, L2, and task 27700) | about 36 | 2.4 |
| Now: home-assistant's hard task | 6 | 0.7 |
| Sonnet's pandas | 54 | 0.7 (0.2 if nothing runs beside it) |
| Haiku's repetitions 2 and 3: pandas | 108 | 1.4 |
| Haiku's repetitions 2 and 3: ruff | 108 | 7.1 |
| Haiku's repetitions 2 and 3: home-assistant | 108 | 13.0 |
| **All** | | **about 25** |

   - Two streams run, so 25 stream hours are about 12.5 hours of the clock. About 65 hours are left to the freeze.
   - Our view, for your decision: the two repetitions of home-assistant and ruff are where it costs (20 of the 25 hours). A repetition is its own unit, and a record names its method. If the step may change anywhere inside a repo, then at the start of repetition 2.

**6. One question: has playwright begun?** Your list of 12:54 UTC puts it with the repos that have not. But the check run made 12 Haiku and 12 Sonnet records of playwright (3 tasks, L0 and L2) with the old step, and the runs skip those pairs. **Until you say otherwise we treat playwright as begun: it keeps the old step.** Cost: 97 - 15 s a run, about 1.8 stream hours for Haiku's repetition 1, 1.3 for Sonnet, 4.1 for repetitions 2 and 3. Stream 2 reaches playwright at about 15:20 UTC.

**7. The plan for the change.** `batch.sh` now takes the checkout per repo, so a repo keeps one method.

- duckdb, kubernetes and vscode begin with `a2a0932` (checkout `codemem-runs3` on the PC). duckdb starts at about 22:30 UTC (stream 1), kubernetes after playwright (stream 2).
- pandas, ruff, home-assistant and playwright stay on `739fbe3` (`codemem-runs`).
- **The line for duckdb and kubernetes is not written yet: it waits for Andrew's own word this morning.**
- The faulty checkout (`da25c74`) is removed from the PC.

**8. Also on `main`: #93, score only** (`1b24032`). A run at the turn or time limit counts as not completed (new column "at limit"); a cost column from your price table with `total_cost_usd` beside it and in the paired difference; the "used" columns count only the agent's own codemem calls (new: the share of runs with the block, and with an own `search_code` call); a codemem run without its block counts as discarded. On 78 real records the table cost equals the reported cost (largest difference 2.8e-17 USD), and no request had a prompt over 100,000 tokens.

## Checked

- The merge equals the branch that passed every check above (empty diff `588f734` to `a2a0932`); the checkout on the PC is at `a2a0932` and its generated script has the wait, the name check and the unchanged commit line.
- `prep_steps_s` of the check records has `copy_swap` and `sync`; `cmeval_commit` is `a2a0932`.

## Left

- The line for duckdb and kubernetes in the switch file, after Andrew's word.
- The check records (`prepcheck-*`, 3 runs with the fault's race; `prepcheck3-*`, 4 runs) go into one archive on the release, marked as checks.

## Blocked on, or needed from others

- **Andre:** point 6 (playwright), and your decision on point 5.3 when you have it. Neither holds a run up.
- **Andrew:** yes or no to duckdb, kubernetes and vscode on the new step.

## Next

- Andrew, with Claude Code: the switch line when Andrew agrees; the hours of the drive, posted before the Mac goes off; the ruff report at about 21:00 UTC or when the Mac is back.
