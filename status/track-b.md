# Track B, retrieval: status

**Owner:** Wilson. **Plan:** `docs/plan/track-b-retrieval.md` on `main`.
**Updated:** 2026-11-26 13:07 UTC, by Wilson (with Claude Code). Rows marked "from Nov 22" are carried over from an earlier status and were not checked again.

| | |
|---|---|
| Now | B1 and the query path: codemem's search loop against a grep agent on the 3 fair pandas pilot tasks, without tests (branch `wilson/loop-vs-grep-e2e`, `2c2a7b6`, folder `eval/experiments/b1-loop/`; entry of 2026-11-26 13:07). Grep: $0.14, 4 of 6 gold functions edited. Loop with 50 results per round: $0.75, 2 of 6; with 25: $0.28, 2 of 6; with 10: $0.27, 3 of 6. One run each, nothing built or tested, so no ranking. B8 (the MCP integration) is on `main` with #26 (entry of 2026-11-25 22:06) |
| Done | The B1 loop scripts and end-to-end outputs are in git (`wilson/loop-vs-grep-e2e`, not merged). On `main` with #26: the `light` wording that says when to call `search_code`, the two Claude Code hooks (`codemem hook`), `init --write-hooks`, the agent note written by default, `"alwaysLoad": true` in the `.mcp.json` that `init` writes. Seen live on Claude Code 2.1.314 with Sonnet, one run per case: `alwaysLoad`, the first-search refusal, the "nothing found" reminder. The reminder changed nothing in the one dead-end case tried. No adoption number exists |
| Next | 0. The loop: 3 to 5 runs per arm and task, a real grade of the saved diffs, and a loop that starts with few results and widens only when nothing is found. 1. Choose from Andre's list (20:56). Not chosen and not started; candidates are the faults (model still loading on the first search, the result as one JSON string, an absolute `path_prefix`) and a reminder after a shell search. 2. Tag `codemem-today`. 3. The adoption check (B-E9) on track A's `tool` setup. 4. From Nov 22, not started: B1 (the table of why today's searches miss), then B2 (keywords) and the `api` part of B5, side by side |
| Blocked on | nothing |
| Needs from other tracks | A: whether the grader can grade a saved diff in a task's image (the loop's diffs on the 3 pandas tasks; Wilson's laptop has no Docker or NVIDIA GPU). C: Andre to look at `wilson/loop-vs-grep-e2e`. A: whether an arm with the hooks or the agent note is wanted (the runner removes `.claude/` and `CLAUDE.md`). From Nov 22: A, vague rewrites of the dev tasks, a first subset by Nov 27; C, the vector store interface, agreed by Nov 25 |
| Gives to other tracks | A: the `light` wording on `main` is #26's. It is not declared frozen: the fixes above would change what a result looks like. Tool names, parameters and the card layout are unchanged by #26, and no index needs a rebuild |
| Dates | From Nov 22: Nov 28, evening: `codemem-final` frozen. Dec 3: the last freeze. Dec 8: the paper on arXiv |
