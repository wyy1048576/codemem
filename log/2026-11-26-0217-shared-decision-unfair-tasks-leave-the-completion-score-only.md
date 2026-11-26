# Decision for track A: tasks with unfair hidden tests leave the completion score, and stay in the search measures

- **Track:** from Andre, as project lead. Answers track A's entry of 2026-11-26 02:05
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 02:17 UTC
- **Work package:** A2 (task filters), A8 (vague prompts)
- **Branch, commits, pull request:** none. A decision

## Done

**The decision (Andre):** your option 1, with one distinction.

| | |
|---|---|
| The completion score ("did the agent finish the task") | counts only tasks where a correct fix made from the issue can pass the hidden tests. The tasks that fail that screen are left out of it, at every prompt level |
| The search measures | keep every task, also the screened-out ones: whether and when the agent reaches the gold files, the steps and tokens up to there, and the retrieval eval. None of these needs the hidden tests |
| The task count | validate more candidates per repo to get back to the planned 20 per repo |
| When a task is dropped for good | only after your second, independent screen. Until then the 8 are marked, not removed |

**Your two questions.**
- (a) Yes: the removed tasks are used for the retrieval eval and for the localization measures.
  Their gold files are valid labels whatever the tests assert.
- (b) Yes, for the completion set: "a correct, general fix made from the issue passes all hidden
  tests" is the test.

**What was weighed.**
- Writing what the tests need into the prompt (option 3) keeps every task, and it works: with
  version 1's lines Haiku completed 6 of the 8. But pandas went from 2 of 10 to 10 of 10 with
  them. At that level every setup scores near the top, and the runs can no longer show whether
  search helped. The line is also nothing a user writes. So no line beyond version 2's rule.
- Losing 44% of the tasks: with 60 validated candidates per repo, about 33 remain, above the
  sample of 20. A repo with few candidates can fall short.

**If a repo falls short after the screen:** say so here before changing a rule. The fallback
Andre would look at first is to drop the hidden test cases that go beyond the issue and keep the
task. It costs a review per task and makes the tests weaker, so it is not the default.

## Checked

- Nothing was run. The numbers are those of track A's entries of 01:52 and 02:05.

## Left

- Track A: the second screen, more candidates per repo, the scores of tonight's runs.

## Blocked on, or needed from others

- Nothing. Wilson's view was asked for in the entry of 02:05 and is still welcome.

## Next

- Track A carries on. Track C: nothing follows from this entry.
