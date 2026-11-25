# `codemem init` now registers codemem with `alwaysLoad` for Claude Code (in pull request #26, not merged)

- **Track:** B
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-25 11:50 UTC
- **Work package:** B8 (the MCP integration)
- **Branch, commits, pull request:** branch `wilson/agent-steering-hooks`, a second commit `800e579`. Pull request #26, open, not merged

## Done

This corrects one line of the entry of 2026-11-25 11:36, which listed `alwaysLoad` as "not in
#26". It is in #26 now. It is item 3 of the entry of 10:22.

`codemem init --agents claude` writes this entry to `.mcp.json`:

```json
{"mcpServers": {"codemem": {"command": "codemem", "args": ["mcp"], "alwaysLoad": true}}}
```

The file for Cursor is unchanged. Nothing else changed: no tool name, no wording, no index.

## Checked

- `uv run pytest`: 277 passed.
- Claude Code's MCP documentation: `alwaysLoad` is a setting of a server entry, for every server
  type, and "The server's tools then load into context regardless of the ENABLE_TOOL_SEARCH
  setting." It also makes startup wait for that server's tools, for at most 5 seconds.
- **Not checked:** a Claude Code session started from an `.mcp.json` that `init` wrote. Track A's
  `tool` run of 11:34 listed the four tools in its first event, but that run passes its own MCP
  configuration and had tool search off.
- Not documented, so not known: what a Claude Code version without the setting does with it.

## Left

- As in the entry of 11:36: review and merge of #26, one live session with the hooks, the tag
  `codemem-today`.

## Blocked on, or needed from others

Nothing new.

## Next

- Wilson: get #26 reviewed and merged.
