# Track B: why grep is cheaper than the codemem loop: a token and cache breakdown on the 8 L2 tasks

- **Track:** B
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-26 15:30 UTC
- **Work package:** B1, end-to-end cost
- **Branch, commits, pull request:** none. Scripts and outputs are on Wilson's laptop
  (`analysis/b1-links/llm_query/out/e2e-vague8/replay/`); `llm.py` there now logs token usage per call

## Done

The 8 contamination-free pilot tasks at L2 (entry of 14:40). Grep's tokens are from Claude Code's usage reports. The loop's
costs are exact per call (from its answer cache). Its tokens are rebuilt from the characters of each call's input,
fitted to 6 fresh probe calls; the rebuilt sizes are within 2% of the 6 runs that replayed exactly.

| | grep | loop, 5 per round | loop, 10 per round |
|---|---|---|---|
| Model requests | 48 (Claude Code counts 60 turns) | 39 | 29 |
| Input tokens sent, all requests | 539k | ~221k | ~180k |
| …of which cache reads | 479k (89%) | ~48k (system prompt only) | ~35k (system prompt only) |
| …of which cache writes | 60k | ~173k | ~145k |
| Output tokens | 17k | ~27k | ~22k |
| Code read (characters) | 85k (tool results) | 277k | 274k |
| Cost, total (USD) | 0.46 | 0.97 | 0.80 |
| …on cache writes | 0.24 | 0.69 | 0.58 |
| …on output | 0.17 | 0.27 | 0.22 |

Rates the billed costs imply, per million tokens: cache write (1 hour) about $4, cache read about $0.10,
output about $10, uncached input about $2. They reproduce every call's cost.

**Why grep is cheaper although it sends 3 times more tokens:**
- Grep is one conversation: each turn re-sends the earlier ones as an exact prefix, billed as cheap cache reads.
- Each loop call is a new `claude -p` conversation. The CLI writes its whole input to the cache at the premium rate,
  and nothing ever reads it back: about 70% of the loop's cost buys nothing.
- The loop also reads about 3 times more code (whole chunks, test files included) and writes more output.

Per request: grep about 11k input tokens at an average of about $0.49 per million, loop-10 about 6k at about $3.2 per
million.

**Other providers.** DeepSeek, OpenAI and Google also discount cached prefixes. As far as we know, DeepSeek and
OpenAI charge no premium to store them (to be checked against their pricing pages). On those prices, the loop
loses the write premium but grep still wins: input in normal-token equivalents is about 108k for grep against about
149k for loop-10.

## Checked

The rebuilt call sizes match the 6 runs that replayed from the cache to within 2%. The rates reproduce the cost of the
probe calls and of grep's runs. The 6 probe calls cost about $0.11.

## Left

Send loop calls without cache writes, which should take loop-10 from about $0.80 to about $0.51. Show the judge fewer
chunks, or no test files.

## Blocked on, or needed from others

Nothing.

## Next

Wilson: a loop without cache writes and with a smaller judge input.
