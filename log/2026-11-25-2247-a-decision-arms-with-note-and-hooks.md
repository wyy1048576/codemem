# Decision: the eval gets two more codemem arms, one with the agent note and one with the hooks

- **Track:** A. Answers track B's question (status, "whether an arm with the hooks or the agent note is wanted")
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-25 22:47 UTC
- **Work package:** A1 (setups), B8 (adoption)
- **Branch, commits, pull request:** none yet. Nothing is built

## Done

**A decision, made by Andrew after the team meeting; Wilson asked for both arms.**

| Arm | Setup | The agent gets | State |
|---|---|---|---|
| baseline | `grep` | Claude Code alone | built |
| A | `tool` | + codemem's MCP server | built |
| B | `tool-note` (working name) | + the agent note that `codemem init` writes by default | to build |
| C | `tool-hooks` (working name) | + the note and the two hooks of `codemem init --write-hooks` | to build |

- The note and the hooks will come from the real `codemem init` command, run in the task repo before the agent starts, and not from a copy of the text. The repo's own agent files are still removed first.
- The arms are reported apart. C is "everything on": the first shell search is refused once, so use is pushed, not chosen.
- First batch, when built: 18 tasks x A, B, C = 54 Haiku runs, on codemem `041124e`, two runs at a time. It measures use of codemem, not benefit.
- The PC's codemem is at `041124e` (#26) from now. The 20 indexes built at `9dfe3fe` are reused: the index code did not change.

## Checked

- Nothing to check: a decision and a plan.

## Left

- The build (about half a day) and the batch. Both wait for Andrew's go.

## Blocked on, or needed from others

- **Wilson:** on Claude Code 2.1.332 the agent has no Grep or Glob tool, so only the shell part of the first-search hook can fire, and the lost-trail hook never does. If C should have a lost-trail reminder for shell searches, it has to be in codemem before the batch. Say here if a newer commit than `041124e` should be used.

## Next

- Track A's session: build B and C when Andrew says go.
