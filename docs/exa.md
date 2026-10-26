# What we take from Exa

**Status:** research notes, exploratory. How codemem works is in [architecture.md](architecture.md).

Exa runs a web search engine for AI agents, and its blog is a model for both our techniques and
our write-up. We don't use Exa's product. This page merges two reading passes:
- **Oct 4, 2026:** 13 sources (the vector DB, BM25, exa-d, Canon, Highlights, WebCode, RL
  outcomes, the Latent Space podcast, …).
- **Oct 23, 2026:** all 47 blog posts (31 linked from the index, 14 only in the sitemap, 2
  unlisted), 24 Learn/SEO articles (spot-checked; no engineering content), and the external talks
  and podcasts.

How the ideas turn into research experiments is in [advanced-design.md](advanced-design.md).

> **Caveats.** The pages were read through an extraction model, so quotes are close to verbatim,
> not exact. Numbers marked *(chart)* were read off images and are approximate. Exa never discloses
> its embedding architecture, its loss, its reranker architecture or its near-duplicate detection.
> Those parts of our design have no Exa recipe to copy. Check anything before citing it.

---

## 1. The short version

- **Exa never writes about keeping an index fresh** as data changes, not even in exa-d. That is
  exactly our gap: search over *your own repo* while the code changes.
- **Its embedding objective has a natural code version.** "Next-link prediction" becomes
  "next-reference prediction" (call site → callee, test → function, issue → fixed function). This
  is the most Exa-like research thread available to us.
- **Its search pipeline is hybrid** (keyword + embeddings, merged with RRF, then reranked). Exa
  called hybrid "the most powerful search architecture" already in May 2025, so hybrid is not
  new; it is cheap to copy.
- **Its coding-agent benchmark (WebCode) covers web docs only.** Nobody has published one for
  searching your own repo as it changes. Ours would be "WebCode for your own repo".
- **Its evaluation tricks are cheap and make results credible:**
  - score retrieval separately from task success;
  - drop tasks a model can answer from memory;
  - change only the retriever between runs;
  - report bootstrap confidence intervals.

## 2. What codemem already uses

