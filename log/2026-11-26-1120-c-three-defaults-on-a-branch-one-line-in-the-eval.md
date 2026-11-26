# Track C: three new defaults on a branch (idle unload, a cache age limit, a deeper first scan); one line changes in the eval's runner; the audit fixes have started

- **Track:** C. Point 2 is for track A, point 3 for track B
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 11:20 UTC
- **Work package:** C4, C5, C2 (follow-ups Andre decided on today)
- **Branch, commits, pull request:** `andre/track-c-defaults` (`3b00339`), on `main` at `d9c858e`. Andre opens the pull request. Two more branches are in work, not pushed: `andre/saved-index-integrity`, `andre/worktree-freshness`

## Done

**1. Three defaults, one commit each** (Andre's decisions of today):

| Setting | Was | Is | Why |
|---|---|---|---|
| `model_idle_minutes` | 0: the model stays for as long as codemem runs | 60 | a session nobody uses gives back its model's 1.3 GB |
| `vector_cache_max_age_days` (new) | no limit but the 8 GB cap | 30 | the cache no longer keeps for ever what a machine once embedded |
| the compact index's first scan | 2,000 codes | 4,000 | with 2,000 one search on each of two real indexes lost a result of its top 50 |

- **An idle time costs latency, not results.** The first search after an unload waits for the
  model, for up to 20 s (a reload takes 2 to 6 s on an M1). At start-up the rule is unchanged.
- **An index keeps its vectors in the cache.** Once a day it marks the vectors it holds as used,
  so what ages out is what no index needed for 30 days. A rebuild of a repo in use stays free.

**2. For track A: one line in `eval/src/cmeval/e2e_run.py`, and one in its test.**
`codemem_mcp_config` now puts `CODEMEM_MODEL_IDLE_MINUTES=0` into the environment of the codemem
server in a run's container, so that no run differs by whether an unload fell into it. The model
stays in memory for the whole run, as it does today. `CODEMEM_MODEL_IDLE_MINUTES` is a new
variable that codemem reads; an older codemem ignores it. Please look at that line in the pull
request. On the PC every repo is on the exact index, so the scan's depth does not touch a result.

**3. For track B:**

- A search through the MCP server can take up to 20 s, once, after an hour without one. Before,
  it answered from keywords after 4 s, with the "still loading" note. The note stays for a start
  and for a load that takes longer than that.
- `Embedder.freed_idle` is a new property with a default (false), so a plugin embedder keeps
  working. `Indexer.cache_upkeep` and `Store.vector_hashes` are new. `meta` has one more key,
  `cache_marked_day`.

**4. The audit fixes are in work**, on two branches: a checksum for saved search indexes and a
tie between a saved index and its database's state; and worktrees inside the checkout,
`codemem search` after `git switch`, and the errors with the embedding server down. One of them
changes what the file scan and the watcher skip: a folder that is another checkout of the same
repository (a linked worktree such as `.claude/worktrees/<name>`), and nothing else.

## Checked

- In an environment made from `main`'s lock file (FAISS 1.16.0), on an M1: 631 tests pass; 628
  pass and 3 are skipped with the suite forced onto the compact index, and the same on the exact
  one. The eval's suite: 785 pass, 20 skipped.
- The cache's upkeep on a copy of the real vLLM cache (194,000 vectors): 0.4 s to read the
  index's 144,000 hashes, 0.2 to 0.7 s to mark them, 12.5 s to delete all of them at once.
- Not checked: Linux, x86, Windows.

## Left

- The pull request (Andre). The two branches of point 4.

## Blocked on, or needed from others

- **Andrew:** a look at the one line of point 2.
- **Still open from 10:37:** whether `uv sync` works on your machines since #38 (FAISS 1.16.0).

## Next

- Track C's session: the audit fixes, then the results doc.
