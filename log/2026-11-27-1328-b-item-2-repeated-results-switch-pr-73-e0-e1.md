# Track B, item 2: the switch for repeated results is on a branch, PR #73 (off by default); E0 reproduces the 12:25 table; E1: shortening alone saves little

- **Track:** B. Answers item 2 of the entries of 12:25 and 12:40 UTC (Andre), with a part for track A (Andrew)
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-27 13:28 UTC
- **Work package:** B8 (the integration), item 2 of 12:40
- **Branch, commits, pull request:** `wilson/search-dedup` off `463171c`, commit `242a7bf`, PR #73 (https://github.com/wyy1048576/codemem/pull/73), not merged. E0 and E1: `eval/experiments/search-dedup/` on that branch

## Done

**The switch.** `search_dedup` in the config, or the environment variable `CODEMEM_SEARCH_DEDUP`: `off` (the default), `shorten`, `refill`. New file `src/codemem/dedup.py`; `server.py` keeps one memory per session in `build_server`.

- **What the server remembers**, per chunk key: the `content_hash` when sent, a hash of the card text (without its number), card or full (`get_chunk`), and at which tool call. Nothing on disk; no change to the index, the ranking, the chunks, any default, or the tool list (`tools/list` is byte-for-byte that of `463171c`).
- **When a result comes back short.** All must hold: sent in this session at most 10 tool calls ago (`search_dedup_forget_calls`); the same `content_hash` now; the card would read the same, or it was sent in full by `get_chunk`; the index current for this search (`Freshness.complete`, and the answer not from keywords only); and the query not one this session already sent (same words, `path_prefix`, `kinds`, `tests`).
- **The short form is two lines, not one:** the head line exactly as on a card (`N. path:a-b  name  [id N]`), then `   (shown earlier as a card, unchanged)` or `(… in full by get_chunk, unchanged)`. About 110 characters against a card's 450. The mark is on its own line because track A's parser (`e2e_replay._HEAD`) reads a head line only when nothing follows `[id N]`. Andre, say if you want it another way.
- **Otherwise a full card,** with a mark line when it was sent before: `(changed since shown earlier)`, or `(shown earlier, other lines this time)` for the same code with another preview window. Repeats keep their place in the order.
- **`refill`** asks the ranking for up to 50 more and walks on until the page has `k` full cards; with fewer, the page says how many are new. **`shorten`** keeps the same `k` results as `off`.
- **Getting the card back:** `get_chunk(id)`, never shortened; or the same query again, which shows every result as a card. A note under the page says both.
- **A session is one MCP client.** Track A's gate does its own handshake and warm-up search on the same process before Claude Code's handshake. The memory resets when the client's name and version change, so the gate's warm-up is never taken as sent, and the agent's first search is a full page (test).

**For track A (Andrew).** `CMEVAL_CODEMEM_SEARCH_DEDUP=off|shorten|refill` sets the mode for a batch, like `CMEVAL_CODEMEM_STEERING`; unset, codemem's default (`off`). `run.json` records it under `identity.codemem.search_dedup`; `eval/README.md` says so. Unset, nothing in a run changes. The first search of a session is the same in every mode, so the first-search counts are not touched.

**E0: the counts of the 12:25 table, reproduced exactly** from `log/2026-11-27-1225-shared-data/` (Haiku, arms `tool`, `tool-v0`, `tool-q`): 102 sessions; one / two / three / four or five searches: 59 / 27 / 9 / 7; 43 searched more than once; 536 results in their later searches, 156 already sent (29%); 13 of 43 with a function of the fix in a later search that the first did not have. Sonnet: no session searched twice.

**E1: `shorten`, replayed on the same sessions** (no model call; a short result counted as 110 characters, tokens = characters / 4; text a result adds is read again from the cache on every later turn):

| Forget after this many tool calls | Search text saved, of 777,507 characters | Sessions that save | New-text tokens saved | Cache-read tokens saved |
|---|---:|---:|---:|---:|
| never | 62,436 (8%) | 39 | 15,609 | 56,028 |
| 10 (the default) | 62,436 (8%) | 39 | 15,609 | 56,028 |
| 3 | 52,379 (7%) | 36 | 13,095 | 47,089 |

Against the bill of the 43 sessions that searched more than once (469,357 new-text tokens, 3,945,485 cache reads), shortening saves about 3% of the new text and 1.4% of the cache reads. **So `shorten` alone is a small saving.** What `refill` brings cannot be replayed: the records hold no ranking below the 10 cards. That needs E3.

**Question 2 of 11:45, now with the switch:** still no MCP run shows codemem worse than grep. The switch changes nothing for a session that searches once, which is most sessions (59 of 102 for Haiku; all 34 for Sonnet).

## Checked

- `tests/test_dedup.py`, 14 tests: the first search the same on and off; repeats short, in order; refill to `k` new cards; an edit between two searches, through the MCP server after `update`, comes back in full and marked; never short when the index is not current; another preview window gives a full card; the same query again gives every card; `get_chunk` unchanged and counted; forgetting; the switch; **off byte-for-byte equal to main's `format_results`** (a copy of main's function in the test); track A's `_HEAD` pattern reads every result of a page, short or not; a gate session followed by an agent session.
- The fast suite on Windows: 743 passed, 6 failed; the same 6 fail on a clean `463171c` on this machine (CRLF fixtures, worktree paths, container memory).
- The eval: the new assertions are in `test_codemem_mcp_config`, which cannot run on Windows (its setup makes symlinks); the setting was checked by hand (passes the mode, refuses `on`). `test_e2e_run.py` and `test_e2e_replay.py` fail the same 16 tests with and without the change.
- **Not checked:** E3 (Claude Code sessions, off / shorten / refill), E4 (stale-view transcripts), E5 (compaction; a subagent shares the main agent's process and client name, so it may get a short line for a result it never saw, and needs `get_chunk` or the same query), Linux, the eval's container.

## Left

- E3 to E5 of the 12:25 entry.
- **Item 1 of 12:40 (the must) has not started:** codemem over MCP against grep, Haiku and Sonnet, `463171c`, track A's `tool` setup. Track B's local `mcp` arm (PR #45's harness) runs the older `7c24558` with hooks and an appended prompt, so it does not count for item 1.

## Blocked on, or needed from others

- **Andre:** review PR #73, and decide at the lock whether it goes in; and whether two lines for a repeat is acceptable.
- **Andrew:** nothing needed; the setting is there if a batch wants it.

## Next

Wilson, with Claude Code: item 1, then E3.
