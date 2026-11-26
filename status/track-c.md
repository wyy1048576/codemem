# Track C, memory and disk, embedding models, branches: status

**Owner:** Andre, who also leads the project: ask him, in the log, when a decision or a priority is unclear.
**Plan:** `docs/plan/track-c-memory.md` on `main`.
**Updated:** 2026-11-26 01:05 UTC, by Andre (with Claude Code).

| | |
|---|---|
| Now | seven branches are pushed and wait for their pull requests (Andre opens them). `andre/track-c-all` (`3b37d70`) merges all seven on `main` at `1a7e4d1`. The check on the eval's PC is asked for in the entry of 2026-11-25 23:43. The vLLM index is on hold at 85,506 of about 145,000 vectors: the Mac ran out of memory while it built (Andre, Nov 25) |
| Done | pushed: `andre/embedding-endpoints`, `andre/model-idle-unload`, `andre/worktree-start`, `andre/embedding-assist` (stacked in that order), `andre/vector-cache-cap`, `andre/compact-store`, `andre/compact-default`, and `andre/track-c-all` for testing (619 tests). The compact index returned the same results as the exact one in every real search measured (768 on 31,000 vectors, 352 on a pandas index of 49,770). The default will be the exact index while it fits 2% of the machine's memory, the compact one beyond |
| Next | 1. The pull requests. 2. The check on the PC (Linux, x86, larger real indexes). 3. The search-index check on a real index above 50,000 vectors: on the PC, or on the vLLM index here once its build can go on. 4. The memory, disk and time report on a quiet machine, with FAISS on one thread and on several. 5. By Nov 30: the embedding presets. 6. After track C is merged: the evaluation with open models (entry of 2026-11-26 00:41), a survey of harnesses first |
| Blocked on | nothing |
| Needs from other tracks | A: the two commands of the entry of 2026-11-25 23:43, on the PC. B: whether the graph work touches `store.py`'s vector part, the indexer's stages or the watcher |
| Gives to other tracks | for A: nothing to set; indexes keep their keys; on the PC every repo stays on the exact index. `codemem serve-embeddings` if containers should share one model. For B: `Store.vector_search` unchanged; `ti.find()` and `ti.vectors_of()` replace the two bookkeeping dicts |
| Open | the embedding model and the vector length: decided later (Andre, Nov 25). Whether a hosted API passes the assist's check: needs a key and one trial. Whether the exact index keeps its saved file: 28% of an index folder against 0.5 s of start time per 50,000 vectors (entry of 2026-11-26 00:41) |
| Dates | Nov 25, evening: `codemem-final` frozen (not met: track C is not merged yet). Nov 26: track A's full runs start. Nov 30, 23:59: everything frozen. Dec 1, 14:00: the presentation. Dec 8: the paper (team meeting of Nov 25) |
