# Track C, memory and disk, embedding models, branches: status

**Owner:** Andre. **Plan:** `docs/plan/track-c-memory.md` on `main`.
**Updated:** 2026-11-23 02:44 UTC, by Andre (with Claude Code), from the plan. Only a pilot exists.

| | |
|---|---|
| Now | not started |
| Done | a pilot only (plan §5): on 30,977 stored vectors, a 40-byte one-bit code kept 99.9% of the exact top 10 within its top 100. The queries were code vectors, not real questions |
| Next | 1. C1: the compression table on real queries. 2. C8: the `api` embedding preset and its fixes, beside C1. 3. Agree the vector store interface with B, by Nov 25. 4. C2: the compact store |
| Blocked on | nothing |
| Needs from other tracks | B: which vector types stay (code only, or code and usage). A: vague rewrites of the dev tasks, for C1, when they exist |
| Gives to other tracks | the embedding configuration the eval uses: a local model first, Qwen through Nebius later. Nothing built yet. Tell A in the log as soon as the compact store builds one repo |
| Open | whether the shared vector store (C9) is built in this phase (plan §7.5) |
| Dates | Nov 28, evening: `codemem-final` frozen. Dec 3: the last freeze. Dec 8: the paper on arXiv |
