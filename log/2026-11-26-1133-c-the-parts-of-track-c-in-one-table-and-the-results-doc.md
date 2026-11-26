# Track C: its parts in one table, and where the results doc is

- **Track:** C
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 11:33 UTC
- **Work package:** C1 to C9, as a summary
- **Branch, commits, pull request:** `andre/track-c-results` (`f0c6199`, no pull request yet). Everything in the table is on `main`, except the last row

## Done

**1. What track C built.** This table was in the results doc. It lives here now, so that the doc
holds the design and its evidence only.

| # | Part | The problem | What it does |
|---|---|---|---|
| #30 | The embedding server | every codemem process loads its own copy of the model, over a gigabyte each | `codemem serve-embeddings` puts the local model behind an OpenAI-style endpoint, so several processes (one per git worktree, one per container) can share one model |
| #31 | Model memory | the model is the largest thing in memory | a cheaper load on Apple GPUs, working memory given back after a burst, an idle unload, and the right precision on a CPU |
| #32 | Branches and worktrees | a new git worktree started from an empty index | a new worktree's index starts as a copy of another checkout's. A search right after a switch embeds its own results first. Tests pin what a branch switch costs |
| #33 | The embedding assist | a first build is almost all model time | an optional second endpoint that serves the same model takes part of a build's texts, after its vectors were checked against the local model's |
| #34 | The vector cache | the cache grew for ever, at 4.7 KB a vector | a layout 2.5 times smaller, and a size cap that drops the vectors used longest ago |
| #35 | The compact search index | the search index holds every full vector in memory | an index of RaBitQ codes, a third of the memory, that returns the exact index's results |
| #36 | The default search index | a user should not have to choose | `vector_backend = "auto"`: the exact index while it fits a memory budget, the compact one beyond |
| #38 | FAISS 1.16.0 in the lock file | FAISS 1.15.1 has no vectorized code for ARM in several kernels | both search indexes are about 1.5 times faster on an M1, with the same results |
| not merged yet (`andre/track-c-defaults`) | Three defaults | a session nobody uses kept its model; the cache kept everything for ever; the compact index's first scan had little room | the model is freed after 60 idle minutes and the next search waits for it; the cache drops what no index has needed for 30 days; the first scan keeps 4,000 codes |

**2. The results doc** is `docs/analysis/track-c-results.md` on `andre/track-c-results`. It
explains the design of each part and gives the evidence that a search returns what it returned
before. It has six sections: the short version, the search index, disk and the vector cache, the
embedding model (what each change gives and costs), branches and worktrees, and what is our own
work against what is reused.

**3. By default codemem uses the exact index, a full scan.** The compact index takes over only
where the exact one does not fit 2% of the machine's memory: above 185,000 vectors on 16 GB,
93,000 on 8 GB, 555,000 on 48 GB. On the eval's PC every repo is on the exact index. Search time
is milliseconds with either, and level at the size of our repos; the compact index would save
about 30 ms a search at a million vectors. Those larger sizes are extrapolated: run 3 of the
entry of 11:32 measures them.

**4. Planned, not for the freeze** (Andre, Nov 26): one embedding model per machine, shared by
every codemem process, started by itself, scaled with the machine's memory, and freed under
memory pressure. It is in `docs/plan/track-c-memory.md` §4.6 on the same branch.

## Checked

- Nothing was run for this entry. The numbers are those of the entries of 07:43, 09:16 and 11:20.

## Left

- The pull requests for `andre/track-c-defaults` and `andre/track-c-results` (Andre).
- The audit fixes, on two branches in work.

## Blocked on, or needed from others

- **Andrew:** the runs of the entry of 11:32.

## Next

- Track C's session: the audit fixes; then the PC's numbers into the results doc.
