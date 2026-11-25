# The first agent runs work end to end; what they show about Claude Code, tokens and our counters

- **Track:** A. Parts of it matter for tracks B and C: see "For the other tracks"
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-25 09:34 UTC
- **Work package:** A1 (runner, score), A2 (cross-check), and a review of A9's code
- **Branch, commits, pull request:** the runner: branch `e2e-runner`, no pull request yet. Review fixes: pull request #23, open

## Done

- **The runner** (`cmeval e2e run`, `cmeval e2e score`): Claude Code in the task's container as a
  user that is not root, on an internal network, with the proxy as its only route; limits of 50
  minutes and 150 turns; the agent's change captured and graded; one `run.json` per run; a batch
  that resumes, stops at a usage limit, and stops after three errors in a row.
- **The first real run went through at the first attempt** (pandas 70742, `grep`, Haiku): finished
  by itself, not completed (2 of 4 tests that had to start passing; all 227 others kept passing),
  108.7 s, 17 turns, 823,596 processed tokens.
- **A code review of the generator, the grader and the proxy,** by an independent reader, with one
  question: can this give a wrong verdict or number without an error? 12 findings, 11 fixed in
  pull request #23.
- **A bring-up batch** on the 18 valid tasks (Haiku, `grep`, one repetition) is running.

## Checked

- **The two token counts are equal on a real multi-turn run:** 823,596 from the proxy and
  823,596 from `modelUsage`, over 18 requests.
- Every setup check passed on every run so far. The login token is in no file of any run.
- Of the first 8 pandas runs, 2 completed. **These are not results:** Haiku, one repetition, and
  test lists from before the review fixes.
- The review fixes have unit tests (538 pass). They have not run on containers yet.

## Left

- **The step counts in the run records are wrong, and are being rebuilt.** See point 2 below.
- Pull request #23 changes the validation rules, so every saved validation is done again, and the
  saved agent changes are graded again. No model tokens are needed for that.
- The `tool` setup. No run with codemem yet.

## For the other tracks

1. **Three faults that could give a wrong result, found by the review** (fixed in #23):
   - **pytest stops at a test file that does not import.** Before the fix, a new test file often
     imports a name that does not exist yet. Then no test of the other files runs, every test
     looks "missing before", and a test that the real fix breaks is not seen. This is why pandas
     67471 showed 28,465 tests that "start passing". Fix: `--continue-on-collection-errors`.
     Every pytest recipe needs it.
   - **Old images and old test lists were reused after a recipe change,** also with `--force`.
     Images and lists now carry a fingerprint of what made them.
   - **The token cross-check agreed when both sides were empty** (0 = 0). It now refuses.
2. **Claude Code 2.1.332 has no Grep and no Glob tool.** It searches with `grep` and views files
   with `sed -n`, `head` and `tail` through Bash, several per call. It also edits through the
   shell. So a counter that watches tool names is wrong: the first version said "1 file read, gold
   file not read" for a run that edited the gold file. The counts are being rebuilt from the shell
   commands and, independently, from where the gold file's path appears in tool results. Plan
   §4.1 describes the `grep` setup with the older tool list.
3. **Track B: the length of codemem's tool descriptions is paid on every turn.** An empty run in
   the container costs about 35,600 tokens: Claude Code's system prompt and its tool definitions.
   That text is sent again on every turn, as a cache read. In the first run it was about three
   quarters of all tokens. So turns drive the token total, not the code that is read. Each 1,000
   tokens of tool description cost about 17,000 tokens in a 17-turn run, in every `tool` run.
4. **Some tasks validate and are still poor end-to-end tasks.** In pandas 67291 the real fix only
   adds tests, and the issue describes a symptom in another package. The agent stopped: "the code
   the issue is about isn't in this repository." Validation shows that the tests work. It does
   not show that the issue text is enough. A filter for fixes that change only test files is
   planned. The solvability check of §9 may be needed earlier than planned.

## Blocked on, or needed from others

**Andre: a third decision, with the two of the entry of 09:00.**

3. **ripgrep in the task images.** The old Grep tool brought ripgrep with it. Through the shell
   the agent has only what the image has, and our images have plain `grep`. The baseline may then
   search worse than on a developer's machine, which would favour codemem. Proposal: install
   ripgrep in every base image, in every setup. Yes or no?

## Next

- The bring-up batch ends; the review fixes and the runner are merged; validation and grading are
  done again under the new rules; the step counts are recomputed for the saved runs.
- Then the `tool` setup, and the six pass conditions of §2.2 (one is met: the grader is right).
