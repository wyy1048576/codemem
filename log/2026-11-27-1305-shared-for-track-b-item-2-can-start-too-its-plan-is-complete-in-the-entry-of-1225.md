# For track B: item 2 can start too. Its plan is complete in the entry of 12:25, and Andre says: proceed, and explore

- **Track:** shared: Andre's word, for track B. It lifts the hold of the note of 12:55 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 13:05 UTC
- **Work package:** B8, B1
- **Branch, commits, pull request:** none

## Done

**The note of 12:55 said that item 2 waits for an update of the plan and of the branch. Nothing is pending: that was a misunderstanding on our side.** The plan for item 2 is the entry of 12:25 UTC, and it is complete, with its data file (`log/2026-11-27-1225-shared-data/`). Build on `main` at `463171c`, on your branch `wilson/search-dedup`, as that entry says.

**Both items are open now, in this order.**

1. **Item 1 first: codemem measured the way the runs use it** (the announcement of 12:40, repeated in the note of 12:55). It is the must.
2. **Item 2 beside it: the repeated results** (the entry of 12:25). Its first two steps, E0 and E1, call no model, so they can go while item 1's sessions run.

**What Andre wants from item 2, in his words:** he is curious whether codemem can save more by being smarter and not showing the agent what earlier searches of the session already showed. He is particular about the plan because he wants no unwanted side effect: nothing hidden from the agent, and never changed code shown as seen. You are free to explore within that. If you need something cleared up, ask here.

**The size of the prize, so that nobody expects too much** (our 102 Haiku sessions with the tool):

| Repeated results are | |
|---|---|
| of the results of second and later searches | 29% (156 of 536) |
| of all results codemem returned | 10% (156 of 1,554) |
| of all search-result text | 10%, about 20,000 tokens over 102 sessions |
| of the cost of a session that searches more than once | about 2 to 3% |

So shortening repeats alone saves a few percent. The larger question is the refill: whether giving those places to results the session has not seen saves later calls. It is not a must: if it does not pay, or keeping it right costs more than it gives, say so with the numbers and drop it.

**What stands from the announcement:** results in this log by 22:00 UTC, at the latest 23:00 UTC, with the place of the raw records; post what you have at that time. These times replace the 19:00 and 03:00 UTC written in the 12:25 entry. The lock is Nov 28, 00:30 UTC.

## Checked

The table: counted from the session data in the 12:25 data folder (Haiku, arms `tool`, `tool-v0`, `tool-q`). The cost share is an estimate: repeated text at the price of new text, against the recorded cost of those sessions.

## Left

Nothing on our side for track B's two items.

## Blocked on, or needed from others

**Track B:** a line here when item 1 has started (which tasks, which arms, which versions).

## Next

Andre's session: the review of what track B posts, from 22:00 UTC.
