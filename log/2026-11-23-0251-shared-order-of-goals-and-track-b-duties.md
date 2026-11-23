# The order of goals, and two duties for track B

- **Track:** shared: for everyone to read
- **Who:** Andre, with Claude Code
- **When:** 2026-11-23 02:51 UTC
- **Work package:** none: planning. It adds B8 and the experiment B-E9
- **Branch, commits, pull request:** `main`. The edits to `docs/plan/`, `CONTRIBUTING.md`, `AGENTS.md` and `CLAUDE.md` are in Andre's working tree, for him to commit

## Done

**The order of goals is now at the top of `docs/plan/overview.md`.** Andre set it, and everyone
works to it:

1. **Primary: the study.** An end-to-end account of what an index costs and what it gains for a
   coding agent that already has grep: completion, time and tokens over the whole agent run. If
   the answer is that grep is simply better, we report that. This is why track A matters most.
2. **Part of the study: the model gap.** A result for Claude may not hold for smaller open models
   such as Qwen or Llama, so the same comparison is run with them.
3. **Secondary: the system.** A codemem that is small and fast and finds what grep misses. This is
   tracks B and C.

**Track B owns the MCP integration** (track B §5, work package B8, experiment B-E9). It is in
scope because a better ranking changes nothing if the agent keeps using grep: agents such as
Claude Code and Codex have to actually call codemem. That covers how the tools are registered,
the text that tells an agent when to call them, a fast and useful first answer, and a server that
never hangs. Track A's pipeline measures it: how often codemem is called, and at which turn first.

**Track B announces every change on the day it lands** (track B §8, `CONTRIBUTING.md` §3). Changes
to the algorithm and to what the index stores are expected. Each one gets a log entry that says
what changed, whether indexes must be rebuilt, whether a tool name, a description or the card
layout changed, its result on the retrieval eval, and the configuration and commit to run.

## Checked

- Read in `src/codemem/agents.py`: `codemem init` writes `.mcp.json` for Claude Code and prints a
  snippet for Codex. It does not ask for the tools to be loaded up front.
- Read in `src/codemem/prompts.py`: all agent-facing text is there, in three strengths. The
  default is `light`.
- Nothing was run. The bar in B-E9 (called in two thirds of the runs that name no file) is a
  proposal, to settle after the first measurement.

## Left

- The adoption bar, after the first numbers.

## Blocked on, or needed from others

- **Wilson:** read track B §5 and §8 before the next change lands.
- **Andrew:** the report of the iteration plan (track A §3.4) should show how often codemem was
  called and at which turn first. The run record lists both now (track A §6).

## Next

- Wilson: B1, then a first look at adoption as soon as one task runs end to end.
