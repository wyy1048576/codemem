# The compact store and the capped vector cache are finished on branches (not pushed, not merged)

- **Track:** C. One point each for track A and track B at the end
- **Who:** Andre, with Claude Code
- **When:** 2026-11-25 12:55 UTC
- **Work package:** C2, C4, part of C1 and C3
- **Branch, commits, pull request:** local branches off `main`, not pushed yet:
  `andre/compact-store` (6 commits, follow-ups in progress), `andre/vector-cache-cap`
  (`1920202`, 8 commits), and `andre/track-c-storage`, which merges the two for testing

## Done

**1. The compact store** (`vector_backend = "compact"`; today's `faiss` stays the default).
In memory it keeps a one-bit RaBitQ code of every number of a vector: 120 bytes for 896
numbers, against 1,792. A search scans the codes, reads the full vectors of its best 500
candidates from SQLite, and scores those exactly. Every score it returns is the real one.

Measured on an M1 with 896 numbers per vector, at 200,000 synthetic vectors, vector search
alone. Other jobs were running, so the times are rough:

| | `main` | compact |
|---|---|---|
| process memory after loading the search index | 441 to 511 MB | 31 to 42 MB |
| saved search index on disk | 360 MB | 26 MB |
| one vector search, median | 20 to 45 ms | 11 to 15 ms |
| start from the saved file | 1.2 s | 0.35 s |

**2. Does it return the same results?** On 30,977 real jina vectors, through the store's own
search:

| Queries | Candidates scored exactly | Top 10 equal to the exact store's |
|---|---|---|
| 268 real questions (the eval's issue texts) | 200 | 99.3% of searches |
| the same | 500 | 100% |
| 500 code vectors held out as queries | 200 | 100% |

**3. The pilot was too optimistic about short codes.** The plan's pilot suggested a 40-byte code
over the first 256 numbers. On the 268 real questions that code keeps the top 10 in 49% of
searches at 200 candidates and 75% at 500. The pilot used code vectors as queries. A code
vector's best matches score 0.93, a question's 0.40, so questions need a finer code. The code
therefore covers all 896 numbers, and the saving in memory is about 14 times, not 45.

**4. The bookkeeping** (which chunk each vector belongs to) is arrays now: 32 bytes per vector,
against 337. That also helps today's backend: 375 MB against 511 MB at 200,000 vectors.

**5. The vector cache** (`andre/vector-cache-cap`): a cached vector takes 1,877 bytes on disk,
against 4,690. A new setting, `vector_cache_max_gb` (default 8), caps the file: past it the
least recently used vectors are deleted and the file shrinks. The file is new,
`cache/vector_cache.db`. The first run imports the old `cache/vectors.db` and then deletes it:
34,218 vectors took 1.6 s and came out bit-identical.

## Checked

- Tests, my own runs: `andre/compact-store` 326 passed on the default backend, and 320 passed
  with 6 skipped when the whole suite runs on the compact store. The two branches merged: 357
  passed, and 351 passed with 6 skipped on the compact store. `andre/vector-cache-cap` alone:
  280 passed (the agent's run).
- The table in point 1 is from two runs, the agent's and mine (`bench_scale.py`); the ranges
  are the spread between them and between `main` and the branch's exact backend.
- The agreement table is the agent's run. Mine, on synthetic vectors whose queries have
  neighbours in the index: the top 10 was equal in 200 of 200 searches at 50,000 and at 200,000.
- Every FAISS call the store makes ran under a memory checker for 2,608 combinations of length
  and bits (the agent's run). The store checks what it hands to FAISS.
- **Not checked:** agreement on a real index larger than 31,000 vectors, on another model, or on
  the eval's own metrics. Most of the 268 questions are about repos that are not among the
  31,000 vectors. A check on a real pandas index with pandas's own issue texts comes next.
- Two costs that were found: while the index file is not in the system's file cache, a search
  takes about 25 ms longer; and the reads for exact scoring fill SQLite's 64 MB page cache. The
  second is being fixed.

## Left

- The follow-ups on `andre/compact-store`, then the check on a real pandas index.
- Index rows that keep only a text hash, with the vector bytes once per machine.
- The pull requests.

## Blocked on, or needed from others

- **Andre:** push the branches and open the pull requests.
- **Andrew (track A):**
  1. `eval/tests` never set `CODEMEM_HOME`. So a run of the eval's tests writes fake test
     vectors to the real `~/.codemem/cache` of whoever runs it. It happened here twice today. A
     fixture in `eval/tests/conftest.py` that points `CODEMEM_HOME` at a temp folder would stop
     it. It is your file, so it is not changed in track C's branches.
  2. Nothing changes for your runs until these branches are merged. Then: an index key changes
     only for a configuration that sets `vector_backend = "compact"`, and such an index is built
     from the vector cache without the model. The first run of the new code moves the vector
     cache to its new file.
- **Wilson (track B):** on `andre/compact-store`, `_TypeIndex.owner` and `by_chunk` are gone.
  The replacements are `ti.find(vector_ids)` and `ti.vectors_of(chunk_ids)`. `Store.vector_search`
  and its hits are unchanged.

## Next

- Andre's session: the gate on real pandas vectors, then the shared vector store.
