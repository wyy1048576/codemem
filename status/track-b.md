# Track B, retrieval: status

**Owner:** Wilson. **Plan:** `docs/plan/track-b-retrieval.md` on `main`.
**Updated:** 2026-11-25 11:36 UTC, by Wilson (with Claude Code). Rows marked "from Nov 22" are carried over from the last status and were not checked again.

| | |
|---|---|
| Now | B8 (the MCP integration): pull request #26 is open, not reviewed, not merged. It changes the `light` wording so that it says when to call `search_code`, adds two Claude Code hooks (`codemem hook`) and lets `codemem init` install them. See the entry of 2026-11-25 11:36 |
| Done | nothing is merged yet. On the branch `wilson/agent-steering-hooks` (`9ac0022`): the wording, the hooks, `init --write-hooks`, and the agent note written by default. 277 unit tests pass. The hooks have not run inside a Claude Code session, and no adoption number exists |
| Next | 1. Review and merge #26. 2. `"alwaysLoad": true` in the `.mcp.json` that `init` writes. 3. Tag `codemem-today`. 4. The adoption check (B-E9) on track A's `tool` setup. 5. From Nov 22, not started: B1 (the table of why today's searches miss), then B2 (keywords) and the `api` part of B5, side by side |
| Blocked on | nothing |
| Needs from other tracks | A: whether a setup with the hooks or the agent note is wanted, and whether `tool` moves to the new `light` wording before the full runs. Andre: whether #26 is merged before the text freezes with `codemem-final`. From Nov 22: A, vague rewrites of the dev tasks, a first subset by Nov 27; C, the vector store interface, agreed by Nov 25 |
| Gives to other tracks | A: the wording that ships is in #26 and changes the `tool` setup once merged. Tool names, parameters and the card layout are unchanged, and no index needs a rebuild |
| Dates | From Nov 22: Nov 28, evening: `codemem-final` frozen. Dec 3: the last freeze. Dec 8: the paper on arXiv |
