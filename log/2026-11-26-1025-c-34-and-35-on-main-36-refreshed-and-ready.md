# Track C: #34 (the vector cache) and #35 (the compact search index) are on `main`; #36 is refreshed and ready

- **Track:** C. Points 3 and 4 are for tracks A and B
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 10:25 UTC
- **Work package:** C2, C3, C5
- **Branch, commits, pull request:** on `main`: #34 (`b62cddf`), #35 (`4b0709f`). Open: #36 `andre/compact-default` (`3c122c5`). Pushed, no pull request yet: `andre/faiss-1-16` (`d001d9f`), `andre/track-c-results` (`07c4a5d`)

## Done

**1. #34 and #35 are on `main`.** Each squash is, byte for byte, the branch that was tested (the
tree of `main` after each merge equals the tree of the tested branch).

**2. #36 is refreshed on today's `main`** and shows only its own change (27 files). Its content
is the combined code that was tested all along (`andre/track-c-all`, now `5ac9fec`).

**3. What is new on `main` for track A:**

| | |
|---|---|
| nothing to set | the default is still the exact index. The compact index is used only where a configuration sets `vector_backend = "compact"` |
| an index built earlier | keeps its key and its vectors. It rebuilds its saved search index once, from its own rows, because the saved file now names the database it belongs to |
| the vector cache | moves into a new file at the first run (an old cache is imported once, bit for bit), and has a cap of 8 GB (`vector_cache_max_gb`) |
| FAISS | still 1.15.1 in the lock file. The compact index says so in a sentence if an older FAISS is installed |

**4. What is new on `main` for track B:**

- `_TypeIndex.owner` and `by_chunk` are gone. Use `ti.find(vector_ids)` and
  `ti.vectors_of(chunk_ids)`. `Store.vector_search` and its hits are unchanged.
- The plugin contract has an optional `bind(fetch)` (`docs/data-model.md` §12.4). Existing
  plugin classes keep working.
- The SQLite index `vectors_type` is replaced by `vectors_owner`.

## Checked

- #35's branch on `main` with #34: 588 tests pass; 581 pass and 7 are skipped with the suite
  forced onto the compact index.
- #36's content on today's `main`: 622 tests pass; 619 pass and 3 are skipped forced onto the
  compact index, and the same forced onto the exact one.
- Not checked: Linux, x86, Windows.

## Left

- #36 (Andre merges). Then `andre/faiss-1-16` and `andre/track-c-results`.
- The fixes the audits asked for.

## Blocked on, or needed from others

- **Andrew and Wilson:** the question of the entry of 09:50 (an Apple-silicon Mac on macOS 14?)
  is still open. It holds `andre/faiss-1-16`.

## Next

- Andre: #36.
