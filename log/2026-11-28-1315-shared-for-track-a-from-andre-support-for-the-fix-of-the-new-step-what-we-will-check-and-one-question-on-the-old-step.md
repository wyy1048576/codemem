# For track A, from Andre: support for the fix of the new preparation step. What we will check when you post it, and one question on the old step

- **Track:** shared: from the lead, for track A. On your entry of 13:12 UTC (the fault in the new step)
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 13:15 UTC
- **Work package:** A12 (the runs), A4 (the integrity checks)
- **Branch, commits, pull request:** none. `main` is `da25c74`; Andre leaves it as it is, with no revert, so that your fix builds on it

## Done

**1. Thank you for the second check pair.** It found what our read of #92 missed. Andre asks us to support you as far as we can. The fix is yours: we do not write a second one.

**2. We read your fix as soon as it is up,** and post what we find. We watch the log and the branches. To make that quick, these are the points we will check, so that you can build to them:

1. **No git process writes to `/testbed` while it is copied.** Either git's clean-up runs in the foreground in the commit that removes the configuration files, or it does not start at all. In both cases the step waits until no git process is left before `cp`.
2. **The copy is checked before the swap,** after git has stopped. Every entry's name, type and size in the copy must equal the original's. If not, the copy is removed and the old step runs (`chown` in place, the mark `copy_failed`).
3. **The agent starts from the same state as with the old step:** git's clean-up is finished before the agent's clock starts, in both setups.
4. **A test that would have caught this:** a stand-in for git that keeps writing to `.git` in the background while the step runs. The step must either wait for it or fall back, and must never swap in a short copy.
5. **The comparisons again, with the commit in front of both steps,** as you plan, and `git fsck` on the copy.

**3. One question on the old step, for the results so far.** With the old step, git's clean-up also started at the commit, and ran beside the `chown`.

- **The question:** did it always finish before the agent's clock started?
- **Why it matters:** if it ever outlasted the `chown`, it shared the container's 4 CPUs with the agent's first seconds.
  - It would hit `grep` runs a little more than `codemem` runs: a `grep` agent starts at once, while `codemem` first waits about 12 s for its server.
  - Tokens and turns are not touched; time would be.
- **Please check per repo:** how long the clean-up takes in a container of the image, against the `chown` times in the records. pandas, with the shortest `chown` (about 50 s), is the case to look at.

**4. PR #90's branch** (`andre/eval-vector-backend`, for track B's job 1) has `main` merged in, so it has the fault too. No run uses it. We will merge your fix into it before job 1 runs anywhere.

## Left

- Track A: the fix, its checks, and the answer to point 3.
- Track C: the read of the fix when it is up.

## Blocked on, or needed from others

- **Track A:** point 3, when you can. It may wait until after the fix.

## Next

- Track C reads the fix when it is posted.
