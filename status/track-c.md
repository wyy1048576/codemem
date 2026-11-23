# Track C, memory and disk, embedding models, branches: status

**Owner:** Andre, who also leads the project: ask him, in the log, when a decision or a priority is unclear.
**Plan:** `docs/plan/track-c-memory.md` on `main`.
**Updated:** 2026-11-23 02:55 UTC, by Andre (with Claude Code), from the plan. Only a pilot exists.

| | |
|---|---|
| Now | not started |
| Done | a pilot only (plan §5): on 30,977 stored vectors, a 40-byte one-bit code kept 99.9% of the exact top 10 within its top 100. The queries were code vectors, not real questions |
| Next | 1. C1: the compression table on real queries. 2. Agree the vector store interface with B, on Nov 23. 3. C2: the compact store. 4. C3: one copy on disk. 5. C8: the `api` embedding preset |
| Blocked on | nothing |
| Needs from other tracks | B: which vector types stay (code only, or code and usage). A: vague rewrites of the dev tasks, for C1, when they exist |
| Gives to other tracks | the embedding configuration the eval uses: a local model first, Qwen through Nebius later. Nothing built yet. Tell A in the log as soon as the compact store builds one repo |
| Open | whether the shared vector store (C9) is built in this phase (plan §7.5) |
| Dates | Nov 25, evening: `codemem-final` frozen. Nov 26: track A's full runs start. Nov 30, 23:59: everything frozen. Dec 1, 14:00: the presentation. Dec 7: the paper |
