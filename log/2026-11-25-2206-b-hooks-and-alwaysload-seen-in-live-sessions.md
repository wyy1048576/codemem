# The hooks and `alwaysLoad` of #26 work in live Claude Code sessions; the lost-trail reminder changed nothing in the one case tried

- **Track:** B. Points 4 and 5 answer track A (15:57, 20:41) and Andre (20:56)
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-25 22:06 UTC
- **Work package:** B8 (the MCP integration)
- **Branch, commits, pull request:** no new commit. The runs used `wilson/agent-steering-hooks` at `800e579`. Pull request #26 was merged into `main` by Andrew at 21:13 UTC as `041124e`

## Done

**1. Six live sessions.** Each is one headless run (`claude -p`) of Claude Code 2.1.314 with
Sonnet (`claude-sonnet-5-5`), on Wilson's laptop, in a clone of `requests` v2.32.3 on which
`codemem init --write-hooks` had been run. So the clone has the `.mcp.json` with `alwaysLoad`, the
two hooks and the agent note. This version of Claude Code has the Grep and Glob tools. One run per
row, so each row shows that a behaviour happens, not how often.

"Tool calls" lists every tool call of the run in order. "Turns" is `num_turns` in Claude Code's
result event.

| Run | Prompt | What differs | Tool calls | Turns |
|---|---|---|---|---|
| A | "Where does this library decide whether to drop the Authorization header when it follows a redirect?" (no identifier) | tool search forced on (`ENABLE_TOOL_SEARCH=true`) | `search_code` | 2 |
| B | as A | as A, but codemem registered without `alwaysLoad` (`--mcp-config`, `--strict-mcp-config`) | `ToolSearch`, `search_code` | 3 |
| C | "call Grep with pattern zzz_not_here_qq; if refused, repeat; report every message word for word" (a scripted test) | tool search forced on | Grep (refused), Grep (nothing found) | 3 |
| D | "List every line that calls or defines should_strip_auth" (an exact name) | none | Grep (refused), Grep | 3 |
| E | "Explain what the function strip_authorization_on_redirect does" (a name that does not exist) | none | Grep (refused) and `search_code` in one turn, Grep (nothing found), Grep, Read | 6 |
| F | as E | hooks off (`--settings` with `disableAllHooks`) | Grep (nothing found), `search_code`, Grep | 4 |

**2. What this confirms of #26's "Not checked" list.**
- `alwaysLoad` does what the documentation says. With tool search on, the agent called
  `search_code` as its first call (A). Without the setting it had to call `ToolSearch` first (B).
  Claude Code read the server from the `.mcp.json` that `init` wrote, with no flag (`source:
  project`, `status: connected`).
- The first-search hook refuses the first Grep once, and the same call repeated goes through
  (C, D, E). The agent sees the refusal as `PreToolUse:Grep hook error: <our text>`.
- The lost-trail hook's "nothing found" reminder reaches the agent, as `PostToolUse:Grep hook
  additional context: <our text>` (C: the agent quoted it. E: the hook's state file shows it
  fired; the text is not in the event stream).
- A Grep result has the shape the hook assumes: `{"mode": "files_with_matches", "filenames": [],
  "numFiles": 0, "totalFiles": 0}`.
- The footer "Lost the trail later? Search again in different words." is at the end of the live
  `search_code` result.

**3. Behaviour, one run per case.**
- No identifier in the question: `search_code` first, with no push from a hook (A, B).
- An exact name: the agent went to Grep, was refused once, repeated the Grep and never called
  codemem (D). So the first-search hook cost one tool call and did not divert it.
- A dead end: the reminder had nothing to change. In E the agent had already called `search_code`
  when the reminder arrived. In F, with no hooks, its next call after the empty Grep was
  `search_code` anyway. Both answers were right (the function does not exist; the closest is
  `should_strip_auth`). The hooks made E two turns longer than F.

**4. For track A (15:57, point 4) and Andre (20:56, item 2).** The same on 2.1.314: the tool
result is one JSON string, `{"result":"1. src/requests/sessions.py:127-157 ...\\n   def ..."}`,
both in the `tool_result` content and in `tool_use_result.content`. Sonnet answered from it in
all four runs that searched (A, B, E, F). Not checked what the model itself receives.

**5. How this fits track A's finding (20:41, point 5).** It agrees with it. The one prompt with
no identifier went to `search_code` first; the one with an exact name went to Grep. This is not
evidence about Haiku, about 2.1.332, or about the 18 pilot tasks: here the model is Sonnet, the
repo is small and well known, the wording is #26's, and the agent has a Grep tool.

## Checked

- Every statement above is from the six event streams (`--output-format stream-json`) and the
  hook's state files under `~/.codemem/hook-sessions/`. The streams are on Wilson's laptop, not in
  the repo.
- Cost as reported by Claude Code: about $0.96 for the six runs.
- **Not checked:** the "more than 50 files" and "three in a row" reminders; a Glob result; the
  first-search hook on a shell `rg`, `grep` or `find`; Claude Code 2.1.332; Haiku; any repetition.
- No adoption number exists. B-E9 is still open.

## Left

- From Andre's entry of 20:56, not started and not decided: items 1 to 4 (the model still loading
  on the first search, plain text instead of the JSON string, an absolute `path_prefix`, results
  that are a next step), item 5 (inject the first results), item 6 (a reminder after a shell
  search: today only the first-search hook looks at shell commands), item 7 (grep-shaped output
  for `codemem search`).
- The tag `codemem-today`.

## Blocked on, or needed from others

- **Andrew:** #26 is on `main`, so the `light` wording there is the new one. It is **not** declared
  frozen: items 2 to 4 of Andre's entry would change what a result looks like. A frozen commit
  will be named here.
- Nobody else.

## Next

- Wilson: choose from Andre's list. Claude Code's reading of this evidence, not yet Wilson's
  decision: the faults (items 1 to 4) and a shell reminder (item 6) matter more than the
  lost-trail hook as built.
