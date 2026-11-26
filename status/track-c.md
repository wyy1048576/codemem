# Track C, memory and disk, embedding models, branches: status

**Owner:** Andre, who also leads the project: ask him, in the log, when a decision or a priority is unclear.
**Plan:** `docs/plan/track-c-memory.md` on `main`.
**Updated:** 2026-11-26 09:56 UTC, by Andre (with Claude Code).

| | |
|---|---|
| Now | #30 to #33 are on `main` (`b69ab80`). #34 is refreshed and waits for its merge; #35 and #36 follow. Two audits found no blocker (entry of 2026-11-26 03:05). The real vLLM index is built (144,729 vectors) and the compact index is checked on it: the true top 10 and top 50 in all 762 searches, and the repo's check script passes on it (entries of 2026-11-26 07:43 and 09:16) |
| Done | pushed: `andre/embedding-endpoints`, `andre/model-idle-unload`, `andre/worktree-start`, `andre/embedding-assist` (stacked in that order), `andre/vector-cache-cap`, `andre/compact-store`, `andre/compact-default`, and `andre/track-c-all` for testing (619 tests). The compact index returned the true top 10 in every real search measured (768 on 31,000 vectors, 1,640 on a pandas index of 49,770, 1,466 on a vLLM index of 144,729); two of those searches, both with questions about another repo, lost one result of their top 50. The default will be the exact index while it fits 2% of the machine's memory, the compact one beyond |
| Next | 1. #34, #35, #36 merged (Andre), each refreshed after the one before. 2. A follow-up branch with the fixes the audits asked for. 3. The check on the PC (Linux, x86). 4. The pull request for `andre/faiss-1-16`, which moves the lock file to FAISS 1.16.0 (entry of 2026-11-26 09:50). 6. The evaluation with open models: the survey is done, mini-SWE-agent first |
| Blocked on | nothing |
| Needs from other tracks | A and B: whether a machine is an Apple-silicon Mac on macOS 14, and one run of `andre/faiss-1-16` on Linux and on Windows (entry of 2026-11-26 09:50). A: the two commands of the entry of 2026-11-25 23:43, on the PC. B: whether the graph work touches `store.py`'s vector part, the indexer's stages or the watcher |
| Gives to other tracks | for A: nothing to set; indexes keep their keys; on the PC every repo stays on the exact index. `codemem serve-embeddings` if containers should share one model. For B: `Store.vector_search` unchanged; `ti.find()` and `ti.vectors_of()` replace the two bookkeeping dicts |
| Open | whether the compact index's first scan keeps 4,000 codes once FAISS 1.16.0 is in (entry of 2026-11-26 09:16). The number of results a search returns (entry of 2026-11-26 07:58). The embedding model and the vector length: decided later (Andre, Nov 25). Whether a hosted API passes the assist's check: needs a key and one trial. Whether the exact index keeps its saved file: 28% of an index folder against 0.5 s of start time per 50,000 vectors (entry of 2026-11-26 00:41) |
| Dates | Nov 27, noon Pacific at the latest: codemem's design is locked; the aim is the night of Nov 26 (Andre, entry of 2026-11-26 09:56). Nov 27 to Nov 30: the runs. Nov 30, 23:59: everything frozen. Dec 1, 14:00: the presentation. Dec 8: the paper (team meeting of Nov 25) |
