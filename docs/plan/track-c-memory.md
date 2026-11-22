# Track C: memory and speed

**Status:** a plan, written Nov 22, 2026. Nothing here is built yet, except the small pilot in §5.
The shared context is in [overview.md](overview.md). How codemem stores vectors today is in
[architecture.md](../architecture.md) §5.

**Goal.** Make the index small enough that memory is no longer a reason not to run codemem on a Mac
with 16 to 24 GB, without losing accuracy. Searches are already fast; they only have to stay fast.

**Done means:**
1. a measured table of what each compression choice costs in accuracy, on our own code vectors and
   real queries;
2. a vector store that needs 15 to 45 times less memory than today and returns the same top
   results;
3. each vector stored once on disk, not two or three times;
4. a size cap on the machine-wide vector cache;
5. a memory, disk and latency report for 50,000 to 1,000,000 chunks, which becomes the cost figure
   of the paper.

**Track C works with track B.** B decides which vectors exist and how a query flows. C decides how
those vectors are stored, scanned and re-checked. The two meet at one interface (§8).

---

## 1. In plain words

A **vector** is the list of numbers the embedding model gives for a piece of code. Texts with
similar meaning get similar lists. codemem finds code by meaning by comparing the query's vector
with every chunk's vector.

Today every vector has 896 numbers, each stored in 2 bytes: 1,792 bytes per vector. A large repo
has about 200,000 of them, and codemem keeps them all in memory. That is 358 MB of RAM for one
repo, on top of the 2.2 GB the embedding model takes.

**The idea of this track.** Most of those bytes are needed only for the last step. To find
*roughly* the right 100 candidates among 200,000, a very coarse copy of each vector is enough. To
put those 100 in exactly the right order, the full vectors are needed. But only 100 of them, and
they can be read from disk.

Follow the running example. An agent asks codemem: *"add OCR to the upload pipeline"*.

```
 the query ──► embedding model or API ──► one query vector
                                               │
     ┌─────────────────────────────────────────┴───────────────────────────────────┐
     │ STEP 1, in memory: compare the query with a coarse code of every chunk       │
     │   200,000 codes × 40 to 136 bytes = 8 to 27 MB          about 2 to 10 ms     │
     │   keep the best 100                                                          │
     └─────────────────────────────────────────┬───────────────────────────────────┘
                                               ▼
     ┌──────────────────────────────────────────────────────────────────────────────┐
     │ STEP 2, from disk: read the full vectors of those 100 and score them exactly │
     │   100 × 2 KB = 200 KB read                                about 1 to 3 ms    │
     └─────────────────────────────────────────┬───────────────────────────────────┘
                                               ▼
                    the same top 10 that comparing every full vector would give
```

Five terms used below:

- **Matryoshka vectors.** Some models are trained so that the first 256 or 512 numbers of a vector
  still work as a shorter vector. Cutting a vector short this way is called truncation.
- **Quantization.** Storing each number in fewer bits: 16 bits today, 8 bits, or just 1 bit (is the
  number above or below zero?).
- **RaBitQ.** A 2024 method for 1-bit codes. It subtracts the average vector, rotates every vector
  by the same random rotation, keeps one bit per number, and stores two small correction numbers
  per vector. The rotation is what gives it a proven bound on its error for any model's vectors.
- **Rescoring.** Step 2 above: re-checking the best candidates with the full vectors.
- **ANN index.** A structure (HNSW, IVF) that avoids comparing the query with every vector, at the
  price of sometimes missing a neighbour. codemem has none: it compares with every vector, which
  is called an exact scan.

---

## 2. Where memory and disk go today

Measured on vLLM: 6,235 files, 102,000 chunks, 145,000 vectors.

