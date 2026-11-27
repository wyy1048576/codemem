# Track B, retrieval: status

**Owner:** Wilson. **Plan:** `docs/plan/track-b-retrieval.md` on `main`.
**Updated:** 2026-11-27 23:15 UTC, by Wilson (with Claude Code). Rows marked "from Nov 22" are carried over from an earlier status and were not checked again.

| | |
|---|---|
| Focus | **codemem as an MCP tool inside Claude Code** (Andre's direction, entries of 12:25 and 12:40 UTC). The loops and the hybrid replace the agent and are on hold as evidence only (answer of 12:56). Item 1 (the must): codemem over MCP against grep, Haiku and Sonnet, `463171c`, by 22:00 UTC. Item 2: no result paid for twice in a session |
| Now | **Item 1 has not run.** It missed 22:00 and 23:00 UTC. **Item 2:** PR #73 (`wilson/search-dedup`, now at `60685a8`). D1 of the review of 14:10 is fixed, so the switch can merge while off. D2 (fail open), D3 (a lock), D4 (refill keeps the candidate count) and D5 (moved, unchanged code) are open. They must be fixed before any mode is used in a run. Andre's sessions (15:15): no mode costs quality, and the saving is 7 to 15% of the search text. (Entry of 23:15.) |
| Done | Answer to the 11:45 questions (12:56). PR #45: the loop, hybrid and hybrid_v2 results (evidence only). On `main` with #26: the `light` wording, the two hooks, `init --write-hooks`, the agent note, `alwaysLoad` |
| Next | 1. Item 1: Claude Code + codemem over MCP (`tool` setup) against grep, Haiku and Sonnet, codemem `463171c`, with the checks of the 13:15 entry. 2. D2 and D3, then D4 and D5, each with a test. 3. The 13:25 case (results seen only by name) in the write-up of item 2. 4. Held: renaming control, the loop work |
| Blocked on | nothing |
| Needs from other tracks | C: the decision at the lock (00:30 UTC Nov 28) on whether #73 goes in with the switch off. A: grade the saved diffs in PR #45 if still wanted |
| Gives to other tracks | A: `CMEVAL_CODEMEM_SEARCH_DEDUP` (PR #73) for a batch with the switch; unset changes nothing, and no index needs a rebuild. A: the `light` wording on `main` is #26's |
| Dates | Track B's results in this log by 22:00 UTC (latest 23:00), Nov 27. The lock: Nov 28, 00:30 UTC. Runs from 01:00 UTC. Results frozen Dec 1, 07:59 UTC. Presentation Dec 1, 22:00 UTC. Dec 8: the paper on arXiv |
