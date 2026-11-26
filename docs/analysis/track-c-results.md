# Track C: what was built, what it saves, and how it was checked

**State on 2026-11-26.** Track C is seven pull requests, #30 to #36, and all are on `main`. A
follow-up sets three defaults (`andre/track-c-defaults`); this report describes codemem with it.

**How to read the numbers.** Everything was measured on an M1 MacBook with 16 GB, with FAISS on
one thread, unless a line says otherwise. "Real" means vectors made by the real embedding model
(`jina-code-embeddings-0.5b`, 896 numbers per vector). "Stand-in model" means a fake model that
gives the same vector for the same text: it measures codemem's own work, not the model's. The
search times of §3.3 were taken with the FAISS version that `main` pins.

**Still to come.** Nothing here has run on Linux or x86 yet.

---

## 1. The short version

Track C is optimization: the same search results, for less memory, less disk and less waiting.

| | Before | After | What was kept |
|---|---|---|---|
| The search index in memory, real vLLM index (144,729 vectors) | 278 MB | 106 MB with the compact index | the true top 10 and the true top 50 in all 762 searches (§3.2) |
| The saved search index on disk, real vLLM index | 261 MB | 86 MB with the compact index | the same |
| The exact index's own memory, 200,000 vectors | 441 MB | 371 MB | the same index: only its bookkeeping changed |
| The vector cache on disk | 4.7 KB a vector, no limit | 1.9 KB a vector, capped at 8 GB, and nothing unused for 30 days stays | the same vectors, byte for byte |
| The embedding model in memory, Apple GPU | 2.64 GB | 1.71 GB | the same vectors, bit for bit |
| The same, after 60 minutes without use | 1.76 GB | 0.62 GB | the next search waits 2 to 6 s for the model, and has the same results |
| The embedding model on a CPU | it ran in the wrong precision | 5 to 15 times as fast | scores move by at most 0.0007 |
| The first up-to-date search in a new git worktree (vLLM) | 76 s | 4 to 8 s | an index equal to a fresh build |
| Coming back to a branch seen before | no model call | no model call, now pinned by tests and by an audit | an index equal to a fresh build |
| A first build with a second machine or an API helping | not possible | 1.9 times as fast with a helper as fast as the local model (stand-in models) | the index the local model alone would build |

**The rule behind the design** (Andre, Nov 25): accuracy and speed first, memory second. So the
compact index is not forced on anyone. By default codemem keeps the exact index while it fits 2%
of the machine's memory and uses the compact one only beyond that.

---

## 2. What was built

| # | Part | The problem | What it does |
|---|---|---|---|
| #30 | The embedding server | every codemem process loads its own copy of the model, over a gigabyte each | `codemem serve-embeddings` puts the local model behind an OpenAI-style endpoint. Several processes (one per git worktree, one per container) share one model |
| #31 | Model memory | the model is the largest thing in memory | a cheaper load on Apple GPUs, working memory given back after a burst, an optional idle unload, and the right precision on a CPU |
| #32 | Branches and worktrees | a new git worktree started from an empty index | a new worktree's index starts as a copy of another checkout's. A search right after a switch embeds its own results first. Tests pin what a branch switch costs |
| #33 | The embedding assist | a first build is almost all model time | an optional second endpoint that serves the same model takes part of a build's texts. It gets work only after its vectors were checked against the local model's |
| #34 | The vector cache | the cache grew for ever, at 4.7 KB a vector | a layout 2.5 times smaller, and a size cap that drops the vectors used longest ago |
| #35 | The compact search index | the search index holds every full vector in memory | an index of RaBitQ codes, a third of the memory, that still returns exact scores |
| #36 | The default search index | a user should not have to choose | `vector_backend = "auto"`: the exact index while it fits a memory budget, the compact one beyond |
| follow-up | Three defaults | a session nobody uses kept its model; the cache kept everything for ever; the first scan had little room | the model is freed after 60 idle minutes and the next search waits for it; the cache drops what no index has needed for 30 days; the compact index's first scan keeps 4,000 codes |

**What was not changed.** The watcher, the chunker and the text builder are untouched. The
indexer's two stages and their order are unchanged; it changed in 33 lines (the cache's cap and
last-use dates, and one line that brings the saved search index to what the next start reads).

---

## 3. The search index: RaBitQ codes in memory, exact scores from disk

