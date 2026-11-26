# Does the agent find the right code sooner with codemem? 186 sessions on pandas

Date: 2026-11-26. Written for Andre, before the design lock (Fri Nov 27, noon Pacific), and shared as it is.
186 Claude Code sessions, none discarded. Nothing in `src/` or on any branch changed by it. The records,
streams, scripts and running tables are on Andre's Mac (`.cache/review/compare/`).

**The question.** You expected an agent with grep alone to need several searches before it lands on the right
code, and an agent with codemem beside grep to land there sooner, in fewer turns and tokens. Each session asked
Claude Code where in pandas a change has to be made, in the repository at the task's own commit, and was scored on
whether its answer named a file and a function that the real fix changed.

## The finding

1. **Every arm found the right code about equally often.** On these 17 pandas tasks a gold file came first in 14
   to 17 of 17 sessions, in every arm and at both levels. Both models know pandas and grep for function names
   they remember, so accuracy sits near the ceiling: this sample cannot show codemem helping accuracy.
2. **As a tool, codemem did not shorten the search.** Haiku called `search_code` in all 34 of its sessions, at
   turn 1, and the first result held a gold file in 28. Yet it took as many turns and tokens as grep alone (turns
   lower in 8 and 9 of 17 pairs, higher in 5 and 7; tokens split evenly). It saved wall-clock seconds: faster in
   12 of 17 pairs at each level. Sonnet without hooks called it in 3 of 17 sessions.
3. **codemem's results saved when they were in the prompt.** `upfront` (the 20 results of one codemem search
   written into the prompt, nothing to call) took fewer turns than grep in 13 of 17 Haiku tasks (sign test p 0.02)
   and 12 of 17 Sonnet tasks (p 0.00), and fewer tokens in 13 and 12, with the same accuracy. Against `tool` it
   used fewer tokens in 15 of 17 Haiku tasks (p 0.00) and 14 of 17 Sonnet tasks (p 0.01).
4. **Making Sonnet search first, with codemem's two hooks, costs and finds nothing more.** On 8 tasks: a turn more
   in 4, none fewer; more tokens in 7 of 8; the same answers.
5. **The branch (`tool+`) does not beat main (`tool`).** In the 10 task-levels where main's first result had no
   gold function among its cards, the branch's showed one in 6 (3 as a card, 2 in a `related:` line, 1 in "More
   results"), but the answers came out the same: a gold function named in 9 of the 10 in both. It costs more: dearer
   than grep in 16 of 17 pairs at L1. A name that was only listed was the agent's next step in 4 of 34 sessions.
6. **Two faults in codemem:** its server aborts when a query arrives during its start-up warm-up on the Apple GPU,
   and it does not index Cython (`.pyx`), where three of these tasks have gold files.

## One task through the arms: 69924

The L2 request: "Group-by cumulative sum, min, max and rank give wrong results on datetime or timedelta columns
when a group key is NaN. Please fix." The fix is in `pandas/core/groupby/ops.py` (`WrappedCythonOp._get_cython_vals`,
`_call_cython_op`): the Python layer that prepares the values before the Cython loops in
`pandas/_libs/groupby.pyx`, which is where a reader of pandas looks first.

| Model | Arm | First file of the answer | Turns | Tokens | What happened |
|---|---|---|---|---|---|
| Sonnet | grep | `groupby.pyx` (wrong) | 7 | 67,992 | went straight to the Cython loops it remembers |
| Sonnet | tool | `groupby.pyx` (wrong) | 5 | 47,402 | did not call `search_code` |
| Sonnet | tool+h | `groupby.pyx` (wrong) | 6 | 61,517 | the hook refused its grep; its search had the gold function as a card; it went back to the `.pyx` |
| Sonnet | upfront | **`ops.py` (right)** | **3** | **19,311** | its first grep went into `ops.py`, a file from the list |
| Haiku | grep | `ops.py` (right) | 7 | 123,917 | grepped and read its way there |
| Haiku | tool | `ops.py` (right) | 9 | 186,079 | 5 searches: the first returned a `.pyi` stub, tests and benchmarks |
| Haiku | tool+ | `groupby.pyx` (wrong) | 4 | 78,943 | found `ops.py` by its second search, still put the `.pyx` first |
| Haiku | upfront | `groupby.pyx` (wrong) | 8 | 145,230 | began in `ops.py`, then followed the `.pyx` |

