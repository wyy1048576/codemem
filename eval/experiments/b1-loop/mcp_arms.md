# codemem over MCP in Claude Code: hooks against a CLAUDE.md only (smoke test, 2 tasks)

Two easy L1 tasks of `e2e-b45`: Sonnet 5.5, medium effort, one Claude Code conversation per run (prompt cache on), one run each.
codemem through `mcp_codemem.py`, on the older codemem `7c24558` (not the `463171c` of item 1).

| Arm | What the agent gets beside Read, Edit, Write, Grep and Glob |
|---|---|
| `grep` | nothing |
| `mcp` | codemem, PR #26's first-search and lost-trail hooks and wording, `alwaysLoad`, our hooks (repeated greps, a stuck note, a Stop review), an appended prompt (`system_mcp.txt`) |
| `mcpmd` | codemem with `alwaysLoad` and **only a `CLAUDE.md`** (`claude_md_codemem.md`) that says when to call it; no hooks, no appended prompt. The repo's own `CLAUDE.md` and `.claude/` are moved aside for the run |

| Task | Arm | Function edited (the gold one) | Cost | Turns | Seconds | codemem searches | Cache written / read (tokens) |
|---|---|---|---:|---:|---:|---:|---|
| playwright-41682 | grep | yes, `resolveGlobBase` | $0.041 | 4 | 18 | 0 | 6,640 / 28,540 |
| playwright-41682 | mcp | yes | $0.056 | 7 | 38 | 1 | 7,235 / 71,331 |
| playwright-41682 | mcpmd | yes | $0.059 | 4 | 35 | 0 | 11,536 / 29,087 |
| pandas-67025 | grep | `ArrowExtensionArray._str_extract`, 2 of 5 gold | $0.043 | 4 | 16 | 0 | 6,177 / 26,934 |
| pandas-67025 | mcp | the same | $0.081 | 9 | 34 | 0 | 10,025 / 84,232 |
| pandas-67025 | mcpmd | the same | $0.048 | 4 | 20 | 0 | 6,766 / 31,768 |

- **Without hooks, the turns are grep's:** Grep, Read, Edit, answer in both tasks, the same as grep. The `mcp` arm's extra turns
  were the hooks (pandas: a refused first Grep, then the Stop review) plus some extra looking around.
- **codemem was not called in `mcpmd`.** Both prompts name an exact identifier, and the `CLAUDE.md` says to Grep in that case.
  So these two tasks test the overhead, not codemem's search.
- **What is left of the overhead** is codemem's tool descriptions and the `CLAUDE.md` on every turn: pandas $0.048 against $0.043.
  Playwright's $0.059 is mostly a cold cache: its first turn read nothing from the cache and wrote 8,723 tokens (the
  first run with the new prompt); pandas, run next, read 4,609 at its first turn.
- One run per cell: inside the noise. Raw streams: `out/e2e-b45/L1/<task>/{grep,mcp,mcpmd}.*`.
