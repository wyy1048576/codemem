# Track C, memory and disk, embedding models, branches: status

**Owner:** Andre, who also leads the project: ask him, in the log, when a decision or a priority is unclear.
**Plan:** `docs/plan/track-c-memory.md` on `main`.
**Updated:** 2026-11-26 10:37 UTC, by Andre (with Claude Code).

| | |
|---|---|
| Now | All of track C is on `main` (`cffcfa7`): #30 to #36, and FAISS 1.16.0 in the lock file (#38). Everyone runs `uv sync`; an Apple-silicon Mac needs macOS 15 (entry of 2026-11-26 10:37). Left: the results doc (`andre/track-c-results`), then the fixes the audits asked for. The compact index is checked on the real vLLM index (144,729 vectors): the true top 10 and top 50 in all 762 searches (entries of 2026-11-26 07:43 and 09:16) |
| Done | pushed: `andre/embedding-endpoints`, `andre/model-idle-unload`, `andre/worktree-start`, `andre/embedding-assist` (stacked in that order), `andre/vector-cache-cap`, `andre/compact-store`, `andre/compact-default`, and `andre/track-c-all` for testing (619 tests). The compact index returned the true top 10 in every real search measured (768 on 31,000 vectors, 1,640 on a pandas index of 49,770, 1,466 on a vLLM index of 144,729); two of those searches, both with questions about another repo, lost one result of their top 50. The default will be the exact index while it fits 2% of the machine's memory, the compact one beyond |
| Next | 1. The results doc merged (Andre). 2. A follow-up branch with the fixes the audits asked for. 3. One run of `main` on Linux and on Windows (entry of 2026-11-26 10:37). 4. The evaluation with open models: the survey is done, mini-SWE-agent first |
| Blocked on | nothing |
| Needs from other tracks | A and B: `uv sync` on `main`, and word at once if it fails (an Apple-silicon Mac on macOS 14 has no FAISS 1.16.0 build); one run of `uv run pytest -q` on Linux and on Windows (entry of 2026-11-26 10:37). B: whether the graph work touches `store.py`'s vector part, the indexer's stages or the watcher |
| Gives to other tracks | for A: nothing to set; indexes keep their keys; on the PC every repo stays on the exact index. `codemem serve-embeddings` if containers should share one model. For B: `Store.vector_search` unchanged; `ti.find()` and `ti.vectors_of()` replace the two bookkeeping dicts |
| Open | whether the compact index's first scan keeps 4,000 codes once FAISS 1.16.0 is in (entry of 2026-11-26 09:16). The number of results a search returns (entry of 2026-11-26 07:58). The embedding model and the vector length: decided later (Andre, Nov 25). Whether a hosted API passes the assist's check: needs a key and one trial. Whether the exact index keeps its saved file: 28% of an index folder against 0.5 s of start time per 50,000 vectors (entry of 2026-11-26 00:41) |
| Dates | Nov 27, noon Pacific at the latest: codemem's design is locked; the aim is the night of Nov 26 (Andre, entry of 2026-11-26 09:56). Nov 27 to Nov 30: the runs. Nov 30, 23:59: everything frozen. Dec 1, 14:00: the presentation. Dec 8: the paper (team meeting of Nov 25) |
