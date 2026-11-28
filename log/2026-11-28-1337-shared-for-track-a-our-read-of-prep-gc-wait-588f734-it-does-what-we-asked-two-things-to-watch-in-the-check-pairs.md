# For track A: our read of `prep-gc-wait` (`588f734`). It does what we asked. Two things to watch in your check pairs

- **Track:** shared: from track C, for track A. On your branch `prep-gc-wait` and our entry of 13:15 UTC (the five points)
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 13:37 UTC
- **Work package:** A12 (the runs), A4 (the integrity checks)
- **Branch, commits, pull request:** `prep-gc-wait` at `588f734`, on `main` `da25c74`. We read the code and the tests; we did not run them

## Done

**Our five points, against the branch:**

1. **No git process writes during the copy: yes.**
   - The step waits until no process of the container is named `git`, for at most 600 s, and falls back to the old step (`git_busy`) after that.
   - The name covers the whole clean-up: `gc` runs `repack`, `pack-objects`, `prune` and `pack-refs` as `git` processes. Waiting, and leaving git's own settings alone, keeps the commit as it is with the old step.
2. **The copy is checked before the swap: yes, by its names.**
   - Names are enough here. After the wait nothing writes, and git replaces a file by a rename, so no file can be copied half written. A missing or extra object shows as a name.
   - If you add sizes, leave folders out: their sizes differ between the two steps anyway.
3. **The agent starts from the same state: yes.** The clean-up has ended before the copy, so before the agent's clock.
4. **A test that would have caught it: yes.** Git ends during the wait, git keeps running, a loose object missing, an extra pack, a tool that fails.
5. **The comparisons with the commit in front, and `git fsck`:** yours to come, as you planned.

**Two things to watch in your two check pairs:**

1. **The wait must end when git's clean-up ends.**
   - A finished `gc` stays in `/proc` as a zombie named `git` until the container's first process reaps it. That process is `bash /out/agent.sh`, since `docker run` has no `--init`.
   - bash should reap it at once, but if it ever does not, every run waits 600 s and falls back.
   - **Check:** no `git_busy`, and a `copy_swap` step of about the length of your comparisons (40 to 55 s), not ten minutes.
2. **No image may start a git process that stays,** such as `git fsmonitor--daemon`. Then every run would wait 600 s and fall back. The same check shows it.

**Our verdict:** no blocking issue. When point 5 and the check pairs pass, the switch is yours to decide, within our entry of 12:54 UTC: a repo that began with the old step keeps it until Andre decides.

## Left

- Track A: point 5, the two check pairs, and the pull request.

## Blocked on, or needed from others

- None.

## Next

- We merge the fix into PR #90's branch when it is on `main`.
