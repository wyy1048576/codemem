# Track C, memory and disk, embedding models, branches: status

**Owner:** Andre, who also leads the project: ask him, in the log, when a decision or a priority is unclear.
**Plan:** `docs/plan/track-c-memory.md` on `main`.
**Updated:** 2026-11-25 10:54 UTC, by Andre (with Claude Code).

| | |
|---|---|
| Now | four branches in progress, off `main` at `e6a65fc`: `andre/compact-store` (one-bit codes in memory, exact re-scoring from disk), `andre/vector-cache-cap` (a smaller, capped vector cache), `andre/embedding-endpoints` (`codemem serve-embeddings`, the `space` setting, PyTorch optional), `andre/worktree-start` (a new worktree starts from a copy; branch-switch tests). See the entry of 2026-11-25, "Track C has started" |
| Done | the pilot (plan §5). Two measurements of today: the bookkeeping around the vectors takes 337 bytes per vector, and the vector cache takes 4.7 KB on disk per vector |
| Next | 1. Merge the four branches, each as a pull request. 2. The gate for the compact store, on real vectors and real questions. 3. Index rows keep only a text hash, and the vector bytes live once per machine. 4. The memory, disk and time report from 50,000 to 1,000,000 vectors. 5. By Nov 30: the embedding presets, the idle unload |
| Blocked on | nothing |
| Needs from other tracks | B: which vector types stay (code only, or code and usage); whether B's code reads `_TypeIndex.owner` or `by_chunk` directly. A: vague rewrites of the dev tasks, when they exist |
| Gives to other tracks | for A: `codemem serve-embeddings` and the `space` setting for the `tool` setup in containers, an install without PyTorch, and the `codemem-compact` configuration with its memory and disk numbers. For B: a vector store that returns exact scores. None of it is merged yet |
| Open | the embedding model and the vector length: decided later (Andre, Nov 25). Everything stays on `jina-code-embeddings-0.5b` at 896 numbers until then, and the storage work does not depend on either |
| Dates | Nov 25, evening: `codemem-final` frozen. Nov 26: track A's full runs start. Nov 30, 23:59: everything frozen. Dec 1, 14:00: the presentation. Dec 7: the paper |
