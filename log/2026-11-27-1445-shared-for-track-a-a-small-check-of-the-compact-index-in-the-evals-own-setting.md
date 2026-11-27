# For track A: a small check of the compact index in the eval's own setting, before the runs if it fits

- **Track:** shared: from track C's session, for track A. Andre asked for it
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 14:45 UTC
- **Work package:** C2 (the compact index), the check run
- **Branch, commits, pull request:** none. codemem `463171c`

## Done

**Why.** The runs use the exact index (`CODEMEM_ENV` in `e2e_index.py` pins `faiss`). That is right and it stays. But it means the compact index has never answered a real agent's search. Offline it returns the same results: on your PC, the same top 10 and top 50 for every question on the pandas and playwright indexes (your entry of 06:20 UTC); on the M1, 762 of 762 searches on vLLM. Andre wants one small confirmation in the eval's own setting before the presentation says so.

**It must not delay the start at 01:00 UTC, and it changes nothing in the main runs.** If it does not fit before the start, run it beside the first batch. Its runs count in no table.

## Needed from track A, cheapest first

**1. A replay, with no seat.** Take the first `search_code` call of each run that has one (the 62 of your replay of Nov 26 are enough). Ask each query twice against the task's index: once as the runs do, and once with `CODEMEM_VECTOR_BACKEND=compact` in codemem's environment, on a copy of the index. Report:
- how many queries, and for how many the two lists are the same 10 results in the same order;
- for every query where they differ: the query, both lists, and keep that index copy;
- the median time of a search with each index;
- the line of `index_status` that names the index, once for each.

**2. Six agent runs, if there is time.** The six tasks of the check run, setup `tool`, Haiku, L2, once, with the compact index forced. It needs a way to set the index for a batch, as `CMEVAL_CODEMEM_STEERING` sets the wording: today `CODEMEM_ENV` is a constant. The saved copy of a task's index is the exact one, so the server builds the compact index from the database when it starts (seconds at pandas' size); the gate has to wait for it as it waits for the model. Report, beside the same six cells of the check run: whether the first search returned the same list, any note on a search, completed, turns, tokens and seconds.

**What we expect, so that a difference is noticed:** the same lists in every case; `index_status` naming the compact index; a search a few milliseconds slower or faster, and no large slowdown on the container's 4 CPUs.

## Checked

Nothing new: this is a request. The pin of the exact index was read in `eval/src/cmeval/e2e_index.py` on `main`.

## Left

Nothing on our side.

## Blocked on, or needed from others

**Track A:** part 1 when the PC has a quiet half hour; part 2 only if it costs the start nothing.

## Next

Andre's session: read the result when it is posted.
