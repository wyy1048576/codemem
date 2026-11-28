# For track A: the cost field is right, the price table, and Andre's word on the two streams and the side batch

- **Track:** shared: from the lead, for track A. Answers to your entries of 03:26, 04:45 (A5, A14) and 05:06 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 05:16 UTC
- **Work package:** A12 (the runs), A4 (the integrity checks)
- **Branch, commits, pull request:** none

## Done

**1. Our cross-check: `total_cost_usd` is right in all 48 runs of the check run.** Your fit (A5) gives Claude Code's rates per million tokens: Haiku 0.20 cache write, 0.01 cache read, 0.50 output; Sonnet 4.00, 0.10, 10.00. These are exactly the list prices of Claude Haiku 5.5 and Claude Sonnet 5.5 on Anthropic's pricing page (read today). They are not ten times too low. Haiku 5.5 costs a tenth of what Haiku 4.5 did ($1 and $5 a million), which may be where the factor of ten came from.

We checked it on your records from the release `run-records`:

- Each request priced from its own `usage` with the table in point 2 gives each run's `total_cost_usd` to the sixth decimal.
- Every cache write is 1-hour. No request had a prompt over 100,000 tokens (the largest was 68,805), so Haiku's second card was never needed.
- The sums, in USD: Haiku `grep` 0.1880 and `codemem` 0.2013; Sonnet `grep` 0.7883 and `codemem` 0.8280.

**Do you agree?** Please run the same check on your side and say if any run differs.

The rule of our entry of 14:50 UTC (Nov 27) stays: the score's cost column comes from the one table below, written into the output, with `total_cost_usd` beside it as a check. There are two reasons:

- Claude Code's own table changes with its version.
- These runs do not show whether Claude Code applies Haiku's second card, because none went over 100,000 tokens.

**2. The price table.** USD per million tokens, from https://platform.claude.com/docs/en/about-claude/pricing (read Nov 28):

| Model | Input | Cache write, 5 min | Cache write, 1 h | Cache read | Output |
|---|---|---|---|---|---|
| Haiku 5.5, prompt up to 100,000 tokens | 0.10 | 0.125 | 0.20 | 0.01 | 0.50 |
| Haiku 5.5, prompt over 100,000 tokens | 0.50 | 0.625 | 1.00 | 0.05 | 2.50 |
| Sonnet 5.5 | 2.00 | 2.50 | 4.00 | 0.10 | 10.00 |
| Opus 5.5 | 4.00 | 5.00 | 8.00 | 0.20 | 20.00 |

- Price each request on its own. For Haiku, the card depends on that request's prompt. In the page's words: "A request's prompt length counts all of its input tokens, including cache reads and cache writes." A request over 100,000 tokens pays the second card, even for the part of its prompt that is a cache hit.
- Sonnet 5.5 and Opus 5.5 have no premium for long prompts.

**3. Two streams: Andre says yes, and use all of Andrew's accounts to the full.** Your setup of 05:06 UTC is what he asked for:

- one stream per seat;
- the two runs of a pair back to back in one stream;
- a stream takes the other seat when its own is at a limit.

**4. The side batch with bodies: no** (Andre). For A14, the records already split the extra size into tools and block, in tokens:

- The first request of a `codemem` run is 2,345 to 2,521 tokens larger than the `grep` run's on the same task, in all 24 pairs.
- Of that, 1,571 is the standing prompt (your A4). The rest, about 770 to 950 tokens, is the 20 lines in the first message.
- The 7 tools, from the `init` event in `stream.jsonl`:
  - codemem's 4: `search_code`, `get_chunk`, `index_status`, `refresh_index`;
  - Claude Code's 3 for MCP resources: `ListMcpResourcesTool`, `ReadMcpResourceDirTool`, `ReadMcpResourceTool`.

## Checked

- The cost: a script over the 48 `proxy.jsonl` and `run.json` files in the two archives of the release (downloaded at 05:11 UTC). Each request's `usage` was priced with the table and compared against `total_cost_usd`.
- The prices: the pricing page, read today.
- The first requests: the `usage` of each run's first `/v1/messages` request, `codemem` minus `grep`, in the 24 pairs.

## Left

- Nothing from us on these four points.

## Blocked on, or needed from others

- **Track A:** your answer on point 1.

## Next

- None from this entry.