| What | Where | Size | Why it is there |
|---|---|---|---|
| the embedding model (0.5B parameters, 2 bytes each) | RAM | about 2.2 GB | to embed edits and queries; reloading it takes 7 to 13 s |
| every vector, 2 bytes per number, in FAISS | RAM | 260 MB | the exact scan |
| every vector as a SQLite row | disk | about 310 MB | the source of truth |
| a saved copy of the FAISS index | disk | 260 MB | faster start |
| the keyword table's own copy of each chunk's text | disk | 161 MB | removed on branch `andre/fts-contentless` |
| chunks, keywords, links | disk | about 330 MB | everything that is not a vector |
| the machine-wide vector cache | disk | about 4.5 KB per vector, never shrinks | a third copy, shared by every index |

The whole index is 1,062 MB on disk, and vectors are 570 MB of it. Across the nine eval repos an
index takes 10 to 14 KB per chunk, from 0.25 GB (playwright) to 2.35 GB (Godot).

**Two facts set the priorities.**
- **In RAM, the model is 8 times the vectors.** Shrinking vectors helps, but a user who embeds
  through an API has no model in memory at all. Model memory is its own lever (§4.6).
- **On disk, the same vector is stored up to three times.** Removing copies is free of accuracy
  risk, so it comes first.

---

## 3. The target

A proposed budget for a repo with 200,000 vectors. Work package C1 confirms or corrects it.

| | Today | Target | How |
|---|---|---|---|
| RAM for vector search | 358 MB | under 30 MB | 1-bit codes in memory (§4.2) |
| Disk for vectors | 717 MB in two copies, plus the cache | 100 to 410 MB in one copy | one copy (§4.4), shorter vectors (§4.1) |
| Time of the vector step | about 20 ms | under 10 ms with rescoring | a 1-bit scan is faster than a 2-byte scan |
| Accuracy | the reference | the same top 10 in at least 99% of searches, and no significant drop in the eval's primary metrics | rescoring (§4.2) |
| RAM for the model | 2.2 GB | 0 with an API, under 1.5 GB with the light local model, freed when idle | §4.6 |

The 410 MB figure is one copy at 1,024 numbers of 2 bytes. The 100 MB figure is one copy at 256
numbers.

---

## 4. The levers

### 4.1 Shorter vectors

**What it is.** Keep only the first 256, 512 or 1,024 numbers of each vector. It works for models
trained for it. `jina-code-embeddings-0.5b` is trained for 64, 128, 256 and 512. Qwen3-Embedding
accepts any length from 32 up to its full size. EmbeddingGemma 2 is trained for 128, 256 and 512.

**What exists.** codemem's `embedding_dim` setting already truncates when the search index is
built. Vectors are stored at full size, so every length can be tested without embedding anything
again.

**What we know.**
- On our vectors, cutting 896 numbers to 256 keeps 89% of the exact top 10 in its own top 10, and
  all of it in its top 50 *(pilot, §5)*.
- Qwen publishes no quality numbers for shorter vectors. Third-party tests on general text find
  about 99% of full quality at 512 numbers, 96% at 256 and 91% at 128 *(reported)*.
- On code, EmbeddingGemma 2's card gives 78.7, 77.2, 76.2 and 71.4 at 768, 512, 256 and 128
  numbers *(reported)*.
- A 0.6B model fine-tuned for issue localization loses about 1 point at 512 numbers, 5.5 at 256
  and 15 at 64 (SweRank, as cited in [advanced-design.md](../advanced-design.md) §7).

So 512 looks nearly free everywhere, 256 costs a few points before rescoring, and below 256 the
loss grows fast.

**What to decide.** Which length is stored on disk. Rescoring can only be as exact as the stored
copy, so this length is the real ceiling on accuracy. The length used in memory can be shorter.

### 4.2 One bit per number, then rescoring

**What it is.** In memory, keep 1 bit per number instead of 16. Use those codes to pick the best
100 to 200 candidates. Then read the full vectors of those candidates from disk and score them
exactly. The final order is exact; only the choice of candidates is approximate.

**Two ways to make the bits.**

