# Vague prompts: the "Done when" lines are too wide, do not judge the method by them

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-26 01:52 UTC
- **Work package:** A8 (vague prompts)
- **Branch, commits, pull request:** `main` at `1a7e4d1` (PR #29); no new commit yet

## Done

- A limit of `eval/tasks/vague-pilot18-v1.jsonl` was found while its runs were in progress.
  13 of the 18 tasks carry a "Done when" line at L1 and at L2. The rule in
  `vague-rules-v1.md` is wider than plan section 9: it allows the line at both levels, and for
  exact values, messages and extra cases, not only for a new name that the tests call.
- The result: about 8 of the 13 lines read like the test file in prose (one has about 170
  words). No user writes that. For those tasks the L2 prompt gives more than the issue does.
- Interim numbers (Haiku, setup `tool`, one repetition): pandas 10 of 10 completed at L1 and at
  L2. With the issue as written (L0) the pilot had 2 of 10, and the L0 set that runs now has 2 of
  7 so far.
- **Decision (Andrew):** the next version has no "Done when" line, or one short line that names
  something new that the tests call (L2 only, as the plan says). Tasks whose hidden tests need
  more than that are removed from the vague set. The 54 runs finish as they are.

## Checked

- All 13 lines were read again. The counts above are from the run logs on the PC.
- Not checked yet: how often codemem was called at each level. That comes when the runs end.

## Left

- Rules version 2, the list of tasks that stay, new rewrites in a new file, a pull request.
- The scores and the adoption counts of the 54 runs.

## Blocked on, or needed from others

- **Wilson:** you can take any row of `vague-pilot18-v1.jsonl` to verify the format
  (`{id, level, prompt}`). The 5 tasks without a "Done when" line are the ones that will not
  change: playwright 41850, 42919, 43146, 43148 and pandas 68090. Do not use completion on the
  other 13 as a measure.

## Next

- Track A's session: version 2 of the rewrites after the runs end, then the report.
