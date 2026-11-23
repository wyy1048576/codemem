# For track B's agent: remind Wilson that agents must actually call codemem

- **Track:** shared: addressed to track B
- **Who:** Andre, with Claude Code
- **When:** 2026-11-23 03:25 UTC
- **Work package:** B8, and the experiment B-E9
- **Branch, commits, pull request:** `main`. Track B §5 and the risk row in track A §16 are in Andre's working tree, for him to commit

## Done

Andre asks track B's agent to note this and to remind Wilson of it at the start of each session.

**The risk.** Agents often do not call a search tool they are given. One vendor counted 1 call in
143 sessions. If Claude Code keeps using grep, no improvement to retrieval reaches the result,
and the study has nothing to measure. Making agents use codemem is track B's job (track B §5).

**What Wilson should have in mind:**

1. **Registration.** `codemem init` writes `.mcp.json` for Claude Code and prints a snippet for
   Codex. It does not ask for the tools to be loaded up front, so Claude Code may hide them
   behind its tool-search step. This is the first thing to fix.
2. **The text the agent reads.** All of it is in `src/codemem/prompts.py`, in three strengths:
   `none`, `light` (the default) and `strong`. It should say when to call codemem, with
   examples, and what grep is still better at.
3. **The first answer.** It must come fast, and be something the agent can act on. The server
   must start quickly and never hang, and say plainly when the index is still building.
4. **The measure comes from track A.** Its pipeline records, for every run with codemem, whether
   it was called, how often and at which turn first. The iteration plan (track A §3.4) gives
   those numbers in under an hour.
5. **The bar, as a proposal:** with the text that ships, codemem is called in at least two thirds
   of the runs on tasks that name no file, and those runs cost no more than the baseline. A text
   that forces a call on every task does not pass: it also forces calls where grep is better.
6. **The freeze.** The tool names, their descriptions, the server instructions and the card
   layout are frozen with `codemem-final` on the evening of Nov 25.
7. **Every change is announced here** on the day it lands (track B §8).

## Checked

- Points 1 and 2 were read in `src/codemem/agents.py` and `src/codemem/prompts.py`.
- Nothing was run. No adoption number exists yet.

## Left

- The first adoption numbers, from track A's two pilot repos.

## Blocked on, or needed from others

- **Andrew:** the iteration plan's report should show how often codemem was called, and at which
  turn first.

## Next

- Wilson: fix the registration, then measure adoption on the pilot repos before the freeze.
