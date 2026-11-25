# The compact store's default changed: accuracy first, a third of today's memory

- **Track:** C. This corrects the numbers of the entry of 2026-11-25 12:55
- **Who:** Andre, with Claude Code
- **When:** 2026-11-25 15:46 UTC
- **Work package:** C2
- **Branch, commits, pull request:** `andre/compact-store` (`ea93781`), local, not pushed. All five
  track C branches are merged for testing on `andre/track-c-all` (`03fc6f3`), local too

## Done

**Andre's decision (Nov 25):** accuracy and recall come first, and a saving of two to three times
is enough. So the compact store's default is no longer the smallest code that passes a bar. It
is the most faithful one that costs no search time.

**How the default works** (`vector_backend = "compact"`, with `bits = 4`, `dim = 0`,
`rescore = 200`). A search takes three steps:
1. it scans a 1-bit code of every vector (120 bytes for 896 numbers);
2. it ranks the scan's best 2,000 again by a finer 4-bit code (468 bytes);
3. it reads the best 200 of those from SQLite and scores them exactly.

**What it keeps.** 30,977 real jina vectors, 268 real questions and 500 code vectors as queries,
with no filter and with filters that keep 10% and 1% of the vectors:

| Setting | Same top 10 as the exact index | Top 50, mean overlap | Worst search (top 10 / top 50) |
|---|---|---|---|
| the default: 4 bits, 200 candidates | every search | 1.0 | 1.0 / 1.0 |
| 2 bits, 500 | every search | 1.0 | 1.0 / 1.0 |
| 1 bit, 500 | every search | 0.9975 | 1.0 / 0.88 |
| 1 bit, 200 | 99.3% | 0.9717 | 0.90 / 0.72 |

**What it costs and saves,** at 200,000 vectors of 896 numbers on an M1:

| | `main` | compact, the default | compact, 1 bit |
|---|---|---|---|
| process memory for vector search | 441 MB | 132 MB | 33 MB |
| saved search index on disk | 360 MB | 119 MB | 26 MB |
| one vector search, against the exact index | 1 | 0.92 times | 0.61 times |

On a small index (31,000 vectors) the default is about 2 ms slower than the exact index (8.5 ms
against 6.2 ms).

**Also on the branch:**
- A saved search index is read only into the database it was saved from. On `main`, deleting
  `index.db` by hand and leaving the `vec_*` files gave wrong results after the rebuild.
- The reads for exact scoring use a connection of their own with a 2 MB cache: over 400 searches
  the process grew by 0.2 to 15 MB, against 62 to 80 MB.
- `vacuum_if_sparse` gave back one free page per call. It gives back all of them.

## Checked

- The tables are the agent's measurements. My runs: the branch's suite, 349 passed on the default
  backend and 343 passed with 6 skipped on the compact one. All five branches together: 511
  passed, and 504 passed with 7 skipped on the compact one.
- The times were taken with other jobs running. The ratio to the exact index was measured with
  the two taking turns, query by query, in one process.
- **Not checked:** real vectors beyond 31,000, another model, the eval's own metrics. A real
  pandas index (about 50,000 vectors) is being built for a check on pandas's own 352 issue texts.
- **A known limit:** for a query that has nothing near it in the index (synthetic vectors, every
  score is noise) the default returned the exact top 10 in 78% of searches. Real questions about
  other repos did not show it.

## Left

- The check on the real pandas index.
- The pull requests.

## Blocked on, or needed from others

- **Andre:** push the branches and open the pull requests.
- **Andrew:** nothing. When the branch is merged, `codemem-compact` is today's retrieval with
  `vector_backend = "compact"` and nothing else set.

## Next

- Andre's session: the pandas check, then the pull requests.
