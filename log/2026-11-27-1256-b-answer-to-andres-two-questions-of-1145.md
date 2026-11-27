# Track B, answer to Andre's two questions of 11:45 UTC: yes, the hybrid replaces the agent, and track B moves back to MCP; no MCP run yet shows codemem worse than grep

- **Track:** B. Answers the shared entry of 2026-11-27 11:45 UTC. Read too: 12:25, 12:40, 12:55, 13:05, 13:15
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-27 12:56 UTC
- **Work package:** B1, B8
- **Branch, commits, pull request:** none (PR #45 unchanged by this entry)

## Done

**Question 1. The hybrid is not a coding agent with codemem added.**

- **(a) Your reading is right.** Each step of `e2e_hybrid.py` and `e2e_hybrid2.py` is one `claude -p` call with no tools, our own system prompt and a JSON schema; our Python program runs the search and applies the edit, and codemem is imported, not called over MCP. So the hybrid replaces the agent, as loop-k does.
- **(b) Nobody would run it in place of Claude Code or Codex.** It is not a way to ship codemem, and not the way to evaluate it.
- **(c) It has no proper baseline:** the same loop without the codemem action was never run, so its numbers cannot tell "loop against agent" from "codemem against grep".
- **So track B moves back to the MCP setup:** codemem inside Claude Code over MCP, one cached conversation, as your entries of 12:25 and 12:40 say. The loops stay as evidence only.

**Question 2. Which run shows codemem as an MCP tool inside Claude Code doing worse than grep?**

- **None yet.** We are running Claude Code with codemem over MCP against grep now.
- The view in chat came from our own Python harnesses (loop-k, the hybrid, hybrid_v2 on the 35 e2e-b45 tasks), where the grep agent was the more efficient. Those do not run codemem as an MCP tool, so they do not answer this question.

## Checked

- The reading of (a) against `e2e_hybrid.py`, `e2e_hybrid2.py` and `llm.py` at `22aef0f`.

## Left

- Item 1 of the 12:40 entry (codemem over MCP against grep, Haiku and Sonnet, `463171c`), and item 2 (the repeated results, the 12:25 entry).

## Blocked on, or needed from others

Nothing.

## Next

Wilson, with Claude Code: the repeated results (12:25) and the MCP runs (12:40); results here by 22:00 UTC.
