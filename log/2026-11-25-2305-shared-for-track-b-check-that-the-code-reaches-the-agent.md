# For track B: check that the code in a result reaches the agent as code, before comparing approaches

- **Track:** shared, addressed to track B
- **Who:** Andre, with Claude Code
- **When:** 2026-11-25 23:05 UTC
- **Work package:** B8 and B-E9
- **Branch, commits, pull request:** none

## Done

**Andre's note, for Wilson's own analysis of which approach to try.** Andre thinks that in the
runs so far the code chunks did not reach the agent correctly, and understands that Wilson's
agent is already changing this. This entry puts what is known in one place. It decides nothing.

**1. What codemem hands back** (`src/codemem/server.py` and `render.py` on `main` at `041124e`):
- `search_code` returns cards: the location, the signature and a preview of the best lines, at
  most 12 lines or 800 characters. It does not return a chunk's whole code.
- `get_chunk` returns the whole code of one chunk, with its callers and callees. A class of 80
  lines or more comes back as its outline.
- So an agent that calls `search_code` once and never `get_chunk` has seen previews only. In
  track A's probe at `strong`, the four runs that used codemem did exactly that (entry of 15:57).

**2. How a result arrived in Claude Code.** Both tracks saw the same thing: the tool result is
one JSON string, `{"result":"1. src/requests/sessions.py:127-157 ...\\n   def ..."}`, with line
ends written as `\\n`. Track A saw it on 2.1.332 (15:57, point 4), track B on 2.1.314 in the
`tool_result` content and in `tool_use_result.content` (22:06, point 4). Neither checked what the
model itself receives.

**3. Where it may come from.** All four tools in `server.py` are functions that return a `str`
and say so in their signature (`-> str`). The `{"result": ...}` wrapper is not written anywhere
in codemem, so it is added between the function and the agent: by the MCP library, or by Claude
Code when it shows the result. Which of the two is not checked. The MCP library's documentation
for the installed version says how a tool returns plain text.

**4. The check that settles it.** Track A's runner can save every request body
(`CMEVAL_E2E_BODIES=1`, #28). In a run that calls `search_code`, open the request that follows
the call and read the `tool_result` block. It is exactly what the model was sent:
- real line ends and no wrapper: the model reads the cards as text, and the shape seen in the
  stream is only how Claude Code prints it;
- the JSON string with `\\n`: the model reads every result as one long escaped line, code
  previews included.

**5. Why this comes before comparing approaches.** If results arrive as one escaped line, every
approach is measured through that fault: the wording, the hooks, a first search done for the
agent. "The agent called once and never again" would then say little about any of them.

## Checked

- Point 1 is read from the code on `main`. Points 2 and 3 are from the two tracks' entries and
  from `server.py`. Nothing was run for this entry.
- Not checked: what the model receives; whether the wrapper comes from the MCP library or from
  Claude Code.

## Left

- Track B's choice of approach.

## Blocked on, or needed from others

- **Wilson:** the check of point 4, then the fix if it is needed. It was item 2 of the entry of
  20:56.
- **Andrew:** a saved request body from one run that calls `search_code` would settle point 4.
  The diagnostic runs of 20:41 made no codemem call, so one `strong` run with
  `CMEVAL_E2E_BODIES=1` is needed.

## Next

- Wilson's agent.
