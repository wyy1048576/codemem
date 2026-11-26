# Finding the right code: every idea worth trying, what it gave, and where it stands

**What this page is for.** One list of the ways to make codemem's search return what an agent
needs, and to get an agent to use it, with what each one gave when it was tried. It is our
working list for track B, from Andre's ideas, our own, and the survey of current practice.

**The goal.** codemem is called at the start of a task, usually once, for a request that names no
code. So two things matter: how often a function the real fix changed is in the first search's
results or named on its page, and whether an agent then gets to the right code sooner.

**How the search ideas were tested** (sections 1 to 3). Offline, on the real pandas and vLLM
indexes, with the issue as the query. Every setting was chosen on one half of the 733 issue tasks
and is reported on the other half: 175 vLLM tasks and 162 pandas tasks. The 16 vague pandas
requests (L1: names removed; L2: a short user request) were never used to choose anything.
Today's search puts a function to change in the top 10 for **99 of 175** (vLLM), **94 of 162**
(pandas), **9 of 16** (L1) and **8 of 16** (L2). Numbers below are on the same scale.

**Where the misses are.** When the function is not in the top 10, it is mostly just below it or
one call away from a result. About half of the missed functions are already candidates of the
merge, and none was cut by the model's length limit. It is ranking and reach, not chunking or
embedding.

**The running example.** pandas 68195 at L2: "The as-of merge error for a negative distance
limit says it has to be positive, but zero is allowed. Make the message say non-negative." The
function to change, `_AsOfMerge._validate_tolerance`, is not in today's top 10 (four tests and
three `validate_limit` functions are). It is result 11.

---

## 1. Search ideas that need no model call and no change to an index

| # | Idea | Whose | vLLM / pandas (of 175 / 162) | L1 / L2 (of 16) | Where it stands |
|---|---|---|---|---|---|
| | today | | 99 / 94 | 9 / 8 | |
| 1 | The graph as a fourth list: callers and callees of the best results join the merge | Andre | 100 / 99 | 10 / 9 | not adopted: random neighbours do as well (3) |
| 2 | The graph as a lift: a candidate that calls, or is called by, a top result moves up | ours | 93 / 98 | 9 / 10 | not adopted |
| 3 | A random subset of the neighbours, and as many random chunks (the control for 1 and 2) | Andre | as 1 | | it shows that 1's small gain is not the graph's |
| 4 | File siblings: the other functions of the best results' files, as a list | ours | 103 / 96 | 9 / 9 | not adopted: gold files in the top 10 fall by 1 to 5 |
| 5 | A ranking of files, lifting the chunks of the best files | ours | 98 / 94 | 9 / 8 | not adopted |
| 6 | Exact names in the query looked up among definitions | ours | 104 / 94 | 9 / 8 | not adopted: a vague request names nothing |
| 7 | Merge settings (200 candidates per list, other weights; a shortened keyword query) | ours | 104 / 96; shortened query +3 / -7 | 9 / 9 | not adopted: pandas files fall by 5 |
| 8 | **Related names on each result:** its 3 callers and callees closest to the query, on one line | Andre, ours | **117 / 108** | 12 / 9 | on the branch (`card_relations`) |
| 9 | Tests as a bridge: hop from the best tests to what they call | ours | 98 / 93 | 9 / 9 | not adopted |
| 10 | At most 3 results of one file | ours | 94 / 87 | 9 / 7 | not adopted: worse |
| 11 | Tests weighted down, or kept out of the 10 results and named after them | ours | weighted 104 / 99; kept out 103 / 100 | weighted 9 / 9; kept out 10 / 11 | on the branch as an option, off (`tests_apart`). The labelled answers are never tests, so this measure favours it |
| 12 | **A query in two parts:** names the agent knows or guesses go in an argument of their own, ranked by keywords alone | Wilson's one-shot, ours | with a short query: 58 to 88 of 175, 70 to 81 of 162 | 11 / 11 | on the branch (`names`) |
| | **The next 20 results listed by name** after the 10 (how many results to return) | ours | **116 / 108** | 11 / 12 | on the branch (`more_results`) |
| | 8 and the next 20 together | | **127 / 117** | **13 / 12** | the branch's defaults |

What it shows:

- **Andre's graph idea does not improve the ranking, and does help as names on the page.** Put
  into the ranking, neighbours gain 1 to 5 tasks, and random neighbours gain as much. Shown as
  three names under each result, they reach 18 and 14 more tasks.
- **Simply listing results 11 to 30 by name reaches as many tasks as the graph does** (17 and
  14), but not the same ones, which is why the branch has both.
