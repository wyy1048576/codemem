# Track B: item 1 has started (late): Claude Code with codemem 463171c over MCP against grep only, Haiku and Sonnet

- **Track:** B. The line asked for in the entry of 12:55 UTC
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-27 23:20 UTC
- **Work package:** B1, B8 (item 1 of 12:40)
- **Branch, commits, pull request:** none yet. Harness: `analysis/b1-links/llm_query/run_item1.py` and `score_item1.py` on Wilson's laptop (pushed with the results)

## Done

**Item 1 started at 23:16 UTC, past the 23:00 limit.** Results follow here as soon as the first full block is in.

- **Arms:** `grep` (Claude Code, built-in Read, Edit, Write, Grep, Glob; no shell) and `tool` (the same plus codemem's MCP server, all its tools allowed, wording `light` as 463171c ships it). Nothing else differs: same prompt, flags, tools.
- **Models:** `claude-haiku-5-5` and `claude-sonnet-5-5`. Claude Code 2.1.314, `-p`, stream-json, `--setting-sources ""`, `--strict-mcp-config`, `--permission-mode acceptEdits`. Prompt cache on (one conversation per run).
- **Tasks:** the 14 vague-prompt tasks of PR #45 (8 pilot, 6 b7; pandas and playwright), L1 and L2. One run per cell first, a second if time allows.
- **codemem `463171c`** (a worktree at that commit). Each run: its own repo copy at the task's base commit and its own index, copied from a base index that 463171c built for the repo and then brought up to date from that run's copy before the agent starts; `codemem status` saved per run.
- **Model loaded before the first search:** `catchup_budget_ms = 180000`, so the first search waits for the model. Every result is checked for a loading note.

**Deviations, said now:** the embedder is our Intel Arc plugin (same model, jina-code-embeddings-0.5b; documents on the GPU in float16, queries on the CPU in float32), because a CPU-only index of pandas does not fit the time. No request bodies are saved (no proxy here); every stream is.

## Checked

- A first grep run (Haiku, playwright 41850, L2) completed with tokens read from the cache.

## Left

The runs, the checks of the 13:15 entry with their counts, the tables.

## Blocked on, or needed from others

Nothing.

## Next

Wilson, with Claude Code: the results here.
