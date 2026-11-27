# For track B: sessions with the switch of PR #73 off, on `shorten` and on `refill`. No loss of quality; the saving is 7 to 15% of the search text and does not show in tokens or cost

- **Track:** shared: track C's session ran track B's branch in sessions, as announced at 14:10 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 15:15 UTC
- **Work package:** B8, item 2 of the announcement of 12:40
- **Branch, commits, pull request:** `wilson/search-dedup` at `242a7bf` in a detached checkout on the Mac; nothing changed on it

## Done

**What ran.** Claude Code 2.1.285 with codemem over MCP from your branch, Haiku, our 17 pandas tasks at their base commits, L2 and L1, three arms that differ only in `CODEMEM_SEARCH_DEDUP`: 102 sessions, none discarded. The agent names the functions to change and edits nothing. Before the sessions: with `off`, three searches through the server returned byte for byte what `463171c` returns.

**Quality first (Andre's condition: a saving must not cost quality).**

| | `off` | `shorten` | `refill` |
|---|---|---|---|
| L2: right function in the answer (of 16) | 14 | 15 | 15 |
| L2: against `off` by task, better / same / worse | | 1 / 15 / 0 | 1 / 15 / 0 |
| L1: right function (of 16) | 15 | 15 | 16 |
| L1: against `off` by task | | 1 / 14 / 1 | 1 / 15 / 0 |
| Right file first, L2 / L1 (of 17) | 15 / 17 | 15 / 17 | 14 / 16 |

- **The switch caused none of the worse cells.** Each was read: in two of them nothing came back short at all, and in the others the only short line was an unrelated test.
- **Two runs of `off` differ by 1 to 2 tasks on the function and 2 on the file** (this run and today's earlier run of the same configuration). Every difference between the arms is inside that.

**The saving.**

| | `off` | `shorten` | `refill` |
|---|---|---|---|
| Characters of search results, all sessions, L2 | 152,384 | 138,010 (9% less) | 141,042 (7% less) |
| The same, L1 | 123,382 | 104,827 (15% less) | 111,944 (9% less) |
| Results sent short, L2 / L1 | | 32 / 14 | 28 / 17 |
| Median tokens of a session, L2 | 69,497 | 61,695 | 60,657 |
| Median tokens, L1 | 65,299 | 60,564 | 62,932 |
| Median turns | 4 | 4 | 4 |

- **Only the cut in search text is the switch's own.** Two runs of `off` differ by 8% (L2) and 37% (L1) in median tokens, so the differences in tokens, cost and turns between the arms are noise.
- **`refill`** brought 37 results onto a page from beyond the first `k`. One of them was a function of the fix. Its sessions made no fewer later calls than `off`.

**What the agents did with the 91 short results** (in 28 sessions): 15 were reopened (`get_chunk`, or a read at those lines); 29 were named in the answer, each sent as a full card earlier in the session; none was asked for by repeating the query; no agent's text mentioned the short form or acted as if a result were missing. 17 of the 31 searches with short lines were sent in the same turn as the earlier search, which is the case of defect D3.

## What follows from it

- **No mode costs quality here.** That was the condition, and it is met on these tasks.
- **The saving is real and small:** it is in the search text, and too small to show in a session's tokens or cost. `shorten` saves the most; `refill`'s extra cards paid once in 37.
- **For the lock:** nothing here needs a mode to be on in the runs. Whether #73 goes in with the switch off is Andre's decision at the lock; it needs D1 either way, and D2 and D3 before a mode is used.

## Checked

Recounted from the raw records by Andre's session: the right-function counts and pairs, the file counts, the search characters and the medians above. The transcripts of the worse cells and the use of short results were read by the agent that ran the sessions.

Not checked: Sonnet (it does not search twice); any repo but pandas; a fix run with tests; sessions long enough to be compacted; a subagent.

## Left

Nothing on our side for item 2.

## Blocked on, or needed from others

**Track B:** item 1 (the must), then D1 to D5 of the review.

## Next

Andre: the decision on #73 at the lock.
