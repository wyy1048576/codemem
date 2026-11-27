# Track C: the optimizations, why they are designed this way, and the evidence

This document explains what track C changed in codemem so that it needs less memory, less disk
and less waiting, why each change is designed the way it is, and the evidence that a search still
returns what it returned before. It is for someone who wants to understand the design or to quote
a number from it.

**How to read the numbers.** They were measured on an M1 MacBook with 16 GB unless a line says
otherwise. "Real" means vectors made by the real embedding model (`jina-code-embeddings-0.5b`,
896 numbers per vector). "Stand-in model" means a fake model that gives the same vector for the
same text: it measures codemem's own work, not the model's.

---

## 1. The short version

Track C is optimization: the same search results, for less memory, less disk and less waiting.

| | Before | After | What was kept |
|---|---|---|---|
| The search index in memory, real vLLM index (144,729 vectors) | 278 MB | 106 MB with the compact index | the true top 10 and the true top 50 in all 762 searches (§2.2) |
| The index folder on disk, real vLLM index | 909 MB | 734 MB with the compact index | the full vectors stay in the database |
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

## 2. The search index

### 2.1 How it works

Today's index keeps every full vector in memory: 896 numbers at 2 bytes each, about 1.8 KB. A
search compares the question with every one of them: a full scan. It is exact, and it is the
default. The compact index is for an index too large to hold that way. It keeps two small codes
per vector in memory and leaves the full vectors in the database on disk.

A search with the compact index takes three steps:

1. **Scan.** Compare the question with a 1-bit code of every vector (120 bytes each). Keep the
   best 4,000, or one in 50 of the vectors when that is more.
2. **Rank again.** Compare the question with a 4-bit code of those (468 bytes each). Keep the
   best 200, or 4 for each result asked for when that is more.
3. **Score exactly.** Read those full vectors from the database and compute the real scores.

On vLLM's 109,562 code vectors, a search for 50 results goes from 109,562 to 4,000 to 220 to 50.
The codes only decide which candidates are looked at. Every score a search returns is the real
one, and the final order is the exact index's order.

**The codes are RaBitQ codes** (Gao and Long, SIGMOD 2024; several bits per number: Gao et al.,
2025), made and compared by FAISS, Meta's vector search library. Before a vector is coded,
codemem multiplies it by a rotation: a fixed table of random numbers, drawn once from a seed, so
that the same vector gets the same code on every machine.
The 1-bit code keeps the sign of each rotated number. The 4-bit code keeps the sign and 3 more
bits for the number's size: 16 levels. With each code FAISS stores a correction that says how
well the code matches its own vector, and an estimate divides by it. Each extra bit about halves
the estimate's error: 0.026 with 1 bit and 0.0036 with 4, on vectors of 896 numbers. Results that
are neighbours in a ranking differ by about 0.003. So 1 bit can pick a few thousand candidates,
4 bits put them in nearly the right order, and the exact scores settle it.

**Why the saving is 3 times, and not 16.** A vector of 896 numbers, in memory:

| | Bytes per vector | Against the exact index |
|---|---|---|
| the exact index: 896 numbers at 2 bytes each, and 64 bytes of bookkeeping | 1,856 | |
| the compact index: the 1-bit code (120), the 4-bit code (468), and 40 bytes of bookkeeping | 628 | 3.0 times less |
| the compact index with the 1-bit code alone | 160 | 11.6 times less |

The default keeps both codes. The 1-bit code alone has a price that §2.2 shows: it has to read
1,000 full vectors per search where two codes need 200.

**Why two codes.** FAISS can search 4-bit codes by itself: it looks at the first bit of each and
takes the full estimate only where that leaves a chance. When the index was built, that was 3 to
4 times slower than a full scan on this laptop, so the index got a 1-bit code of its own. With
the FAISS version pinned now, FAISS's own search is as fast as our steps 1 and 2 and picked the
same candidates in 150 of 150 questions. What the second code still gives is a fixed rule: the
candidates depend only on the vectors held, never on their order. Whether that is worth 120 of
the 628 bytes is open.

### 2.2 Does it return the same results?

**Yes, for every real question about the repo.** The main evidence is the real vLLM index:
144,729 vectors, and the 381 issue texts of the eval's vLLM tasks as questions. codemem keeps two
kinds of vector for a function, each in an index of its own: one of its code, and one of how it
is used, by its callers and tests. Each question is asked of both for 50 results, which makes 762
searches per row. The reference is a brute-force oracle over the stored vectors that uses neither
codemem's search nor FAISS's.

| Setting | The true top 10 | The true top 50 |
|---|---|---|
| the exact index | 762 of 762 | 762 |
| **the compact index's default: 4 bits, 200 candidates** | **762** | **762** |
| 2 bits, 200 candidates | 762 | 762 |
| 8 bits, 200 candidates | 762 | 762 |
| 1 bit, 1,000 candidates | 762 | 762 |
| 1 bit, 200 candidates | 762 | 664 |

