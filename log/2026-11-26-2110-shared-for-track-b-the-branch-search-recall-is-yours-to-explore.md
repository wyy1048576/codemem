# For track B (Wilson's agent): `andre/search-recall` is not merged and is yours to explore. Its four parts, what each gave, what nobody has tried, and how to run a combination

- **Track:** shared: from track C's session, for track B; point 6 is for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 21:10 UTC
- **Work package:** B-E3, B-E7 (what a search returns), B8 (does the agent use it)
- **Branch, commits, pull request:** `andre/search-recall` (tip `1c48f2c`, merged with `main` `e6f2d30`; no pull request merged). `andre/track-b-lab` (`694e5d9`): the lab's scripts, small result files, report and running log in `eval/experiments/b-search-lab/`; a record, not for merging. Files with this entry: `log/2026-11-26-2110-shared-data/`

## Done

**The decision.** Andre does not merge `andre/search-recall` on today's evidence: it puts the right code in front of the agent more often, and no session has shown a better outcome. It stays a branch. **Track B is asked to explore it and find the best combination of its parts, or show that none pays.** What follows is what we know, so that you start from it. It adds to our entry of 21:00 UTC.

**1. The four parts, and the switch of each.** All act at search time; none changes an index.

| Part | Switch | On the branch |
|---|---|---|
| Related names: each result names its callers and callees closest to the query (the call graph as presentation) | `card_relations`, 0 = off | 3 |
| The next results by name, one line each, after the 10 | `more_results`, 0 = off | 20 |
| Names the caller knows or guesses, ranked by keywords alone as a fourth list of the merge | the argument `names` of `search_code`, `search()` and `CodememService.search`; `codemem search --names a,b`. `[rrf] weights = { names = 0 }` turns the list off | available |
| Tests kept out of the 10 results, the best 5 named after them | `tests_apart`, `tests_apart_count` | false, 5 |

- The first, second and fourth are top-level keys of `config.toml` in `CODEMEM_HOME`, or of `.codemem.toml` in the repo. No environment variable sets them.
- With `card_relations = 0`, `more_results = 0`, no `names` and `tests_apart = false`, a search is `main`'s, result for result (tests check it).
- A callee with more than 100 callers is not named (`RELATION_MAX_CALLERS`): calls are linked by name, and such a callee is mostly a common method name.

**2. What each part gave.** "On paper": the lab, held-out tasks, a function to change in the 10 results or named on the page, vLLM of 175 / pandas of 162; today 99 / 94. "In sessions": Haiku, 16 pandas tasks at L1 and L2, the agent asked where the change has to be made.

| Part | On paper | In sessions |
|---|---|---|
| Related names | 117 / 108. With 5 names a result 119 / 111; callers only 111 / 110; callees only 105 / 97 | the function was only in a related line in 2 of 30 first searches |
| Next 20 by name | 116 / 108; vague L2 from 8 to 12 of 16. Track A's replay of real agent queries: a gold function in the results for 49% at 10, 63% at 20, 67% at 30, 76% at 50 | the function was only in that block in 2 of 30 first searches |
| Both | 127 / 117 | on the page in 27 of 30 first searches, against 22 of 30 on `main` (the agents wrote their own queries) |
| `names` | with the issue's own names beside a short query: 58 to 88 of 175, 70 to 81 of 162 | Haiku filled it in half of its sessions. Where it did, the function was in the 10 results in 12 of 15 cells, against 11 on `main` |
| Tests apart | 103 / 100; vague L2 from 8 to 11. The labelled answers are never tests, so this measure favours it | never run |

- **Outcome:** the branch and `main` both named the right function in 15 of 15 tasks at each level (grep alone: 13). The agent's next step followed a name that was only listed in 3 of 32 sessions.
- **Cost:** about 900 tokens more a search (5,801 to 9,332 characters). At L1 the branch cost more than grep in 15 of 16 pairs, `main` in 10 of 16.

**3. New: fixes that change two or more functions.** The same lab, pandas, the whole issue as the query, 127 tasks with about 5 functions to change each (69 in the held-out half). How many tasks have every function to change on the page:

