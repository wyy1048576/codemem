# The grader is on main and is right on 18 of 18 tasks; the recording proxy agrees with Claude Code's own count

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-25 08:33 UTC
- **Work package:** A1 (the grading step) and A2 (the recording proxy and the cross-check)
- **Branch, commits, pull request:** the grader: pull request #21, merged as `a2c3655`. The proxy: branch `e2e-proxy`, commit `06f86d5`, no pull request yet

## Done

- **The grader** (plan §4.7). In a fresh container of the task's image it applies the agent's
  change, puts the hidden test files in place, rebuilds, and runs the task's tests. Completed =
  every test that had to start passing passes, and every test that had to keep passing still
  passes. The hidden test files win over the agent's version of them.
- **`cmeval e2e grader-check RECIPE --tasks FILE`** grades the real fix and an empty change for
  every valid task.
- **A valid task now saves its two test lists** (`tests.json` beside its record).
- **The recording proxy** (plan §5.1, §5.3): `cmeval proxy --log FILE`, a summary of one run, and
  the cross-check against `modelUsage`. On a branch, not merged.

## Checked

- **First pass condition of the first end-to-end test (§2.2): "the grader is right".** On the PC,
  for all 18 valid tasks of the two admission samples (pandas 10, playwright 8): the real fix
  completes the task, and an empty change does not.
- The 20 sampled tasks were validated a second time. Verdicts and test counts are the same as
  the first time.
- **The proxy, on one real headless run** (Claude Code 2.1.332, subscription login,
  `claude-haiku-5-5`, on the PC): the login works through the proxy, and the proxy's sums equal
  `modelUsage` in all four classes (input 2, output 380, cache write 22,079, cache read 0).
  The proxy's log holds no token. This answers one of the "check on the first day" points of §4.3.
- One run with one model call. The 1% rule on real multi-turn runs is not shown yet.
- Unit tests: 497 pass with the grader, 498 on the proxy branch.

## Left

- The proxy's pull request.
- The runner: the agent inside the task's container, as a user that is not root, with the model
  API as its only network route. No agent has run on a task yet.
- From §5, not built: thinking tokens as a sum of their own, tokens before the first edit, the
  comparison of time to first byte with and without the proxy, usage in the OpenAI format.
- The two playwright tasks that are not valid (42856, 42859): cause still open.

## Blocked on, or needed from others

Nothing.

## Next

- The runner, then bring-up runs with Haiku on the 18 tasks in the `grep` setup.
- Validation of 60 candidates per repo, when the PC is free for it.