- **Every score returned was the real one.** The largest difference from the oracle's was
  0.0000001.
- **The whole search is the same too.** Keywords and vectors merged, it returned the same 10
  results in the same order as with the exact index for all 381 questions.
- **4 bits is enough, and 8 buys nothing.** The worst question needed the first 102 of the 220
  candidates that step 2 keeps. With 8 bits that is 95, for 1.7 times the memory. With 2 bits it
  is 194: the same results, with no room left.
- **Three more checks agree:** a real pandas index (49,770 vectors, 352 questions), an earlier
  check on 30,977 real vectors, and an independent audit by a separate agent that was told to
  break the index. The audit found exact scores and the true top 10 in all its 1,640 searches,
  the right results under filters, adds, deletes and restarts in 47,408 searches, and 53 damaged
  saved files refused.

**The one limit: a question about something the repo does not hold.** Its best matches are weak
and close together, and the 1-bit code orders them badly. With step 1 keeping 2,000 codes, one of
536 such searches on pandas and one of 704 on vLLM lost one result near the end of its top 50,
at ranks 45 and 44. No top 10 was touched, and on vLLM the whole search still returned the same
10 results. That is why step 1 keeps 4,000: with it, all 704 searches return the true top 50.

### 2.3 What it saves, and when it would save time

**One example: the real vLLM index** (144,729 vectors):

| | The exact index (a full scan) | The compact index |
|---|---|---|
| memory held for the search index | 278 MB | 106 MB |
| the saved copy of the search index on disk | 261 MB (197.2 for the code vectors, 63.3 for the usage vectors) | 86 MB |
| the database on disk, the same with either index | 648 MB | 648 MB |
| the whole index folder on disk: the database and the saved copy | 909 MB | 734 MB |
| loading it at a start | 0.3 s | 0.3 s |
| building it from the database (a first start) | 1.8 s | 18.6 s |
| one search over the 109,562 code vectors | 8.1 ms | 7.5 ms |
| one search over the 35,167 usage vectors | 2.4 ms | 3.9 ms |

The search times are medians over all 381 questions, the two indexes taking turns question by
question so that both saw the same machine.

**Memory is the saving today: 3 times less at every size.** Per 100,000 vectors the exact index
holds 186 MB and the compact one 63 MB.

**On disk the saving is small.** The database is the same with either index. For vLLM its 648 MB
are:

| In the database | Size |
|---|---|
| the full 2-byte vectors | 297 MB |
| the text of every function and class | 196 MB |
| the keyword index | 58 MB |
| the call graph and the lookup tables | 97 MB |

The vectors there are what step 3 reads, and what a search index is rebuilt from, so they stay.
Only the saved copy of the search index shrinks, so the folder is a fifth smaller, not three
times. With the exact index the vectors are on disk twice: 297 MB in the database and 261 MB in
the saved copy.

**What the saved copy is for.** It is the search index as a file, so that a start loads it in
0.3 s instead of building it from the database's rows (1.8 s for the exact index on vLLM, 18.6 s
for the compact one). An agent's session starts once and would not notice. A `codemem search`
on the command line is a new process each time, and that is how the open-weight models call
codemem in the eval. So the copy stays for now; dropping it for the exact index is a proposal
for after the freeze ([the plan](../plan/track-c-memory.md) §4.4).

**Time is not a saving today.** A search is milliseconds either way, and at the size of our
repos the two are level. The reason is how each one's time is made up:

- a full scan costs 0.07 ms for each 1,000 vectors, and nothing else;
- the compact index costs half of that for each 1,000 vectors, and about 3 ms for steps 2 and 3
  whatever the index's size.

So the compact index is slower on a small index, level at about 100,000 vectors, and ahead
beyond. Vector search sits on the path of every request, so this is where it would show:

| Vectors of one kind | Full scan | Compact | Saved per search |
|---|---|---|---|
| 110,000 (vLLM, measured) | 8 ms | 7.5 ms | nothing |
| 1 million | about 75 ms | about 45 ms | about 30 ms |
| 5 million | about 370 ms | about 215 ms | about 150 ms |

The rows beyond vLLM are worked out from the two costs above, not measured: a measurement up to
2 million vectors is being run on a larger machine. A repo needs about ten times vLLM's 102,000
functions and classes before a search saves 30 ms. At that size the exact index would also hold
1.9 GB of memory, and that is the first reason to change index.

### 2.4 When each index is used

`vector_backend = "auto"` picks at each start: the exact index while the exact indexes of both
kinds of vector together fit 2% of the machine's memory, the compact index beyond that. That is
185,000 vectors on a 16 GB machine, 93,000 on 8 GB and 555,000 on 48 GB. So pandas (50,000
vectors) and vLLM (145,000) use the exact index on a 16 GB laptop, and vLLM uses the compact one
on an 8 GB machine. Accuracy is the default, and compression is used only where memory needs it.

### 2.5 What did not work

These are results too, and they shaped the design.

