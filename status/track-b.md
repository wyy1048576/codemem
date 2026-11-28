# Track B, retrieval: status

**Owner:** Wilson. **Plan:** `docs/plan/track-b-retrieval.md` on `main`.
**Updated:** 2026-11-28 00:40 UTC, by Wilson (with Claude Code). Rows marked "from Nov 22" are carried over from an earlier status and were not checked again.

| | |
|---|---|
| Focus | **codemem as an MCP tool inside Claude Code** (Andre's direction, entries of 12:25 and 12:40 UTC). The loops and the hybrid replace the agent and are on hold as evidence only (answer of 12:56). Item 1 (the must): codemem over MCP against grep, Haiku and Sonnet, `463171c`, by 22:00 UTC. Item 2: no result paid for twice in a session |
| Now | **Item 1, Haiku: done, late** (entry of 00:40): over 14 tasks, neither codemem arm edits more of the fix than grep, and both cost more in most pairs; Sonnet not done. **Item 2:** PR #73 (`6146896`), D1 to D5 fixed; Andre's review of 23:59 leaves four points (an order test, the 30 s path, refill with calls in flight, a cancelled call). **PR #85** (`wilson/no-hooks`, for after the freeze): no hooks, when to search in the wording, `k` 1 to 10, an augmented query that the agent fills in (entry of 00:40) |
| Done | Answer to the 11:45 questions (12:56). PR #45: the loop, hybrid and hybrid_v2 results (evidence only). On `main` with #26: the `light` wording, the two hooks, `init --write-hooks`, the agent note, `alwaysLoad` |
| Next | 1. PR #73: the points of 23:59. 2. Sessions for PR #85 (Haiku first). 3. Item 1: Sonnet and a second run per cell, if still wanted. 4. The 13:25 case (results seen only by name) in the write-up of item 2 |
| Blocked on | nothing |
| Needs from other tracks | C: the decision at the lock (00:30 UTC Nov 28) on whether #73 goes in with the switch off. A: grade the saved diffs in PR #45 if still wanted |
| Gives to other tracks | A: `CMEVAL_CODEMEM_SEARCH_DEDUP` (PR #73) for a batch with the switch; unset changes nothing, and no index needs a rebuild. A: the `light` wording on `main` is #26's |
| Dates | Track B's results in this log by 22:00 UTC (latest 23:00), Nov 27. The lock: Nov 28, 00:30 UTC. Runs from 01:00 UTC. Results frozen Dec 1, 07:59 UTC. Presentation Dec 1, 22:00 UTC. Dec 8: the paper on arXiv |
