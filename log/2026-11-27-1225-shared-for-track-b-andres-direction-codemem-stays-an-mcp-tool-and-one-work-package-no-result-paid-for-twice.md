# For track B, Andre's direction: codemem stays an MCP tool inside the agent, a task starts with a codemem search, and one work package full time: a later search must not pay again for results already shown

- **Track:** shared: from track C's session, for track B. This is the direction announced at 09:55 UTC. It replaces the renaming control and the hybrid work for now
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 12:25 UTC
- **Work package:** B8 (the integration), B1
- **Branch, commits, pull request:** none yet. Data for part 2: `log/2026-11-27-1225-shared-data/sessions-with-codemem-searches.jsonl`

## Done

**For whoever runs this:** please use the strongest model you have for the design, the review of results and the write-up: Claude Fable 5.2, or Opus 5.5 at max effort. The agents under test stay Haiku and Sonnet. We check the branch and every number against the raw records tomorrow, so keep the records.

**The lock** is today 20:00 UTC and it is soft for this work: if part 2 is right by then, or by the evening, Andre decides whether it goes in. So everything below is built behind a switch that is off by default.

## Part 1. The frame for everything track B builds from here

1. **MCP style.** Whatever track B explores has to work as codemem inside a coding agent: what `search_code` and `get_chunk` return, their arguments, what the server remembers within one session, or text placed in the first message. Not a program that replaces the agent. A Python harness is fine for exploring an idea, but the write-up must say how the idea becomes behaviour of the MCP server, and the result that counts is measured in Claude Code with codemem over MCP.
2. **A task starts with a codemem search that returns enough:** 10 results as cards, or 20 by name. All three tracks see it: in our sessions 20 names in the first message cut turns against grep in 13 of 17 tasks for Haiku and 12 of 17 for Sonnet; in your runs Sonnet chose codemem at step 1 in 46 of 70 and in 3 of 133 later steps; in track A's runs the agent makes one call in its first three turns. After that the agent greps precisely. That is codemem's job: fewer blind exploring calls at the start.
3. **Stay inside the prompt cache, and count cost the same way for every arm.** One conversation, tool descriptions that never change, results only appended. For every arm report tokens by kind (new text written, re-read from the cache, output), turns, seconds and cost. Never dollars alone.
4. **On hold:** the hybrid and loop-k work, a new index with smaller chunks, the overnight index of the largest repo for the loops, and the renaming control. Andre: renaming is future work, not for Dec 1. Please stop the large index run if it has started; the machine is needed for part 2.

## Part 2. The work package: no result paid for twice in one session

### The problem, measured

`search_code` returns its 10 best results every time, whether or not this session has already been sent them. Each repeated card is new text again (the dear part of the bill) and is then re-read on every later turn.

One session (pandas 70205, Haiku, two searches): 6 of the second search's 10 results had been sent by the first, about 60% of its 9,029 characters.

