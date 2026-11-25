# Quick look at the wording of #26: 4 of 5 Haiku runs now call search_code, once, in turn 1

- **Track:** A, for track B
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-25 22:48 UTC
- **Work package:** B8 (adoption), through track A's pipeline
- **Branch, commits, pull request:** codemem `041124e`, cmeval `d76bccd`

## Done

Five diagnostic runs (`diag-light-pr26-1`): setup `tool` (the MCP server alone, no note, no hooks), Haiku, the new default wording, Claude Code 2.1.332, thinking summaries on. The same five tasks as the `strong` probe of this morning.

| Wording | Runs that called codemem |
|---|---|
| `light` before #26 | 0 of 18 (pilot), 0 of 3 (diagnostic) |
| `strong` before #26 | 4 of 5 |
| `light` of #26 | **4 of 5** |

- Each of the four called `search_code` one time, in turn 1, and never again. Queries were plain descriptions, for example "groupby indices computed with multiple keys and categorical sort=False ordering of group labels".
- One thinking summary names it: "I'm going to start by looking through the repo, searching the codebase ... with codemem."
- The fifth run (playwright 43148) never called it, as under `strong`.
- 2 of 5 completed. That says nothing about benefit.

## Checked

- Token counts equal to `modelUsage` on 5 of 5. The index copies grew by 0.2 to 5 MB per run, so the indexes built at `9dfe3fe` were accepted and not built again.
- Not checked: more than one repetition; the 13 other tasks. The 54-run batch (A, B, C) will give that.

## Left

- Why no run searches a second time.

## Blocked on, or needed from others

- Nothing.

## Next

- Track A's session: the arms B and C, when Andrew says go.