- **On the example:** with the branch, the page's "More results, by name" block starts with
  `pandas/core/reshape/merge.py:2599  _AsOfMerge._validate_tolerance`, and the as-of merge test at
  result 7 gains `related: merge_asof (pandas/core/reshape/merge.py:649)`.
- **What the names cost:** a search answer grows from 5,801 to 9,332 characters on average on
  the vLLM issues, about 900 tokens a search; 4 to 9 ms; no model call.

## 2. Ideas that need a small build or Andre's yes

| # | Idea | What it gave, or why it did not run |
|---|---|---|
| 13 | A representation per file | run as a whole-file keyword list: 96 / 96, L1 11, L2 11. Not adopted: no gain with a whole issue, and it needs a new table in every index. A vector per file was not run |
| 14 | A reranker (a second model reorders the best 50) | not run: a model download, 1 to 3 s a search on a laptop, and the survey found no case for it before the lock |
| 15 | The agent as the reader: more, shorter results | the outline of each top-10 file reaches 125 / 129, but an answer becomes 10,000 to 16,000 characters. Capped at 5 names a file: 109 / 109. The next 20 by name (section 1) is the cheap form |
| 16 | Results up front, with no tool call | tested with real sessions: section 4 |

## 3. Ideas that change what is indexed (after the lock)

Not run: each needs every index built again. Token-level vectors (late interaction), other
chunking, context in the embedded text, a stronger embedding model, docs and comments as chunks.

Found on the way: **codemem does not index Cython.** 41 of the 352 pandas tasks have a Cython
file among the files to change, 25 of them only Cython. For those codemem can return nothing.

## 4. Getting it called, and used well

Tested with real Claude Code sessions on this Mac: short probes (80 with Haiku and Sonnet, then
33 with Sonnet), and a comparison in which the same agent is asked where a change has to be made
(17 pandas tasks at their own commits; read-only; the answer names files and functions).
The comparison is still running; the numbers are those of 2026-11-26, 19:00 UTC.

| # | Idea | What it gave |
|---|---|---|
| 22 | Wording that says when to call it (`light`, on main) | **Haiku calls it:** in turn 1 in every codemem session of the comparison so far. **Sonnet does not:** 0 of 11 probes, 2 of 8 full sessions. It greps names it remembers, on vLLM as on pandas. `strong` wording: 5 of 11 |
| | codemem's own optional hooks (the first grep of a session is refused once) | Sonnet then searches every time (11 of 11 probes, 8 of 8 sessions). But against grep alone its turns were never lower (equal in 4 tasks, higher in 4) and its tokens higher in 7 of 8, for the same answers. **Not for the evaluation's setup** |
| 23 | **Results in the first message:** one search on the request before the session, its 20 best matches in the prompt as `path:line  name` | **Sonnet, 8 tasks: fewer turns than grep in 6, never more; the right file first in 8 of 8.** Running for Haiku (17 tasks) and for Sonnet's other 9 |
| 24 | Results inside the agent's own grep (a hook adds codemem's matches when a grep finds nothing) | not built |
| 25 | A shell command with grep-like output | not built: the command loads the model at each call today |
| 26 | A first result that pays (the branch's page) | Haiku, 10 tasks: no gain in turns or right answers against today's codemem, and more tokens at L1. The function to change was missing from the first result's page in 2 of 28 first searches, against 8 of 28 on main (the agents wrote different queries, so this is not a controlled count). A name that was only listed was used once in 16 sessions |
| 27 | The comparison itself: grep only against grep plus codemem | Haiku, 10 tasks: codemem is faster in 9 of 10 at L2 and 7 of 10 at L1, and named the right function on the one or two tasks grep missed. Turns and tokens split evenly. Every setup is near the ceiling on these tasks |

What it shows so far:

- **A weaker model pulls; a stronger model has to be handed the list.** Haiku calls the tool by
  itself. Sonnet remembers these repos and goes straight to grep; making it search first costs
  it a turn, and handing it 20 names saves one.
- **On tasks this easy, a better page does not change the outcome.** When the first result
  misses, the agent finds the function by reading and grepping onward.

---

## How we decide

- A search idea is adopted when it puts a function to change in the top 10, or on the page, for
  clearly more tasks, on tasks it was not tuned on, on both repos, and it loses nothing on the
  vague requests; and when real sessions show no harm.
- It is switched by a setting, and it changes no index, or it waits for after the lock.
- What is not clear by Friday noon goes to the paper as an experiment, not into the runs.
