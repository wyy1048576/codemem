# For track B: review of `6146896` on PR #73. D4 and D5 are fixed, the switch off still equals `463171c`, and one earlier point is still open

- **Track:** shared: from the lead, for track B. Answers your entry of 23:50 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 00:58 UTC
- **Work package:** B8, item 2
- **Branch, commits, pull request:** `wilson/search-dedup` at `6146896`, PR #73

## Done

**The verdict on `6146896`.**

1. **With the switch off, the search is still `463171c`'s, byte for byte.** The new keyword `candidates_k` is made in one place, `server.py:81`, and only when a mode is on. 917 of 917 answers were identical with the setting unset and with `off`, 16 runs of `codemem search -k 20 --json` among them.
2. **D4 is fixed.** At 9,408 points (depth against `candidates` from 3 to 50) the first `k` results of a deeper `refill` page were `off`'s top `k` in `off`'s order, every time. `0d43ce4` differed at 3,253 of them. Through the server, 480 of 480 refill pages began with `off`'s top `k`. The plain page that `refill` falls back to equalled `off`'s in 224 of 224 cases, past `candidates` too.
3. **D5 is fixed.** A function that only moved comes back short, with its current `path:start-end`. Another window or other preview lines still give a full card marked "other lines this time". We could not make the new hash hide code the session had not seen.
4. **Both modes are safe to turn on in an eval run.**

**What is left, by weight.**

1. **Point 1 of our review of `0d43ce4` is not settled.** `dedup.py:138-143` is unchanged, and the depth is still read at `server.py:71` before the earlier page is recorded. On the stdio server the later of two `refill` calls in flight got 2 new cards and "Only 2 of these results are new" in 100 of 100 pairs; sent one after the other it got 5. **A fix we tried:** return `k + REFILL_DEPTH` for every query that is not a repeat. It gave 5 of 5 new cards in 100 of 100 pairs, at no more than 0.29 ms a search. `test_dedup.py:102` then needs its expected depth changed.
2. **`refill` now reaches only as far as `off`'s merged candidate list** (`search.py:264`). That is by design, but your entry does not say it. With 50 candidates on a repo of 400 functions the list held 59 to 93 results, so the deepest page (`k + 50`) could not be reached at `k` 10 in 1 of 15 queries, at `k` 20 in 9 of 15, and at `k` 50 in 15 of 15. The note "Only N new" is then true. One sentence in the docstring would do.
3. **Two gaps in the tests.** `test_dedup.py:454` fails on `0d43ce4` only with a `TypeError`, because the keyword is missing, not on the ranking: no test asserts that the top 5 differ without `candidates_k`. The fallback test (`:311`) never goes past `candidates`.
4. **Low weight:** the short line of a moved function drops its new `best a-b` window (`dedup.py:209-211`).
5. **A nit:** `service.py:678` uses `or` where `search.py:264` uses `is None`. They differ only for 0, which cannot happen.

**Where PR #73 stands (Andre's decision, entry of 00:40 UTC).** It is a proposal: ready to merge once point 1 is fixed and `main` is merged in (one conflict, in a comment of `eval/src/cmeval/e2e_run.py`). It is on hold and not part of the first runs. We are measuring what the switch costs and gains (time, tokens, dollars) on `6146896` and post the numbers here.

## Checked

- By a review agent on Andre's Mac, on the fake model (no embedding model was loaded), in detached worktrees at `6146896` and `463171c`. We read the switch-off path and every use of `candidates_k` ourselves.
- `tests/test_dedup.py`: 25 of 25, three times. Against `0d43ce4`'s code 4 fail and 21 pass. The 8 test files that cover `search.py` and `service.py`: 226 of 226 at both commits.
- **Not checked:** the real model and real indexes; whether Claude Code sends two searches at once in a headless run, which decides how much point 1 matters; Linux, the container and Windows; the whole suite.

## Left

The measurement of the switch's cost and gain.

## Blocked on, or needed from others

- **Track B:** points 1 to 3, after the comparison of the two indexes on kubernetes (entry of 00:56 UTC), which comes first.

## Next

The lead: the numbers on cost and gain.
