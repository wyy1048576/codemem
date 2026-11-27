# Track B, side test: codemem over MCP with only a CLAUDE.md (no hooks, no appended prompt) takes grep's turns on 2 easy tasks; the hooks were the extra cost

- **Track:** B. Evidence for item 1 of 12:40 and for Andre's rule "no hooks, no change of wording". It does not replace item 1
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-27 23:32 UTC
- **Work package:** B8
- **Branch, commits, pull request:** `wilson/loop-vs-grep-e2e`, commit `a423e3a`, PR #45; results in `eval/experiments/b1-loop/mcp_arms.md`, raw streams in `out/e2e-b45/L1/<task>/{grep,mcp,mcp0,mcpmd}.*`

## Done

**Why.** Track B's local `mcp` arm (PR #26's hooks and wording, our own hooks, an appended prompt) cost more than grep on two easy tasks: $0.056 and $0.081 against $0.041 and $0.043. The pandas session never called codemem and still took 9 turns. Its transcript shows where they went. Turn 1 was a Grep refused by the first-search hook, and turn 2 the same Grep again. The last two turns were the Stop hook's review. Three turns in between were extra looking around.

**What ran.** A new arm, `mcpmd`: codemem over MCP with `alwaysLoad`, no hooks, no appended prompt. It gets only a `CLAUDE.md` that says when to call `search_code`: at the start when the task gives no exact name, or after two Greps that did not find the code; never when the task names an exact function, file or error string. The repo's own `CLAUDE.md` and `.claude/` were moved aside for the run, because the grep arm never loads them. Sonnet 5.5, medium effort, one run per cell, codemem `7c24558` through track B's wrapper (not `463171c`).

| Task (L1) | Arm | Gold function edited | Cost | Turns | codemem searches |
|---|---|---|---:|---:|---:|
| playwright-41682 | grep | yes | $0.041 | 4 | 0 |
| playwright-41682 | mcp (hooks + prompt) | yes | $0.056 | 7 | 1 |
| playwright-41682 | mcpmd (CLAUDE.md only) | yes | $0.059 | 4 | 0 |
| pandas-67025 | grep | 2 of 5 | $0.043 | 4 | 0 |
| pandas-67025 | mcp (hooks + prompt) | 2 of 5 | $0.081 | 9 | 0 |
| pandas-67025 | mcpmd (CLAUDE.md only) | 2 of 5 | $0.048 | 4 | 0 |

- **Without hooks the session is grep's:** Grep, Read, Edit, answer, the same function edited.
- **codemem was not called:** both prompts name an exact identifier, and the `CLAUDE.md` says to Grep then. So these tasks measure the overhead, not the search.
- **The overhead left** is the tool descriptions and the `CLAUDE.md` on every turn: pandas $0.048 against $0.043. Playwright's $0.059 is mostly a cold cache: its first turn read nothing from the cache and wrote 8,723 tokens.

## Checked

- Turns, tool calls and cache use were read from the raw streams. The edited hunks were compared with grep's diff: the same function in both tasks.
- **Not checked:** more than one run per cell, tasks without an exact name in the prompt, Haiku, `463171c`.

## Left

Nothing more is planned for this test. It supports Andre's rule: item 1's `tool` setup (no hooks, no wording) is the right comparison.

## Blocked on, or needed from others

Nothing.

## Next

Item 1, as posted at 23:20.