Over our Haiku sessions with the tool (Claude Code 2.1.285, 17 pandas tasks, L1 and L2, main's result page):

| | |
|---|---|
| Sessions | 102 |
| Searches per session | one: 59, two: 27, three: 9, four or five: 7 |
| Sessions that searched more than once | 43 |
| Results returned by those later searches | 536 |
| Of them, already sent earlier in the session | 156 (29%) |
| Sessions where a later search found a function of the fix that the first had missed | 13 of 43 |

Sonnet never searched twice (34 sessions). The file in the data folder has all 210 sessions, one line each: arm, model, level, task, turns, tokens by kind, cost, and every `search_code` and `get_chunk` call with its turn, query, the cards returned in order (`path:line name`) and the size of the result.

### What Andre wants, in his order

- **2.1 Do not send again what the session has already been sent.** That is the inefficiency.
- **2.2 Do not restrict the agent.** It may search again, with the same or other words, and it may want the same function again: to check that it is current, to verify, to use it. A later search is often the useful one (13 of 43 above). Nothing may be hidden from it or made harder to get.
- **2.3 No systematic error.** The worst case is code that changed while the agent is told it has seen it. A wrong "seen" is worse than a repeated card.
- **The number of results must not shrink.** The point is not to show less. A slot that a repeat would have taken should go to a result the session has not seen.

### What the code gives you (main, `463171c`)

- **One server process per agent session** (`server.py`, `run_stdio`), so what the session was sent can be kept in memory in `build_server`. No file, no index change.
- **A card** (`render.format_results`): a head line with `path:line`, the name and `[id N]`; the signature; the first docstring line; at most 6 preview lines. About 450 characters. `card_label` gives the name alone.
- **A chunk's id does not change when its code changes** (`Store.upsert_chunk`: "chunk_id is stable across updates"). Its `content_hash` does. So an id alone cannot say "seen".
- **The preview depends on the query** for a long function (`ResultCard.best_lines`, the best-matching window). The same function can come back with other lines.
- **Freshness is already tracked:** `resp.freshness`, `store.pending_paths()`, and the note `freshness_note` puts under a result when edits are not indexed yet.
- **`search_code` caps `k` at 50,** and each of the three lists holds `candidates` = 50 before the merge.

### A starting design (yours to improve or replace, with evidence)

1. **What the server remembers per session,** for each chunk key (`path::qualname`): the `content_hash` it had when sent, a hash of the card text that was sent (without its rank number), how it was sent (card, or in full by `get_chunk`), and at which call.
2. **A search walks its ranking in order.** For each result:
   - never sent: a full card;
   - sent, same `content_hash`, and the card would read the same: **one line**, with today's `path:line`, the name, and "shown earlier, unchanged";
   - sent, but the `content_hash` differs: a **full card, marked "changed since it was shown"**;
   - sent, same code, but the preview would show other lines: decide by experiment (a full card, or only the new lines);
   - in a file with edits that are not indexed yet: never one line.
3. **It goes on until it has shown `k` full cards,** or the ranking ends, or a depth limit. Repeats keep their place in the order, so the agent still sees that a known function ranks first again. If fewer than `k` new results exist, the page says so.
4. **`get_chunk` is never shortened.** It always returns the current code in full.
5. **The agent can always have the full card again.** Candidates: nothing new (the one line has `path:line`, and `get_chunk` or a file read gets the rest); the same query text sent again gives a full page; or one new argument. Fewest moving parts that pass the tests wins.
6. **Forgetting.** The server cannot see the agent's context. After Claude Code compacts a long conversation, or when a subagent calls the tool, "sent" no longer means "the model has it". Candidates: forget after a number of calls or minutes; the same-query rule of point 5; a line that always carries enough to reopen. Settle it with the tests of E5.
7. **No filter inside the vector index is needed to start.** Skipping a few dozen sent results in a merged ranking of up to 150 candidates leaves enough. If a session outruns that, raise the candidates for that call, or pass an exclusion set to the store (FAISS has id selectors, and the compact store already searches under a selector). Measure first.

Andre's own questions, which the write-up should answer: is hashing what was sent the right test of "seen"; and is skipping in the ranking enough, or is a filter in the index needed?

### What to find out (your judgement, and reading up is welcome)

- **One line, or one line plus the signature?** What is the least the agent needs to act on a repeat without asking again?
- **Refill or only shorten?** Refill (always `k` new cards) is what Andre asks for. Shorten-only is the control that shows what a page saves. Does refill bring in useful results, or only deeper noise?
- **How do other tools handle it?** Agents with retrieval, IDE search, iterative retrieval in the research literature: look for what is known about showing seen results again, and say what you took.
- **Results seen in full through `get_chunk`,** or named only (the "more results by name" of `andre/search-recall`): how should a later search treat each?
- **Anything else you find that makes a later search cheaper without hiding anything.** You have room here. Say what you tried and what you dropped.

### Experiments, in this order

- **E0. Reproduce the measurement** from the data file with your own script: the table above, and the tokens a session pays for repeats. One hour. It checks our numbers and gives you the simulator's input.
- **E1. Simulate before building.** Replay each recorded session's searches under each rule (shorten, refill, with and without forgetting): text saved, new results gained, and at which search a function of the fix would first appear. No model call. Use it to drop weak variants.
- **E2. Build it behind a switch that is off by default,** on a branch off `463171c`. With the switch off, every output is byte-for-byte what main returns: a test proves it. Unit tests, at least:
  - the first search of a session is identical with the switch on and off;
  - a second search turns repeats into one line and fills up to `k` new cards;
  - a function edited between two searches comes back in full, marked as changed;
  - a result in a file with pending edits is never shortened;
  - a long function whose preview window differs is handled as you decided;
  - `get_chunk` is unchanged;
  - whatever lets the agent get the full card again works;
  - the forgetting rule.
- **E3. Sessions in Claude Code with codemem over MCP.** Arms: switch off, shorten, refill. Haiku first: it searches again in 43 of 102 sessions. Then Sonnet, with the 20 names in the first message, to see that nothing breaks where the tool is rarely called. Tasks: your 35 at L1 and L2. At least two runs per cell, because one run cannot show a small effect: in our data two runs of the same arm differ by about 3 tasks of 16 on what the first search shows. Report per arm and as pairs by task: searches per session, repeats sent, text of search results, tokens by kind, cost, turns, seconds, the functions of the fix edited or named, and how often the agent reopened a shortened result.
- **E4. The stale-view test.** Scripted sessions in which a function is edited between two searches, by the agent and from outside, with the index current and with the edit still pending. The agent must be shown the new code every time. Read the transcripts: does the agent ever say it has seen something it has not?
- **E5. Compaction and subagents.** A session long enough to be compacted, then a search. A subagent that searches after the main agent did. Does the agent recover what it needs?
- **E6. If time allows:** fix runs graded by track A's tests.

### Rules for the runs, so that they count

- **codemem `463171c`** and your branch on top of it. Not the copy at `7c24558`.
- **The server must be loaded before the first search.** Use track A's gate (`eval/src/cmeval/codemem_gate.py`) where it runs, or set `catchup_budget_ms` high in `$CODEMEM_HOME/config.toml` so that the first search waits for the model. Drop any session in which a result holds a loading note, and say how many.
- **One repo copy and one index per session.** No folder shared between sessions.
- **Claude Code as the agent,** with codemem over MCP and the same built-in tools in every arm. State the version, the tools and the flags.
- **Keep every stream and every request body.** We recount from them.

### Done when

- With the switch off, nothing changes (the byte-for-byte test passes, and the whole suite passes).
- With it on: no case, in tests or transcripts, where changed code is shown as seen; the first search is unchanged; nothing the agent asked for was withheld.
- Sessions that search more than once pay for less repeated text, and the functions of the fix are found at least as often, pair by pair, beyond the difference between two runs of the same arm.
- The write-up says which variant you recommend, what it saves in tokens by kind and in cost, what it costs, and what you could not check.

### What comes back, and when

- **A branch** `wilson/search-dedup` off `463171c`, one pull request, the switch off by default. No change to the ranking, the index, the chunk sizes or any default.
- **A results file** with the tables and the raw records beside it, and a log entry in the usual form.
- **A first report by 19:00 UTC** (E0, E1, the design you chose, the state of E2), so that Andre can decide at the lock. **The full report by Nov 28, 03:00 UTC.** Post what you have at each time; do not wait for the rest.

## Checked

- The table: counted from the raw session records on the Mac (102 Haiku sessions of the arms `tool`, `tool-v0` and `tool-q`; yesterday's 34 alone give 67 of 217, 31%).
- The facts about the code: read at `463171c`.
- Not checked: anything about compaction or subagents; any of this on Windows.

## Left

Track C's session reviews the branch and the findings when they arrive.

## Blocked on, or needed from others

**Track B:** part 2, full time, and the two answers asked at 11:45 UTC. **Track A:** nothing now. If this goes in, a later search's result text has a new one-line form; the first search of a session is unchanged, so the first-search counts of the runs are not touched.

## Next

Wilson, with his agent: E0 and E1 first, then E2. Andre: the decision at the lock, and again in the evening.
