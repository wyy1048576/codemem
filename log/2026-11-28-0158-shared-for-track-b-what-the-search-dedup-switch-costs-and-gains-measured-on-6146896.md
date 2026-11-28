# For track B: what the search-dedup switch costs and gains, measured on `6146896`. It costs nothing we can measure; `shorten` saves about 1% of a Haiku session's bill; `refill` costs more than it saves

- **Track:** shared: from the lead, for track B. The numbers announced in our entries of 00:40 and 00:58 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 01:58 UTC
- **Work package:** B8, item 2
- **Branch, commits, pull request:** `wilson/search-dedup` at `6146896`, PR #73

## Done

**The answer.** The switch costs nothing in time. `shorten` only removes text, and what it removes is about 1% of what a Haiku session costs. `refill` adds more text than it saves. Sonnet and Opus never search twice, so for them it does nothing.

**1. Time for one search** (the real embedding model, a copy of the index of pandas 70205, the server at `6146896`, 100 pairs of real queries whose results overlap, 200 pairs per mode).

| Mode | First search, median (ms) | Second search, median (ms) | Second search against `off`'s on the same pair (ms) |
|---|---|---|---|
| `off` | 86.8 | 83.3 | 1.5 between two runs of `off` |
| `shorten` | 85.7 | 83.0 | −0.1 |
| `refill` | 84.7 | 81.9 | −0.6 |

The 95th percentiles are 111 to 129 ms in every mode.

**2. Tokens and dollars inside the same sessions** (a replay without a model call: the searches of 85 saved Haiku sessions with the switch off were sent again in each mode, in order, on the task's own index; each replayed first search equalled the recorded answer byte for byte).

- **43 of the 85 sessions searched more than once.** Only those can differ.
- **`shorten`** sent 134 results as short lines: 8.4% of the search text of those 43 sessions. That is 400 tokens and $0.000093 per such session on average, 2.2% of its bill. Over all 85 sessions it is 1.3% of the bill, and the median session saves nothing.
- **`refill`** adds 4.9% search text (141 more cards) and costs 1.3% more.
- **Search text is about 2.3 characters per token,** not 4: measured from the sessions' own requests (0.433 tokens per character). So the token numbers of your E1 were too low by a factor of about 1.7.
- **Sonnet:** 0 of 67 saved sessions searched twice. **Opus:** 0 of 6 searched at all.

**3. Against the noise.** Two runs of `off` on the same task differ by 62,875 tokens (standard deviation). That is 72 times the mean gain. To see the gain in whole sessions would take about 41,000 sessions per arm.

- In the 102 sessions of 15:15 UTC (`242a7bf`) every difference between a mode and `off` in quality, turns, tokens and seconds is inside what two runs of `off` differ by.
- In 51 new sessions at L2 on `6146896`, `shorten`'s sessions were shorter than that (2 turns and 29,000 tokens fewer at the median). In the sessions of 15:15 UTC the means went the other way. With the replay's 1% in mind, we read this as chance, not as an effect.

**What follows for PR #73.**

- If it merges, `shorten` is the mode worth offering, with `off` as the default. `refill` is a net cost on these sessions.
- Andre's decision stands: a proposal, ready to merge once the open point of our review of 00:58 UTC is fixed and `main` is merged in, on hold, and not part of the first runs.

## Checked

- By a measurement agent on Andre's Mac. With the switch off, three searches, `initialize` and `tools/list` through the server at `6146896` were byte for byte those of `463171c`.
- The unit prices come from the sessions' own records (their token classes and the cost Claude Code reports), not from a price list.
- **Not measured:** a third repetition of the sessions, and L1 on `6146896`; the switch on for Sonnet or Opus; other repos; sessions that edit.

## Left

Nothing on our side.

## Blocked on, or needed from others

Nothing.

## Next

Track B: job 1 comes first (our entry of 01:42 UTC).
