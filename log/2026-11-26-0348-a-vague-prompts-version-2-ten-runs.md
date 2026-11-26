# Vague prompts version 2, 10 runs: completion is back at the level of the original issue, adoption stays high

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-26 03:48 UTC
- **Work package:** A8 (vague prompts)
- **Branch, commits, pull request:** `main` at `bdd58d5`; no new commit

## Done

- 10 more Haiku runs with `eval/tasks/vague-pilot18-v2.jsonl`: the 5 tasks whose prompt changed
  from version 1, at L1 and at L2. Setup `tool`, codemem `041124e`, one repetition, thinking
  summaries on (diagnostic). None discarded. The other 5 tasks of version 2 have the same prompt
  as in version 1, so their runs of the earlier batch count.
- The 10 tasks of version 2, all three levels:

| Prompt | Completed | Runs that called codemem |
|---|---|---|
| L0, the issue as written | 7 of 10 | 4 of 10 |
| L1, names removed | 8 of 10 | 9 of 10 |
| L2, short request | 7 of 10 | 10 of 10 |

- **Completion:** with the lines of version 1 the same tasks had 9 and 10 of 10. Without them it
  is at the level of L0. So the lines carried the rise, and the tasks stay solvable without them.
- **Adoption (for Wilson):** the vaguer the prompt, the more often the agent starts with codemem.
  Every run still makes one call only, in its first three turns, then greps.

## Checked

- The recorded prompt of each run: no "Done when" text, except the one narrow line of
  playwright 42672. Each `run.json` holds the prompts file's hash (`489b0ef7...`).
- Not checked: a baseline arm at L1 and L2; more than one repetition. 10 tasks and one run each
  show behaviour, not an effect size.

## Left

- Playwright 42503 passes at L0 and fails at L1 and at L2, both times on the test of the issue's
  own case. Either the rewrite lost something or it is run-to-run noise. Not read yet.
- Pandas 70742 fails the same two row-slice cases at all three levels. Both screens call it
  fair with medium confidence. It may belong to the unfair tasks.

## Blocked on, or needed from others

- Nothing.

## Next

- Track A: the two tasks above; the screen as a step of the task pipeline; the validation of
  more candidates per repo, when Andrew gives the go.
