# Track B: D4 and D5 of the review of 14:10 are pushed to PR #73, so all five defects are fixed. Refill now keeps off's ranking, and a function that only moved is the same card

- **Track:** B. Answers D4 and D5 of the entry of 14:10 UTC (Andre)
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-27 23:50 UTC
- **Work package:** B8, item 2 of 12:40
- **Branch, commits, pull request:** `wilson/search-dedup`, new commit `6146896` on top of `0d43ce4`, no force push. The branch now holds `242a7bf`, then D1 `60685a8`, D2 and D3 `0d43ce4`, D4 and D5 `6146896`. PR #73 (https://github.com/wyy1048576/codemem/pull/73), not merged

## Done

- **D4: refill keeps off's ranking.** This is the fix the review proposed. `search()` takes a new keyword `candidates_k`: the `k` that each signal's candidate count is set for, which defaults to `k`. With the switch on, the server passes the page's `k`. So a refill page takes the same candidate lists as `off` and only reads further down the same merged list: its first `k` results are `off`'s. The keyword results that are embedded before a search use the same count. With the switch off, nothing new is passed.
- **D5: a function that only moved is the same card.** The card hash now leaves out the head line (the number on the page and `path:line`). The best lines are counted from the chunk's first line. So lines added above a function no longer mark it "other lines this time", and its short line gives its current place. A different best window, or different preview lines, still makes a full card marked "other lines this time" (an older test).

## Checked

- **4 new tests in `tests/test_dedup.py`, 25 in all, pass.** All 4 fail on `0d43ce4`.
  - With `candidates = 3` on the sample repo: a search of 25 with `candidates_k = 5` keeps the 5-result page's top 5, on 5 queries. Without `candidates_k` the top 5 differ on all 5 queries: that is D4, reproduced.
  - Through the server, every refill page lists `off`'s top 5 first, as cards or short lines.
  - A moved card comes back short, with its new lines.
  - Through the server, 3 lines added above `revoke_session` give its short line, 3 lines lower, and no "other lines".
- **The fast suite on Windows:** 753 passed and the same 7 failed as in the entry of 23:35. 6 also fail on a clean `463171c` here. The seventh is the timing test `test_a_search_embeds_its_own_edit_first`: it passed 3 times out of 3 run alone, while item 1's runs were using this laptop.
- **Not checked:** Linux and the container; how Claude Code orders two calls in one message (the timing test the review proposed).

## Left

- The 13:25 case (results seen only by name) in the write-up of item 2.
- Item 1 is running (entry of 23:20).

## Blocked on, or needed from others

**Andre:** all of D1 to D5 are in. Please decide at the lock whether #73 goes in with the switch off. The review asked for D2 and D3 before any mode is used, and for D4 before `off` is compared with `refill`.

## Next

Wilson, with Claude Code: item 1's results; the write-up of item 2.
