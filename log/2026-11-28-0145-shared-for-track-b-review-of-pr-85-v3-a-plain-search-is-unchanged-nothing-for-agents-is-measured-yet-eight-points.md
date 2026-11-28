# For track B: review of PR #85 (v3) at `4902671`. A search without the new inputs is unchanged; what the PR claims for agents is not measured yet; eight points

- **Track:** shared: from the lead, for track B. The review announced in our entry of 01:20 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 01:45 UTC
- **Work package:** B8
- **Branch, commits, pull request:** `wilson/no-hooks` at `4902671`, PR #85. Not merged, and not part of the lock

## Done

**The verdict.**

1. **A search without the new inputs is what it is at `463171c`, with one exception, the cap.** Through `codemem mcp`, 163 of 163 calls with `k` unset or at most 10 were byte for byte the same. All 40 calls with `k` 20 or 50 returned `463171c`'s answer cut to its first 10 results (`server.py:44`). On the command line 165 of 165 runs were the same apart from timing values, `codemem search -k 20 --json` among them: the cap does not reach it, so the evaluation's 20 results at the start are not touched.
2. **What a request costs more:** 1,435 more characters at `light` on every turn (1,221 in the tool list, 214 in the server instructions). The definition of `search_code` that a client receives grows from 984 to 2,205 characters. Characters were counted, not tokens.
3. **Nothing that the PR claims for agents is measured in it.** The branch holds code, tests and the README. Your quick test of 01:15 UTC is the only agent test: Haiku, 8 pairs, the whole package at once, without the 20 results at the start, and a gap that you read as noise yourself.

**The eight points, by weight.**

1. **The evidence against the hooks is thinner than the commit says.** The side test of 23:32 UTC is Sonnet, 2 tasks, 1 run. Two of its extra turns came from a Stop hook, and codemem never had one: at `463171c` it registers PreToolUse and PostToolUse only (`agents.py:55-70`).
2. **It collides with `andre/start-search-hook`.** `git merge-tree` gives 6 conflicted files, all from PR #85, with `hook.py` as modify against delete. PR #85's `codemem hook` (`cli.py:269-275`) returns nothing for UserPromptSubmit, so the search at the start would stop without a word. The smallest way to have both: `hook.py` keeps the starting search, and every other event is a no-op.
3. **Old installs:** hooks written earlier keep starting the command, about 51 ms a process. `init` neither removes them nor says so.
4. **The level `none`** is no longer none: `_FILTERS` (`prompts.py:13-23`) is added to every level, so `none` grows from 291 to 852 characters and tells the agent when to use the new inputs.
5. **`locations`:**
   - Pins can fill all 10 places: with 4 files named, 0 results of the plain search were left, and `k` cannot widen the page.
   - "3 each" holds per folder, not per location: one name found in 2 folders pinned 5 (`search.py:380-388`).
   - On the real vLLM index each file-like location scans the whole path index, about 13.5 ms; `__init__` reads 4,416 chunks, about 54 ms.
6. **A wrong lead can push out the right result.** With `symptom` and `anchors` filled for a wrong lead, the plain search's first result left the page once in 76 tries on the fake model; never with `intent` alone or `anchors` alone. The cause: each new list takes its signal's full weight (`search.py:321-326`).
7. **The types of the inputs:** `intent=null`, or a string where `anchors` or `locations` want a list, fails the whole call. An agent that fills a field in the wrong form then gets no search at all.
8. **PR #73:** PR #85 conflicts with it in `search.py` and `server.py`. With `main` at `739fbe3` PR #85 merges cleanly.

**What is solid.**

- All tests pass: 64 at `4902671` in `test_augmented_query.py` and `test_frontends.py`; the four test files that cover the search pass 109 at both commits. The `k` test does catch a missing cap.
- The no-op `codemem hook` is right and needed: an unknown command ends with 2, which Claude Code reads as a refusal.
- Blank inputs are ignored, pins respect the filters, and the other three tools are unchanged.
- No test covers the weights of the new lists, the limit of 10 pins, a name in several folders, or a comparison with `463171c`.

**For your plan of v3 against v2 (job 2).** Points 2 and 6 and verdict 2 are what the plan should measure: the 20 results at the start in both arms; what the longer definition costs over a whole run; how often a filled-in input moves the right result off the page; and the wording apart from the inputs. We are making a check of our own in our session harness (Haiku and Sonnet, five arms, the 17 pandas tasks and 6 vLLM tasks) and post it here.

## Checked

- By a review agent on Andre's Mac, on the fake model (no embedding model was loaded) and, for the costs of `locations`, on the real vLLM index's path table. We read the cap, the new inputs and the two wordings in the diff ourselves.
- **Not checked:** the real model (the extra time of a search, and whether embedding the query in one batch with the intent shifts its vector), tokens, how agents behave, the records of your test of 01:15 UTC, and the whole suite.

## Left

Our own check of v3 against v2.

## Blocked on, or needed from others

Nothing. Job 1 (kubernetes, the two indexes) comes first.

## Next

The lead: the check of v3 against v2.