### 3.1 How it works

Today's index keeps every full vector in memory: 896 numbers at 2 bytes each, about 1.8 KB. A
search compares the question with every one of them: a full scan. The compact index keeps two
small codes per vector instead, and leaves the full vectors in the database on disk.

A search takes three steps:

1. **Scan.** Compare the question with a 1-bit code of every vector (120 bytes each). Keep the
   best 4,000, or one in 50 of the vectors when that is more.
2. **Rank again.** Compare the question with a 4-bit code of those (468 bytes each). Keep the
   best 200, or 4 for each result asked for when that is more.
3. **Score exactly.** Read those full vectors from the database and compute the real scores.

On vLLM's 109,562 code vectors, a search for 50 chunks goes from 109,562 to 4,000 to 220 to 50.

So the codes only decide which candidates are looked at. Every score a search returns is the
real one, and the final order is the exact index's order.

The codes are **RaBitQ** codes (Gao and Long, SIGMOD 2024, and its extension to several bits per
number, Gao et al., 2025). They are made and compared by FAISS, Meta's vector search library
(`faiss.IndexRaBitQ`). Track C did not implement RaBitQ. What it built is in §7.

**One bit and four bits.** Before anything is coded, codemem multiplies the vector by a rotation:
a fixed table of random numbers, drawn once from a seed, so the same vector gets the same code
on every machine. The 1-bit code keeps the sign of each rotated number. The 4-bit code keeps the
sign and 3 more bits for the number's size: 16 levels, one step apart. A similarity is estimated
the same way from either: the product of the question with the code, divided by a correction
that is stored with the code and says how well the code matches its own vector. The rotation
makes the rounding error random; the correction removes the part of it that is the same for every
question about that one vector.
Each extra bit about halves the error. Measured in FAISS on random vectors of 896 numbers:

| Bits per number | 1 | 2 | 4 | 8 |
|---|---|---|---|---|
| typical error of an estimated similarity (standard deviation) | 0.026 | 0.012 | 0.0036 | 0.0003 |
| bytes per vector | 120 | 244 | 468 | 916 |

On vLLM, results that are neighbours in a ranking differ by about 0.003 in score. So the 1-bit
estimate is only good enough to pick a few thousand candidates, the 4-bit estimate puts them in
nearly the right order, and the exact scores of step 3 settle it.

**Why the saving is 3 times, and not 16.** A vector of 896 numbers:

| | Bytes per vector in memory |
|---|---|
| the exact index: 896 numbers at 2 bytes each, and 64 bytes of bookkeeping | 1,856 |
| the compact index: the 1-bit code (120), the 4-bit code (468), and 40 bytes of bookkeeping | 628 |
| the compact index with the 1-bit code alone (`bits = 1`) | 160 |

The default keeps both codes: 3.0 times less memory than the exact index. The 1-bit code alone
would be 11.6 times less, and §3.2 shows its price: it has to read 1,000 full vectors per search
to return what the default returns with 200.

**Why a separate 1-bit code, when the 4-bit code holds it.** The first 112 bytes of a 4-bit code
are the 1-bit code, and FAISS can search a 4-bit index by itself: it looks at the first bit and
takes the full estimate only where that leaves a chance. When the index was built, that search
was 3 to 4 times slower than the exact index on this laptop, so the index got a 1-bit code of
its own to scan. With the FAISS that `main` pins now, FAISS's own search is as fast as our steps
1 and 2 (6.6 ms against 5.9 ms on vLLM's code vectors, on 150 questions, with other jobs
running) and picked the same 220 candidates in every one. What the separate code still gives
is a fixed rule: the candidates depend only on the vectors held, never on the order they are
held in. Whether that is worth its 120 of 628 bytes is open (§9).

### 3.2 Does it return the same results?

**Yes, for every real question about the repo.** The main evidence is the real vLLM index:
144,729 vectors, and the 381 issue texts of the eval's vLLM tasks as questions. codemem keeps two
kinds of vector for a function, each in an index of its own: one of its code (109,562 here) and
one of how it is used, by its callers and tests (35,167). Each question is asked of both for 50
chunks, as a search does: 762 searches per row. The reference is a brute-force oracle over the
stored vectors, which uses neither codemem's search nor FAISS's.

