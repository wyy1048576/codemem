# Track B, retrieval: status

**Owner:** Wilson. **Plan:** `docs/plan/track-b-retrieval.md` on `main`.
**Updated:** 2026-11-25 22:06 UTC, by Wilson (with Claude Code). Rows marked "from Nov 22" are carried over from an earlier status and were not checked again.

| | |
|---|---|
| Now | B8 (the MCP integration): pull request #26 is merged into `main` (`041124e`, by Andrew, Nov 25 21:13 UTC). Its hooks and `alwaysLoad` were then seen working in six live Claude Code sessions. See the entry of 2026-11-25 22:06. Next is a choice from Andre's list of 20:56 |
| Done | On `main` with #26: the `light` wording that says when to call `search_code`, the two Claude Code hooks (`codemem hook`), `init --write-hooks`, the agent note written by default, `"alwaysLoad": true` in the `.mcp.json` that `init` writes. Seen live on Claude Code 2.1.314 with Sonnet, one run per case: `alwaysLoad`, the first-search refusal, the "nothing found" reminder. The reminder changed nothing in the one dead-end case tried. No adoption number exists |
| Next | 1. Choose from Andre's list (20:56). Not chosen and not started; candidates are the faults (model still loading on the first search, the result as one JSON string, an absolute `path_prefix`) and a reminder after a shell search. 2. Tag `codemem-today`. 3. The adoption check (B-E9) on track A's `tool` setup. 4. From Nov 22, not started: B1 (the table of why today's searches miss), then B2 (keywords) and the `api` part of B5, side by side |
| Blocked on | nothing |
| Needs from other tracks | A: whether an arm with the hooks or the agent note is wanted (the runner removes `.claude/` and `CLAUDE.md`). From Nov 22: A, vague rewrites of the dev tasks, a first subset by Nov 27; C, the vector store interface, agreed by Nov 25 |
| Gives to other tracks | A: the `light` wording on `main` is #26's. It is not declared frozen: the fixes above would change what a result looks like. Tool names, parameters and the card layout are unchanged by #26, and no index needs a rebuild |
| Dates | From Nov 22: Nov 28, evening: `codemem-final` frozen. Dec 3: the last freeze. Dec 8: the paper on arXiv |