| The page shows | All 127 tasks | Held-out 69 | Share of all gold functions (127 tasks) |
|---|---|---|---|
| the 10 results | 14 | 5 | 22% |
| and related names | 30 | 14 | 32% |
| and the next 20 by name | 31 | 16 | 33% |
| and both | 43 | 21 | 38% |
| control: the next 20, and as many results after them as there are related names | 33 | 17 | 35% |

- **This is the one place where the call graph adds more than extra results do:** 43 tasks against 33. For finding one function it does not (points 2 and 3 of the 21:00 entry).
- The 7 vague tasks with several functions: every function on the page for 5 of 7 at L1 and 4 of 7 at L2 with both parts, against 1 and 2 for the 10 results; the control gives 5 and 3.
- vLLM is still being counted. Script: `allgold.py` on the lab branch; per task: `results/allgold-*.json`.
- Offline only: no session has tested whether an agent follows those names on such a task.

**4. What nobody has tried.**

- **Sessions on fixes with several functions, or on the hard tier,** with parts 1 and 2 on against off. Every session of ours was a small fix on pandas.
- **`tests_apart` in any session.** In our probes a third of all result cards were tests or benchmarks, and when the first card was a test the gold file was further down or missing.
- **Other sizes:** `card_relations` 1, 2 and 5; `more_results` 10 and 40.
- **Whether an agent's guessed `names` help.** We measured that agents fill the argument, not what their guesses do.
- **The 20 best matches in the first message, with no tool call.** For Sonnet: fewer turns than grep alone in 6 of 8 tasks, never more, the right file first in 8 of 8. It is your one-shot idea with names in place of code, and it costs one search. Not tried with the branch's page, on another repo, or with an edit and its tests. Haiku's numbers follow.
- **A call graph resolved through imports and types.** Ours links calls by name.
- **Your question to track A, whether an arm with the hooks is wanted** (status of 17:00 UTC): from our sessions, the hooks make Sonnet search every time and cost it a turn and tokens for the same answers, so we are not asking track A for that arm. The agent note was not tested: the runner turns CLAUDE.md off.
- **Your renaming control** bears on all of this: in our sessions Sonnet found the right pandas and vLLM files from memory (its first grep used a real name in 7 of 11 tasks). A gain from search for Sonnet can only show where memory does not reach.

**5. How to try a combination.**

```bash
git fetch origin && git checkout origin/andre/search-recall && uv sync
# one search by hand, on any index you have
codemem search "the request in plain words" --repo <repo> --index-dir <index> -k 10 --names foo,bar
# the switches: lines in $CODEMEM_HOME/config.toml
card_relations = 0
more_results = 40
tests_apart = true
```

- **Offline, with labels:** the lab branch. `validate_branch.py <set>` counts reach with the branch's own `search()`; `allgold.py <set>` the several-function tasks; `README.md` says what they need (two indexes and their query vectors; the paths are those of Andre's Mac).
- **With an agent:** our session harness is tied to that Mac and is not pushed. What it does is in the 21:00 entry, point 5. Your own harness will do, as long as the model is loaded before the first search.

**6. For track A's agent, if Andre asks you to check the branch on Linux.**

```bash
git fetch origin && git checkout origin/andre/search-recall && uv sync && uv run pytest -q
```

Expected: the five failures of `tests/test_compact_store.py` that `main` has on your PC, and no other. On the Mac: 746 passed before the merges with `main`, and the four test files nearest the change pass after them (152 tests). The whole suite was not run again after the merge with #60.

## Checked

- The session counts were recounted from each session's record. The lab's counts for parts 1, 3 and 4 were reproduced with the branch's own `search()`; the several-function counts use that `search()` directly.
- Not checked: anything on Linux; any session on a fix with several functions; `tests_apart` with an agent.

## Left

- The several-function count on vLLM. The comparison's last blocks (the 20 matches in the first message, for Haiku on 17 tasks and for Sonnet on 9 more). Both follow in one short entry.

## Blocked on, or needed from others

- **Wilson:** nothing is blocked. If you take the branch further, say in your status which combination you are trying, so that we do not run the same one.
- **Track A:** the log of the five failures (21:00 entry, point 6), if not posted yet.

## Next

- Andre's session: the final tables; the cause of the Linux failures (an agent has a lead: the bits of a code depend on how many vectors are encoded in one call).
