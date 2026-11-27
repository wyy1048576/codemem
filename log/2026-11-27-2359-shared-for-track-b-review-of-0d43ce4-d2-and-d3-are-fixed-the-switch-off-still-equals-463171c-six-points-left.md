# For track B: review of `0d43ce4` on PR #73. D2 and D3 are fixed, the switch off still equals `463171c`, and six points are left; none blocks `shorten`

- **Track:** shared: from the lead, for track B. Answers your entry of 23:35 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 23:59 UTC
- **Work package:** B8, item 2
- **Branch, commits, pull request:** `wilson/search-dedup` at `0d43ce4`, PR #73. `6146896` (D4 and D5) came in while this review ran and is not reviewed yet

## Done

**The verdict on `0d43ce4`.**

1. **D2 is fixed as asked.** When `page()` fails halfway or `got_chunk()` fails, the agent gets the switch-off answer byte for byte, in both modes, and nothing is recorded.
2. **D3 is fixed in substance.** Threads no longer raise. On the real stdio server the call sent first got the cards in 800 of 800 pairs. At `242a7bf` it went the other way in 6 of 12 and 5 of 12.
3. **The switch off is still `463171c`.** No ticket, no lock and no memory call on that path (`server.py` 62 to 63, and 113). 86 of 86 answers are byte for byte the same, with the setting unset and with `off`.
4. **`shorten` is safe to turn on in an eval run.** Nothing we found can hang a call, fail it, or slow it beyond the 30 s bound. `refill` should wait for D4 before it is compared with `off`.

**Why the blocking wait is harmless.** mcp 2.3.0 starts requests at once and runs sync tools on worker threads, so the wait never holds the event loop. During a full 30 s wait, `index_status` answered in 0.02 s and `get_chunk` in 0.007 s.

**What is left, by weight.**

1. **`refill`, two calls in flight** (`server.py:71`, `dedup.py:141`). The later call reads its depth before the earlier page is recorded. It got 2 new cards and "Only 2 of these results are new" in 200 of 200 pairs, against 5 cards when the calls were sent one after the other. Fix, once D4 is in: always ask `refill` for `k + REFILL_DEPTH`.
2. **A cancelled search is still recorded** (`dedup.py:160-164`). mcp drops its answer, yet a later search showed all 5 of its results as "shown earlier". It was so at `242a7bf` already. We found no small fix in mcp 2.3.0.
3. **The ticket is taken on the worker thread** (`server.py:66`). Over stdio the order never flipped (0 of 800). With the in-memory client the request that arrived second got the cards in 5 of 150 pairs, and in 30 of 30 with a delay of 20 ms put in.
4. **`refill`'s fallback page** (`server.py:99`) equals `off` only while the depth is at most `candidates` (`search.py:259`). This is D4.
5. **The tests do not check the order.** `test_two_searches_sent_at_once_through_the_server` does not check which call got the cards, and it passes on `242a7bf`. Nothing tests the 30 s path or a cancel.
6. **Minor.** A failing `for_client` or `depth` (`server.py:69-74`) still answers a memory page; `ticket` and `release` are unguarded; no log line is written when the 30 s wait runs out (`dedup.py:125`).

**What we ask.**

- A test that fails when the later call gets the cards, and one for the 30 s path (point 5).
- Point 1 together with D4.
- One sentence in the write-up on what a cancelled call does (point 2).

**PR #73 and the lock.** Andre decides. Our advice to him is that it stays out of the lock of 00:30 UTC: with the switch off it changes no run, and a new codemem commit makes track A build every index and block again. It can merge after the freeze. It also needs `main` merged in first: one conflict, in a comment of `eval/src/cmeval/e2e_run.py`.

## Checked

- By a review agent on Andre's Mac, on the fake model (no embedding model was loaded), in detached worktrees at `0d43ce4` and `463171c`. We read the switch-off path in `server.py` ourselves.
- `tests/test_dedup.py`: 21 of 21, three times. `test_frontends.py`, `test_model_idle.py` and `test_worktrees.py`: 156 passed at both commits. The new tests on `242a7bf`'s code: 6 fail and 15 pass.
- Tickets come back after a failing search (the next call took 0.02 s), a cancel (2.42 s) and a timeout (30.02 s, then 0.018 s). None was left open in 8 server runs, about 1,900 tickets. No slow-down: 11.1 ms median for the second call against 10.8 ms alone.
- **Not checked:** how often Claude Code cancels a codemem call in a headless run. Calls in flight do happen: in our sessions of 15:15 UTC, 17 of the 31 searches with short lines were sent in the same turn as the earlier search. Also not checked: the real model and real indexes, Linux, the container, Windows, and `6146896`.

## Left

The review of `6146896` (D4 and D5).

## Blocked on, or needed from others

Nothing.

## Next

We review `6146896`, and post the lock entry at 00:30 UTC.
