# What we can learn from Exa's blog

Notes from reading Exa's technical blog posts (2023–2026, read 2026-10-04). For each area:
1. what Exa does,
2. what we'd **copy** into our project ([PLAN.md](PLAN.md)),
3. where we could **go further** than Exa.

Exa is a model for our techniques and for the style of the write-up. We are not using Exa's product.

> **Caveat:** these notes came from pages passed through an extraction model. Quotes are close to verbatim, not exact. Some numbers appeared only in charts and couldn't be read. Check anything before citing it.

---

## The short version
- **Exa never writes about keeping an index fresh.** Not even [exa-d](https://exa.ai/blog/exa-d), their framework for recomputing embeddings and other derived data as pages change. That's exactly our gap.
- **Their embedding training objective has a natural code version.** "Next-link prediction" becomes "next-reference prediction". This is the most Exa-like research thread available to us.
- **Their search pipeline is now hybrid** (keyword + embeddings, fused with RRF, then reranked) and is cheap to copy.
- **Their benchmark for coding agents ([WebCode](https://exa.ai/blog/webcode)) covers web docs only.** Nobody has published a benchmark for searching *your own repo* as the code changes. Ours would be "WebCode for your own repo".
- **Their evaluation tricks are cheap to copy and make results more credible:**
  - Score retrieval separately from task success.
  - Drop tasks the model can answer from memory.
  - Report bootstrap confidence intervals.
  - Change only the retriever between runs.

---

## 1. Vector database ([How we built a web-scale vector database](https://exa.ai/blog/building-web-scale-vector-db), Dec 2024)

**What Exa does** (for billions of 4096-dim vectors, under 100ms):
1. **Matryoshka truncation.** The embeddings are trained so the first 256 dims work almost as well as all 4096, so they keep only those. The post claims "20x" memory savings, but 4096→256 is 16x; the post doesn't explain the gap.
2. **Binary quantization.** Each value is stored as 1 bit, a further 16x saving.
3. **Asymmetric scoring.** Documents are stored as binary, but the query stays in full float. Scoring is a dot product, not Hamming distance, which recovers precision.
4. **Lookup tables.** The query is split into 4-dim chunks, and the 16 possible dot products for each chunk are precomputed. Scoring a document is then just table lookups. The tables live in CPU registers and the code is written in C++.
5. **IVF clustering instead of HNSW.** They use 100k clusters, and each query searches its own cluster plus nearby ones, for about 1000x more throughput. They avoid HNSW because its "global graph structure can't be partitioned easily".
6. **Filtering** through inverted indexes (filter value → doc IDs) before scoring.
7. **Reranking** of extra candidates with the uncompressed vectors.

**What we copy:** a mini version, a few hundred lines with NumPy/FAISS:
- Use a Matryoshka-capable embedder, truncate, binarize, score with float query × binary docs, then rerank at full precision.
- Benchmark recall and speed against brute force, FAISS IVF and HNSW.

At the size of one repo (10k–100k chunks) we don't need it for speed. It's a vector-DB learning exercise and an ablation.

**Where we go further** (vector-DB freshness):
- **IVF makes inserts cheap** (assign the new vector to its nearest centroid). **HNSW makes deletes awkward** (tombstones, graph repair).
- **New question nobody has measured on code:** as code drifts, how much recall do you lose by keeping the old centroids instead of retraining them?
- This is the strand closest to your vector-DB interest.

## 2. BM25 ([Serving BM25 with 50% memory reduction](https://exa.ai/blog/bm25-optimization), May 2025)

**What Exa does:**
- **Compact postings.** Postings are grouped by term frequency, doc IDs are stored as gaps with varint encoding (≈1.3 bytes per doc instead of 4) and then zstd-compressed, all in one flat buffer. Single-occurrence terms are stored as just a doc ID.
- **Pruning.** Candidates come from the rarest query terms, with WAND-style pruning of docs that can't make the top results.
- **Result:** ~50% less memory and 10% lower latency.

**What we copy:** nothing at our scale. Memory isn't our problem.

**Where we go further:** two freshness insights.
- **Packed postings can't be edited in place.** This pushes toward a log-structured design: a compressed base segment, a small editable delta, and periodic merges. How often to merge is one of our cost-vs-staleness knobs.
- **Global-statistic drift.** BM25 scores depend on corpus-wide statistics (IDF, average doc length). As commits land, scores of chunks that *never changed* still shift. It's cheap to measure and probably worth reporting on its own.

## 3. exa-d, their data framework ([exa-d](https://exa.ai/blog/exa-d), Jan 2026). **Most transferable post.**

**What Exa does:**
- **Derived data as typed columns in a dependency graph.** Each page has dozens of derived artifacts (text → tokens → embeddings…), declared as columns with a dependency DAG. You declare *relationships*, not update steps.
- **Storage in fragments.** Data lives in Lance (the format behind LanceDB) on S3, in fragments: a "fragment" is a group of rows in one file. A fragment may be missing derived columns. One column of one fragment can be written or deleted without rewriting the rest.
- **Model upgrades are new versioned columns** (`embedding_v2`).
- **The executor "computes only what is necessary".** It compares the ideal state (every column filled) with the actual state. It doesn't matter whether a column is missing because the doc is new or because the model changed. *"Backfills and incremental updates follow the same codepath."*
- **Not described:** content hashing, how invalidation spreads downstream, what triggers a run, or any numbers.

**What we copy:** this becomes our architecture, run locally on LanceDB:
```
file → chunks → chunk_hash → { bm25_terms, embedding_vK } → summary_vM → dir_summary → hierarchy
                           → graph_edges
```

**Where we go further** (this is our system contribution):
- **Key every derived value by `(hash of its inputs, transform version)`**, the way Bazel, Nix and rust-analyzer's Salsa do. Invalidation then spreads downstream automatically.
- **Early cutoff.** If re-chunking gives the same hash, skip re-embedding. If a child summary didn't change, skip re-summarizing its parent. That *is* our "layered-lazy" update strategy.
- **Fair comparisons for free.** "Same codepath for backfill and incremental" makes full rebuild vs. incremental update a clean experiment.
- **Staleness measurement for free.** Lance keeps a version per commit, so we can query the index at commit *k* against ground truth at *k+n*.

## 4. Retrieval logic ([Composing a Search Engine](https://exa.ai/blog/composing-a-search-engine) Apr 2026, plus the [Latent Space podcast](https://www.latent.space/p/exa) Jan 2025, plus [Dynamic Highlights](https://exa.ai/blog/dynamic-highlights) Aug 2026)

### 4a. Pipeline (their orchestrator, Canon)
**What Exa does:** every query runs as a DAG with 20+ node types. The example config:
```
dense  retrieve top 50  ─┐
sparse retrieve top 30  ─┴→ RRF fuse (k=60) → authority reranker → relevance reranker
                                         → dedupe (same domain ×4 → 1) → safety → fetch → highlights
```
- A **freshness model** node "decides what to serve".
- A **router** sends queries to the right index.
- Indexes run in parallel and race; the losers are cancelled.
- **Every node is traced**, so they can answer *"why did query x fail to return url z?"*
- Budget is ~250ms.
- **Exa began as "end to end neural", with no keyword search; this 2026 pipeline is hybrid.**

**What we copy:** a "Canon-lite" for code:
- BM25 top-30 plus dense top-50, fused with RRF k=60.
- A **router** that tells a stack-trace or identifier query apart from a vague behaviour description.
- An **authority reranker** that favours central code: PageRank or in-degree on the call/import graph.
- A **relevance reranker** (cross-encoder or LLM).
- **Dedupe by file.**
- A **freshness node** that prefers recently changed or verified-fresh chunks.
- **Per-node tracing**, which doubles as our ablation tool ("why wasn't file Z returned?").

### 4b. How they train embeddings: "next-link prediction" (podcast)
**What Exa does:**
- Take text around a link on the web, hide the link, and train the model to predict which *document* the link points to. They've done it "billions of times".
- They call it "neural PageRank": people refer to the same popular page in many different ways, so the model learns relevance and popularity together.
- They then add synthetic data, supervised fine-tuning, and **LLMs as relevance labellers**.

**What we copy:** "next-reference prediction" for code. Fine-tune a small embedder on our GPU with a contrastive loss, using in-batch negatives plus BM25 hard negatives. Training pairs:

| Context (the "text around the link") | Target (the "linked document") |
|---|---|
| Call site with the callee name masked | Callee's definition |
| Import context | Imported module |
| Issue / PR text | Functions changed by the merged fix (closest to Exa's setup) |
| Commit message | Diff hunks |
| File A | Files that usually change together with A |

All pairs can be mined from git history and GitHub. **Exclude our evaluation repos** to avoid leakage.

**Where we go further:**
- **Temporal hard negatives.** Use older versions of the same function as negatives. The goal is embeddings that ignore harmless edits but move when behaviour changes, which ties the Exa objective to our freshness question.
- Neither Exa nor the code-retrieval papers we found do this.

### 4c. Highlights
**What Exa does:**
- *Old version:* chunk each page, embed the chunks, return the best ones per page.
- *Dynamic Highlights (2026):* join all retrieved docs into one and let a model pick the best tokens across *all* of them in one pass, under one budget.
- **Result:** −30% agent tokens and +2.1% quality.
- Their 2024 [highlights-server post](https://exa.ai/blog/scaling-our-highlights-server) is engineering lessons:
  - A Rust rewrite gave 4x throughput.
  - Python multiprocessing was stuck on the GIL.
  - Remember that CUDA is asynchronous, so synchronize before timing anything.

**What we copy (stretch):**
- Pick lines across all retrieved files jointly, under one token budget for the agent.
- Measure agent tokens saved and whether the gold function is still included.
- This also addresses our "the agent reads 50k tokens instead of 5k" goal.

### 4d. Other ideas worth borrowing
- **Variable compute.** Exa has fast Search vs. slow Websets. We'd have a fast path (hybrid + RRF) and a deep path (adds LLM reranking + graph expansion).
- **Query rewriting.** Exa advises searching "as if you're about to share the link you want". For code: rewrite the issue into "the code containing this bug would look like…" (a HyDE-style rewrite).
- **Long queries.** Exa expects agent queries to be paragraphs. Issues already are.

## 5. Evaluation ([WebCode](https://exa.ai/blog/webcode) Mar 2026, [RL outcomes](https://exa.ai/blog/rl-search-outcomes) May 2026, [people search](https://exa.ai/blog/people-search-benchmark), [Websets evals](https://exa.ai/blog/websets-evals), [publications](https://exa.ai/blog/publications-search))

### WebCode, what it is
Search evaluations for coding agents, over **web docs only, not local repos**. Four parts:

| Part | Size | What it tests |
|---|---|---|
| Contents | 250 URLs | Page-to-markdown extraction quality |
| Highlights | 250 | Snippets from inside a page for a query |
| RAG | ~307–317 | Very long docs; one question about a niche buried section |
| E2E | 33 | Coding tasks on libraries released after Aug 2025, with unit tests |

- **Public** under MIT at `github.com/exa-labs/benchmarks`. The Contents gold answers and E2E executors are not released.
- **Main finding:** answer *correctness* is about the same (~86%) whatever the provider, because it reflects the model writing the answer. Retrieval **groundedness** ("does the result contain the answer?") is what tells providers apart.

### Evaluation ideas we copy

| Exa method | Our version |
|---|---|
| Groundedness vs. correctness | Report "did retrieval return the gold file/function?" (Acc@k) separately from agent success. Also report citation precision (gold hits ÷ results returned) and tokens returned. |
| Parametric-memory filter: keep a question only if two frontier models fail it from memory over 3 tries | Keep a SWE-bench task only if a model, given just the issue and no repo, can't name the gold files. This handles contamination (models have seen Django). |
| Freshness by construction (E2E uses libraries released after a cutoff with ≥3 breaking changes) | A **hard-drift subset:** tasks whose gold functions were added, moved or renamed between the index commit and the query commit. |
| Stub-vs-solution check | Tests must fail before the fix and pass after it. SWE-bench FAIL_TO_PASS tests already do this. |
| Controlled swap, from the RL post: change only the search backend. Exa reached equal performance with 69% fewer tokens. | Keep the agent, prompts and budgets fixed; swap only the retriever (grep alone / BM25 / embeddings / summaries / graph, fresh vs. stale). Headline metric: **tokens and turns needed to reach equal success.** Also count empty-result rate, the rough equivalent of grep or a stale index finding nothing. |
| Two query types for publications: known-item vs. tip-of-the-tongue | Split issues into those that name exact identifiers or a stack trace and those with vague behaviour descriptions. Report Recall, MRR, latency ± std for each. |
| Statistics: 95% bootstrap CIs over 10k resamples; pass@k for k=1..50 | Same, plus repeated runs, since Exa's confidence intervals ignore run-to-run noise. |
| LLM judge with explicit criteria (Websets splits each query into binary criteria) | Only for fuzzy labels, e.g. "is this chunk relevant?" Gold patches give exact labels for the main metrics. |

**Reuse:** Exa's benchmark harness (fixed agent loop, swappable search provider) could take a local-index adapter.

### RL outcomes post, a continuation idea
- **Setup:** Qwen3-4B with LoRA, trained with GRPO for 100 steps, changing only the search backend.
- **Results:** a better retriever means more answers per search call (+10.7% relative), giving a denser learning signal. It helped no matter which engine was used at test time.
- **Code version (beyond this quarter):** RL-train a small coding agent with our index vs. grep alone.

---

## How this changes our plan
**Core this quarter**, cheap and high value:
1. **Architecture.** Use the exa-d-style column DAG on LanceDB, with hash-plus-version keys and early cutoff. These are the update mechanics we need anyway, now with a precedent to cite.
2. **Retrieval.** A Canon-lite hybrid: BM25 + dense, RRF k=60, file dedupe, graph-authority reranker, per-node tracing.
3. **Evaluation.** Groundedness vs. correctness, the parametric-memory filter, the hard-drift subset, the controlled-swap tokens-to-equal-success metric, bootstrap CIs, and the known-item vs. vague split.

**Pick one embedding research thread for this quarter** (needs a team decision):
- **(a) Next-reference prediction fine-tuning plus temporal hard negatives.** The most Exa-like option, uses the GPU, and could be a paper on its own.
- **(b) Exa-style vector DB replication (Matryoshka + binary + IVF) plus centroid-drift study.** The most vector-DB-like option, and less ML risk.

**Stretch / next quarter:** dynamic highlights for code, a learned freshness/router node, and RL-training an agent with our index.

**Blog framing:** "WebCode measures web search for coding agents. We measure search over *your own repo* while the code changes."