| | Plain sign bits | RaBitQ |
|---|---|---|
| How | bit = is the number above zero | subtract the average vector, rotate by a random rotation, take the sign, and store two correction numbers per vector |
| Size at 1,024 numbers | 128 bytes | 136 bytes |
| Guarantee | none. It works when the model's vectors are centred on zero and spread evenly, which is true for some models and not for others | the estimate of the similarity is right on average, and its error shrinks with the square root of the vector's length: about ±0.09 at 256 numbers, ±0.045 at 1,024 and ±0.02 at 4,096, for about 19 pairs in 20. The proof does not depend on the model |
| More bits | no | yes: 2, 4 or 8 bits per number ("extended RaBitQ") |
| In our FAISS | `IndexBinaryFlat` | `IndexRaBitQ(d, metric, bits)`, 1 to 8 bits |

**What we know from our own machine.**
- Our installed FAISS (1.15.1) already has RaBitQ: no new dependency.
- Wrapped the way codemem wraps FAISS today, the flat RaBitQ index accepted adds, deletes by id,
  an id filter and saving to bytes *(pilot)*. Those are the four things the `VectorStore` interface
  needs.
- The faster variant, `IndexRaBitQFastScan`, refused the id filter in the same test. codemem's
  filters (folder, kind, language, tests) use that filter. FAISS 1.16.0, released Nov 9, adds
  filters to it, and its notes also list a fix to filtering in the flat RaBitQ index *(reported)*.
  So filtered results must be checked against the exact store before 1.15.1 is trusted, or the
  version raised.
- FAISS does not rotate by itself. The rotation is a separate step
  (`IndexPreTransform` with a `RandomRotationMatrix`).
- On our jina vectors, RaBitQ and plain sign bits are close: at 256 numbers, the best 100
  candidates hold 99.9% of the exact top 10 with RaBitQ and 99.7% with sign bits. Adding the
  rotation changed RaBitQ's numbers by less than one point *(pilot)*.
- A 1-bit score alone is too rough to show or to merge with other scores. In a test on random
  vectors, the estimated similarity of the top results was 0.16 to 0.17 where the true value was
  0.08 to 0.12. So the scores an agent sees, and the scores B merges, come from step 2.

**What others have published** *(reported)*.

| Finding | Source | What it means for us |
|---|---|---|
| On OpenAI's 1,536-number vectors, 100,000 of them: RaBitQ alone keeps 83% of the top 10 and sign bits 71%. After rescoring the top 100: 99.9% and 99.2% | a 2026 comparison | with rescoring, the two nearly meet on well-behaved vectors |
| Sign bits collapse on vectors that are not centred on zero: 5% and 35% of the top 10 on two classic image and word sets, even after rescoring | the same | the guarantee matters when the vectors are odd. A cut-short vector may be such a case |
| Each extra bit per number halves RaBitQ's error. At 1 bit, halving it takes 4 times the length | the extended RaBitQ paper | 2 or 4 bits on a short vector is a real alternative to 1 bit on a long one |
| For a code embedding model (voyage-code-3) on issue-to-code search: full vectors 75.2; 1-bit codes rescored over the top 100, 72.0. Averaged over 32 code sets the same change costs only 0.2 | Voyage's published table | **finding the code for an issue is where 1-bit codes lose most.** Rescoring 100 may not be enough for our task; the grid goes to 1,000 |
| At equal bytes, more numbers at 1 bit usually beat fewer numbers at full precision; on issue-to-code the order reversed by 1 to 2 points | the same table, and a 2026 study on a Qwen backbone | no rule of thumb: the grid decides per model |

