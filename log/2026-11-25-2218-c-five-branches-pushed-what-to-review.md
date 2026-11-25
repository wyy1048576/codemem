# Track C: five branches are pushed; no install command changes; the default will follow the machine's memory

- **Track:** C. Points for Andrew and for Wilson at the end
- **Who:** Andre, with Claude Code
- **When:** 2026-11-25 22:18 UTC
- **Work package:** C2, C4, parts of C5, C8 and C9
- **Branch, commits, pull request:** pushed, no pull request yet. Andre opens them

| Branch | Tip | Merges | What it is |
|---|---|---|---|
| `andre/embedding-endpoints` | `f26732e` | first | `codemem serve-embeddings`, the `[embedding] space` setting |
| `andre/model-idle-unload` | `ef51e2a` | second, on the first | less model memory, the idle unload, the right precision on a CPU |
| `andre/worktree-start` | `6a96b5e` | third, on the second | a new worktree starts from a copy; branch-switch tests |
| `andre/vector-cache-cap` | `1920202` | any time | the vector cache in a smaller layout, with a size cap |
| `andre/compact-store` | `ea93781` | any time | the compact search index, as a setting |

## Done

**1. The five branches are on `origin`.** Each merges cleanly with `main` at `d76bccd`. All five
together pass the suite: 511 tests, and 504 with 7 skipped when the whole suite runs on the
compact index.

**2. No install command changes.** An earlier entry said PyTorch would become an optional
install. That is withdrawn: PyTorch stays in the standard install, so a plain `uv sync` keeps
working. codemem can still run where PyTorch is absent, as a client of an API or of a served
model, and the README has a recipe for such an environment.

**3. Decided by Andre today: accuracy and speed first, memory second.** So the default search
index will follow the machine:
- the exact index, as today, while it fits a budget of 2% of the machine's memory;
- the compact index beyond that.

On the eval's PC (47 GB) the budget is about 940 MB, which is about 500,000 vectors, so every
repo of the eval stays on the exact index. On a 16 GB Mac the budget is 320 MB, about 170,000
vectors, and larger repos use the compact index. An index built before the change stays valid
and nothing is embedded again. This is being built on a sixth branch, `andre/compact-default`.

**4. Two more pieces are in work:**
- a script in `scripts/` that compares the search indexes on a real index with the eval's own
  questions, so that the larger checks can run on the PC;
- an optional second source for a build's embeddings (`andre/embedding-assist`): an endpoint
  that serves the same model takes part of a build's texts, after a check has shown that it
  gives the same vectors.

## Checked

- My runs, on the pushed tips: 380 passed on the top of the three stacked branches; 349 on
  `andre/compact-store` and 343 with 6 skipped on the compact index; 280 on
  `andre/vector-cache-cap`.
- The numbers behind each branch are in the entries of 2026-11-25 (12:55, 13:48, 15:46, 18:23).
- **Not checked by anyone: FAISS's RaBitQ code on Linux x86.** Every run so far was on an Apple
  M1.

## Left

- The pull requests (Andre). The sixth branch. The check on a real vLLM index, which is still
  building.

## Blocked on, or needed from others

- **Andrew (track A):**
  1. `andre/embedding-endpoints` changes one file of yours: `eval/uv.lock` gains three packages
     (`httpx`, `httpcore`, `certifi`), and no version moves. codemem declares `httpx` now. The
     eval's environment had none, so codemem's API embedder could not run there.
  2. Before `andre/compact-default` is merged, the suite should run once on the PC, on both
     search indexes. The command will be in that branch's entry.
  3. With the default of point 3 your runs stay on the exact index, so nothing in them changes.
- **Wilson (track B):** `andre/compact-store` changes `store.py`'s vector part. If the graph
  work touches that file, start from that branch or tell me where it collides. `Store.vector_search`
  is unchanged; `_TypeIndex.owner` and `by_chunk` are replaced by `ti.find()` and
  `ti.vectors_of()`. If the graph work needs a change in the indexer's two stages or in the
  watcher, say so in the log first: Andre wants to know before that part changes.

## Next

- Andre's session: the sixth branch, the script for the PC, the vLLM check.
