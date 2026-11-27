# For track B: the hybrid replaces the coding agent. Has track B weighed that? And which run shows codemem as an MCP tool doing worse than grep?

- **Track:** shared: from track C's session, for track B. It follows your entry of 10:30 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 11:45 UTC
- **Work package:** B1 (grep against grep plus codemem), B8 (the integration)
- **Branch, commits, pull request:** none. Read from `wilson/loop-vs-grep-e2e` at `22aef0f`

## Done

Thank you for the entry of 10:30: the dates, the MCP runs that do not count, and the loops marked as evidence and not as an arm are all as we see them. Two questions are left. **Please answer both here before the lock (20:00 UTC).**

### Question 1. The hybrid is not a coding agent with codemem added. Has track B weighed that?

Your entry calls the hybrid "the one arm that fits the question". We read the code differently (`e2e_hybrid.py`, `e2e_hybrid2.py`, `llm.py`):

- Each step calls `claude -p` with `--tools ""`, your own system prompt and a JSON schema. The model answers one question per step. Your Python program runs the search and applies the edit.
- So when the hybrid runs, Claude Code's agent is not running. There is no shell, no file listing, no test run, and one edit action. It has three tools: a codemem search, a grep, and opening code.
- codemem is imported as Python. MCP is not used.

So the hybrid lets the model choose between grep and codemem, but it still replaces the agent, as loop-k does. If the team used it, we would not be using a coding agent at all.

- **(a)** Is that reading right?
- **(b)** Who would run it in place of Claude Code or Codex? Is that a realistic way to ship codemem, or to evaluate it?
- **(c)** What is its baseline? The same loop with the codemem action removed has not been run, so "loop against agent" and "codemem against grep" cannot be told apart.

### Question 2. Which run shows codemem as an MCP tool inside Claude Code doing worse than grep?

In chat today the view was put that the tool "still underperforms grep by quite a bit". We find no run that shows it. What exists:

**Track A's runs, graded by the hidden tests** (entry of Nov 26, 19:00 UTC; Haiku, the 10 vague pilot tasks, one run each, codemem `041124e`):

| Prompt | Setup | Completed (of 10) | Runs that called codemem | Median turns | Median tokens |
|---|---|---|---|---|---|
| L1 | `grep` | 8 | 0 | 26 | 1.32M |
| L1 | `tool` | 8 | 9 | 21 | 1.23M |
| L2 | `grep` | 8 | 0 | 26 | 1.21M |
| L2 | `tool` | 7 | 10 | 19.5 | 0.94M |

Track A's reading: "Completion is the same in both arms. With codemem the median run is 5 to 6 turns shorter at L1 and L2." That was on a codemem where about half of the first searches still came back from keywords only.

**Our sessions** (Claude Code 2.1.285, 17 pandas tasks at their base commits, L2, one session per cell; the agent names the functions to change and edits nothing):

| | `grep` | `tool` | codemem's 20 best results in the first message |
|---|---|---|---|
| Haiku: right function named (of 16) | 13 | 15 | 14 |
| Haiku: median cost | $0.0034 | $0.0032 | $0.0024 |
| Haiku: cheaper / dearer than `grep`, by task | | 8 / 9 | 13 / 4 |
| Haiku: share of tokens read from the prompt cache | 85% | 87% | 86% |
| Sonnet: share of tokens read from the prompt cache | 79% | 82% | 76% |
| Sonnet: sessions that called `search_code` | | 3 of 17 | no tool offered |

**The MCP runs of PR #45** (duckdb 25101): keyword-only answers, and by your own entry they do not count.

If there is a run we have not seen, please name it. If there is none, please say so here, so that the three of us work from the same picture.

### Why we stay with codemem as an MCP tool inside Claude Code

- **It is the product, and it is what track A measures:** Claude Code in the task's container, graded by tests. A loop that replaces the agent cannot be a row of that table.
- **It gets the same prompt-cache discount as grep** (table above). The zero cache reads of loop-k and the hybrid come from one new conversation per step with the cache off. Your v2 reads from the cache again with the same searches.
- **The cost gap of the loops is three things, and none of them is the index.** Per task at L1, rebuilt from the per-call table Wilson sent today:

| | grep agent | codemem only | hybrid | hybrid v2 |
|---|---|---|---|---|
| Input | $0.039 | $0.040 | $0.059 | $0.044 |
| Output | $0.020 | $0.024 | $0.028 | $0.023 |
| Total | $0.059 | $0.064 | $0.087 | $0.067 |

  1. Text sent again without the discount: the hybrid, 4.6 calls a task.
  2. New text per task: with the discount equal (v2), 11,797 new tokens against the grep agent's 8,333.
  3. Output per step: 750 tokens a call in loop-k against the grep agent's 347.
- **So smaller chunks in the index are not the remedy.** What a result shows is separate from what is indexed: a raw chunk in the loops is about 2,800 characters (70 lines on average in your runs), a card of `search_code` about 450, a name line about 90. Smaller chunks would cut functions into pieces and force every index to be built again.

### What we take from track B's work (candidates for after the lock; Andre decides)

- **10 cards, then results 11 to 30 by name** (your point 2). It is `more_results` on `andre/search-recall`.
- **No result shown twice in a session** (the loops' rule), in the MCP server. In our Haiku sessions 18 of 34 searched more than once, and 67 of the 217 results of those later searches had been shown before. A repeat would become one line, and be shown in full again if the function was edited since.
- **The query written as intent and symptom.** On 30 held-out pandas tasks with the product's `search()`: a function of the fix in the top 10 for 21 tasks, against 17 with the whole issue. A session test of a wording that asks for it is running now.

## Checked

- Recounted from your files at `22aef0f`: the costs and edit counts of the 35-task table, the tool choices of v2 (codemem at step 1 in 46 of 70 runs, in 3 of 133 later steps), the lines shown per result, and the per-task split above (it rebuilds both bills from list prices).
- Track A's table is quoted from its entry. Our session numbers are counted from the raw records on the Mac.
- Not checked: any diff of the loops with tests.

## Left

The session test of the query wording, and of results in the first message with the tool still offered.

## Blocked on, or needed from others

**Track B:** answers to questions 1 and 2 in this log, before 20:00 UTC. Please hold off on building a new index with smaller chunks for this; the reason is above.

## Next

Andre: the direction for track B (announced at 09:55) follows separately.
