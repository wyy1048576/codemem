# For track A, from Andre: yes to the copy-and-swap step (PR #92), with one `sync` that we added on your branch. Sonnet starts when its stream's Haiku steps are done, and gets fewer tasks, not none, if time or disk runs short

- **Track:** shared: from the lead, for track A. Answers your entries of 08:06 UTC (the preparation step) and 09:47 UTC (point 3, Sonnet)
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 11:18 UTC
- **Work package:** A12 (the runs), A4 (the integrity checks)
- **Branch, commits, pull request:** branch `prep-copy-swap`: our commit `8649223` on top of your `2140d16`, draft pull request #92. Not merged; `main` is at `739fbe3`

## Done

**1. The preparation step: yes, from the next batch of each stream, once the points below are done** (Andre).

- **We added one commit on your branch, `8649223`: a `sync` right before `mark ready`, in every setup.** Please read it before you use the branch.
  - **Why.** The copy and swap leaves its writes in memory, and the kernel writes them to disk in the seconds after the step ends. A `codemem` run then waits for codemem before its clock starts (12.0 s median in the pandas archive, 10.5 to 30.8 s), and a `grep` run starts its agent at once. So without the sync, only `grep`'s agent would start while the disk is still busy. The old step synced every file, so it left nothing to write.
  - The step is marked `sync` in `prep.txt`, so its seconds are in `prep_steps_s`, outside the agent's clock. It also covers the copy of codemem's index.
  - The eval tests pass on our Mac: 932 passed, 25 skipped (20 need ripgrep, which this Mac lacks; 4 need codemem installed; the hard-link test needs GNU cp, as on yours).
- **Compare the old and the new step entry by entry,** as you did for pandas and playwright, on one task each of home-assistant, ruff, duckdb and kubernetes, and post the result. If anything differs beyond the folders' link counts and entry sizes that you found, keep the old step and tell us.
- **Then mark #92 ready. Andre merges it into `main`,** so that every record's `cmeval_commit` is on `main`.
- **Then switch at the start of a batch,** so that both setups of a pair get the same method.
- **If this cannot be done before the Mac goes off,** keep the old step and switch when the Mac is back.
- **vscode** goes ahead with the new step, in two halves, when its tasks are ready, as you proposed.

**2. Sonnet** (Andre).

- **It does not wait for all of Haiku's repetition 1.** A stream starts its Sonnet steps when its own Haiku steps are done, as you propose.
- **Haiku's repetitions matter, but the runs must include Sonnet.** If time or disk runs short, Sonnet gets fewer tasks, not none:
  - in each of its four repos, one hard task and one easy task, at L0, L1 and L2, in both setups;
  - number 1 of each tier, and number 1 of the medium tier where a repo has no hard task;
  - the easy task shows what Sonnet does from memory, the hard one where a search should matter most;
  - the time saved goes to Haiku's repetitions.
- Decide a cut before the repo's first Sonnet batch, and post it. A repo whose Sonnet runs have started is finished as planned.

**3. Please confirm in your next entry** that the runner and the watchdog change nothing inside a run: the same eval commit, setups, prompts, limits and grading. They only choose what runs next and start jobs again. Until the switch, the records should still show `cmeval_commit` `739fbe3` and the step `chown`; we check that in the next archive.

## Checked

- Branch `prep-copy-swap` at `8649223` merges into `main` without a conflict. It changes only the run script and its tests (`eval/src/cmeval/e2e_run.py`, `eval/tests/test_e2e_run.py`, `eval/tests/test_e2e_block.py`), not codemem.
- `main` is unchanged, at `739fbe3`.

## Left

- Track A: the four comparisons, then #92 marked ready.
- Andre: the merge of #92.

## Blocked on, or needed from others

- **Track A:** read `8649223`; the four comparisons; #92 marked ready; the confirmation of point 3.

## Next

- Andre merges #92 when it is marked ready.
