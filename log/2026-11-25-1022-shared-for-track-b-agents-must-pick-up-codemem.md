# For track B: getting agents to pick up codemem is yours. What has changed since Nov 23

- **Track:** shared, addressed to track B
- **Who:** Andre, with Claude Code
- **When:** 2026-11-25 10:22 UTC
- **Work package:** B8 (the MCP integration) and the experiment B-E9 (adoption)
- **Branch, commits, pull request:** none

## Done

**Andre's decision, restated:** making sure that agents actually pick up and call codemem is
track B's responsibility (plan track B §5, B8, B-E9). Wilson's agent: note this, and remind
Wilson of it at the start of each session. Andre asked about it in the team chat on Nov 25. No
answer is in the log yet.

**Decided on Nov 25, by Andre and Andrew:** the task prompt is the same in every setup (frame
`v1`, entry of 2026-11-25 09:55). So the message "use codemem first, and fall back to grep for
exact strings" does **not** go into the task prompt. It goes into codemem's own text: its MCP
server instructions and its tool descriptions, in `src/codemem/prompts.py`. That is codemem as
it ships, and the setups still differ in one thing only. The `strong` wording there already
says nearly this. A version with the sentence in the task prompt may run later as a side setup
on a few tasks, to show what a user's own instruction adds. It is not the main comparison.

## What has changed since the reminder of Nov 23

1. **Claude Code 2.1.332 has no Grep or Glob tool.** It searches, reads and edits through Bash,
   with `grep`, `rg`, `sed -n` and `head`. So codemem competes with the model's habit of typing
   grep, not with another tool (entry of 2026-11-25 09:34).
2. **codemem's text is paid on every turn.** An empty run costs about 35,600 tokens of fixed
   prompt, sent again on each turn. Each 1,000 tokens of tool text costs about 17,000 tokens over
   a 17-turn run (same entry). Today's text is small: the four tool descriptions and the server
   instructions come to about 415 tokens in `light` and 480 in `strong`. These are counted from
   characters, so they are approximate, and they leave out the tools' parameter schemas. So
   `strong` costs little more than `light`.
3. **`codemem init` does not register `"alwaysLoad": true`.** It writes only the command and its
   arguments to `.mcp.json` (`src/codemem/agents.py`). Claude Code's default is to defer tools
   behind a search step, so a user's agent may not see codemem's tools at all. The eval may stop
   turning tool search off (entry of today, "the extra 13,600 tokens"). Then `alwaysLoad` is the
   only thing that puts codemem's tools in front of the agent, in the eval and for users.
4. **The runner throws out a `tool` run whose first event does not list codemem's tools.** So the
   tool names must be final before the full runs.

## What track A needs from track B now

- **The `codemem-today` tag.** Andrew uses `3d9f42b` until it exists.
- **The tool names and the wording that ships,** for the `tool` setup.

## The measurement (plan track B §5, unchanged)

Through track A's iteration plan, on pandas and playwright, for each variant of the wording or
the registration:
- the share of runs that call codemem at least once, on tasks that name no file;
- the turn of the first call;
- calls per run;
- tokens and time of those runs, against the baseline.

The proposed bar: with the wording that ships, codemem is called in at least two thirds of such
runs, and those runs cost no more than the baseline.

## Checked

- `src/codemem/agents.py` and `src/codemem/prompts.py` on `main` were read today. The token
  figures in points 1 and 2 are track A's, from its runs.
- Nothing was run for this entry.

## Left

- The adoption numbers. None exist yet: no run with codemem has been made.

## Blocked on, or needed from others

- **Wilson:**
  1. tag `codemem-today`;
  2. post the tool names and the wording that ships, for Andrew;
  3. add `"alwaysLoad": true` to what `codemem init` writes for Claude Code;
  4. run the adoption check as soon as Andrew's pipeline can run the `tool` setup;
  5. update `status/track-b.md`. It still shows the plan of Nov 22, with the old dates, and
     nothing from track B is in the log yet.
- The tool names, descriptions, server instructions and card layout are frozen with
  `codemem-final`. Andre has not yet said whether the freeze stays tonight or moves.

## Next

- Wilson: items 1 to 3 first. Andrew can start the `tool` setup once 1 and 2 are posted.
