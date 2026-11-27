# For track B: review of PR #73. With the switch off it equals main and can merge after one test fix; with a mode on, four defects to fix first

- **Track:** shared: track C's session reviewed track B's branch, as announced. Answers the entry of 13:28 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 14:10 UTC
- **Work package:** B8, item 2 of the announcement of 12:40
- **Branch, commits, pull request:** reviewed: `wilson/search-dedup` at `242a7bf` (PR #73), in a detached checkout on the Mac. Nothing was changed on it and nothing was pushed

## Done

Thank you for the branch: it does what the work package asked, it arrived fast, and its own numbers hold. The review ran every claim again.

### A. With the switch off: equal to main. It can merge after one small fix

- **Byte for byte on the real server.** A stdio server on copies of the real pandas index: `initialize`, `tools/list` and 45 answers (40 `search_code` with several `k`, `path_prefix`, `kinds` and `tests`; 5 `get_chunk`), about 1.17 million characters, are identical to `463171c`, with the setting unset and with `off`. The new `ctx` parameter does not show in the tool schemas. `codemem search` (22 calls) and `format_results` (1,729 comparisons) are identical too.
- **`render.py`** only moves the loop body into `format_card`. No caller sees a difference.
- **The suites on the Mac:** 752 passed; 749 passed and 3 skipped with the compact index forced; the same with FAISS forced. That is `463171c`'s counts plus your 14 tests.
- **Your E0 and E1 numbers reproduce.**
- **The one fix needed to merge (D1): an eval test fails.** `run_one` now writes `"search_dedup": "default"` into `identity.codemem`, and `eval/tests/test_e2e_run.py::test_run_one_tool_locally` compares that dict exactly: 894 passed and 1 failed on the branch, 895 passed at `463171c`. Add the key to the expected dict of that test:

```
-        "index_bytes_before": 1500, "index_bytes_after": 1600, "index_copy_removed": True}
+        "search_dedup": "default", "index_bytes_before": 1500, "index_bytes_after": 1600, "index_copy_removed": True}
```

  With it, that test and `test_codemem_mcp_config` pass. With the variable unset, the MCP config and the container's environment are unchanged.

### B. With a mode on: the three conditions held in every case we built, and four defects

What held, through the real server: a function edited inside or outside its card, and an edit still pending, never came back short; `get_chunk` is never shortened; the same query again shows every card; `refill` kept `k` new cards whenever the ranking had them; the gate's warm-up is not taken as sent.

| | What happens | The smallest case | The fix we would make |
|---|---|---|---|
| **D2** | **It fails closed.** `server.py` calls `for_client`, `depth`, `page` and `got_chunk` with no `try`. An exception there turns `search_code` or `get_chunk` into a tool error, and the ranking already computed is lost. `page()` also records results as sent while it builds the page, so a page that fails halfway leaves results recorded that the agent never got | patch `page` or `got_chunk` to raise and call the tool: `is_error=True` | wrap the calls; on an exception log it and answer the plain page (`format_results` on `resp.results[:k]`); collect the new records in `page()` and commit them only when the text is built |
| **D3** | **Overlapping calls share the memory with no lock.** The MCP library dispatches requests at once and runs sync tools in worker threads. Which of two calls in flight gets the cards is then a race, and `_forget()` can raise "dictionary changed size during iteration" while the other thread inserts, which becomes D2 | two `search_code` calls sent at once, 12 fresh sessions per mode: the first-sent call got the short lines in 6 (shorten) and 5 (refill) of 12. Two threads on one `SessionMemory` with a 1 µs switch interval: 783 errors in 8,000 pages. Through the real server at the default interval: 0 in 1,200 | a `threading.Lock` around `for_client`, `depth`, `page` and `got_chunk` (the search stays outside it); and for a true order, a ticket taken when `search_code` is entered, so that the first-sent call owns the cards |
| **D4** | **`refill` changes the ranking, not only its depth.** `search()` takes `max(config.candidates, k)` candidates a list. Refill asks for `k + min(len(sent), 50)`, so past 50 each list grows and the merged scores change | five searches of `k` = 10, then a sixth: two results that are not in `off`'s top 10 rank 6th and 8th on the refill page | keep the candidate count at what `off` uses and take more of the same merged list: a separate candidates number into `search()`, the depth only for how far the page walks |
| **D5** | **A function that moved but did not change** comes back as a full card marked "other lines this time": the card hash includes its `path:line` | insert lines above a function between two searches | hash the card without the head line's location |

**How often D3 can happen in the runs.** In our 102 Haiku sessions, 19 send two or more searches in their first search turn. In the recorded streams the second result always came 82 to 136 ms after the first, about one warm search, which fits Claude Code running codemem's calls one after the other in written order. That reading is not proven. The test that decides it: one session that sends two codemem calls in one message, against a server that logs when each request arrives and ends. If you can add that logging in your item 1 runs, please do.

**Known and unchanged:** a subagent shares the connection, so it can get a short line for a result it never saw (your own note). The page's note gives it the way back.

### C. What the agent sees

A short result is two lines, 104 to 122 characters; the note under the page is 164 characters and names both ways back. The first search is the same in every mode. With the real rule, the short form saves 10.0% of the search text of the 43 sessions that search more than once (your E1 rule gave 12.9% on the same sessions). The text is not true in three cases: "shown earlier" for a subagent and for the first of two overlapping calls (D3), and "other lines this time" for a moved function (D5).

## What we ask

1. **Item 1 first.** It is the must, and it has not started. Start its sessions, then do the fixes beside them: they need no model.
2. **D1, as a new commit on the branch** (no force push). With it, the switch can be merged while off.
3. **D2 and D3 before any mode is turned on in a run; D4 before `off` is compared with `refill`; D5 when you can.** Each with a test.
4. **A line here when each is pushed.**

## Checked

- Everything under A: run on the Mac by the review, with counts above. The defects: each shown by a script through the real server or on the class; the code was also read by Andre's session (`dedup.py`, the changes to `server.py`, the eval's runner, and `search()`'s `n = max(config.candidates, k)`).
- Not checked: Linux and the container; Windows; compaction; how Claude Code orders two calls of one message (the test above).

## Left

**Whether a mode costs quality.** Andre's condition is that a saving must not cost quality. Our sessions are running now: Haiku, 17 pandas tasks, L1 and L2, the switch off, on `shorten` and on `refill`, right function and file first, then the saving. The result follows here.

## Blocked on, or needed from others

**Track B:** items 1 to 4 above. **Andre:** the decision at the lock on whether #73 goes in with the switch off.

## Next

Andre's session: the session results, then a recommendation for the lock.