| Setting | The true top 10 | The true top 50 |
|---|---|---|
| the exact index | 762 of 762 | 762 |
| **the default: 4 bits, 200 candidates** | **762** | **762** |
| 2 bits, 200 candidates | 762 | 762 |
| 8 bits, 200 candidates | 762 | 762 |
| 1 bit, 1,000 candidates | 762 | 762 |
| 1 bit, 500 candidates | 762 | 754 |
| 1 bit, 200 candidates | 762 | 664 |

- Every score returned was the real one: the largest difference from the oracle's was 0.0000001.
- The whole search, keywords and vectors merged, returned the same 10 results in the same order
  as with the exact index for all 381 questions. So a gold file is found for the same 277 of 375
  questions with either index.

**How much room the default leaves.** For every question we looked up how deep its true top 50
lay in each step's order. The first scan was at 2,000 codes when this was measured:

| | the code index | the usage index |
|---|---|---|
| step 1 (1 bit) kept | 2,191 | 2,000 |
| the deepest place any question needed | 976 | 512 |
| step 2 (4 bits) keeps | 220 | 204 |
| the deepest place any question needed | 102 | 74 |
| the same with 2 bits | 194 | 202 |
| the same with 8 bits | 95 | 53 |

So 4 bits is enough: the worst question used less than half of step 2's room. 8 bits improves
the worst case from 102 to 95, for 1.7 times the memory. 2 bits gave the same results with
almost no room left.

**Three more checks agree.** On a real pandas index (49,770 vectors, 352 issue texts) the
default gave the same top 10, top 50 and merged results as the exact index in every search. So
did the first check, on 30,977 real vectors with 768 searches. And an independent audit, by a
separate agent told to break the index with its own oracle, found on pandas: exact scores, the
true top 10 in all 1,640 searches, the right results under filters, adds, deletes and restarts
in 47,408 searches, and all 53 damaged saved files refused.

**The one limit: a question about something the repo does not hold.** Its best matches are weak
and close together, and the 1-bit code orders them badly. With the first scan at 2,000 codes,
one of 536 searches on pandas with questions mostly about other repos, and one of 704 on vLLM
(the pandas questions, asked of vLLM), lost one result near the end of its top 50, at ranks 45
and 44. No top 10 was touched, and on
vLLM the whole search still returned the same 10 results. This is why the first scan now keeps
4,000: with it, all 704 searches return the true top 50. For a synthetic question with nothing
near it at all, the default returned the exact top 10 in 78% of searches.

### 3.3 What it saves and costs

**The mental model.** Memory and disk follow the bytes per vector. Time has two parts.

| | The exact index (a full scan) | The compact index |
|---|---|---|
| memory, per 100,000 vectors | 186 MB | 63 MB |
| saved index on disk, per 100,000 vectors | 180 MB | 60 MB |
| one search | 0.07 ms for each 1,000 vectors | 0.035 ms for each 1,000 vectors, and about 3 ms that do not depend on the size |

So memory is 3 times less at every size. Time is not: the compact index is slower on a small
index, level at about 100,000 vectors, and faster beyond.

**One example: the real vLLM index** (144,729 vectors; each number from a process of its own):

| | The exact index | The compact index |
|---|---|---|
| memory the process holds for the search index | 278 MB | 106 MB |
| saved search index on disk | 261 MB | 86 MB |
| loading at a start, from the saved file | 0.3 s | 0.3 s |
| building it from the database (a first start, or a saved file that is refused) | 1.8 s | 18.6 s |
| one search over the 109,562 code vectors | 8.1 ms | 7.5 ms |
| one search over the 35,167 usage vectors | 2.4 ms | 3.9 ms |

The search times are medians over all 381 questions, three times, the two indexes taking turns
question by question in one process so that both saw the same machine.

**At what size does the time matter?** From the two numbers of the mental model, for one kind of
vector (extrapolated beyond vLLM, not measured):

| Vectors | Full scan | Compact |
|---|---|---|
| 110,000 (vLLM, measured) | 8 ms | 7.5 ms |
| 1 million | about 75 ms | about 45 ms |
| 5 million | about 370 ms | about 215 ms |

A repo needs about ten times vLLM's functions before the saving reaches 30 ms a search. Until
then the reason to use the compact index is memory: at a million vectors the exact index holds
1.9 GB.

