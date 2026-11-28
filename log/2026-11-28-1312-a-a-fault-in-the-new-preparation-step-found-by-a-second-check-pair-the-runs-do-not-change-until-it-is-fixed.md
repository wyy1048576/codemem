# Track A: a fault in the new preparation step, found by a second check pair. The runs do not change until it is fixed and checked again. No sample run used the new step

- **Track:** A, for the lead. Corrects our entry of 12:46 UTC (points 4 and 5)
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 13:12 UTC
- **Work package:** A12 (the runs), A4 (the integrity checks)
- **Branch, commits, pull request:** none yet. `main` is `da25c74` (#92) and has the fault; no run uses it

## Done

**The fault.** A second check pair (home-assistant 183382, L1, through `batch.sh` and the new checkout) lost its `codemem` run before the agent started: `rm: cannot remove '/testbed/.git': Directory not empty`, exit 5, the run discarded by the setup check. The `grep` run of the pair was complete.

**The cause: git's own clean-up runs in the background while the step copies the folder.**

- The run script removes the agent's configuration files with `git rm` and `git commit`, before the preparation step. It did this before #92 too.
- The repos in the images have only loose git objects and no pack: home-assistant 31,249, duckdb 16,404, ruff 10,897. Above 6,700, a commit starts `git gc --auto`, and git puts it in the background.
- Every repo has such files (pandas 1, ruff 5, home-assistant 13, playwright 24 or 25, duckdb 2), so the commit and the clean-up happen in every run.
- With the old step that did no harm: `chown` in place does not care what git writes meanwhile.
- With the new step it is a race: the clean-up writes pack files and deletes loose objects while `cp` copies `.git` and `rm` deletes it. The mild outcome is the one we saw: `rm` fails and the run is discarded. The bad outcome is a copy of `.git` with objects missing, without an error.

**Why the comparisons did not show it.** They ran the two steps on the image as it is, without the commit before them. That was a gap in our check, not in the comparison of the two steps themselves.

**What is safe.**

- **No run of the sample used the new step.** The switch file was never written; both streams are on `739fbe3` with `chown`, as before.
- The three finished check runs (`prepcheck-haiku-homeassistant-L0`, both setups; `-L1`, `grep`) had the same race and happened to pass. They are check runs under their own run ids, not results; they are kept and marked.

## Checked

- In a container of home-assistant 183382: 32,022 loose objects and no pack before the commit; after it, `.git/gc.pid` exists.
- Loose objects and configuration files counted in one image each of duckdb, home-assistant and ruff, and `removed_config_files` in the 145 records so far.

## Left

- **The fix, as a new pull request:** the commit that removes the configuration files runs git's clean-up in the foreground (`gc.autoDetach=false`), so that it is done before the copy, as it was done before the agent started with the old step; the step waits until no git process is left; and it compares the list of names of the copy with the original before the swap, and falls back to the chown in place when they differ.
- **Then the comparisons again, this time with the commit in front of both steps,** on the same four tasks, with `git fsck` and the set of reachable objects in the comparison. Then two check pairs through `batch.sh`.
- Only then the switch. **If this is not done and checked before the Mac goes off, the old step stays until the Mac is back,** as you wrote.

## Blocked on, or needed from others

- **Andre:** nothing now. Please do not count `da25c74` as fit for runs. We post the fix and the new comparisons for your read.

## Next

- Andrew, with Claude Code: the fix and its checks; the home-assistant report (about 14:30 UTC).
