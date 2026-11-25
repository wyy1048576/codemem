# Arms B and C are on hold; vague prompts (L1, L2) exist for the 18 pilot tasks and their runs have started

- **Track:** A. Point 1 is for track B
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-25 23:28 UTC
- **Work package:** A1 (prompt levels), the first part of the plan's §9
- **Branch, commits, pull request:** `main` at `1a7e4d1` (#29)

## Done

**1. The arms with the agent note and the hooks are on hold** (Andrew's decision of this evening). Wilson is changing how codemem is presented to agents. Track A builds `tool-note` and `tool-hooks` when Wilson says here that his version is ready, with the commit.

**2. Prompt levels in the runner (#29).** `cmeval e2e run --prompt-level L1|L2 --prompts FILE`. `run.json` records the level and the prompts file's name and hash. The default is L0, the issue as written.

**3. L1 and L2 for the 18 valid tasks of pandas and playwright:** `eval/tasks/vague-pilot18-v1.jsonl`, with the rules in `eval/tasks/vague-rules-v1.md`. L1 keeps every fact and has no path, identifier, trace or code. L2 is 23 to 29 words in a user's voice. A model wrote them from the issue, the real change and the hidden tests.

**4. A finding about the tasks.** 13 of the 18 needed a "Done when" line: their hidden tests assert something that the issue does not state (an exact value or message, a new name, an extra case). In 5 of them the issue does not describe what the real fix does. Example: in pandas 70713 the test asserts chunks of exactly 8,192 selectors, and the issue has no number; a Haiku run that split at 500 was graded not completed. This lowers the completion of every arm at L0, and it is one reason for 6 of 18 in the pilot.

**5. Runs started** (PC, two at a time): the 18 tasks at L1, at L2 and at L0, setup `tool`, Haiku, codemem `041124e`, thinking summaries on. 54 runs. The question is whether the agent calls codemem more when the prompt names nothing.

## Checked

- 711 unit tests on `1a7e4d1`. An automatic leak check: no identifier of the old code in any text outside its "Done when" line.
- Not checked: that the rewritten tasks stay solvable (§9, check 2); no person has read the texts yet (check 3). The texts are a first trial, not the final set.

## Left

- The result of the 54 runs. Then Andrew decides whether rewrites are made for all tasks.

## Blocked on, or needed from others

- **Wilson:** the commit of the version that the arms B and C should use, when it is ready.

## Next

- Track A's session: the result of the runs, here.
