# For track A, from Andre: runs at a limit count as not completed; vscode goes ahead if the disk can carry it

- **Track:** shared: from the lead, for track A. Answers A12 of your entry of 04:45 UTC, and the build order
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 07:01 UTC
- **Work package:** A12 (the runs), A9 (tasks)
- **Branch, commits, pull request:** none

## Done

**1. A12, runs that end at the turn or the time limit: they count as not completed** (Andre).

- The rule is the same in every setup, as the plan says.
- The record keeps how each run ended and the grader's verdict, so a table can still show the graded result beside the score.
- No run has reached a limit so far. The limits are 3,000 s and 150 turns. In the check run the longest run took 815 s (Haiku, `grep`, playwright 43316), and no run took more than 31 turns.

**2. vscode: yes, if the PC's disk can carry it without putting the runs at risk** (Andre). His worry is the disk. The runs come first, as before.

- **Check the disk first.** You described these sizes: an image of about 12 GB, a build that writes about as much again in cache, about 60 builds for a sample, and the archive.
- **If it fits, build vscode before ruff's hard tier.**
- **Post here what you decide, with the disk plan.**

**3. What goes to GitHub:** Andre's word comes later this morning, Pacific time.

## Left

- Andre's word on GitHub.

## Blocked on, or needed from others

- **Track A:** the disk check for vscode, and your decision.

## Next

- None from this entry.
