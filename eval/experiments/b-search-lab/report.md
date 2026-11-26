# What codemem's search misses, and what recovers it

Nov 26, 2026. An offline lab on the real vLLM and pandas indexes, with the product's own `search()`
from `main` (`8d86da8`). The scripts, the small result files and the running log are in this
folder (`running-log.md`). The changes it led to: branch `andre/search-recall`.

## The finding

1. **The misses are mostly ranking, not chunking or embedding.** When the first search of a task
   has no gold function in its top 10, the function is usually already a candidate: in some
   list's top 50 for half the misses, in a list's top 1,000 for most of the rest. The model cut
   no missed function, and long functions are missed no more often than short ones.
2. **The call graph does not help the ranking.** Callers and callees of the top results, added as
   a fourth list or as a lift, gained a few tasks on one repo and lost a few on the other. Random
   neighbours did as well as the most similar ones. Cleaner edges did not help either.
3. **What helps is putting more names on the page.** Naming each result's 3 closest callers and
   callees, or simply naming the next 20 results, puts a gold function in front of the agent for
   about 10 more tasks in 100. The two reach different tasks; together they add about 15.
4. **A short query loses the names an issue gives.** Passed apart, as their own keyword list,
   they win back half to three quarters of that loss.
5. **Test code crowds the top 10** (2 to 5 of the 10 cards). Keeping it out gains on every set,
   but the gold labels are never tests, so this lab cannot judge it.

Four of these are on the branch: the related names, the next results by name, `names` as an
argument, and keeping tests out of the cards as an option that is off. A fifth commit makes every
MCP answer plain text.

## The example used throughout

pandas task 68195. The fix changes `_AsOfMerge._validate_tolerance` in
`pandas/core/reshape/merge.py`: the error for a negative tolerance of `merge_asof` says "must be
positive", though zero is allowed.

| query | the text | where the gold function lands |
|---|---|---|
| L0 | the issue (1,790 characters), titled *merge_asof says "tolerance must be positive" but accepts tolerance=0* | 2nd |
| L1 | the same facts without names: "In an as-of merge ... the error text says that the limit has to be positive ..." | 1st |
| L2 | "The as-of merge error for a negative distance limit says it has to be positive, but zero is allowed. Make the message say non-negative." | 11th |

At L2 the agent sees four tests (`adjust_negative_zero`, `test_interpolate_invalid_nonpositive_limit`,
...) and functions about other limits (`validate_limit`, `validate_limit_area`). The gold function
is 11th: just off the page. It sits at 25 in the keyword list, 95 in the code-vector list and 10 in
the usage list. It is a ranking miss, the commonest kind. We follow it below.

## How it was measured

- **Indexes:** pandas at `a0885a1` (41,632 chunks) and vLLM at `e9acf48` (102,224 chunks), both
  built with the real model. Copies were used.
- **Tasks:** the eval's 352 pandas and 381 vLLM tasks, with the issue as the query (L0); and the
  17 pandas tasks of the vague set at L1 (names removed) and L2 (a 10 to 30 word request). The
  issue's first line alone served as an extra short query on all tasks ("title").
- **Gold:** a gold function counts by path and qualified name in the snapshot. 16 vLLM tasks and 4
  pandas tasks have no gold function left in it.
- **The baseline is the product's search, exactly.** The lab merges the kept lists itself, and
  gives the product's own top 50 for all 733 L0 tasks and all vague queries.
- **Fair comparison:** every setting was chosen on one half of the L0 tasks (by a hash of the
  task id) and reported on the other half (175 vLLM and 162 pandas tasks with a gold function).
  The vague tasks were never used to choose. Intervals are 95% bootstrap intervals over tasks.
- **Small samples:** the vague set has 16 tasks with a gold function. A difference of 1 or 2 there
  is one or two tasks.

## 1. Where the search stands

A gold function in the top 10, and a gold file in the top 10:

| query | tasks | function in the top 10 | file in the top 10 |
|---|---|---|---|
| vLLM, the issue | 342 | 206 (60%) | 277 of 375 (74%) |
| pandas, the issue | 295 | 180 (61%) | 260 of 324 (80%) |
| vague, L0 / L1 / L2 | 16 | 13 / 9 / 8 | 15 / 12 / 13 |
| pandas, the title only | 295 | 136 (46%) | 221 of 324 (68%) |