Only Sonnet's `upfront` put the gold file first, in less than half grep's turns. Part of the reason is a blind
spot: codemem's index holds no `.pyx` file, so its list points only at Python code, right here by luck. On 69015,
whose only gold file is `pandas/_libs/testing.pyx`, the same blind spot made the codemem arms search for a file
they cannot return (Haiku `tool`: 14 turns against grep's 9 at L2, 13 against 5 at L1).

## The numbers

Haiku, 17 tasks (medians; gold function out of 16: 69015 has none):

| Level | Arm | Gold file first | Gold function | Turns | Tokens | Cost $ | Seconds |
|---|---|---|---|---|---|---|---|
| L2 | grep | 15 | 13 | 5 (4 less refused) | 64,786 | 0.0034 | 12.5 |
| L2 | tool | 15 | 15 | 4 | 60,017 | 0.0032 | 8.7 |
| L2 | tool+ | 14 | 15 | 3 | 49,805 | 0.0037 | 8.2 |
| L2 | upfront | 15 | 14 | 4 (3) | 53,486 | 0.0024 | 11.5 |
| L1 | grep | 16 | 14 | 4 | 54,610 | 0.0024 | 11.1 |
| L1 | tool | 17 | 16 | 4 | 60,253 | 0.0026 | 8.7 |
| L1 | tool+ | 16 | 16 | 4 | 63,714 | 0.0032 | 8.2 |

Pair by pair against grep on the same task (arm lower / equal / higher, sign test):

| Model | Level | Arm | Turns | Tokens | Cost | Seconds |
|---|---|---|---|---|---|---|
| Haiku | L2 | tool | 8 / 4 / 5 | 8 / 0 / 9 | 8 / 0 / 9 | 12 / 0 / 5 (p 0.14) |
| Haiku | L2 | tool+ | 9 / 5 / 3 (p 0.15) | 8 / 0 / 9 | 5 / 0 / 12 (p 0.14) | 13 / 0 / 3 (p 0.02) |
| Haiku | L2 | upfront | **13 / 1 / 3 (p 0.02)** | **13 / 0 / 4 (p 0.05)** | **13 / 0 / 4 (p 0.05)** | 11 / 0 / 6 |
| Haiku | L1 | tool | 9 / 1 / 7 | 9 / 0 / 8 | 7 / 0 / 10 | 12 / 0 / 5 (p 0.14) |
| Haiku | L1 | tool+ | 6 / 7 / 4 | 5 / 0 / 12 (p 0.14) | **1 / 0 / 16 (p 0.00)** | 11 / 2 / 4 |
| Sonnet | L2 | tool | 8 / 6 / 3 | 8 / 0 / 9 | 12 / 0 / 5 | 12 / 0 / 5 |
| Sonnet | L2 | upfront | **12 / 4 / 1 (p 0.00)** | 12 / 0 / 5 (p 0.14) | 9 / 0 / 8 | **14 / 1 / 2 (p 0.00)** |
| Sonnet | L2 | tool-h (8 tasks) | 0 / 4 / 4 (p 0.12) | 1 / 0 / 7 (p 0.07) | 2 / 0 / 6 | 4 / 0 / 4 |
| Sonnet | L2 | tool+h (8 tasks) | 2 / 2 / 4 | 1 / 0 / 7 (p 0.07) | 1 / 0 / 7 (p 0.07) | 4 / 0 / 4 |

- Sonnet, 17 tasks: gold file first 15 (grep), 14 (tool), 15 (upfront); median turns 4, 3, 3; tokens 19,020,
  19,303, 18,544. With hooks (8 tasks): 7 and 7 of 8 first, median 27,286 and 30,898 tokens against grep's 15,602.
- Refused commands (the read-only fence): 5 in Haiku `grep` at L2, 1 at L1, 2 in `tool+`, 3 in `upfront`, 2 each
  in the three Sonnet arms; nearly all `awk` or `python`. Without the turns they cost, the `upfront` pairs stay
  13 / 1 / 3 (Haiku) and 11 / 5 / 1 (Sonnet).
- Cost is Claude Code's own figure at list price. It shows what the token sum hides: `tool+` results are longer
  (related names and 20 more names after the cards) and are written to the cache.
- Differences of two or three tasks in 17 are within what chance gives; only the `upfront` turns, Haiku `tool+`'s
  seconds and its cost at L1 pass p 0.05.

## Inside the codemem sessions

- **Haiku called `search_code` in 34 of 34 sessions, always at turn 1, and searched again in 18.** The first result
  held a gold file as a card in 28 and a gold function in 22 (of 32 with one). Right after it, Haiku followed the
  result in 21 sessions (`get_chunk` of a card 10, read a card's file 6, grep a card's name 5), searched again in
  9, answered at once in 3, and turned away in 1.
- **Sonnet called it in 3 of 17 sessions without hooks.** With the hooks, in 8 of 8: in 6 the hook refused the
  first grep and the next call was `search_code` (6 of 6); no later grep was refused.
- **`tool+`:** the agent passed `names` in 22 of 34 sessions; its next step after the first result was `get_chunk`
  of a card in 19, and a name found only in `related:` or "More results" in 4.
- **Five first queries, as Haiku wrote them:**
  - 68195, L2: "as-of merge error when tolerance is negative, must be positive" (the gold function was a card);
  - 69779, L1: "sparsify MultiIndex level labels repeated values hidden in display" (a card);
  - 71129, L2: "append categorical data to HDF5 table with different categories raises error" (the gold file,
    not the function);
  - 68090, L2: "get_group returns wrong rows for multiple groupers with categorical, sort=False, observed=False"
    (no gold file);
  - 69015, L2: "assert_series_equal assert_frame_equal compare object columns containing nested lists unhashable
    type list" (no gold file: it is a `.pyx`).
  The queries are short descriptions in the agent's own words, with pandas names mixed in.

## Where codemem made a session worse

- **More reading after a good result.** 68090, Haiku, L2. Grep went to `def get_group` and `def indices` by name,
  saw a gold file in turn 1 and answered in 5 turns (64,786 tokens). With codemem the first search missed and the
  second found `ops.py` in turn 2, then Haiku opened 9 more functions with `get_chunk` (each comes whole, with its
  callers and callees): 13 turns, 333,764 tokens, the same answer. `tool+` did the same: 14 turns, 370,406 tokens.
- **The Cython blind spot.** 69015 (gold file `testing.pyx`): Haiku `tool` 14 turns against grep's 9 at L2;
  `tool+` lost the gold file at L1; Sonnet `tool` lost it at L2. 69924 above: three arms put the `.pyx` first.
- **The hooks.** Sonnet `tool-h` on 71129: the hook sent it to a search with no gold file in the result, and it
  lost the gold function that its grep session named.

## The branch against main

Both run plain-text results (main at `09c4ef0` has #54), so the difference is only what the branch adds: related
names on each card, the next 20 results by name, and the `names` argument. Pair by pair over Haiku's 34
task-levels, `tool+` against `tool`: turns 12 lower, 14 equal, 8 higher; tokens and cost split evenly; the gold file
first differed in 2 cells, both lost by `tool+` (69924 L2, 69015 L1).

| Level | Cells where main's first result had no gold function card | The branch there: card / related / more / absent | A gold function named: branch, main |
|---|---|---|---|
| L2 | 5 (66352, 68090, 68945, 69924, 71129) | 1 / 0 / 0 / 4 | 4, 4 |
| L1 | 5 (66352, 69924, 70734, 70828, 71129) | 2 / 2 / 1 / 0 | 5, 5 |

This rests on 10 cells, and in all of them main's session named the gold function anyway.

## What it means for your hypothesis

For it: when codemem's first result is good the agent follows it at once, and its 20 results in the prompt made
both models land in fewer turns and tokens than grep (13 and 12 of 17 tasks). Against it: as a tool it added a step
rather than replacing greps (Haiku searched again in 18 of 34 sessions, with turns and tokens unchanged), Sonnet does
not call it unless forced, and forcing it costs. On pandas the agent's own grep, guided by its memory of the code,
already lands in 3 to 5 turns, which leaves codemem little to save. The test that settles it: the same arms on a
repository the models do not know (or pandas with its names disguised), where memory cannot shortcut, comparing
`upfront` with `tool` and `grep`.

## How it was measured

- **The agent:** `claude -p` 2.1.285 on this Mac (M1, 16 GB), headless; the adopt agent's recipe: no settings,
  plugins, hooks or MCP servers of yours, `--permission-mode dontAsk`, tools `Read` and `Bash` with only read-only
  shell commands allowed (`grep`, `ls`, `cat`, `head`, `tail`, `wc`, `cut`, `xargs grep`, and `sed -n`), plus `cd`
  from the Sonnet block on (Haiku: 8 tasks without `cd`, 9 with; the arms of a task always had the same list). At
  most 25 turns. A gate on the first event and a check of the first request in every session. The fence was proven
  with a fake API, no model call: 42 writing or program-running commands refused, the reads ran, no file appeared;
  again with `cd` allowed.
- **The prompt:** the request (L1: the issue with every code name removed; L2: a 10 to 30 word request), then
  "Do not change any file. Find where in this repository the change for this request has to be made ... answer
  with one JSON object". `upfront` begins with "Possibly relevant code, from a search by meaning (it may be wrong):"
  and the 20 results of `codemem search` (`path:line  name`).
- **Scored:** a gold file first in `files`; a gold function named (the answer's name, less any module prefix,
  equals the gold `Class.method`); turns; tokens from the result event (input, output, cache read, cache written);
  cost as Claude Code reports it; seconds from the first model request to the answer.
- **The repository** at each task's base commit, one folder per task: the commit's full tree (`git archive`
  without pandas' `export-ignore` rules, which drop 1,045 of its 2,649 files), with no history, and an empty `.git`
  file: without it codemem, git and Claude Code take the enclosing codemem checkout as the repository. One index
  per task, built with main, newest commit first so that each build reuses the vectors before it: 3 to 1,891 new
  vectors for sixteen of them (30 to 770 s), 16,486 for the oldest (66352, 69 minutes).
- **The code:** `tool` and `upfront` main at `09c4ef0`; `tool+` `andre/search-recall` at `da6cd0f`; the hooks
  arms with codemem's own two hooks, written by `codemem.agents._merge_hooks_json`.
- **The warm-up crash, and the hold.** codemem's server loads its model at start, and a wrapper holds the agent's
  first request until then. The recipe released it 3 s after the model's load line. My two dry runs (a fake API
  that searches at once) both killed the server: `failed assertion _status < MTLCommandBufferStatusCommitted`, exit
  -6. In the code, the warm-up (`service.prewarm`, a document encode in a thread) and a query both call
  `LocalEmbedder._encode`, which runs `model.encode` with no lock; two encodes at once on the Apple GPU abort the
  process. Measured: released 3 s after the load line it crashed, at 8 and 12 s it answered. The hold waited 10 s,
  outside the measured seconds. No server crashed in the 186 sessions; two `search_code` calls in one turn did not
  crash it either.
- **The machine:** one heavy process of mine at a time (a lock file), and none beside another agent's model
  process. One session overlapped another agent's test run: its seconds are left out, its turns and tokens kept.
  One build stalled at 10:23 while the whole machine stopped responding (swap full by the editor and the browser);
  it built on the second try.

## Limits

- One repository, pandas, whose code both models know. 17 recent tasks, one run per cell. L0 (the full issue) was
  not run; neither were the hooks on the other 9 tasks.
- Claude Code 2.1.285 with two tools; the evaluation runs a newer version with about 20 tools.
- Seconds include the API's own latency, which varied over the day; the arms of a task ran one after another in a
  rotating order, so the drift falls on all of them alike.