| Exa idea | Where in codemem |
|---|---|
| Hybrid: dense top 50 + keyword top 30, merged with RRF k = 60 | `search.py`: BM25, code and usage lists (top 50 each), RRF k = 60 |
| exa-d: compute only what is missing; derived data keyed by input hash and version | texts and vectors keyed by text hash and embedder key; the vector cache; epochs |
| exa-d: "backfills and incremental updates follow the same codepath" | one update function for first builds, full checks and single saves, with a verify mode |
| Model upgrades as new versioned columns | the embedder key: a new model re-embeds only its vector type |
| Highlights: return the part that matters | a first step: long-function cards show the best window, focused on the matching lines |
| Two-tier tools: search returns highlights, read returns full bodies | `search_code` + `get_chunk` |
| Instruction and scope parameters | the `path_prefix`, `kinds`, `languages` and tests filters |
| Collapse vendored and duplicate copies | vendored, generated and minified files skipped by default |
| Snapshot "as of a date" for leakage-free evals | the eval indexes each task at its commit (Andrew's harness) |
| Fixed-candidate paired bootstrap | Andrew's harness | done |

---

## 3. Notes by area

### 3.1 Vector database ([web-scale vector DB](https://exa.ai/blog/building-web-scale-vector-db), Dec 2024)

For billions of 4,096-number vectors in under 100 ms:
1. **Matryoshka truncation** to the first 256 numbers. The post says "20×"; 4,096 → 256 is 16×.
2. **Binary quantization:** 1 bit per number (sign(x)), another 16×.
3. **Asymmetric scoring:** documents binary, query in full float, scored by dot product rather
   than Hamming distance, which recovers precision.
4. **Lookup tables:** the query is split into 4- or 8-number pieces with precomputed dot
   products, kept in CPU registers, in C++.
5. **IVF instead of HNSW:** 100k clusters; a query searches its cluster and nearby ones. They avoid
   HNSW because its "global graph structure can't be partitioned easily". Shards are cut by
   cluster.
6. **Filtering** through inverted indexes before scoring.
7. **Reranking** of extra candidates with the full vectors. Documents are stored in fp16; > 500 QPS;
   10× cheaper than cloud quotes.

**For us:** at one repo's size (10k–1M vectors), exact search takes milliseconds, so this is the
compression study (RQ2), not a speed need. Our stored float16 vectors make it possible without
re-embedding. Freshness angle: IVF makes inserts cheap, while HNSW makes deletes awkward. As code
drifts, how much recall is lost by keeping old centroids?

### 3.2 BM25 ([50% memory reduction](https://exa.ai/blog/bm25-optimization), May 2025)

- Postings grouped by term frequency, doc ids gap-encoded as varints (about 1.3 bytes instead of
  4), zstd-compressed, in one flat buffer; 1.8 TB per 1B documents before optimizing.
- Candidates come from the rarest query terms, with WAND-style pruning. Result: about 50% less
  memory and 10% lower latency.

**For us:** memory is not our problem. "Candidates from the rarest terms" was the first thing we
tried for long queries, and it is a lesson: keeping only an issue's 32 rarest words cut keyword
accuracy by a third, because an issue's rarest words are often noise (versions, URLs, the
reporter's names). codemem drops stopwords only (architecture.md §6). Freshness angle: BM25 scores
depend on corpus-wide statistics, so chunks that never changed still shift as commits land.

### 3.3 exa-d, the data framework ([exa-d](https://exa.ai/blog/exa-d), Jan 2026): the most transferable post

- Derived data (text → tokens → embeddings → …) is declared as typed columns with a dependency
  graph. You declare *relationships*, not update steps.
- Data lives in fragments (row groups in Lance files on S3). One column of one fragment can be
  written without rewriting the rest. Fragment metadata is the only source of truth, with
  optimistic manifest commits and rebases.
- Model upgrades are new versioned columns (`embedding_v2`).
- The executor "computes only what is necessary": it compares the ideal state with the actual
  state. It doesn't matter whether a column is missing because the document is new or because the
  model changed: **"backfills and incremental updates follow the same codepath."**
- Checkpoint after each fragment, with convergence after partial failure. Ray actors keep the
  model loaded; the GPU embeds one fragment while the CPU tokenizes the next.
- **Not described:** content hashing, how invalidation spreads, what triggers a run, or numbers.

**For us:** this is our update architecture.
- Every derived value is keyed by the hash of its inputs and the version of the step that made it
  (as in Bazel, Nix, Salsa).
- An unchanged hash stops the work early (early cutoff).
- codemem's incremental update is one code path with a verify mode, which also makes full rebuild vs
  incremental a clean experiment.

### 3.4 The search pipeline ([Composing a Search Engine](https://exa.ai/blog/composing-a-search-engine), Apr 2026; [reranking](https://exa.ai/blog/sota-reranking), Oct 2026)

**Canon,** their orchestrator, runs each query as a DAG of 20+ node types:

```
dense top 50 ─┐
sparse top 30 ┴─► RRF (k=60) ─► authority reranker ─► relevance reranker ─► dedupe (same domain ×4 → 1)
                                                                          ─► safety ─► fetch ─► highlights
```

- A freshness node decides what to serve, and a router picks indexes.
- Indexes race; the losers are cancelled. The DAG is lazy and pull-based, with memoized diamonds
  and durable retry from the failed node, and the type checker rejects unhandled outcomes.
- Every node is traced, so they can answer "why didn't query x return z?". The budget is about
  250 ms; the example trace wins the index race at 80 ms and answers at 180 ms.
- A "TOKEN ANN worker group" in a figure is the only hint of token-level retrieval at Exa.

**Reranking:**
- On their coding set (317 long-context queries), reranking lifts nDCG@10 from 0.524 to
  0.66–0.77 (Voyage best at 0.771).
- **On navigational queries, every third-party reranker scored below the first-stage order**
  (0.30–0.45 vs 0.53). So a reranker must never move an exact hit.
- Protocol: the same candidates in the same order for every system, a stratified paired bootstrap
  (B = 10,000), and graded candidates with hard negatives (prompt injections, keyword stuffing).

**For us ("Canon-lite"):**
- BM25 + dense with RRF (done);
- a router that tells identifier and stack-trace queries apart from vague descriptions, with
  exact-lookup protection;
- an authority prior from the call graph;
- a small code reranker that never moves pinned exact hits;
- dedupe by file;
- per-node tracing (`why_not`) as our ablation tool.

### 3.5 Embedding training: next-link prediction (Latent Space podcast, Jan 2025; Cognitive Revolution podcast, Mar 2024)

- Hide a link on a web page and train the model to predict which document it points to,
  "hundreds of millions of times". The model predicts a document *embedding*, not URL tokens.
- People refer to popular pages in many ways, so the model learns relevance and popularity
  together ("neural PageRank").
- Then synthetic data, supervised fine-tuning, and LLMs as relevance labellers. Exa 2.0's model
  was pre-trained and fine-tuned for over a month on 144 H200s.
- Query formatting advice: write the text a link would follow ("search as if you're about to
  share the link you want").

**For us:** next-reference prediction with a contrastive loss, in-batch and BM25 hard negatives.

| Context ("text around the link") | Target ("linked document") |
|---|---|
| a call site with the callee name masked | the callee's definition |
| import context | the imported module |
| issue or PR text | the functions its merged fix changed (closest to Exa's setup) |
| a commit message | its diff hunks |
| file A | files that usually change with A |

Mine pairs from git history, excluding the eval repos. **Temporal hard negatives** (older
versions of the same function) are our own extension: embeddings that ignore harmless edits but
move when behaviour changes.

### 3.6 Highlights ([Dynamic Highlights](https://exa.ai/blog/dynamic-highlights), Aug 2026; [Highlights](https://exa.ai/blog/highlights-for-agents), Apr 2026)

- **Then:** chunk each page and return the best chunks per page.
- **Now:** join all retrieved docs and let a model pick the best tokens across all of them, under
  one budget. That gives −30% agent tokens and +2.1% quality. On long-context code QA it scores
  87.7 at ~2.45k tokens vs 81.0 at ~4.25k *(chart)*.
- **Size vs accuracy:** 500 characters of highlights match the first 8,000 characters of a page
  (about 90% on SimpleQA *(chart)*). On long technical docs it's 60% vs 6% for truncated text.
- "Reasoning traces take up more than half of the token usage", so a token saving must not
  trigger extra searches.
- Engineering: a Rust rewrite gave 4× throughput; Python multiprocessing was stuck on the GIL;
  synchronize CUDA before timing.

**For us:** pick lines across all results under one token budget, scored by gold-hunk coverage
and end-to-end tokens.

### 3.7 Evaluation (WebCode, How we do evals, ATLAS, RL outcomes, Snapshot, company search)

- **WebCode** (web docs only) has four parts: Contents (250 URLs), Highlights (250), RAG
  (~307–317 long docs), E2E (33 tasks on libraries released after Aug 2025). It's MIT-licensed at
  `github.com/exa-labs/benchmarks`. **Answer correctness is about 86% for every provider; retrieval
  groundedness is what separates them.**
- **How we do evals:**
  - fixed-corpus benchmarks have false negatives;
  - "dense embedding model performance decreases faster than sparse models' with respect to index
    size";
  - their LLM grader matched humans 97% (easy) and 83% (hard);
  - top-5 grading was enough: 5, 10 and 20 results ordered systems the same way.
- **ATLAS:** 547 tasks, only 9% answerable from memory (48–61% for other benchmarks).
  - A **censoring test** (remove the top 7 of every 10 results) keeps 52% of ATLAS's score vs
    81–89% elsewhere. That shows how much a benchmark really depends on search.
  - With the harness fixed, the search backend alone moves scores by 16%.
  - Tasks lose value after about 6 months.
- **RL outcomes:** Qwen3-4B with LoRA, GRPO for 100 steps, changing only the search backend. A
  better retriever means more answers per search (+10.7% relative). Exa reached equal performance
  with 69% fewer tokens.
- **Snapshot:** search the web as of a date, to stop leakage. The code version is indexing as of a
  commit.
- **Company search:** static facts are scored by exact match; dynamic facts need tolerance windows.

| Exa method | Our version |
|---|---|
| groundedness vs correctness | report "did retrieval return the gold function?" separately from agent success |
| memory filter | keep a task only if a model can't name the gold files from the issue alone |
| freshness by construction | a hard-drift subset: gold functions added, moved or renamed between the index commit and the query |
| controlled swap | keep the agent, prompts and budget fixed; swap only the retriever. Headline: tokens and turns to equal success |
| known-item vs tip-of-the-tongue queries | split issues that name identifiers or stack traces from vague ones |
| 95% bootstrap CIs, 10k resamples | the same, plus repeated runs |
| LLM judge with explicit criteria | only for fuzzy labels; gold patches give exact labels |

### 3.8 Product and latency notes

- **exa-code:** a code-example index with code-specific models. It returns "a few hundred tokens"
  of examples. Hallucination rate on completion tasks: 27.1% vs 33.8% (Exa Auto) and 45.9% (no
  retrieval) *(chart)*.
- **Exa Instant:** P50 178 ms *(chart)*. Latency is measured with random words appended to every
  query, to defeat caching.
- **Exa 3.0:** a larger embedding model, and Dynamic Highlights for everyone (95% fewer tokens than
  full text). It uses fewer searches per task than competitors: 7.6 vs 9.5–15.4.
- **Exacluster:** 144 H200 + 80 A100. Flyte hashes image, requirements and source, so tasks are
  reproducible, cached and resumable.
- **Deep, Agent:**
  - query expansion, parallel sub-queries and per-result verification;
  - "highlights guide the model to the right pages; full crawls back the final answer";
  - passing rows you already have excludes them from future results.
- **Variable compute:** a fast path (hybrid + RRF) and a deep path (adds reranking and graph
  expansion).

---

## 4. Transferable ideas, ranked

Gains and costs are estimates for one repo of 10k–100k functions on a laptop plus one GPU. ✔
marks what codemem already does.

1. **Anchor-context fields:** call sites, tests, prior commits and past issues as their own
   retrievers (advanced-design §2). ✔ first step: the usage text.
2. **A query router with exact-lookup protection:** stack frames, dotted paths, error strings (§3).
3. **Leakage-safe evaluation:** index as of a commit, an anchor cutoff, the censoring check (§9). ✔
   index as of a commit.
4. **A small code reranker that sees metadata,** never moving pinned exact hits (§3.3).
5. **Line highlights under one shared token budget,** scored by gold-hunk coverage (§6). ✔ first
   step: best-window cards.
6. **Next-reference contrastive fine-tuning with a Matryoshka loss** (§5).
7. **A Matryoshka-256 binary first stage with rescoring** (§7). ✔ enabled: vectors are stored at
   full size.
8. **Query-time staleness repair** (§8). ✔ catch-up before every search.
9. **Collapse vendored and duplicate code.** ✔ skipped by default.
10. **An internal-API hallucination benchmark** (§9).

Smaller ideas:
- **Representation:** several vectors per function (signature + doc, body, anchors); token-level
  scoring only at rerank.
- **Ranking:**
  - deprioritize decoys (injected "edit me" comments, keyword-stuffed docstrings, legacy copies);
  - at most N results per file;
  - session exclusion (`exclude_ids`);
  - racing signals.
- **Output:** examples instead of definitions for "how do I call X"; accept a compression change
  only if end-to-end tokens drop at equal success.
- **Memory and latency:** memory-mapped immutable base segments plus a small delta; IVF only at
  multi-repo scale.
- **Freshness:** a resident model with pipelined stages; kill-and-resume convergence (✔ epochs make
  it testable); separate refresh policies for static and dynamic fields.
- **Evaluation:** graded decoy sets, scale-sensitivity curves, an LLM judge for gold-patch false
  negatives (validated on about 100 hand labels), cold vs warm latency with cache-busting.
