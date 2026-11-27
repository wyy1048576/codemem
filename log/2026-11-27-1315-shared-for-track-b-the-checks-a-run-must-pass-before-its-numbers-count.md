# For track B: the checks a run must pass before its numbers count. They hold for item 1 and for item 2

- **Track:** shared: from Andre, for track B. It adds to the announcement of 12:40 and the entry of 12:25
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 13:15 UTC
- **Work package:** B8, B1
- **Branch, commits, pull request:** none

## Done

Earlier runs of track B were lost to set-up faults that nobody saw at the time (answers from keywords only, a shared repo copy). So before a run's numbers go into a table, check these. Put the counts in your entry: how many runs passed each check, and how many were dropped and why.

1. **codemem really returns code, found by meaning.**
   - Every `search_code` result lists functions or classes, each with its `path:line`, its signature and lines of its code, as plain text. A result that is only a list of files, a JSON string, or "No results" on a sensible query is a fault: stop and look.
   - No result holds a loading note ("still loading", "cannot embed"). A session with one is dropped and counted.
   - At the start of a run, `index_status` says ready, names the task's base commit and the embedding model, and has a chunk count above zero.
2. **The index is the code the agent sees.** It is built from that run's own repo copy at the task's base commit, with codemem `463171c`. One copy and one index per run.
3. **The arms differ in codemem only.** The same model id, Claude Code version, flags, built-in tools and prompt. Say which built-in tools are on, and whether the shell is: track A's setups have it on.
4. **The cache is on.** Each run's usage shows tokens read from the cache. Give tokens by kind.
5. **The model that answered is the one named.** Claude Code's own side calls to another model are reported apart.
6. **"Found" is counted for functions and for files, apart.** A function of the fix among a search's results, and at which place; and in the agent's edit or answer. A right file with the wrong function is not a function hit.
7. **Count what the agent did with codemem:** how often it called `search_code` and `get_chunk`, at which turn, and its next step after a search.
8. **Two runs per cell where time allows, and pairs by task.** Give the difference between two runs of the same arm, so that a reader can tell an effect from chance.
9. **Keep every stream and every request body.** We recount from them.

If a check cannot be made on your machine, say so in the entry; do not skip it silently. If something here is unclear, ask in this log.

## Checked

Nothing to check: these are the checks themselves.

## Left

Nothing on our side.

## Blocked on, or needed from others

**Track B:** the counts of these checks, with the results.

## Next

Andre's session: the review of what track B posts, from 22:00 UTC.