The vLLM numbers are those of the earlier count, exactly (file 67/74/81/86% at 5/10/20/50,
function 51/60/68/74%). A short query costs a lot: at L2 the example's function drops from 2nd to
11th, and 5 of 16 vague tasks lose theirs.

## 2. What the misses are

For each task with no gold function in the top 10, its closest gold function:

| where it is | vLLM (136 misses) | pandas (115) | vague L2 (8) |
|---|---|---|---|
| fused 11 to 50 (on the next pages) | 48 | 37 | 4 |
| in some list's top 50, fused below 50 | 22 | 26 | 2 |
| only in some list's 51 to 1,000 | 52 | 44 | 2 |
| in no list's top 1,000 | 14 | 8 | 0 |

- **Ranking, mostly.** 70 of 136 vLLM misses and 63 of 115 pandas misses were already candidates.
  Our example is one: 11th.
- **Not chunking or embedding.** The model cut no window of a missed function. Missed functions
  had several windows about as often as found ones (49% against 41% on vLLM, 42% against 50% on
  pandas). Only the 14 vLLM functions no list finds are long (median 114 lines).
- **Names decide most.** The function's name is in the query for 67% of the hits and 18 to 33% of
  the misses. Even then the merge can lose it: 17 misses had their gold function at keyword rank
  1 to 10.
- **Functions nobody calls start behind:** they have no usage vector, so they can be in two lists
  of three. 55% of vLLM misses against 35% of hits.
- **Reach:** one call from a top-10 result gets 35 more vLLM tasks and 40 more pandas tasks; the
  same file 18 and 31 more. For 51 of the 136 vLLM misses and 64 of the 115 pandas misses a gold
  file is already in the top 10: the file is found, the function is not.
- **Long issues are cut too:** 250 of 381 vLLM issues and 121 of 352 pandas issues are longer than
  the model's 1,024 tokens, so the query vector sees only their start.

## 3. What recovers them

Ranked by what they do for the vague prompts, with the title query as a larger check (held-out
halves) and the cost. Today: L1 9 of 16, L2 8 of 16, vLLM title 58 of 175, pandas title 70 of 162.
Settings were chosen on the L0 halves.

| change | L1 | L2 | vLLM title | pandas title | at L0, vLLM / pandas | cost a search |
|---|---|---|---|---|---|---|
| **on the page:** related names + next 20 results (branch, parts 1 and 2) | 13 | 12 | 109 | 96 | 127 / 117 (from 99 / 94) | about 37 names; +61% characters |
| outline of every top-10 file | 12 | 13 | 104 | 101 | 125 / 129 | 200 to 500 names |
| next 20 results by name (part 2) | 11 | 12 | 98 | 87 | 116 / 108 | 20 names |
| 3 related names per card (part 1) | 12 | 9 | 89 | 88 | 117 / 108 | about 17 names, 4 to 9 ms |
| **in the top 10:** names passed apart (part 3) | 11 | 11 | 88 | 81 | +11 / +1 with the issue too | the agent must have names |
| tests kept out of the cards (part 4, off) | 10 | 11 | 67 | 80 | 103 / 100 | labels are never tests |
| a whole-file keyword list | 11 | 11 | 67 | 75 | 96 / 96 | a new table; 3.6 s on a vLLM issue |
| the graph as a fourth list | 10 | 9 | 62 | 76 | 100 / 99 | random does as well |
| the graph as a lift | 9 | 10 | 63 | 72 | 93 / 98 | |

Nothing else helped the vague prompts by more than one task: other fusion settings, file
siblings or files as a list, exact names (vague requests name nothing), files changed together
(only commits older than each issue were used), callees of tests, a cap per file (it hurt: -5 and
-7 at L0). The full table is in `progress.md`.

**Andre's questions about the graph.**
- *Only some neighbours, even at random?* Taking the 5 most similar callers and callees of the top
  3 results moved the top 10 by -1 task on vLLM and +3 on pandas; 5 random ones by +1.6 and +0.2;
  a placebo of 5 random chunks of the repo by -1.2 and 0 (held out, 175 and 162 tasks; random
  draws averaged over 5). The teammate's version added a median of 434 functions a search on
  vLLM, 1 gold function in 1,386 additions.
