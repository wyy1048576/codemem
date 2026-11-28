# For track A: Andre's word on your entry of 02:04 UTC. The runs come first; and if a repo must go, vscode goes first, then trino

- **Track:** shared: from the lead, for track A. Answers "Your word here if the build order or the trino decision should be different"
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 02:14 UTC
- **Work package:** A9 (tasks), A12 (the runs)
- **Branch, commits, pull request:** none

## Done

**Andre's decision, in his order.**

1. **You are free to try whatever gets all the repos in.** The second Docker daemon for builds is fine with him.
2. **The priority is that the eval runs run.** No build, no compaction and no change of setup may put a run at risk or hold the runs up. Where a build and the runs compete for the disk or for time, the runs win.
3. **If a repo has to be dropped, drop vscode first, then trino.**

- **Point 3 is the reverse of your entry of 02:04 UTC** (vscode stays, trino waits). You may still build both. But where the two compete for room or time, trino is the one to keep and vscode the one to give up.
- The six repos that are ready are not in question.

Thank you for the account of where the disk goes and for the index sizes. It is read.

## Checked

Nothing new.

## Left

Nothing.

## Blocked on, or needed from others

Nothing.

## Next

Track A: the early report after the Haiku half of the check run.
