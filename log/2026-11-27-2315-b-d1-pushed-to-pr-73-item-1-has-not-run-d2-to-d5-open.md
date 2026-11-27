# Track B: D1 of the review of 14:10 is pushed to PR #73, so the switch can merge while off. Item 1 has not run and missed 23:00 UTC. D2 to D5 are still open

- **Track:** B. Answers the entries of 14:10 and 15:15 UTC (Andre); a status line for the entry of 12:40
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-27 23:15 UTC
- **Work package:** B8, items 1 and 2 of 12:40
- **Branch, commits, pull request:** `wilson/search-dedup`, new commit `60685a8` on top of `242a7bf` (no force push), PR #73 (https://github.com/wyy1048576/codemem/pull/73), not merged

## Done

- **D1 is fixed.** `eval/tests/test_e2e_run.py::test_run_one_tool_locally`: `"search_dedup": "default"` added to the expected `identity.codemem`. This is the line from the review and nothing else changed. With it, the switch can merge while off.
- **A correction to my entry of 13:28.** That entry said `test_e2e_run.py` fails the same tests with and without the change. That was wrong for this test. It cannot run on Windows, because its setup makes symlinks, so its failure here hid the real one. Thank you for finding it.
- **The reviews of 14:10 and 15:15 are read.** No mode costs quality, and the saving is small. Both are noted for the write-up of item 2.

## Checked

- The runner writes `.get("CODEMEM_SEARCH_DEDUP", "default")` (`eval/src/cmeval/e2e_run.py`, line 937). That matches the new expected value.
- **Not run:** the test itself, which fails on Windows on the symlink before reaching the assertion. Andre's review ran it on the Mac with this exact line and it passed.

## Left

- **Item 1 (the must) has not run.** It was due at 22:00 UTC, at the latest 23:00, and it missed both. Nothing from track B's MCP-vs-grep runs is in this log. It will not be ready before the lock.
- **D2, D3, D4 and D5 are not fixed.** No mode should be turned on in a run until D2 and D3 are fixed, as the review says. With the switch off, the code is unchanged from `463171c`, so the fixes do not block a merge.
- **The 13:25 case,** results the session has seen only by name, is not yet in the write-up.

## Blocked on, or needed from others

- **Andre:** the decision at the lock on whether #73 goes in with the switch off, now that D1 is fixed.

## Next

Wilson, with Claude Code: item 1, then D2 and D3, then D4 and D5.
