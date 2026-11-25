# Track C, memory and disk, embedding models, branches: status

**Owner:** Andre, who also leads the project: ask him, in the log, when a decision or a priority is unclear.
**Plan:** `docs/plan/track-c-memory.md` on `main`.
**Updated:** 2026-11-25 12:55 UTC, by Andre (with Claude Code).

| | |
|---|---|
| Now | follow-ups on `andre/compact-store` and `andre/model-idle-unload`; `andre/worktree-start` in progress; then the check of the compact store on a real pandas index, and index rows that point into one shared copy of the vectors |
| Done | on local branches, not pushed: the compact store (31 to 42 MB against 441 to 511 MB at 200,000 vectors; top 10 equal to the exact store's in 99.3% of 268 real-question searches at 200 candidates, 100% at 500), the capped vector cache (1,877 bytes per vector against 4,690), `codemem serve-embeddings` with the `space` setting and PyTorch as an optional install, the idle unload of the model. See the entries of 2026-11-25 |
| Next | 1. The pull requests, when Andre says so. 2. The gate on a real pandas index. 3. Index rows keep only a text hash. 4. The memory, disk and time report from 50,000 to 1,000,000 vectors. 5. By Nov 30: the embedding presets |
| Blocked on | nothing |
| Needs from other tracks | B: which vector types stay (code only, or code and usage); whether B's code reads `_TypeIndex.owner` or `by_chunk` directly. A: vague rewrites of the dev tasks, when they exist |
| Gives to other tracks | for A: `codemem serve-embeddings` and the `space` setting for the `tool` setup in containers, an install without PyTorch, and the `codemem-compact` configuration with its memory and disk numbers. For B: a vector store that returns exact scores. None of it is merged yet |
| Open | the embedding model and the vector length: decided later (Andre, Nov 25). Everything stays on `jina-code-embeddings-0.5b` at 896 numbers until then, and the storage work does not depend on either |
| Dates | Nov 25, evening: `codemem-final` frozen. Nov 26: track A's full runs start. Nov 30, 23:59: everything frozen. Dec 1, 14:00: the presentation. Dec 7: the paper |
