# Ideas from Exa's blog for local code search

**Scope.** A full sweep of exa.ai/blog on Oct 23, 2026:
- 47 posts (31 linked from the index, 14 only in the sitemap, 2 unlisted)
- 24 Learn/SEO articles (spot-checked; no engineering content)
- the external talks and podcasts listed on the index

This extends `../EXA_NOTES.md` (Oct 4), which covered 13 sources. How the ideas feed our research
plan is in [advanced-design.md](advanced-design.md).

**Reading notes:**
- Numbers marked *(chart)* were read off an image and are approximate.
- Exa never discloses its embedding architecture, loss, reranker architecture or near-duplicate detection. Those parts of our design have no Exa recipe to copy.

---

## 1. Posts that matter for us (not in EXA_NOTES)

| Post | Date | What it teaches us |
|---|---|---|
| [Relevance isn't enough: reranking the web](https://exa.ai/blog/sota-reranking) | 2026-10-23 | See below |
| [Exa Highlights](https://exa.ai/blog/highlights-for-agents) | 2026-04-22 | See below |
| [exa-code](https://exa.ai/blog/exa-code) | 2025-09-25 | See below |
| [How we do evals](https://exa.ai/blog/evals-at-exa) | 2025-05-30 | See below |
| [ATLAS](https://exa.ai/blog/atlas-benchmark) + [another benchmark?](https://exa.ai/blog/another-search-benchmark) | 2026-10-08 | See below |
| [Exa Snapshot](https://exa.ai/blog/exa-snapshot) | 2026-09-17 | See below |
| [Exa 3.0](https://exa.ai/blog/exa-3) | 2026-10-19 | See below |
| [Exa Instant](https://exa.ai/blog/exa-instant) | 2026-02-12 | See below |
| [Exa 2.0](https://exa.ai/blog/exa-api-2-0) / [2.1](https://exa.ai/blog/exa-api-2-1) | 2025-10/11 | See below |
| [Exacluster](https://exa.ai/blog/meet-the-exacluster) | 2025-05-15 | See below |
| [Exa Deep](https://exa.ai/blog/exa-deep) / [Deep Max](https://exa.ai/blog/deep-max) / [Agent](https://exa.ai/blog/exa-agent) / [Agent Ultra](https://exa.ai/blog/exa-agent-ultra) | 2026 | See below |
| [Company search benchmarks](https://exa.ai/blog/company-search-benchmarks) | 2026-01-22 | See below |
| [Cognitive Revolution podcast](https://www.cognitiverevolution.ai/the-example-engine-how-exa-is-creating-the-ai-librarian-for-the-web-with-will-bryk-ceo-of-exa/) | 2024-03-05 | See below |

**Relevance isn't enough: reranking the web**
- Reranking lifts their coding set (317 long-context queries, top-50 from Exa Instant, 720-character extracts) from nDCG@10 0.524 to 0.66–0.77. Voyage is best at 0.771; Exa's own reranker gets 0.685.
- On navigational queries, every third-party reranker scored **below** the first-stage order (0.30–0.45 vs 0.53).
- Their protocol:
  - same candidates in the same order for every system
  - stratified paired bootstrap, B = 10,000
  - drop queries whose candidates are all one label
- Their freshness and authority sets use graded candidates: 2 strong, 8 mostly relevant, 20 hard negatives, 30 easy. The hard negatives include prompt injections and keyword stuffing.

**Exa Highlights**
- 500 characters of highlights equal the accuracy of the first 8,000 characters of a page (SimpleQA, about 90% vs 90% *(chart)*).
- On long technical docs, highlights score 60% vs 6% for truncated text at 500 characters *(chart)*.
- Computed per request, under 100 ms, not cached.

**exa-code**
- A dedicated code-example index with code-specific retrieval models. It returns "a few hundred tokens" of examples, or full docs when examples don't suffice.
- It is evaluated by hallucination rate on code-completion tasks: 27.1% vs 33.8% for Exa Auto and 45.9% with no retrieval *(chart)*.

**How we do evals**
- Fixed-corpus benchmarks have false negatives. "Dense embedding model performance decreases faster than sparse models' with respect to index size."
- "In training, the effective corpus size is determined by the batch size."
- Their LLM grader matched humans 97% (easy) / 83% (hard) after prompt iteration.
- Top-5 grading is enough: 5, 10 and 20 results gave the same ordering of systems.

**ATLAS and its companion essay**
- 547 tasks, of which 9% are answerable from memory (vs 48–61% for BrowseComp, WideSearch and DSQA).
- **Censoring test:** remove the top 7 of every 10 results, and ATLAS keeps 52% of its score; other benchmarks keep 81–89%. This shows how much a benchmark actually depends on search.
- With the agent harness fixed, the search backend alone moves scores by 16%.
- Tasks lose value after about 6 months (model training cycles).

**Exa Snapshot**
- `snapshotAsOf`: search the web as it was on a date, to stop eval and RL leakage. Code analog: index as of a commit.

**Exa 3.0**
- A larger embedding model; Dynamic Highlights made generally available (95% fewer tokens than full text).
- Fewer search queries per task than competitors: 7.6 vs 9.5–15.4 *(alt text)*.

**Exa Instant**
- P50 178 ms *(chart)*.
- Latency method: random words appended to every query, to defeat caching.

**Exa 2.0 / 2.1**
- Embedding model pre-trained and fine-tuned for over a month on 144 H200s.
- "Lexical compression", "assembly optimizations"; "semantic+lexical databases from scratch".

**Exacluster**
- 144 H200 + 80 A100.
- Flyte hashes image, requirements and source code, for reproducible, cached, resumable tasks.

**Exa Deep, Deep Max, Agent, Agent Ultra**
- query expansion plus parallel sub-queries plus per-result verification
- "highlights guide the model to the right pages; full crawls back the final answer"
- passing rows you already have excludes them from future results
- row-level F1 (stricter than cell-level)

**Company search benchmarks**
- Static facts are scored by exact match; dynamic facts need tolerance windows and refresh.

**Cognitive Revolution podcast**
- The training objective, stated most concretely: hide the link and predict which page follows, "hundreds of millions of times".
- The model predicts a document *embedding*, not URL tokens.
- A "neural PageRank" quality prior.
- Query formatting: write the text a link would follow.

## 2. Details EXA_NOTES missed in the posts it covered

**Web-scale vector DB**
- Documents are fp16, at > 500 QPS and under 100 ms.
- Binarization is sign(x).
- Lookup tables use **4- or 8-dim** sub-vectors and are written in C++.
- Shards are cut by cluster.
- The DB is 10× cheaper than cloud quotes.
- A multi-stage scoring query language already existed in 2024.

**BM25**
- 1.8 TB per 1B documents before optimization.
- Term frequencies fit a 2-byte bitmap.
- A `doc_id+1` encoding makes a zero byte work as a separator.
- 8-byte `(offset, len)` posting pointers.
- **Exa called hybrid "the most powerful search architecture" already in May 2025.** Hybrid is not new in 2026.

**Composing a Search Engine**
- Lazy pull-based DAG, cascading cancellation, memoized diamonds, durable retry from the failed node.
- The type checker rejects graphs with unhandled outcomes.
- Several pipeline items appear **only in figures**:
  - same domain ×4 → 1
  - safe search
  - authority-weighted ranking
  - query enrichment emitting `filter(dateRange, includeText)`
  - a **"TOKEN ANN worker group"**: the only hint of token-level retrieval at Exa
- Example trace: the index race is won at 80 ms, the response comes at 180 ms.

**Dynamic Highlights**
- On "Long-context code QA": 87.7 at ~2.45k tokens vs 81.0 at ~4.25k for standard highlights *(chart)*.
- "Reasoning traces take up more than half of the token usage", so a token saving must not trigger extra searches.

**exa-d**
- Each column of each fragment is its own file; fragment metadata is the only source of truth.
- Optimistic manifest commits, then rebase.
- Checkpoint after each fragment, with convergence after partial failure.
- Ray actors keep the model loaded.
- The GPU embeds one fragment while the CPU tokenizes the next.

## 3. Transferable ideas, ranked

Gains and costs are estimates for one repo of 10k–100k functions on a laptop plus one GPU. ✔ marks what v2 already does.

### Top 10
1. **Anchor-context fields:** call sites, tests, prior commits, past issues as their own retrievers (advanced-design §2).
2. **Query router with exact-lookup protection:** stack frames, dotted paths, error strings (§3).
3. **Leakage-safe evaluation:** index as of a commit; anchor cutoff; censoring check (§9).
4. **A small code reranker that sees metadata**, never moving pinned exact hits (§3.3).
5. **Line highlights under one shared token budget**, scored by gold-hunk coverage (§6). ✔ first step: best-window cards.
6. **Next-reference contrastive fine-tuning with a Matryoshka loss** (§5).
7. **Matryoshka-256 binary first stage plus rescoring** (§7). ✔ enabled: vectors stored at full dimension.
8. **Query-time staleness repair** (§8).
9. **Collapse vendored and duplicate code.** ✔ vendored, generated and minified files skipped by default.
10. **Internal-API hallucination benchmark** (§9).

### By area

**Representation**
- several vectors per function: signature+doc, body, anchors
- token-level scoring only at rerank (Exa's "token ANN" figure)
- format queries like anchors: let the calling agent fill `as_commit` / `as_code` / `identifiers`

**Ranking**
- authority and decoy handling: deprioritize injected "edit me" comments, keyword-stuffed docstrings, legacy copies
- ✔ diversity: at most N results per file
- session exclusion (`exclude_ids`)
- racing signals with cancellation
- per-node tracing (`why_not`)
- instruction and scope parameters (globs, `exclude_tests`) ✔ partly: kinds, languages, test weight

**Output**
- two-tier tools (search returns highlights; read returns full bodies) ✔ `search_code` + `get_chunk`
- examples instead of definitions for "how do I call X" queries
- accept a compression change only if end-to-end tokens drop at equal success

**Memory and latency**
- memory-mapped immutable base segments plus a small delta
- token-vector compression only if token vectors are precomputed
- IVF only at multi-repo scale

**Freshness**
- resident model with pipelined stages
- ✔ kill-and-resume convergence: epochs make it testable
- static vs dynamic fields with separate refresh policies

**Evaluation**
- fixed-candidate paired bootstrap ✔ (Andrew's harness has the paired bootstrap)
- graded decoy sets
- scale-sensitivity curves
- an LLM judge for gold-patch false negatives, validated on about 100 hand labels
- ability-split query sets
- cold vs warm latency with cache-busting