- *Is the graph the problem?* No. Without the edges into callees that have more callers than the
  99th or the 90th percentile (95 or 10 on vLLM), or with only the edges whose callee's name is
  defined once, the graph ranked no better than with all edges. The unique-name edges did worst.
- *Is chunking and embedding the problem?* No, see section 2.
- *Then where does the graph pay?* As names on the cards (section 3's table). In the example it
  does not reach: the cards of two `merge_asof` tests name `merge_asof`, the entry point, and the
  gold function is more than one call further.

**Whole files and file outlines.** A keyword ranking over whole files finds files better than
chunk keywords only for short pandas queries (L2: a gold file in the top 5 for 12 of 16 against 7);
on vLLM it does not, and with a whole issue it is slow. Showing each top-10 file's outline reaches
the most tasks, at 10 to 30 times the names. Each file's 5 functions closest to the query reach
about as many as the next 20 results.

**The example, change by change (L2).** Today: 11th, off the page. Part 2 names it first under
"More results, by name". Part 1 does not reach it: the nearest name it adds is `merge_asof`, more
than one call away. Part 3 with a guessed `names=["merge_asof"]` brings more
`merge_asof` tests up, not the gold function: a guessed entry point is not the place to change.
Part 4 puts it 5th among the cards. The full pages are in `results/example-page.txt`.

## 4. What was built (branch `andre/search-recall`, from `origin/main`)

| commit | what | default |
|---|---|---|
| `ba1ea14` | part 1: each result names up to 3 callers and callees, closest to the query by stored code vectors; results and callees with over 100 callers left out | `card_relations = 3` |
| `f821dc7` | part 0: every MCP tool answers in plain text (no `{"result": ...}` copy, which showed the model `\n` for each line end) | always |
| `868fea6` | part 2: after the cards, the next results by name | `more_results = 20` |
| `dc074ae` | part 3: `names`, a fourth keyword-only list, built as in the lab | used when given |
| `b38f74b` | docs: the character budget | |
| `32b79b8` | part 4: tests kept out of the cards and the best 5 named after them; a `tests` argument wins | `tests_apart = false` |

None changes an index, and none changes today's ranking: parts 1 and 2 add lines, part 3 acts
only when names are given, part 4 only when switched on. Parts 1, 3 and 4 were run with the
branch's own search on the index copies and gave the lab's numbers; part 2 names the search's own
results 11 to 30 (tested).

**What it costs.** On the 381 vLLM issues the answer of `search_code` is 5,801 characters on
average (95th percentile 7,660) today and 9,332 (11,713) with parts 1 and 2; on the vague requests
5,125 (6,865) and 7,967 (9,426). The related names take 4 to 9 ms a search. With all of an issue's
identifiers as names, the extra keyword search takes 58 ms on pandas and 376 ms on vLLM. Part 4,
when on, searches the test chunks a second time: 40 to 140 ms for a short query, 343 ms for a
whole pandas issue.

Tests: each part on and off on the test repo, the first k unchanged, hubs left out, a named
function moving up, the four MCP tools returning plain text. The full suite ran on the last
commit (see `progress.md`).

## 5. What I am least sure of

- **Reach is not use.** A name on the page counts as found; whether an agent opens it is for the
  agent runs to show. The 37 extra names may also distract.
- **The vague set is 16 tasks.** Its gains are 1 to 5 tasks. The title query stands in for a short
  query, but it is not a user's request.
- **Names come from the issue here.** Part 3's gain assumes the agent passes real identifiers. A
  guess can backfire, as in the example.
- **Tests.** The gold labels are never tests (1 of 488 pandas gold files, 13 of 604 vLLM), so
  every number that favours keeping tests out is favoured by construction.
- **One snapshot.** Each index is one later commit, which already holds the fix.

**What would decide:** the agent comparison on this branch, with parts 1 and 2 on and off and
part 4 on and off, measuring how often the agent opens a named function and how many turns it
takes to reach the gold file.
