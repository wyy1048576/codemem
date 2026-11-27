# Track B, retrieval: status

**Owner:** Wilson. **Plan:** `docs/plan/track-b-retrieval.md` on `main`.
**Updated:** 2026-11-27 13:28 UTC, by Wilson (with Claude Code). Rows marked "from Nov 22" are carried over from an earlier status and were not checked again.

| | |
|---|---|
| Focus | **codemem as an MCP tool inside Claude Code** (Andre's direction, entries of 12:25 and 12:40 UTC). The loops and the hybrid replace the agent and are on hold as evidence only (answer of 12:56). Item 1 (the must): codemem over MCP against grep, Haiku and Sonnet, `463171c`, by 22:00 UTC. Item 2: no result paid for twice in a session |
| Now | **Item 2 built:** PR #73 (`wilson/search-dedup`, `242a7bf`, off `463171c`): the switch `search_dedup` = off (default) / shorten / refill; a result the session was sent, unchanged, comes back as its head line and `(shown earlier …, unchanged)`; changed code in full and marked; refill keeps `k` full cards. Off is byte-for-byte main (test); tool list unchanged; track A's `CMEVAL_CODEMEM_SEARCH_DEDUP` sets it for a batch. E0 reproduces the 12:25 table exactly; E1: shorten saves 8% of search text, about 3% of new text and 1.4% of cache reads in sessions that search twice (entry of 13:28). **Item 1 not started** |
| Done | Answer to the 11:45 questions (12:56). PR #45: the loop, hybrid and hybrid_v2 results (evidence only). On `main` with #26: the `light` wording, the two hooks, `init --write-hooks`, the agent note, `alwaysLoad` |
| Next | 1. Item 1: Claude Code + codemem over MCP (`tool` setup) against grep, Haiku and Sonnet, codemem `463171c`, the checks of the 13:15 entry, results here by 22:00 UTC. 2. Item 2, E3: sessions off / shorten / refill, Haiku first, two runs per cell; then E4 (stale view) and E5 (compaction, subagents). 3. Held: renaming control, the loop work |
| Blocked on | nothing |
| Needs from other tracks | C: review PR #73 and the decision at the lock (00:30 UTC Nov 28); whether two lines for a repeat is acceptable. A: grade the saved diffs in PR #45 if still wanted |
| Gives to other tracks | A: `CMEVAL_CODEMEM_SEARCH_DEDUP` (PR #73) for a batch with the switch; unset changes nothing, and no index needs a rebuild. A: the `light` wording on `main` is #26's |
| Dates | Track B's results in this log by 22:00 UTC (latest 23:00), Nov 27. The lock: Nov 28, 00:30 UTC. Runs from 01:00 UTC. Results frozen Dec 1, 07:59 UTC. Presentation Dec 1, 22:00 UTC. Dec 8: the paper on arXiv |
