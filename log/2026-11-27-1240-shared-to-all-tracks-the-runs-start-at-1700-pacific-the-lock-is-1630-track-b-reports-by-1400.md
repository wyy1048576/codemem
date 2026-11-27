# To all tracks: the runs start today at 17:00 Pacific, the lock is 16:30 Pacific. Tracks C and A are ready; track B is pending and reports by 14:00 Pacific

- **Track:** shared: Andre's decisions, for tracks A and B
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 12:40 UTC
- **Work package:** the run plan (`docs/plan/runs.md`)
- **Branch, commits, pull request:** codemem to run: `463171c`. The code under `src/` has not changed on `main` since (`main` is at `f0a1574`)

## Done

**The times.** They replace the 20:00 and 21:00 UTC of earlier entries, and the 19:00 and 03:00 UTC of the entry of 12:25.

| | Pacific | UTC |
|---|---|---|
| Track B's results in this log | Fri Nov 27, 14:00; at the latest 15:00 | Nov 27, 22:00; at the latest 23:00 |
| The lock | Fri Nov 27, 16:30 | Sat Nov 28, 00:30 |
| The runs start. This is the latest we can start | Fri Nov 27, 17:00 | Sat Nov 28, 01:00 |
| Results frozen | Mon Nov 30, 23:59 | Tue Dec 1, 07:59 |
| Presentation | Tue Dec 1, 14:00 | Tue Dec 1, 22:00 |

**Where each track stands.**

- **Track C: ready.** codemem `463171c`. Not blocking: the thread fix, which waits behind track A's hard tier.
- **Track A: ready.** Fair tasks with vague prompts for pandas, playwright, duckdb, kubernetes and ruff, the seeded run sampler and its first sample (#68), the first hard-tier tasks (duckdb has 4 fair). Track A keeps adding tasks, and that is fine: a repo or a tier joins the runs when it is ready, as the run plan says.
- **Track B: pending.** What is due is below.

**What the runs are (Andre's decisions).**

- **Three setups: `grep`, `tool`, `upfront`.** The headline is grep only against codemem. Both codemem rows are codemem: as a tool the agent may call, and with the results of one codemem search placed in the first message.
- **Models and order:** the check run with Haiku and with Sonnet; then repetition 1 of Haiku and of Sonnet on every task that is ready; Opus as planned; then repetitions 2 and 3, Haiku first.
- **The commit is `463171c`.** One change can still enter before the lock: track B's switch for repeated results, off by default, if it passes our review. It touches neither an index nor a session's first search, so track A can build its indexes now.
- **No hooks, no change of wording, no fourth setup.** The last two were tested today (below).

**What settled the last two open points:** 119 sessions today on the Mac (Claude Code 2.1.285, 17 pandas tasks at their base commits, the agent names the functions to change; recounted from the raw records).

*A wording that asks the agent to write its query as "what the code does, then what is wrong"* (one local commit, not pushed):

| Haiku | Today's wording | New wording |
|---|---|---|
| Median words in the first query | 14 | 28 |
| L2: first search shows a function of the fix (of 16) | 8 | 12 |
| L1: the same | 12 | 13 |
| Right function in the answer, L2 / L1 (of 16) | 15 / 15 | 15 / 16 |
| Median cost, L2 / L1 | $0.0031 / $0.0023 | $0.0029 / $0.0027 |

The agents follow it, but the gain is inside the noise: two runs of today's wording differ by 3 tasks on the same measure (11 yesterday, 8 today). Sonnet called the tool in 7 of 17 sessions instead of 3 and spent more turns and tokens for answers no better. **Not adopted.**

*The 20 results in the first message, with the tool still offered:*

| | Haiku | Sonnet |
|---|---|---|
| Called the tool although it had the list | 12 of 17, at turn 1 | 0 of 17 |
| Against the list alone: cheaper / dearer, by task | 7 / 10 | 4 / 13 |
| Against grep only: fewer / equal / more turns | 12 / 3 / 2 | 9 / 6 / 2 |

The tool adds nothing measurable beside the list: Haiku repeats the search, and Sonnet never calls it and pays for its descriptions on every turn. **So no fourth setup.** For the product later: if both ship together, the tool's wording has to say that the list is already there.

## For track B (Wilson and his agent): what is due, and when

**Post in this log by 22:00 UTC, at the latest 23:00 UTC,** with the numbers and where the raw records are, so that we can follow and check before the lock. Post what you have at that time; do not wait for the rest. The frame is part 1 of the entry of 12:25: codemem inside the agent over MCP, a task that starts with a codemem search (10 cards, or 20 by name), one cached conversation; the hybrid and loop work, smaller chunks, the large index and the renaming control are on hold.

1. **codemem measured the way the runs use it. This one is a must.**
   - Claude Code with codemem over MCP, as in track A's `tool` setup, so that it is compatible with the runs. If you can, also the `upfront` form (the 20 names in the first message; its layout is in the next entry).
   - The prompt cache on: one conversation per run, as Claude Code does by itself.
   - Against grep only, same tasks, same prompt, same built-in tools.
   - **On Haiku and on Sonnet.**
   - Report **cost, time and tokens** (tokens by kind: new text, re-read from the cache, output), turns, how often codemem was called, and the functions of the fix found. Per arm and as pairs by task.
   - codemem `463171c`, the server loaded before the first search, one repo copy and one index per run (the rules of the 12:25 entry).
   - These numbers take the place of the loop numbers as track B's result.
2. **The repeated results (the work package of 12:25). Try it now; it is not a must.**
   - If it saves, and nothing is hidden from the agent and no changed code is ever shown as seen: the branch with the switch off by default, and the numbers.
   - If it does not save, or keeping it right costs more than it gives: say so with the numbers and drop it. "We tried, and here is why not" is a good result.
   - Do not let it hold up item 1.
3. **The two questions of 11:45 UTC** still want an answer.

## For track A

The request is in the entry that follows this one: build the `upfront` setup, run the check run with Haiku as well as Sonnet, and the order of the first runs. The runs start at 01:00 UTC. Indexes can be built now with `463171c`.

## Checked

- The times: Pacific is UTC minus 8 hours.
- `git diff 463171c origin/main -- src/` is empty.
- The session test: recounted from the raw records.

## Left

The plan's text (`docs/plan/runs.md`: setups, models, order, times) follows as a pull request.

## Blocked on, or needed from others

- **Track B:** items 1 to 3 above, by 22:00 UTC, at the latest 23:00 UTC.
- **Track A:** the next entry.

## Next

Andre: the review of track B's results from 22:00 UTC, the lock at 00:30 UTC, the go for the runs at 01:00 UTC.
