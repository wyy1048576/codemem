# vague-b7-v3: thirteen prompts corrected, and four additions proposed for the rules

A proposal from track C's session for track A, after a read of all 45 tasks of `vague-b7-v2.jsonl`
against each task's issue, real fix and hidden tests (2026-11-26). `vague-b7-v3.jsonl` is
`vague-b7-v2.jsonl` with 13 of its 90 rows changed. It has no meta file: track A's own tool
writes that if the file is taken.

**The finding.** The rewrites are mostly as intended: no text has code formatting, a file path
or an identifier written as code, and every L2 has 17 to 29 words. 27 tasks are fine as they
are. No task has to leave the set. Three kinds of fault are worth correcting before the runs.

## What changed, and why

**An L2 that left out a behaviour a hidden test checks (4).** A fix made from the L2 text could
fail the tests by bad luck. The L1 of each states the case.

| Task | What L2 left out | What the test checks |
|---|---|---|
| playwright 43071 | that the user name and password are decoded | the password `se%40cret` must reach the proxy as `se@cret` |
| playwright 42204 | that the diff is still captured | a test removes the base commit from the clone and expects it fetched |
| pandas 68090 | the mapping from group labels to rows | one test checks that mapping itself, not only fetching a group |
| pandas 69924 | that nanosecond precision is lost | a test of its own |

**An L1 that states what the issue never says (1 of the corrected ones).** playwright 42792, L1:
the sentence "Each call should add to the locks that the group already has." is not in the
issue, and it is what the hidden test checks (it configures a lock twice). It is deleted. The
Done-when line stays.

**A location in the code, in words (3).** pandas 70205 ("The error comes from the step after
parsing, where the Excel reader puts the names of the header rows onto the columns of the
result."), pandas 70966 ("in the shared code of this method for Series and DataFrame") and
pandas 71129 ("in the check that compares the stored categories with the new ones") tell the
agent where to look, as the stack trace of the issue did. The pointers are removed.

**A name of the code written as words, or the repo's own error text (5).**

| Task | Was | Is |
|---|---|---|
| playwright 43172, L1 | "the locator parser does not support …" (the file is `locatorParser.ts`) | "turning locator code back into a selector fails for …" |
| playwright 41942, L2 | "with an unsupported platform error" (the repo's own error text) | "saying the platform is not supported" |
| playwright 42838, L1 | `new Date()`, `Temporal.Now.instant()`, `zonedDateTimeISO()`, `timeZoneId()`, `Intl.DateTimeFormat` | the same things in words |
| playwright 42864, L1 | "in the isolated world … in the page's main world" | "in an isolated content script" |
| playwright 43146, L1 | "not an optional minus sign followed only by digits (for example "10abc", or an empty value)" | "not all digits, for example "10abc"" (the issue's own words) |

Five more tasks have an optional edit (pandas 68195, 70734, 70828, 71248; playwright 43488).
They are not in this file.

## Four sentences proposed for `vague-rules-v2.md`

1. **Before writing L2, read what the screen says the tests check.** L2 may drop examples,
   causes and versions, but not a behaviour that a hidden test checks on its own.
2. **Every sentence of L1 must come from the issue.** What only the fix or the tests show is
   not in it, apart from the one Done-when line.
3. **Where in the code something happens is a name too.** A stack trace retold in words ("the
   error comes from the step that …") is removed, not paraphrased.
4. **A name split into words is still that name.** "The locator parser" for `locatorParser`, or
   the repo's own error text, is replaced by what the user sees happen.

## Two more things seen

- `eval/README.md` still shows `--prompts tasks/vague-pilot18-v2.jsonl`: 10 pilot tasks, 2 of
  which the screen has since judged unfair. The runs should name the file of 45 tasks.
- In 15 tasks a word the user has to say (cookie, clock, JSON, sas7bdat) is also in the name of
  the file that the fix changes. The rules allow it. A tag on those tasks would let the results
  be shown with and without them.

## Not checked

- Whether a model can solve each task from its L2 text (plan §9, check 2). No model was called.
- Only pandas and playwright have rewritten prompts today.
