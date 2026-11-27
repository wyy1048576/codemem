# Track C, memory and disk, embedding models, branches: status

**Owner:** Andre, who also leads the project: ask him, in the log, when a decision or a priority is unclear.
**Plan:** `docs/plan/track-c-memory.md` on `main`.
**Updated:** 2026-11-27 22:43 UTC, by Andre (with Claude Code).

| | |
|---|---|
| Now | **codemem's own code on `main` is that of `463171c` (#65).** Everything merged after it is docs and eval code, so the indexes and blocks made with `463171c` stay valid. The entry on the lock comes on Nov 28 at 00:30 UTC. **The memory probe on the run sample is done** (entry of 2026-11-27 22:43 UTC): with the L2 request alone, Haiku and Sonnet name the right file in about half of the sessions, Opus in two thirds |
| Done | On `main` since Nov 26: track C's results page (#40, #74), the three defaults (#51), the eval's pins (#52), the fixes the audits asked for (#53), tool answers in plain text (#54), the fix of the OpenMP crash on macOS (#60), the compact index on Linux (#65). All of track C's parts were on `main` before that (#30 to #36, #38) |
| Next | 1. The lock entry (Nov 28, 00:30 UTC). 2. The memory probe again when vscode or trino join the run sample. 3. The compact index's cost on many threads: track A measured the first fix on the PC (its entry of 2026-11-27 18:27 UTC: the overhead on all cores falls from 34 to 52 ms to 4 to 5 ms, results identical). Whether the second fix goes on top, and when either is merged, is Andre's decision; neither is part of the lock. 4. The evaluation with open models: the harness and the models are expected on Sat Nov 28 |
| Blocked on | nothing |
| Needs from other tracks | A: the two parts of the thread work that are left and the replay with the compact index (its entry of 2026-11-27 19:35 UTC, under "Left"), after the check run |
| Gives to other tracks | For A: the memory probe's result for each task and model (`log/2026-11-27-2243-c-data/memory-probe-by-task.jsonl`), for a split of the run pairs into tasks a model places from memory and tasks it does not. The code of the `codemem` setup (merged by track A in #77). On the PC every repo stays on the exact index. For B: `Store.vector_search` unchanged; `ti.find()` and `ti.vectors_of()` replace the two bookkeeping dicts |
| Waiting for a pull request or a merge | `andre/track-c-docs` (the Linux PC's measurements in the results page, and what comes next in the plan). `andre/compact-threads` (the plan's section on threads, proposed), with the two candidate fixes on `andre/compact-threads-fix-rotation` and `andre/compact-threads-fix-faiss` |
| Open | As listed on Nov 26 and not gone through again since: the number of results a search returns (entry of 2026-11-26 07:58); whether the exact index keeps its saved file; the embedding model and the vector length (decided later: Andre, Nov 25); whether a hosted API passes the assist's check; one shared embedding model for every codemem process on a machine (not before the lock) |
| Dates | Nov 27, 16:30 Pacific (Nov 28, 00:30 UTC): codemem is locked. 17:00 Pacific: the runs start, with the check run first. Sat Nov 28 and Sun Nov 29: reserved for running. Nov 30, 23:59 Pacific: results frozen. Dec 1, 14:00 Pacific: the presentation. Dec 7: the paper's first submission (a soft date); up to Dec 10 for the level of a conference |
