# Track B: PR #85, for after the freeze. The hooks go; when to search goes into the wording; `k` is 1 to 10; and `search_code` gets an augmented query that the agent fills in

- **Track:** B. Design work for after the freeze: not for the lock, not for the runs
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-28 00:40 UTC
- **Work package:** B8 (the integration)
- **Branch, commits, pull request:** `wilson/no-hooks` off `main` `722ded5`, commit `4902671`. PR #85 (https://github.com/wyy1048576/codemem/pull/85), not merged

## Done

1. **No hooks.**
   - Removed: `hook.py`, `init --write-hooks`, the two hook texts and their tests.
   - Why: the side test of 23:32 found the hooks were the extra cost (a refused Grep was just sent again, and the review step added turns), and the rule of 12:40 says no hooks.
   - `codemem hook` stays as a no-op that ends with 0. A `.claude/settings.json` written earlier still runs it, and an unknown command would end with 2, which Claude Code reads as a refusal.
2. **What the hooks said is now in the `light` texts** (the `search_code` description, the server instructions, the agent note):
   - call `search_code` for the first search on a task, unless there is a clear anchor (an exact function, class or file name, or an error string);
   - call it when the trail is lost and there is no direction to grep.
3. **`search_code`: `k` is 1 to 10** (was 1 to 50), and the description says so.
4. **An augmented query, written by the agent's own model** (whatever model the coding agent runs), as optional inputs of `search_code`. This is what track B's loop did with a model call of its own (`aug_retriever.py`, PR #45).
   - `intent` and `symptom`: one more ranking by meaning per vector signal.
   - `anchors`: one more keyword ranking.
   - `locations`: files or functions the task names. Their chunks come first: at most 10, 3 per location, within the filters.
   - With none of these inputs, the search is the plain one.

## Checked

- 18 new tests. The anchor and location tests fail without the inputs. With no input, the scores equal the plain search's.
- **The fast suite on Windows:** 723 passed, and 6 failed. These are the same 6 that fail on a clean `main` here.
- **Not checked:** the real embedding model; sessions with an agent. Whether agents fill in the fields, and whether that helps, is not known. The `light` description grows from about 790 to 1,350 characters. The item 1 entry of 00:40 shows a fuller `detailed` wording made Haiku search less, so this needs sessions before it is adopted.

## Left

- Sessions with an agent (`light` with the fields, against `main`'s `light`). Haiku first.
- **PR #73, the points of Andre's review of 23:59:** a test that fails when the later call gets the cards; a test of the 30 s path; `refill` asking for `k + REFILL_DEPTH` with two calls in flight; one sentence on a cancelled call. `6146896` (D4 and D5) is not yet reviewed.
- **Overlap between #73 and #85:** `k` (50 against 10) and `candidates_k`. Whichever merges second brings these in line.

## Blocked on, or needed from others

**Andre:** PR #85 is for after the freeze. It needs your decision on hooks and wording for the product.

## Next

Wilson, with Claude Code: the points of 23:59 on PR #73; sessions for PR #85.
