# Track B: D2 and D3 of the review of 14:10 are pushed to PR #73. A failure in the memory now answers the plain page, and two calls in flight keep the order they came in

- **Track:** B. Answers D2 and D3 of the entry of 14:10 UTC (Andre)
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-27 23:35 UTC
- **Work package:** B8, item 2 of 12:40
- **Branch, commits, pull request:** `wilson/search-dedup`, new commit `0d43ce4` on top of `60685a8` (D1); no force push. PR #73 (https://github.com/wyy1048576/codemem/pull/73), not merged

## Done

- **D2, fail open.** `server.py` wraps every call into the memory. If one raises, the server logs it and answers the plain page: the first `k` results, exactly as with the switch off. `get_chunk` answers as usual and is just not recorded. `page()` and `got_chunk()` now work on copies and change the memory only once the text is built, so a page that fails halfway records nothing. This is the fix the review proposed.
- **D3, a lock and an order.**
  - Every method of `SessionMemory` holds one lock. The search itself runs outside it.
  - `search_code` takes a ticket when it is entered. It builds its page only after every earlier ticket's page is done, so of two calls in flight the one sent first gets the cards and the later one the short lines.
  - A ticket is given back in a `finally`, also when the search fails. A page waits at most 30 s for an earlier call, then goes ahead.
- **With the switch off nothing changes:** no ticket, no lock, the same path as `463171c`.

## Checked

- **7 new tests in `tests/test_dedup.py`, 21 in all, pass:**
  - a page failing on its second card records nothing;
  - with a memory whose `page` and `got_chunk` raise, every answer equals the switch-off answer, for both `shorten` and `refill` (refill had already asked for more than `k`);
  - 4 threads × 400 pages, with `depth` and `got_chunk`, on one memory with a 1 µs switch interval: no error;
  - two tickets, the later one's search done first: it waits, then gets the short lines;
  - a ticket given back without a page does not hold up the next;
  - two `search_code` calls sent at once through the real server: neither is an error, and exactly one page has the short lines.
- **The old code fails the new tests:** on `242a7bf` the test of the page failing halfway, both plain-page tests and the threads test fail.
- **The fast suite on Windows:** 749 passed and 7 failed. 6 of these are the same failures as on a clean `463171c` here. The seventh, `test_frontends.py::test_a_search_embeds_its_own_edit_first`, only checks that a search takes less than 1 s, and it loads neither `server` nor `dedup`. Rerun alone, it passed 4 times out of 4.
- `test_off_is_byte_for_byte_main` still passes.
- **Not checked:** Linux, the container, the timing test that the review proposed (logging when each request arrives and ends).

## Left

- **D4:** refill should keep `off`'s candidate count. **D5:** a function that moved but did not change should not be marked "other lines this time".
- The 13:25 case (results seen only by name) in the write-up.
- Item 1 is running (entry of 23:20).

## Blocked on, or needed from others

**Andre:** D1 to D3 are in. That covers what the review asked for before a merge with the switch off (D1), and before any mode is used in a run (D2, D3).

## Next

Wilson, with Claude Code: D4 and D5 if time allows; item 1's results.
