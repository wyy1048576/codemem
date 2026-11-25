# Track C has started: four branches in progress, and what will change for A and B

- **Track:** C
- **Who:** Andre, with Claude Code (one lead session and four agents, each in its own worktree)
- **When:** 2026-11-25 10:54 UTC
- **Work package:** C2, C3, C4, part of C5, C8 and C9
- **Branch, commits, pull request:** local branches off `main` at `e6a65fc`, not pushed yet:
  `andre/compact-store`, `andre/vector-cache-cap`, `andre/embedding-endpoints`,
  `andre/worktree-start`. Each becomes its own pull request

## Done

Nothing is finished. This entry says what is being built, so that nobody is surprised by it.

**Decided by Andre today:**
- **The embedding model and the vector length are decided later.** Everything stays on today's
  model (`jina-code-embeddings-0.5b`, 896 numbers) until he says otherwise. Track C's storage work
  does not depend on the model or the length.
- **Memory:** one-bit codes in memory (RaBitQ), and exact scores for the best candidates from the
  full vectors on disk.
- **Disk:** one full-precision copy of each vector, kept once per machine and shared by every
  branch, worktree and index of a repo. The saved copy of the search index and the copy in each
  index go.
- **Branches:** one index per checkout, updated in place on a switch. A switch re-chunks the
  changed files and takes vectors by text hash from the shared copy, so a branch seen before costs
  no model time.

**The four branches:**

| Branch | What it builds |
|---|---|
| `andre/compact-store` | `vector_backend = "compact"`: one-bit codes in memory, the best 200 or more candidates re-scored exactly from SQLite. Today's backend stays the default until the gate below passes |
| `andre/vector-cache-cap` | the machine-wide vector cache in a smaller layout, with last-use dates, a size cap (`vector_cache_max_gb`) and eviction |
| `andre/embedding-endpoints` | `codemem serve-embeddings`: the local model behind an OpenAI-style endpoint, so several codemem processes share one model; an `[embedding] space` setting; PyTorch as an optional install |
| `andre/worktree-start` | a new git worktree's index starts as a copy of the main checkout's; tests that pin what a branch switch costs |

A fifth step follows when the first two are merged: each index keeps only the text hash of a
vector and reads the bytes from the shared store.

**Two measurements from today** (M1, 896 numbers per vector):
- The Python bookkeeping around the vectors (which chunk each vector belongs to) takes 337 bytes
  per vector, 67.5 MB at 200,000 vectors. A one-bit code takes 120 bytes. So the bookkeeping is
  rewritten as arrays in the same branch, or the saving would be a third of what the plan says.
- The vector cache takes 4.7 KB on disk for each 1,792-byte vector: 148 MB for 31,477 vectors.

## Checked

- The test suite passes on `main` at `e6a65fc`: 249 passed. One test,
  `test_cli_init_writes_configs`, fails when the virtual environment's `bin` folder is not on
  `PATH`, because it expects the command `codemem`. It is an environment matter, not a fault.
- Nothing of the four branches is checked yet.

## Left

- All of it. The gate for the compact store: on real vectors and real questions, its top 10
  equals the exact store's top 10 in at least 99% of searches (plan track C §9, C2).

## Blocked on, or needed from others

Nothing is needed today. Three changes to expect, each announced again when it is merged:

- **Wilson (track B):** the `VectorStore` plugin contract (data-model §12.4) gets one optional
  hook, through which a backend can read stored vectors by id. Existing backends keep working
  unchanged, and `search` still returns the real similarity as the score. If track B's code reads
  `_TypeIndex.owner` or `by_chunk` directly, say so here: those two become arrays.
- **Andrew (track A), for the `tool` setup in containers:** `codemem serve-embeddings` is meant
  for exactly that case. One model runs on the host, on its GPU, and each container's codemem
  reaches it with `[embedding] provider = "openai"`. Today that would re-embed the whole repo
  inside the container, because the embedder's key holds the address. The `space` setting removes
  that. Also: the local model moves to an optional install, `codemem[local]`. A plain install is
  for API users and has no PyTorch, which keeps it out of the task images.
- **Andrew:** the configuration name for the compact store will be `codemem-compact`:
  `vector_backend = "compact"` on today's retrieval. It is posted here with its memory and disk
  numbers as soon as it builds a repo.

## Next

- Andre's session: review and merge the four branches as they finish, run the gate, post the
  numbers.
