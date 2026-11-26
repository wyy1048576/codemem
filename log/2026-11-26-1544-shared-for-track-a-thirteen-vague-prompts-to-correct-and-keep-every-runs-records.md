# For track A, from Andre: thirteen of the vague prompts need a correction before the runs (a proposal file is ready), and please keep every run's full records

- **Track:** shared: from track C's session, for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 15:44 UTC
- **Work package:** A9 (the vague prompts), A5 (what a run records)
- **Branch, commits, pull request:** `andre/vague-prompts-v3` (`5a7c2a2`): `eval/tasks/vague-b7-v3.jsonl` and `eval/tasks/vague-b7-v3.changes.md`. A proposal: take it, change it or leave it

## Done

**1. All 45 tasks of `vague-b7-v2.jsonl` were read** against each task's issue, real fix and
hidden tests (Andre asked for this check before the runs start on these texts).

**The rewrites are mostly as intended.** No text has code formatting, a file path or an
identifier written as code. Every L2 has 17 to 29 words. The ladder works: for pandas, a word
that leads a text search to the fixed file is in 12 of 17 issues, 3 of 17 L1 texts and 2 of 17
L2 texts. 27 tasks are fine as they are. No task has to leave the set.

**13 rows are worth correcting, of three kinds:**

| Kind | Tasks | Example |
|---|---|---|
| An L2 that leaves out a behaviour a hidden test checks. A fix made from it can fail by bad luck | playwright 43071, 42204; pandas 68090, 69924 | 43071 L2 ends "Please make it use them." The issue says the user name and password are decoded, and the test passes `se%40cret` and expects `se@cret`. Proposed: "Use them, percent-decoded." |
| An L1 that states what the issue never says | playwright 42792 | "Each call should add to the locks that the group already has." is not in the issue, and it is what the hidden test checks. Proposed: delete it; the Done-when line stays |
| A place in the code, or a name of the code, in words | pandas 70205, 70966, 71129; playwright 41942, 42838, 42864, 43146, 43172 | 70205 L1: "The error comes from the step after parsing, where the Excel reader puts the names of the header rows onto the columns of the result." 43172 L1: "the locator parser" (the file is `locatorParser.ts`) |

- **The proposal:** `eval/tasks/vague-b7-v3.jsonl` on the branch is your v2 file with those 13
  rows changed and the other 77 untouched. `vague-b7-v3.changes.md` beside it gives every change
  with its reason. It has no meta file: your tool writes that if you take the file.
- **Four sentences proposed for the rules,** so that the prompts of the other repos do not get
  the same faults (their full text is in the changes file): read what the screen says the tests
  check before writing L2, which may drop examples and causes but not a tested behaviour; every
  sentence of L1 comes from the issue; a stack trace retold in words is removed; a name split
  into words is still that name.
- **Two more things seen.** `eval/README.md` still shows `--prompts tasks/vague-pilot18-v2.jsonl`
  (10 pilot tasks, 2 since judged unfair): the runs should name the file of 45. And in 15 tasks a
  word the user has to say (cookie, clock, JSON) is also in the name of the fixed file: a tag on
  those would let the results be shown with and without them.

**2. Please keep the full records of every run** (Andre). Your runner already keeps what is
needed: the agent's event stream with every tool call and its result, and the proxy's log with
the clock and the token counts of every model request. Two asks:

- **Do not prune them,** also not for discarded runs, and not when disk gets tight: the task
  images can go first. We want to follow, for any run, which command led to which.
- **One table per run, one row per turn:** seconds, tokens, the tool, its command or query, and
  whether it showed, opened or edited a gold file. That is the view of the whole chain that the
  paper will show for a `grep` run beside a `tool` run of the same task.

## Checked

- Three of the faults were checked a second time against the task files by hand (43071, 42792,
  70205). The 13 replacements each matched its v2 text exactly once.
- Not checked: whether a model can solve each task from its L2 text (plan §9, check 2). Only
  pandas and playwright have rewritten prompts today.

## Left

- Nothing on our side.

## Blocked on, or needed from others

- **Andrew:** take or change the 13 rows before the check run; the four sentences for the rules
  before the prompts of the next repos are written; the two asks of point 2.

## Next

- Track C's session, now working on track B's part with Andre: what the search misses, and
  whether an agent finds the right code sooner with codemem beside grep. Results follow here.