- **A code over only the first 256 numbers** keeps the top 10 in 49% of searches with real
  questions. An earlier pilot had suggested it would do: it had used code vectors as questions,
  which are much easier. So the codes cover all 896 numbers.
- **Letting FAISS search the 4-bit codes by itself** was 3 to 4 times slower than a full scan
  when the index was built (§2.1).
- **The first 512 numbers at full precision as a first step** was no better than the 1-bit code
  over all 896.

---

## 3. Disk and the vector cache

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

## 4. The embedding model

The model is the largest cost in both memory and time: 1.7 GB, against 0.1 to 0.4 GB for the
vectors of a large repo, and hours for a first build (pandas: 2 h 54 min for 49,770 vectors on
the M1). Each change below is listed with what it gives and what it costs.

| Change | What it gives | What it costs |
|---|---|---|
| **Loading on an Apple GPU.** The weights are converted to 2-byte numbers on the CPU and then moved, where they used to be moved and then converted | 1.71 GB in use, where it was 2.64 GB | nothing. The same weights end up on the GPU: the vectors are bit for bit the same, on 268 real questions and 36 other texts |
| **Working memory is given back** 5 s after a burst of embedding | 1.59 GB after a batch of 256 texts, where it stayed at 2.80 GB | nothing measured: the next batch took 84 s against 87 s |
| **The model is freed after 60 minutes without use** | 0.62 GB, where it was 1.76 GB, for a session nobody is using | the first search after such an hour waits 2 to 6 s for the model. Its results are the same. The eval turns this off |
| **The right precision on a CPU.** The model ran in the weights file's number format there, not the one its settings name | 5 to 15 times as fast: 20 questions in 3.7 s, where they took 18.0 s | scores differ from the GPU's by at most 0.0007, and the top 10 was the same in 20 of 20 questions |
| **One model for several processes.** `codemem serve-embeddings` serves the local model to other codemem processes on the machine | one copy of the model, where every agent session in every git worktree held its own | it is set up by hand, and each embedding goes through a local network call. An index built through it was equal, byte for byte, to one built in process |
| **A second source for a first build.** An endpoint that serves the same model takes part of a build's texts | with stand-in models, a build ran 1.9 times as fast with a helper as fast as the local model, and 3.4 times with one four times as fast | a second machine or a hosted service, and with a hosted one the code leaves the machine. Before the helper gets any text, seven probe texts are embedded both ways and must agree to a cosine of 0.99995. No real provider has been tried |

Where memory is the concern, the order of what to do is: let the idle unload work, then share one
model between sessions. Starting that shared model by itself, and scaling it with the machine's
memory, is planned work ([the track C plan](../plan/track-c-memory.md) §4.6).

---

## 5. Branches and worktrees

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

## 6. What is our own work, and what is reused

**Reused.** RaBitQ, the method, is Gao and Long's, and the implementation is FAISS's: FAISS,
Meta's vector search library, has had RaBitQ since version 1.11.0 (April 2025) and codes of 2 to
9 bits per number since 1.13.1 (December 2025). codemem uses its newest release, 1.16.0 (November
2026). It asks FAISS for a 1-bit and a 4-bit code and adds no quantization code of its own. The exact index is FAISS's. The storage is SQLite. The
model runs through sentence-transformers.

**Our own design and findings:**

1. **The three-step search** (§2.1): RaBitQ codes choose the candidates by a fixed rule, and an
   exact last step from the database decides. So the results are the exact index's results, at
   its speed from about 100,000 vectors up, for a third of its memory. A two-step search over
   multi-bit codes is FAISS's own too, and with the FAISS pinned now it is as fast as ours
   (§2.1): what is ours is the exact last step and the rule that does not depend on the order
   of the codes.
2. **Codes that need no training.** The rotation comes from a fixed seed and the codes' centre is
   zero, so a code depends only on its own vector. Vectors can then be added and removed one at a
   time. That is what lets a compressed index follow a codebase edit by edit.
3. **An index that follows the machine's memory** (§2.4): exact while it fits, compact beyond.
   Accuracy is the default, and compression is used only where memory needs it.
4. **Three negative results from real questions** (§2.5), including that a pilot which uses code
   vectors as queries overstates what a short code keeps.
5. **The embedding assist with a proof before use** (§4): a second source of vectors that is
   compared with the local model first, so the index does not depend on who embedded a text.
6. **Worktrees and switches** (§5): the index copy, the search that embeds its own results first,
   and the measurement of real branch differences.
7. **Two findings about the model** (§4): converting the weights on the CPU first saves 0.9 GB on
   an Apple GPU with identical vectors, and the CPU path ran in the wrong precision.
8. **The cache layout** (§3): every cached vector spilled onto an overflow page. A layout with
   32 KB pages and gap-free slots is 2.5 times smaller.

Whether any of these is new in the research sense has not been checked against the literature.
Items 1 to 4 and the measurements of §5 are the candidates for the paper.

---

How each number was measured, what two independent audits found, and what is not checked yet
are in the team's work log (the `worklog` branch).
