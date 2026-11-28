# For track A, from Andre: a correction to 12:51 UTC. Do not change the preparation step inside a repo until you have verified that it cannot touch the results, and Andre has decided

- **Track:** shared: from the lead, for track A. Corrects point 2 of our entry of 12:51 UTC ("mixed levels are fine")
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 12:54 UTC
- **Work package:** A12 (the runs), A4 (the integrity checks)
- **Branch, commits, pull request:** none

## Done

**1. Andre's rule: if a change could taint tokens, turns, cost or time, even remotely, it is not made.** So point 2 of 12:51 UTC waits for your check. Point 1 and point 3 stand.

**2. Until Andre decides:**

- **A repo that began with the old step keeps it,** at every level and in every later step: the rest of ruff, home-assistant and its hard task, and pandas in any later step.
- **A repo that has not begun may begin with the new step, and keeps it throughout:** duckdb, playwright, kubernetes, vscode.

**3. Please verify, and post:**

1. **Whether the change can reach the agent at all.** The folders differ only in their link count and, for some, their entry size. An agent sees that only when it lists a folder of `/testbed` in long form (`ls -l`, `stat`, `du`, `find -printf`).
   - Our count over the 102 records we have (pandas repetition 1 and the check run): at most 7 runs had such a command, 8 of 1,188 Bash calls.
   - In only one or two of those 7 was it a folder of `/testbed`. The others listed files, which are the same after both steps, or folders outside `/testbed`.
   - Please count over all your records, and say whether any such output would differ.
2. **What else differs for the agent between the two checkouts** (`da25c74` against `739fbe3`): is it #92 alone?
3. **What keeping the old step would cost, in hours of a stream,** for the repos that began with it:
   - the rest of ruff and of home-assistant now;
   - Sonnet's pandas;
   - Haiku's repetitions 2 and 3 of pandas, ruff and home-assistant.

**4. Andre decides after your answer.** Rules 1 and 2 of 12:51 UTC still hold: no idle or wasted work, and nothing that taints the results.

## Left

- Track A: the check and the costs.
- Andre: the decision.

## Blocked on, or needed from others

- **Track A:** points 3.1 to 3.3.

## Next

- Andre decides when the step may change inside a repo, if at all.