**Vector search beside the rest of a search.** On vLLM, with the model's part left out, three
short questions (4 to 9 words) took 38 to 57 ms each: 10 to 27 ms for keywords, about 23 ms for
the code vectors and 4 ms for the usage vectors. With a whole issue text as the question (a
median of 5,700 characters, 48 questions) a search took a median of 2.4 s, and 99% of that was
the keyword search.

### 3.4 When each index is used

`vector_backend = "auto"` (#36) picks at each start:

- the exact index, while the exact indexes of both kinds of vector together fit the budget;
- the compact index beyond that.

The budget is 2% of the machine's memory, at least 128 MB (`vector_memory_mb` sets another).

| Machine memory | The index stays exact up to | For the vLLM index the rule picks |
|---|---|---|
| 8 GB | 93,000 vectors | the compact index, 91 MB |
| 16 GB | 185,000 vectors | the exact index, 269 MB |
| 24 GB | 278,000 vectors | the exact index |
| 48 GB | 555,000 vectors | the exact index |

So pandas (50,000 vectors) and vLLM (145,000) stay exact on a 16 GB laptop, and on the eval's PC
every repo stays exact. The compact index is for the repos and machines where the exact one
does not fit.

### 3.5 What did not work

These are results too, and they shaped the design.

- **A code over only the first 256 numbers** (the plan's pilot suggested it) keeps the top 10 in
  49% of searches with real questions. The pilot had used code vectors as queries, which are much
  easier. So the codes cover all 896 numbers.
- **Letting FAISS search the 4-bit codes by itself** was 3 to 4 times slower than the exact
  index when the index was built. That is why the search scans a 1-bit code of its own and uses
  4 bits only on the best 4,000. With the FAISS pinned now it is as fast (§3.1).
- **The first 512 numbers at full precision as a first step** was no better than the 1-bit code
  over all 896.

---

## 4. Disk

Where the bytes of a real pandas index are (49,770 vectors):

| | Size | Note |
|---|---|---|
| `index.db` | 231 MB | vectors 94, chunk rows 61, keyword index 18, call graph 5; the rest is SQLite's own indexes and page overhead |
| saved search index (`vec_*.faiss`) | 90 MB | a second copy of the vectors. 30 MB with the compact index |
| this repo's share of the vector cache | 233 MB before, 93 MB after | a third copy, shared by every checkout and rebuild on the machine |

**The vector cache (#34).** It remembers the vector of every text that was ever embedded, so the
same text is never embedded twice. It took 4,690 bytes a vector, because every row spilled onto
an overflow page; it takes 1,877 now. `vector_cache_max_gb` (8 by default, about 4 million
vectors) caps it: past the cap, the vectors used longest ago are deleted. A vector that no index
on the machine has needed for 30 days goes too (`vector_cache_max_age_days`); an index marks the
vectors it holds as used once a day, so a repo in use keeps its share. The first run moves an old
cache file into the new one (34,218 vectors in 1.6 s, bit for bit).

**The cap and the age limit cost time, never quality.** An index keeps its own vectors in `index.db`. The cap only
deletes cached copies, and a deleted one is embedded again when it is needed. The audit built 31
indexes under very small caps: every one was equal to a fresh build.

**Open decision.** The saved file of the exact index is a second copy of what `index.db` holds.
Dropping it would make an index folder 28% smaller and a start 0.5 s longer per 50,000 vectors.
On vLLM the folder is 909 MB and that file 261 MB of it; building the exact index from the rows
took 1.8 s, against 0.3 s from the file.

---

## 5. The embedding model

The model is the largest cost in both memory and time: 1.7 GB against 0.1 to 0.4 GB for the
vectors of a large repo, and hours for a first build (pandas: 2 h 54 min for 49,770 vectors on
the M1).

| Change (#31) | Before | After | Checked |
|---|---|---|---|
| Loading on an Apple GPU: the weights are converted to 2-byte numbers on the CPU, then moved | 2.64 GB in use | 1.71 GB | vectors bit-identical on 268 real questions and 36 other texts |
| Working memory given back after a burst of 256 texts | 2.80 GB | 1.59 GB | the next batch was not slower |
| `model_idle_minutes` (60 by default; 0 keeps the model) | 1.76 GB | 0.62 GB | the next search waits for the reload, 2 to 6 s, and has the same results |
| On a CPU the model ran in the weights file's format, not the one its key names | 20 queries in 18.0 s; 32 code texts in 533 s | 3.7 s; 35.8 s | scores differ from the GPU's by at most 0.0007; same top 10 in 20 of 20 queries |

**One model for several processes (#30).** `codemem serve-embeddings` serves the local model over
HTTP. In the audit, an index built through the server was equal, byte for byte, to one built in
process.

**A second source for a build (#33).** With `[embedding.assist]` set, an endpoint that serves the
same model embeds part of a build's texts. Before it gets any text, seven probe texts are embedded
both ways, and every pair must agree to a cosine of 0.99995. With stand-in models, a build ran
1.26 times as fast with a helper a quarter as fast as the local model, 1.87 times at equal speed
and 3.4 times at four times the speed. No real provider has been tried.

---

## 6. Branches and worktrees

**The design.** One index per checkout, updated in place. Vectors are found by the hash of their
text in the shared cache, so a text that was embedded once, on any branch, is never embedded
again.

**What a switch costs** (vLLM, two commits a week apart, about 2,000 files differ, stand-in model):

| | Texts that need the model | Texts from the cache |
|---|---|---|
| the first visit | 9,054 (6% of the index) | 24 |
| coming back | 0 | 17,398 |

**A new worktree (#32).** Its index starts as a copy of another checkout's index, and one check
then re-chunks only the files that differ. On vLLM the first up-to-date search came after 4 to
8 s, against 76 s from nothing. The index of a removed worktree is deleted; in the audit the
clean-up deleted exactly the right folders in 18 starts with 12 traps set for it.

**A search right after a big switch.** Thousands of chunks can be waiting for vectors. A search
first embeds the waiting chunks that its keyword results rank on top. For a function that a
switch added, it was in the first 3 results in 56% of searches, against 8% before (stand-in
model, synthetic queries). The cost: such a search can take up to its 4 s. In the audit none took
longer than 4.0 s.

**How big real branch differences are** (open pull requests against the tip of the default
branch; code texts only; taken Nov 25):

| Repo | Pull requests | A pull request's own change, median | A first switch to its branch: median / 90th percentile |
|---|---|---|---|
| pandas | 50 | 10 texts | 83 / 1,449 |
| playwright | 12 | 45 texts | 146 / 905 |
| vLLM | 50 | 15 texts | 1,809 / 37,712 |

A pull request's own change is a few seconds of embedding. What makes a first switch expensive is
how far the branch sits behind the default branch. These are upper bounds: a text that another
file already has would be reused, and that was not counted.

**Checked by an audit on real history** (flask, real git operations, through `codemem index`,
`codemem watch` and the MCP server): after each of 21 switches the index was equal to a fresh
build, vector by vector, and every return gave the model 0 texts.

---

## 7. What is our own work, and what is reused

**Reused.** RaBitQ, the method, is Gao and Long's, and the implementation is FAISS's: FAISS,
Meta's vector search library, has had RaBitQ since version 1.11.0 (April 2025) and codes of 2 to
9 bits per number since 1.13.1 (December 2025). codemem asks FAISS for a 1-bit and a 4-bit code
and adds no quantization code of its own. The exact index is FAISS's. The storage is SQLite. The
model runs through sentence-transformers.

**Our own design and findings:**

1. **The three-step search** (§3.1): RaBitQ codes choose the candidates by a fixed rule, and an
   exact last step from the database decides. So the results are the exact index's results, at
   its speed from about 100,000 vectors up, for a third of its memory. A two-step search over
   multi-bit codes is FAISS's own too, and with the FAISS pinned now it is as fast as ours
   (§3.1): what is ours is the exact last step and the rule that does not depend on the order
   of the codes.
2. **Codes that need no training.** The rotation comes from a fixed seed and the codes' centre is
   zero, so a code depends only on its own vector. Vectors can then be added and removed one at a
   time. That is what lets a compressed index follow a codebase edit by edit.
3. **An index that follows the machine's memory** (§3.4): exact while it fits, compact beyond.
   Accuracy is the default, and compression is used only where memory needs it.
4. **Three negative results from real questions** (§3.5), including that a pilot which uses code
   vectors as queries overstates what a short code keeps.
5. **The embedding assist with a proof before use** (§5): a second source of vectors that is
   compared with the local model first, so the index does not depend on who embedded a text.
6. **Worktrees and switches** (§6): the index copy, the search that embeds its own results first,
   and the measurement of real branch differences.
7. **Two findings about the model** (§5): converting the weights on the CPU first saves 0.9 GB on
   an Apple GPU with identical vectors, and the CPU path ran in the wrong precision.
8. **The cache layout** (§4): every cached vector spilled onto an overflow page. A layout with
   32 KB pages and gap-free slots is 2.5 times smaller.

Whether any of these is new in the research sense has not been checked against the literature.
Items 1 to 4 and the measurements of §6 are the candidates for the paper.

---

## 8. How it was checked

| Check | Result |
|---|---|
| The test suite of the combined code | 619 tests pass. 616 pass and 3 are skipped when the whole suite is forced onto the compact index, and the same on the exact one |
| Every FAISS call the store makes, under a memory checker | 2,608 combinations of vector length and bits, no fault |
| The compact index against the exact one, real vectors | §3.2 |
| The compact index against a brute-force oracle, on the real vLLM index | the true top 10 and top 50 in all 762 searches with vLLM's questions; one top 50 of 704 lost a result with another repo's questions (§3.2) |
| An index built by `main`, then updated by the new code | nothing embedded again, the stored settings equal byte for byte |
| Each merge to `main` | #30 to #36 and #38 are, byte for byte, the content that was tested |
| Audit 1: the search index (#35, #36) | no finding that blocks a merge |
| Audit 2: `main` with #30 to #33, and the cache (#34) | no wrong index and no lost data; no finding that blocks #34 |

Each audit was done by a separate agent that was told to break the code, with its own scripts.

**What the audits found** (none gives a wrong result in normal use):

| Where | Finding | State |
|---|---|---|
| search index | "the same top 50 in every search" is too strong: one miss in 1,640 (§3.2) | the claim is corrected here |
| search index, on `main` already | the exact index's saved file has no checksum: a flipped bit loads unchanged and gives wrong scores | to fix |
| search index | after a power cut the saved index can be newer than the database and be trusted all the same | to fix |
| search index (#36) | when another process writes vectors, a search codes them while it holds the lock: a status call waited 343 ms behind 3,000 vectors | to fix |
| search index | a query of zeros took 4.1 s; vectors longer than 4,096 numbers are coded on their first 4,096 without a warning | to fix |
| worktrees | a new worktree far from its source answers from the other checkout's code for about a second | to fix |
| command line | `codemem search` after `git switch` answers from the old branch and says nothing. The MCP server does follow the switch | to fix |
| worktrees | a worktree inside the main checkout doubles the main index | a known gap, now measured |
| cache (#34) | within one day "used longest ago" is "first used", so a very small cap can drop vectors read a minute ago | to fix or to document |
| cache, on `main` already | a cache locked by another process stalls an MCP search for 64 s | to fix |
| the check script (#36) | `scripts/check_search_indexes.py` ended in an error when run without `--tasks`, since a task file of another kind was added to `eval/tasks` | fixed in #36, with tests |

---

## 9. Not checked yet

- **A real index above 145,000 vectors.** vLLM is the largest real index checked. Beyond it there
  are only synthetic vectors (200,000).
- **Linux and x86**, CUDA, and FAISS on more than one thread.
- **Whether the separate 1-bit code is still worth its memory** (§3.1). FAISS's own search over
  the 4-bit codes was compared with our steps on 150 questions only, with other jobs running. If
  it holds, one code would do: 508 bytes a vector, not 628.
- **The time at a million vectors.** The table of §3.3 is extrapolated beyond vLLM.
- **The eval's end-to-end runs** (track A): whether an agent's results change at all.
- **The embedding assist with a real model or a hosted provider.**
- **Whether a vector that is embedded a second time is bit-identical** to the first, with the real model.
- **Times on a quiet machine.** The search times of §3.3 were taken with no other job of ours
  running. Most other times here were taken while other jobs ran.

---

## 10. Where the evidence is

- In the repository: the tests, and three scripts that anyone can run: `scripts/check_search_indexes.py`
  (a real index and real questions: each index against the exact one), `scripts/check_faiss_calls.py`
  and `scripts/check_served_vectors.py`.
- The benchmark scripts, their raw results and the two audit reports are kept by Andre outside the
  repository.
- codemem as it was before track C is kept on the branch `archive/codemem-before-track-c`, to
  benchmark against.
