# 8 of the 18 pilot tasks have hidden tests that the issue does not cover: input wanted

- **Track:** A (a question for tracks B and C at the end)
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-26 02:05 UTC
- **Work package:** A8 (vague prompts), and the task filters of A2
- **Branch, commits, pull request:** `main` at `bdd58d5` (PR #37)

## Done

- **Version 2 of the vague prompts is merged:** `eval/tasks/vague-pilot18-v2.jsonl` (10 tasks,
  20 rows), rules in `eval/tasks/vague-rules-v2.md`. A "Done when" line is now allowed only to
  name something new that the tests call, in at most 25 words. One task has such a line.
- **Each of the 18 pilot tasks was screened** against its issue, its real change and its hidden
  tests. The question: does a correct, general fix made from the issue alone pass all hidden
  tests? For 8 tasks the answer is no. They are out of the vague set. The reasons for each one
  are in `eval/tasks/vague-pilot18-v2.meta.json` (`screen.removed`, `screen.fair_at_L0`).

| Task | What the hidden tests need and the issue does not give |
|---|---|
| playwright 42164 | The issue asks for a list of groups. The tests read annotations of type 'serial', one per enclosing suite, with a location and in a fixed order |
| playwright 43000 | The issue asks that the main frame stays correct. The tests need the whole tree of four nested frames, and a second case the issue does not mention |
| pandas 66225 | The case in the issue works before the fix. The tests check the reverse case (a real missing value comes back as missing) |
| pandas 66227 | The issue is about Series arithmetic and asks for OverflowError. The tests check DataFrame sums and want another error class with an exact message |
| pandas 67291 | The issue says only that length-zero arithmetic has no tests. The tests need fixes in three unrelated array types |
| pandas 67471 | Many test files use a new skip marker by name, and a test checks that the Qt clipboard set-up restores the locale. The issue names neither |
| pandas 68587 | The issue shows one case. The tests cover two engines, three result types, two error classes with exact messages, and two more code paths |
| pandas 70713 | The tests assert a split at exactly 8192 selectors. The issue does not find the cause |

- **These 8 are unfair at every prompt level, also with the issue as written (L0).** In the pilot
  and in the L0 set of tonight, none of them was completed. The tasks that were completed are all
  among the 10 that the screen kept.
- Evidence that the tests, not the agent, decide these: with a "Done when" line that states what
  the tests check (version 1), Haiku completed 6 of the 8.

## Checked

- The screen was one read per task by an Opus session, and its reasons were reviewed. No test was
  run for it. Confidence: 7 high, 1 medium (pandas 67291). Of the 10 kept tasks, one verdict is
  low (pandas 68945) and four are medium.
- Not checked: a second, independent screen. The 8 are not final before that.

## Left

- A decision for the task pool as a whole. 8 of 18 is 44%. If the rate holds, a screen removes
  close to half of the valid tasks, so more candidates per repo are needed to reach the planned
  counts.

## Blocked on, or needed from others

Input from **Andre** (the plan is his) and **Wilson**, before track A decides. The options:

1. **Screen them out of every reported set** (what SWE-bench Verified does). The prompt stays
   the real issue. Cost: about half the tasks, so more validation runs. Track A leans to this.
2. **Keep them and report completion twice:** on all tasks and on the screened tasks. No task is
   lost, but half of each arm's failures say nothing about search.
3. **Keep them with a "Done when" line** that states what the tests need. Tried tonight: the
   line gives the agent more than the issue does, and no user writes it. Track A is against it.

Questions: (a) is there a use in the plan for the removed tasks that we do not see, for example
the retrieval eval, where a task needs only its gold files and no hidden tests? (b) The plan has
a model screen in the task filters. Is "a correct fix from the issue passes the tests" the
intended test there, or something narrower?

## Next

- Track A: a second screen of the 18, the scores of tonight's runs, then the decision.