Products that ship 1-bit codes rescore 3 to 4 times as many candidates as they return (Elastic,
Qdrant, Hugging Face's recipe) *(reported)*.

A related method, Google's TurboQuant, also rotates and then quantizes each number. RaBitQ's
authors dispute how its paper compared the two, and Qdrant ships it *(reported)*. Nothing in this
plan depends on it; it is noted so that nobody is surprised by the name.

**What to decide.** RaBitQ or plain bits, how many bits, and how many candidates to rescore. The
pilot says both work on jina vectors. The open questions are whether that holds for Qwen vectors,
for real queries, for very short vectors, and above all for issue-to-code search, where published
numbers are least kind to 1-bit codes.

### 4.3 No ANN index

**What it is.** Keep comparing the query with every vector, and add no HNSW or IVF structure.

**Why.** At our sizes an exact scan is already fast, and it keeps three things simple:
- **updates:** a code edit adds and deletes a few vectors. An exact scan needs no rebalancing;
- **filters:** a search limited to one folder just skips the other ids;
- **correctness:** there is no recall setting to tune or to explain.

**What we know** *(pilot, M1, 8 threads, 100,000 vectors of 1,024 numbers)*:

| Format in memory | One scan | Memory |
|---|---|---|
| 2 bytes per number (today's format) | 10.9 ms | 205 MB |
| 1 byte per number | 18.5 ms | 102 MB |
| RaBitQ, 1 bit | 4.7 ms | 13.6 MB |
| RaBitQ, 1 bit, FastScan | 1.0 ms | 13.6 MB |
| plain sign bits | 0.5 ms | 12.8 MB |

Scan time grows in step with the number of vectors. A second measurement on the same M1 confirms
it at larger sizes: at 200,000 vectors, 21 ms in today's format, 9 ms for RaBitQ and 2 ms for its
FastScan variant; at 1,000,000, 45 ms and 10 ms for the two RaBitQ variants, in 136 MB. A repo of
200,000 chunks is far below any size that needs an ANN index. Published advice agrees: an exact
scan is enough into the hundreds of thousands of vectors, and an ANN index earns its place above
about a million *(reported)*.

Two smaller findings from the same measurement:
- **Plain NumPy over 2-byte vectors is 3 to 5 times slower than FAISS** (109 ms at 200,000). If we
  ever write the scan ourselves, it has to work on bits, not on 2-byte numbers.
- **One update costs 51 ms at 1,000,000 vectors,** and about a fifth of that at 200,000. Fine for
  a repo; one more reason to revisit the design before a whole-machine index.

**What to decide.** The size at which we would change our mind. Proposed: revisit at 5,000,000
vectors, which only the "search a whole folder or machine" follow-up could reach.

### 4.4 One copy on disk

**What it is.** Store each vector once.

| Copy today | Proposal | Cost |
|---|---|---|
| the SQLite row, 2 bytes per number, full length | keep it, at the length chosen in §4.1 | none |
| the saved FAISS file | drop it. The 1-bit codes are rebuilt from the rows when codemem starts | 0.4 to 1.4 s more at each start (measured for today's format) |
| the machine-wide cache | keep it, in the same compact format, with a size cap (§4.7) | evicted vectors are embedded again if their text comes back |

Reading 100 rows by id for rescoring is the one new disk access per search. If SQLite is too slow
for it on a cold disk, the fallback is a flat file of vectors opened as a memory map: row `i`
starts at byte `i × row size`.

### 4.5 Reranking

**What it is.** After the vector step, a second model reads the query and each candidate's code
together and scores the pair. This is called a cross-encoder. It is more accurate than comparing
two vectors, and much slower.

**What we know.** Rescoring with full vectors (§4.2) is a reranking step that costs almost
nothing: 0.25 ms for 500 vectors in memory. It is part of the design, not an option. For
cross-encoders the evidence is mixed. All *(reported)*.

| | Evidence |
|---|---|
| **Helps** | a general reranker of 4B or more: over a 0.6B embedding model's top 100, code search rises from 75.4 to 81.2. A 7B or 32B reranker trained on issues: the right function in the top 10 for 86.1% or 88.7% of SWE-bench Lite issues, up from 82.1% |
| **Hurts** | a 0.6B reranker scores 73.4 on the same test, **below** the embedding model it reranks. On a 2026 code benchmark, "no off-the-shelf reranker is net-positive across all tasks": the 0.6B one lost up to 8% on one kind of query, the 4B one up to 3% |
| **Exact names** | Exa measured every third-party reranker below the first-stage order on queries that name what they want ([exa.md](../exa.md) §3.4). No study on code was found |
| **Time** | on a data-centre GPU, 100 short texts take 0.17 to 1.1 s depending on the model. No timing on a Mac was found. From our own embedding speed, 30 to 50 candidates would take 6 to 11 s on an M1 with a 0.6B model |
| **Hosted** | DeepInfra serves the Qwen rerankers at $0.01 to $0.05 per million tokens, well under a cent per search. No rerank endpoint was found at Nebius |

So a reranker small enough for a laptop is the kind that hurts, and the kind that helps needs a
GPU or an API.

**The plan.** Treat a cross-encoder as an experiment with a gate, in this order:
1. measure what full-vector rescoring already gives;
2. try a large reranker through an API on the top 30, with exact-name matches pinned so it cannot
   move them;
3. only if step 2 saves an agent tokens or time end to end (track A measures this), look for a
   reranker small enough for a laptop.

### 4.6 The model's memory

The model is the largest block of RAM, and how big it is depends on which of track B's three
embedding options the user picks.

| Option (track B §5) | Model RAM | Lever |
|---|---|---|
| an embedding API | 0 | also make PyTorch an optional install, which saves about 1 GB of disk |
| the light local model | 2.2 GB for today's model in PyTorch. For EmbeddingGemma 2 on a 16 GB M4: 0.8 to 1.2 GB under llama.cpp, 5 to 7 GB under MLX or PyTorch *(reported)* | the runtime matters more than the model here: measure each. Unload after some idle minutes; a reload takes 7 to 13 s today, during which searches answer from keywords with a note |
| Qwen 8B, run locally | 8 GB at 8 bits. A 4-bit file is 4.7 GB, but its vectors differ too much from the full model's to share an index (track B §5.3) | the same idle unload. On 16 GB it leaves too little for an IDE and an agent; the option is documented for 24 GB and up |

### 4.7 The cache cap

The vector cache makes branch switches and rebuilds free, and it only grows. Track B owns how
branches use it ([track-b-retrieval.md](track-b-retrieval.md) §6). Track C owns its format and its
limit:
- store cache entries in the same compact format as the index rows;
- record when each entry was last used;
- when the cache passes its cap, delete the entries unused for longest;
- proposed default cap: 4 times the size of the largest live index, and never less than 1 GB.

---

## 5. What the pilot already shows

The pilot took an hour and reuses what is on disk. It is a sanity check of the idea and of FAISS,
not the result.

**Setup.** The 31,477 real `jina-code-embeddings-0.5b` vectors in our vector cache (896 numbers
each), from the small eval repos. 500 of them were held out and used as queries. The "true top 10"
of a query are its 10 nearest vectors at full precision. Each row asks: how much of that true top
10 is among the format's own best 10, 50 or 100?

| Kept in memory, per vector | Bytes | In its top 10 | In its top 50 | In its top 100 |
|---|---|---|---|---|
| 896 numbers × 2 bytes (today) | 1,792 | 100% | 100% | 100% |
| 896 numbers × 1 byte | 896 | 99.6% | 100% | 100% |
| 256 numbers × 2 bytes | 512 | 88.9% | 100% | 100% |
| 896 numbers × 1 bit, RaBitQ | 120 | 88.3% | 100% | 100% |
| 512 numbers × 1 bit, RaBitQ | 72 | 83.6% | 99.9% | 100% |
| 256 numbers × 1 bit, RaBitQ | 40 | 77.3% | 99.4% | 99.9% |
| 256 numbers × 1 bit, plain sign bits | 32 | 76.7% | 98.7% | 99.7% |
| 128 numbers × 1 bit, RaBitQ | 24 | 69.5% | 96.8% | 99.1% |
| 128 numbers × 1 bit, plain sign bits | 16 | 68.0% | 94.9% | 98.1% |

**How to read it.** Take the row "256 numbers × 1 bit, RaBitQ". Each vector takes 40 bytes in
memory, 45 times less than today. On its own it is not good enough: only 77% of the true top 10
are in its top 10. But 99.9% of them are in its top 100. Rescoring those 100 with the full vectors
from disk then returns the true top 10 in 99.9% of cases.

**More bits at equal size made little difference.** 896 numbers × 1 bit (120 bytes), 512 × 2 bits
(148 bytes) and 256 × 4 bits (148 bytes) all had 100% of the true top 10 in their top 50.

**Four reasons not to trust these numbers yet:**
1. The queries were code vectors, not real questions. A question's vector sits in a slightly
   different place.
2. The cache holds the same functions at many commits, so near-copies make neighbours easy to
   find.
3. The model was jina 0.5B. Qwen vectors are longer and may behave differently.
4. "The same top 10 vectors" is not "the agent found the right code". The eval's own metrics
   decide.

Raw numbers and the script are in `.personal/benchmarks/` (`2026-11-22-quantization-pilot.json`,
`quant_pilot.py`), outside git. Work package C1 redoes the pilot properly.

---

## 6. Experiments and gates

Each experiment has a question and a rule for what counts as a pass. Thresholds are proposals to
agree as a team before running.

| # | Experiment | Question | Pass |
|---|---|---|---|
| C-E1 | The compression grid, from stored vectors: lengths (128, 256, 512, 1,024, full) × formats (2 bytes, 1 byte, RaBitQ at 1, 2 and 4 bits, plain sign bits) × candidates rescored (0, 50, 100, 200, 500, 1,000) × rescoring against the short or the full vector. It includes rows of equal size, such as 512 bytes spent as 4,096 × 1 bit, 1,024 × 4 bits or 256 × 2 bytes. Queries: the eval's dev tasks, as issue texts and as track A's vague rewrites. Also with a folder filter that keeps 100%, 10% and 1% of chunks | Which format keeps the eval's primary metrics? | function MRR and tokens to the first right function within the noise of the 2-byte reference (paired test, not significant, difference under 0.01 MRR). Choose the smallest memory format that passes |
| C-E2 | The same grid on Qwen3-Embedding vectors (8B and 0.6B) for two or three repos, embedded once through the API | Does the choice depend on the model? | one default that passes C-E1's rule for every model option; if not, a default per model |
| C-E3 | Stored length: rescoring against 256, 512 and 1,024 stored numbers | What is the smallest stored copy with no loss? | same rule as C-E1 |
| C-E4 | Scale: memory, start-up time and search time at 50k, 100k, 200k, 500k and 1M vectors, with edits and filtered searches mixed in | Does the exact scan hold up? | the vector step under 10 ms at 200k and under 60 ms at 1M on an M1; a one-function edit still searchable in under 0.5 s |
| C-E5 | Reranker gate (§4.5) | Does a cross-encoder pay for its time? | only judged end to end by track A: fewer tokens or less time at equal completion |
| C-E6 | Model memory: resident memory of the codemem process for each embedding option, idle and busy, with and without idle unload | What does a user actually give up? | reported, no threshold |

**The grid costs no model time.** Vectors are stored at full size, so C-E1 and C-E3 only reread
them. C-E2 needs one API build per repo, about $1 to $2 for a repo the size of Godot.

---

## 7. Work packages

Sizes are rough working days for one person.

| # | Work | Deliverable | Done when | Needs | Days |
|---|---|---|---|---|---|
| C1 | **Measure first.** A script that runs the grid of C-E1 on any index, with real queries, and writes one table | the table for Python, C++ and TypeScript dev tasks; a recommended default (stored length, memory format, candidates) | the team has agreed the default and the pass rule | the eval's dev tasks; A's vague rewrites when they exist | 3 |
| C2 | **The compact vector store.** A `VectorStore` that keeps 1-bit codes in memory and rescoring candidates from SQLite | the store, selectable with `vector_backend`, then the default | on every dev query, its top 10 after rescoring equals the exact store's top 10 in at least 99% of cases; adds, deletes, filters and restart pass the existing store tests | C1's default; the interface change in §8 | 5 |
| C3 | **One copy on disk.** Drop the saved FAISS files; store rows at the agreed length; fold in the keyword-table branch | a smaller index and its new size table for the nine eval repos | index size per chunk reported before and after; update and rebuild still give the same results (the eval's existing check) | C1 | 3 |
| C4 | **The cache cap.** Last-used dates, a size cap, eviction, the compact format | a bounded cache and a `codemem status` line showing its size | a test fills the cache past its cap and sees the oldest entries go; a branch switch back to a cached branch still embeds nothing | B's branch design | 3 |
| C5 | **Model memory.** Idle unload; PyTorch as an optional install for API users | measured resident memory per embedding option | C-E6's table exists; an API-only install has no PyTorch | B's embedding options | 3 |
| C6 | **Scale and cost report.** The benchmark of C-E4, rerun on every release candidate | one figure: memory and time against repo size, today's design against the new one | numbers for 50k to 1M vectors on an M1 and one newer Mac | C2, C3 | 2 |
| C7 | **Reranker study** (only if the gate in §4.5 opens) | a yes or no, with end-to-end numbers | track A's runs with and without it | A's harness | 4 |

**When** (the dates are in [overview.md](overview.md) §8):

| By | Packages | What it gives |
|---|---|---|
| when track A moves to API embeddings | from C5, the install without PyTorch for API users | track A's task containers need it then. Its first runs use the local model |
| **Dec 1** | C1, C2, C3 | the compression table, the compact store and one copy on disk, in the configuration that is presented |
| **Dec 8** | C6, and from C5 the memory table per embedding option | memory, disk and scan time from 100,000 to 1,000,000 vectors, and what each embedding option costs in memory, for the paper |
| **Later, no date** | C4, the idle unload of C5, and C7 if its gate opens | the cache cap, a model that leaves memory when idle, the reranker study |

C1 goes first: it is cheap, it needs nothing from the other tracks, and it decides what C2 builds.

---

## 8. What track C needs from, and gives to, the others

| With | C needs | C gives |
|---|---|---|
| **Track B** | which vector types exist (code only, or code and usage); the embedding options and their vector lengths; the branch design the cache must serve | a vector store that returns **exact** scores for its top results, so B can merge by score and not only by rank; the memory and time cost of each of B's options |
| **Track A** | vague rewrites of the dev tasks, for C1; end-to-end runs for the reranker gate | a frozen, named configuration for each agent run (for example `codemem-compact`), with its memory and disk numbers for the paper; an install without PyTorch for the task containers, before A's first runs that embed through an API |

**Tell track A as soon as the compact store works.** Track A starts on today's index, the heaviest
it will ever be, and for that reason on two or three pilot repos only
([track A](track-a-evals.md) §2.2). Once the compact store builds one repo, write it in the work
log ([CONTRIBUTING.md](../../CONTRIBUTING.md) §4): the configuration name, the commit, and the
measured memory and disk next to today's. Track A then indexes its pilot repos again and expects a
much smaller footprint: for 200,000 vectors, under 30 MB of memory for vector search against 358 MB
today (§3). That drop is what lets track A index every task repo.

**One interface change.** Today a `VectorStore` gets vectors and returns ids with scores. A store
that rescores must be able to read full vectors by id. Proposed: the store is built with a
function `fetch(ids) -> vectors` that reads the SQLite rows, and `search` returns exact scores for
what it returns. Stores that hold full vectors ignore the function. This changes the plugin
contract in [data-model.md](../data-model.md) §12.4, so it needs B's agreement and a note to anyone
with a plugin.

**What must not change.** The eval adapter's contract (data-model §12.2): `search()` and its cards,
`format_results()`, `Config.index_settings()`. A new vector format is an index-time setting, so it
must appear in `index_settings()`. Otherwise two eval systems with different formats would share
one index.

---

## 9. Risks and open questions

| Risk or question | Why it matters | What we do |
|---|---|---|
| Real queries lose more than the pilot suggests | the pilot used code vectors as queries | C1 uses real queries before anything is built; rescoring more candidates is the first remedy |
| The right format differs by model | three embedding options, one default | C-E2; accept a default per model if needed |
| FAISS's RaBitQ changes, or lacks something we need | the fast variant refused id filters in our version, and a filtering fix landed in the next | the method is small enough to write ourselves: about 40 lines of NumPy (a rotation, sign bits, two numbers per vector), measured at 62,000 vectors a second to encode at 1,024 numbers. Keep that as the fallback, and test every filtered search against the exact store |
| Reading 100 rows from SQLite is slow on a cold disk | it would add tens of milliseconds to the first search | measure in C2; fall back to a memory-mapped flat file |
| Storing short vectors closes the door on later experiments | today's full-size rows let us test any format without embedding again | keep "store full size" as a setting, on for research and off by default |
| A smaller index hides an accuracy loss in one language | averages hide it | every table is reported per language, and for vague queries separately |
| Is the usage vector still needed? | it is a quarter of all vectors | B decides (its ablation of usage vectors against graph expansion); C reports what each answer costs |

---

## Sources

Items marked *(reported)* in this file were read by research passes on Nov 22, 2026. Re-read a
page before citing it in the paper. Items marked *(pilot)* are our own measurements of that day.

**RaBitQ and its relatives**
- RaBitQ (SIGMOD 2024), https://arxiv.org/abs/2405.12497 · extended RaBitQ (SIGMOD 2025),
  https://arxiv.org/abs/2409.09913
- FAISS change log, https://github.com/facebookresearch/faiss/blob/main/CHANGELOG.md
- The authors' library, https://github.com/VectorDB-NTU/RaBitQ-Library
- TurboQuant, https://arxiv.org/abs/2504.19874 · the RaBitQ authors' reply,
  https://arxiv.org/abs/2604.19528

**One bit per number, and shorter vectors**
- RaBitQ against sign bits on OpenAI vectors,
  https://dev.to/ahmad_shawar_de8d35d546cf/your-embeddings-are-32x-bigger-than-they-need-to-be-maybe-309h
- Hugging Face, embedding quantization, https://huggingface.co/blog/embedding-quantization
- mixedbread, binary Matryoshka vectors, https://mixedbread.com/blog/binary-mrl
- voyage-code-3's table of lengths and precisions,
  https://www.mongodb.com/company/blog/voyage-code-3-more-accurate-code-retrieval-lower-dimensional-quantized-embeddings
- BitEmbed (a Qwen3 backbone), https://arxiv.org/abs/2606.25674
- Elastic, scalar quantization, https://www.elastic.co/search-labs/blog/scalar-quantization-optimization
- Qdrant, quantization, https://qdrant.tech/documentation/manage-data/quantization/
- Exa's vector database, https://exa.ai/blog/building-web-scale-vector-db

**Exact scan**
- sqlite-vec's measurements, https://alexgarcia.xyz/blog/2024/sqlite-vec-stable-release/index.html
- FAISS, choosing an index, https://github.com/facebookresearch/faiss/wiki/Guidelines-to-choose-an-index

**Rerankers**
- Qwen3-Reranker, https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- CoREB, https://arxiv.org/abs/2605.04615
- SweRank, https://arxiv.org/abs/2505.07849 · SweRank+, https://arxiv.org/abs/2512.20482
- Reranker timings, https://aimultiple.com/rerankers · hosted prices,
  https://deepinfra.com/models/reranker

**Ours**
- The pilot: `.personal/benchmarks/2026-11-22-quantization-pilot.json` and `quant_pilot.py`
  (outside git).
- Today's sizes: [architecture.md](../architecture.md) §5 and §10, and the checkpoint slides.
