# Advanced design: where codemem goes after the baseline

**Status:** proposal only. Nothing here is implemented. It builds on the v2 baseline
([architecture.md](architecture.md), [data-model.md](data-model.md)) and is evaluated with
Andrew's harness (`eval/`).

**Inputs:**
- a sweep of all 47 Exa blog posts (Oct 23, 2026), adding to the earlier `EXA_NOTES.md`
- the multi-vector and code-retrieval literature up to Oct 2026
- the dev50 results of the MVP
- what the v2 work showed

Numbers from papers are as reported there; anything marked *(est.)* is my own arithmetic.

---

## 0. The short version

Six research directions, ordered by expected gain for the cost. Each has a cheap first
experiment that runs on the M1 laptop, and a decision gate before the expensive part.

| # | Idea | Plain words | RQ | First experiment (cheap) |
|---|---|---|---|---|
| 1 | **Anchor text for code** | describe a function by what its callers, tests, commits and past issues say about it | RQ1a | add call-site lines and pre-cutoff commit messages to `usage`, ablate each source |
| 2 | **Query routing + exact-lookup protection** | when an issue names a file, function or error string, look it up exactly; only use "meaning" search for the vague rest | RQ1d | a stack-trace / identifier extractor as a new RRF signal |
| 3 | **Many vectors per function** (your multi-vector intuition) | stop squeezing a whole function into one vector; let each query word find its best match inside the code | RQ1 (new) | windows on/off ablation (exists), then an off-the-shelf code ColBERT as an extra signal |
| 4 | **Train on the repo's own links**, then distill | Exa's "next-link prediction" for code: learn from call sites → callee, test → function, issue → fixed function | RQ1b | LoRA on 0.5B with mined pairs from repos outside the eval set |
| 5 | **Highlights under one token budget** | give the agent the 10 lines that matter, not the 80-line function | RQ2 (tokens) | v2's focused previews, scored by gold-hunk coverage |
| 6 | **Cheap index** | Exa's vector recipe: shorter vectors, 1 bit per number, re-check the top | RQ2 (cheap) | dims × int8/binary × rescoring grid, from v2's stored float16 vectors (no re-embedding) |

Two warnings frame everything:

1. **Exa's experience and the code-localization literature agree.** The biggest measured gains
   come from **training on the right task** and from **reranking**, more than from the shape of
   the representation:
   - Fine-tuning on issue → function pairs takes Qwen3-Embedding-0.6B from 62.8 to 75.2 function Acc@10 on SWE-bench Lite. An untuned 8B model gets 65.2 on Verified, versus 71.8 for a tuned 0.6B (SweRank, SweRank+).
   - Reranking lifts Exa's code set from nDCG@10 0.524 to 0.66–0.77.

   So idea 3 is exciting and novel, but ideas 1, 2 and 4 are the safer wins.
2. **Generic rerankers can hurt exact lookups.** On Exa's navigational set, every third-party
   reranker scored *below* the first-stage order (0.30–0.45 vs 0.53). Any reranker we add needs
   the exact-lookup protection of idea 2.

---

## 1. Where the baseline loses

**What dev50 says about the MVP** (Andrew's run, 50 SWE-bench Verified tasks, Python):

- **Usage text is the largest single gain.** Function MRR goes 0.334 → 0.423 (bm25+code → +usage). The anchor-text idea already works in its crudest form: callers' *names* only.
- **When the issue names no gold identifier,** codemem (MRR 0.346) beats the dev-tuned grep baseline (0.188) by a wide margin. When it names one, they are close (0.488 vs 0.424). This is where routing (idea 2) should help, and where an exact lookup should win outright.
- **Function-level all-gold success@10 is 0.37.** Published untuned 0.5–0.6B embedders reach about 0.60 Acc@10 on Verified. The harnesses differ (corpus, test files, metric details), so this is not a like-for-like gap. Still, it says the baseline is far from what a tuned retriever can reach (0.72 at 0.6B, 0.76 at 8B, about 0.80 with a reranker).
- **Indexing cost is real.** Embedding takes 99% of index time (django about 9 minutes on an M-series GPU). Updates between distant commits re-embed most of a repo when formatting changes (django's 2022 `black` reformat).

**What building v2 showed:**

- **Non-target code crowds results.**
  - On the fixture, a test helper class (`FakeUser`) became a callee of the test that mentions "disabled user". It took rank 2, and `revoke_session` fell from 4 to 7.
  - On `requests`, exception classes (`ConnectTimeout`, `RetryError`) outrank `HTTPAdapter.send` for "retry a request when the connection fails".
  - Down-weighting tests or showing only functions restores the order. On 13 dev tasks, halving the scores of tests, classes and blocks made 4 tasks better at function level and none worse, so it is now the default ([baseline-v2-diff.md](baseline-v2-diff.md) §5.3).
- **Long issues are noisy queries.**
  - Median issue length on dev50 is 1,444 characters, and the longest is 24,769 (stack traces, logs, code).
  - BM25 ORs every token, and the embedder truncates the query at 1,024 tokens.
  - Ideas 2 and 3 (query-side compression) both target this.

**What the 13 local dev tasks show, task by task** (v2 default; numbers in
[baseline-v2-diff.md](baseline-v2-diff.md) §5.3).

- Of 12 tasks with function gold, v2 puts a gold function in the top 10 for 8, and every gold function for 7 (success@10 0.583).
- The 4 misses (seaborn-3069, flask-5014, pytest-5787, pytest-7324) and one near-miss (pytest-10081) fall into four patterns. Each points at an idea below.

| Pattern | Tasks (rank of the first gold function) | What happened | Idea that targets it |
|---|---|---|---|
| **The issue names the fix site, and retrieval still misses it** | seaborn-3069: the issue says *"Probably straightforward to do in `Plotter._finalize_figure`"*, a gold function. It is not in the top 50 of v2, and not in BM25's either. pytest-7324: the reproducer calls `Expression.compile("False")`, in the gold file. It ranks 16. | In an issue of 1,187 characters, BM25 splits the dotted name into common words (`plotter`, `finalize`, `figure`), and the dense query is about scales. | Idea 2: route dotted names, stack frames and error strings to an exact symbol lookup that fusion cannot bury. |
| **The issue describes a symptom; the fix sits elsewhere** | seaborn-3069: `Nominal._setup` ranks 2, but the fix is in its caller `Plotter._setup_scales` (rank 48). pytest-5787: the chained-exception *display* code ranks top, but the fix is in report *serialization* (`BaseReport._to_json` / `_from_json`, not in the top 50). pytest-7324: the issue is about a compiler crash; the fix is in the parser's `not_expr`. | The retriever finds the code that the issue talks about. The fix is in a caller, a producer or a serializer of that code. | Idea 1: anchors, i.e. what callers and tests say about a function. Also a 1-hop expansion of the top hits along call edges (the callers of `Nominal._setup` include `Plotter._setup_scales`), and the reranker of idea 2. |
| **Tests that reproduce the issue outrank the code** | pytest-10081: three `test_unittest.py` tests took ranks 1, 3 and 5. Without weights the gold `TestCaseFunction.runtest` ranked 16; with tests ×0.5 it ranks 7. pytest-5787: 4 of the top 6 were tests. | A reproducing test shares the issue's words and code snippets. | Tests ×0.5 (now the default). Idea 1 treats a test as an anchor of the code it calls, not as a competitor. |
| **The class and its siblings compete with the method** | flask-5014, *"Require a non-empty name for Blueprints"*: the class `Blueprint` ranked 1 and three of its methods 2–4. The gold `Blueprint.__init__` ranked 24 without weights and 17 with classes ×0.5. | The skeleton and every method match "Blueprint". Nothing says the check belongs in the constructor. | A reranker that reads the code (idea 2); several vectors per function (idea 3), so a long constructor is matched by its validation lines. |

Two cautions:
- These are 13 tasks from small repos. The full dev50 will show whether the same patterns dominate.
- The first pattern is the cheapest to fix: exact lookup needs no model. It is also where a tuned grep baseline is strongest, so it is the first thing to build (§11).

---

## 2. Anchor text for code (idea 1)

### 2.1 In plain words

On the web, the words people write when linking to a page often describe it better than the
page itself ("the best essay on fundraising" → paulgraham.com/...). Exa built its search engine
on this: it trains a model to predict the linked page from the text around the link, hundreds
of millions of times (Cognitive Revolution podcast, 2024; Latent Space, 2025).

Code has links too: **calls, tests, commits and issues**. `revoke_session` says nothing about
"disabled users". But `disable_user` calls it, `test_disabled_user_loses_sessions` tests it, and
a past commit "Fix sessions surviving account deactivation" touched it. Those texts are its anchor text.

### 2.2 What to add (in order of cost)

The MVP's `usage` text has caller and test *names*. Proposed anchor fields, each its own
vector type and BM25 field (`data-model.md` §11: a new vector type is just a new text builder):

| Field | Content per function | Leakage rule |
|---|---|---|
| `callsites` | the caller's signature + the 3 lines around each call site (up to 20 diverse callers) | current snapshot only |
| `tests` | names + assert lines of tests that reach the function (directly or via one hop) | current snapshot only |
| `commits` | subjects (+ first body line) of commits that changed the function's lines, mapped via `git log -L` or hunk→span mapping | **only commits before the indexed commit** |
| `issues` | titles of past issues whose fix PR changed the function | **only PRs merged before the task's base commit**; issues from the eval tasks themselves are excluded |

The `issues` field is the most Exa-like, and the most powerful in principle. It describes a function in the
**same language as the query**: issue language, not code language. It is also the most dangerous
for leakage. That's why it is keyed by the eval's own freshness cutoff, and checked with Andrew's
leakage checks.

### 2.3 How to index anchors

- **Several anchors per function are naturally multi-vector.** Embed each call site separately and score the function by its best-matching anchor (max), or by MaxSim over anchors. v2's table already holds several parts per chunk (`data-model.md` §5.3).
- **Popularity bias.** Utility functions have thousands of callers. Cap and diversify: different files first, de-duplicated call lines, at most 20 per field. Report results split by caller count.

### 2.4 Experiments

- **Ablation ladder on dev50:** `usage` (names, today) → `+callsites` → `+tests` → `+commits` → `+issues`. Report function MRR, R@10 and tokens.
- **Splits:**
  - by `identifier_in_query`: the hypothesis is that anchors help most when the issue names nothing
  - by caller count
- **Cost:** call sites and tests are local and cheap. Commits need one `git log` pass per repo snapshot. Issues need the GitHub API (Andrew's collection pipeline already fetches PRs).

---

## 3. Query routing and exact-lookup protection (idea 2)

### 3.1 In plain words

Some issues contain the answer's address: a traceback line `File "django/db/models/query.py",
line 1203, in _filter_or_exclude`, a dotted path, an exception class, a quoted error message.
For those, an exact lookup beats any similarity search. For vague issues ("Disabled users stay
logged in"), meaning-based search is the only option. Exa routes queries to different indexes
and protects navigational queries from rerankers that would bury the exact hit.

### 3.2 Design ("Canon-lite")

```
issue ─► extract: stack frames (path, line, function), dotted names, identifiers in backticks,
         quoted error strings, exception types, config keys
      ─► signals:  exact_path_line  exact_symbol  phrase(error string)  bm25  code  usage  anchors
      ─► RRF  (exact signals weighted high; an exact unique hit is pinned to rank 1)
      ─► optional reranker on the rest (never moves pinned hits)
```

- **New RRF signals.**
  - `trace`: the chunk containing each stack-frame line, frames nearest the error first.
  - `symbol`: chunks whose qualname equals an extracted identifier.
  - Both are cheap SQL lookups on data v2 already has (`find_chunk_at`, `chunks_name`).
- **Query-side compression for long issues:**
  - drop log noise (timestamps, hex addresses)
  - keep the first and last frames of long tracebacks
  - embed the title and the body separately and fuse them (a cheap multi-query)

### 3.3 Reranker (after routing works)

- **A small cross-encoder**, or a small LLM, scores the top 30–50 with metadata in the input: path, qualname, signature, a 720-character extract, `is_test`, kind.
- **What the evidence says:**
  - Exa's code set gains 0.13–0.25 nDCG@10 from reranking.
  - SweRankLLM-Small (7B) lifts Verified Acc@10 from 71.8 to 79.4.
  - A 0.6B reranker (Qwen3-Reranker-0.6B) scores *below* its own embedder on MTEB-Code, so size matters.
- **Placement:**
  - On a laptop, a 0.6–1.5B reranker on 30 candidates is feasible (about 1–2 s on MPS, est.).
  - The deep path uses an LLM listwise reranker (or delegates to the calling agent).

### 3.4 Other pipeline ideas from Exa

| Idea | Code version | Cost |
|---|---|---|
| Dedup "same domain ×4 → 1" | collapse vendored or duplicated copies (MinHash on normalized bodies); at most 2 results per file in the top 10 | low |
| Session-aware exclusion (Exa Agent Ultra) | `exclude_ids`: don't return what the agent already read this session | trivial |
| Deep path (Exa Deep: parallel sub-queries + verification) | 3–8 sub-queries → fast path each → RRF → verify top 20 | medium (LLM calls) |
| Per-node tracing (Canon) | `why_not(query, path)`: which signal ranked a chunk where, and what cut it | low |
| Instruction field (MAIR's `Instruct:`) | agent passes constraints ("only in the CUDA kernels") to filters and the reranker | low |

---

## 4. Many vectors per function (idea 3: your multi-vector intuition)

### 4.1 In plain words: why one vector is lossy

Today a whole function becomes one list of 896 numbers. That list has to say everything the
function does: its name, its loops, its error handling, the one line that clears sessions. A query
about one detail must match the *summary* of the whole function. For short functions that's
fine. For long ones the detail is averaged away. This is your intuition, and the theory
agrees: ME-BERT (Luan et al. 2021) shows that a single vector's margin shrinks as documents grow,
so long documents need more dimensions or more vectors.

The alternative is to keep **one vector per token** (or per line, or per small group of
tokens):
1. The transformer reads the whole function once. Self-attention lets every token look at every other token. That is the "cross-attention across the n words" you describe, and it already happens inside the model.
2. So each token's output vector is contextualized: the vector for `delete` in `db.sessions.delete(session_id)` knows it is about sessions.
3. Then, at search time, **each query word looks for its best-matching code token**, and the function's score adds up those best matches.

This is **late interaction** (ColBERT), and the score is called **MaxSim**.

### 4.2 How to score many vectors

Notation:
- query token vectors `q_1..q_n`
- code token vectors `d_1..d_m`
- similarity `s_ij = q_i · d_j`

| Scoring | Formula | What it does | Verdict |
|---|---|---|---|
| average of everything | `(1/nm) Σ_i Σ_j s_ij` | **mathematically equal to `mean(q) · mean(d)`**, i.e. one vector per side again | useless: storing token vectors buys nothing |
| weighted average with fixed weights | `Σ a_i b_j s_ij = (Σ a_i q_i) · (Σ b_j d_j)` | still one vector per side | useless for the same reason |
| max over everything | `max_ij s_ij` | one strong match decides | too brittle |
| **MaxSim** | `Σ_i max_j s_ij` | every query word finds its best match, then the matches add up | the standard; use it |
| IDF-weighted MaxSim | `Σ_i w_i max_j s_ij`, `w_i` = query-token importance | rare query words count more | small gains (+1–4% R@10 on BEIR); likely more for long noisy issues *(hypothesis)* |
| soft MaxSim | `Σ_i τ log Σ_j exp(s_ij / τ)` | τ→0 is MaxSim, large τ is averaging | more robust to decoy tokens, worse on clean data |
| top-k MaxSim | mean of the k best `s_ij` per query word | between max and average | robust to long documents; k = 2–4 |

**The key point for your question ("max dot product or weighted average?").** An average only
helps if its weights depend on the *pair* (query word, code token), as softmax or max weights do.
With fixed weights it collapses back to a single vector. So the answer is **max, summed over
query words**. The open choice is how to weight the query words, which matters for long issues.
All variants can be swept at search time over the same stored vectors. Gains are larger when the
scoring function is also used in training.

### 4.3 Your "fine-tuned 8B with cross-attention over n base embeddings", mapped to what exists

Your description has three possible readings. Each exists in some form, and each leaves a gap
for us.

| Reading | What it is | Closest prior work | What is open |
|---|---|---|---|
| A. n tokens → an 8B model → store all n vectors | ColBERT with a big backbone | jina-embeddings-v4 (128-d multi-vector head), CRISP (Gemma-2B) | nothing on issue → function localization; storage (below) |
| B. m learned "query slots" cross-attend over the n token vectors → store m vectors (m ≪ n) | learned pooling: a fixed small set of vectors per function | Poly-encoder codes; Set Transformer pooling (PMA); ConstBERT; MetaEmbed; **FLINT** (Perceiver-style latents, MaxSim, index 5–9× smaller than ColBERTv2, Oct 2026) | none evaluated on code localization; **pooling seeded by code structure**; repo context as extra keys; nested budgets per function length |
| C. the query and the code attend to each other | a cross-encoder reranker | SweRankLLM, Qwen3-Reranker, jina-reranker-v3 | not precomputable, so it reranks only the top 30–50 (idea 2) |

**The 8B question, concretely** *(est.: 2 × non-embedding params FLOPs per token, 30M tokens for a 100k-function repo)*:

| Embedder | H100 | A100 | M1 laptop |
|---|---|---|---|
| 0.5B (today) | ~1–3 min | ~3 min | hours (our measurement: ~4.7 texts/s on MPS fp16 for `requests`) |
| 1.5B | ~3 min | ~10 min | many hours |
| 8B | ~17 min | ~1 h | does not fit in 16 GB at fp16 |

**Storing raw 8B token states is impossible.** 100k functions × 300 tokens × 4096 dims × 2 bytes ≈ 246 GB.
So the 8B model's role is **teacher**: score (issue, function) pairs, and distill those scores
into a small multi-vector student (a 0.5–1.5B backbone with a 128-dimension token head) that
runs locally.

### 4.4 The proposed novel piece: structure-seeded pooled late interaction

This makes reading B specific to code, and it is the part no one has published:

1. A small backbone (jina-code-0.5B or 1.5B) reads the function once and gives n token states.
2. **Seeds from the syntax tree.** Instead of m generic learned latent vectors (FLINT), start the m pooling queries from code structure:
   - one for the signature
   - one per top-level statement block
   - one for the identifiers it calls
   - plus a few free latents
3. **Repository context as extra keys.** The pooler may also attend to the anchor texts of section 2 (call-site lines, test asserts). The function's vectors then encode how it is used, not only what it says.
4. **Nested budgets.** Train with m ∈ {4, 8, 16, 32} nested (Matryoshka over the number of vectors). A function then gets more vectors when it is longer, and the index chooses its own storage/accuracy point.
5. **Score** with MaxSim (IDF-weighted on the query side). **Compress** the query side too: a 3,000-token issue becomes ~32 query vectors (FLINT shows that query-side pooling cuts search time per query token by about 80×).
6. **Train** in two stages:
   - contrastive: issue → fixed function, with hard negatives
   - KL distillation from an 8B teacher's scores (the ColBERTv2 / PyLate recipe)

*Hypothesis:* on long functions and long issues, this beats a single vector of the same backbone
at equal bytes per function. *Decision gate below.*

### 4.5 A free bonus: line highlights

MaxSim tells you **which code token** each query word matched. Map tokens to lines and you get
the lines of the function that the query is about, with no separate highlight model. That
connects idea 3 to idea 5: Exa's Dynamic Highlights (500 characters ≈ 8,000 characters of text in answer quality).

### 4.6 Storage and speed for 100k functions (~300 tokens each)

| Representation | Storage | Query cost | Training |
|---|---|---|---|
| single vector, 896-d fp32 (MVP) | 358 MB (fp16 179 MB) | ms | none |
| windows, max over parts (v2) | ~1.1–1.4× the above | ms | none |
| per token, 128-d fp16 | ~7.7 GB | brute force ~2 TFLOP per long issue; PLAID tens of ms | token head needed |
| per token, ColBERTv2 2-bit residuals | ~1.1 GB | PLAID: ~30 ms on 8 CPU threads at 8.8M passages | token head needed |
| + token pooling ×2 (post hoc) | ~0.54 GB | about half | none (≈100% retained at ×2) |
| fixed 32 vectors × 128-d, 2-bit (pooled, §4.4) | ~115 MB | ~26 GFLOP brute force | pooler needed |
| MUVERA single-vector encoding + exact rerank | ~128 MB + multi-vectors on disk | single-vector speed | none |

**Update cost is the same as today in every row.** One changed function means re-encoding that
function. PLAID-style centroids drift as code changes. *How much recall stale centroids lose
over a repo's history* is itself a small, publishable freshness question (it ties to RQ3).

### 4.7 Experiments and gates

| Step | Where | What | Gate |
|---|---|---|---|
| E-A0 | laptop, **now** | `cm2-no-windows` vs `cm2-bm25-code-usage` (window ablation, config exists), split by function length | does one-vector-per-function hurt long gold functions? |
| E-A1 | laptop | window scoring sweep: max vs top-2 mean vs sum; window size 1k/3k/6k chars | best cheap multi-vector |
| E-A2 | laptop | off-the-shelf code ColBERT (LateOn-Code 149M via PyLate) as (a) a 4th RRF signal, (b) a rerank-only stage over the hybrid top 200 | if < +2 function MRR points, multi-vector is not our main bet |
| E-A3 | GPU | controlled training: same backbone, same data; single vector vs token MaxSim vs pooled m ∈ {4..32}, **at equal bytes per function** | if multi-vector < +3 Acc@10 points on Verified + fresh, focus on ideas 1, 2, 4 |
| E-A4 | GPU | the structure-seeded pooler (§4.4) vs FLINT-style free latents vs ConstBERT | the novel result |
| E-A5 | GPU | 8B teacher (Qwen3-Embedding-8B or a LoRA-tuned 8B) → distill into the 0.5–1.5B student | does distillation close most of the 8B gap locally? |

**Caveat to test early:** causal (decoder) multi-vector encoders show a length bias toward
longer chunks (ECIR 2026 workshop). Function lengths are heavy-tailed, so check the bias on
our data before training.

---

## 5. Train on the repo's own links, then distill (idea 4)

### 5.1 In plain words

Exa trains its embedder by hiding a link and predicting which page it points to. In code, we can
hide a call and predict which function it calls, or hide which function a test checks, or which
functions an issue's fix changed. These pairs come for free from git history and the call
graph, and they are exactly the task an agent has.

### 5.2 Training pairs

| Context (the "text around the link") | Target (the "linked page") | Source |
|---|---|---|
| call site, callee name masked | callee definition | call graph |
| test function | function under test | call graph + test detection |
| commit message | functions it changed | git history (before the cutoff) |
| issue title + body | functions the fix changed | GitHub (before the cutoff), plus public sets (SWE-Gym, SWE-smith, SWE-rebench) for repos **outside** the eval |

### 5.3 Recipe

- **Loss:** InfoNCE with in-batch negatives plus hard negatives:
  - same-file siblings
  - same name in another module
  - BM25 top-k non-gold
  - **older versions of the same function** (temporal negatives: the embedding should move when behaviour changes, not when formatting changes)
- **Matryoshka loss** at {64, 128, 256, full} dims (links to idea 6).
- **Larger effective batch** with GradCache. Exa: "in training, the effective corpus size is determined by the batch size".
- **LoRA** on jina-code-0.5B or 1.5B. Published budgets: jina-code-0.5B trained 8.3 h on 4×A100; CoRet 24 h on 8×A10G. A per-repo LoRA should be 1–2 GPU-hours *(est.)*.
- **Two arms:**
  1. cross-repo training (generalization)
  2. per-repo adaptation (does a repo's own history help on its future issues?)

  Hold out whole repos. Mix in general data so small repos don't overfit.

### 5.4 Risks

- **Leakage:** pairs must come only from before each task's base commit, and never from eval tasks.
- **Overfitting to SWE-bench-like repos:** test on fresh big repos (vLLM, Kubernetes), per Andrew's design.
- **Licensing:** SweRankEmbed is CC-BY-NC, so ship our own fine-tune of an Apache/MIT base.

---

## 6. Highlights under one token budget (idea 5)

### 6.1 In plain words

An agent pays for every token it reads. Exa found that 500 characters of well-chosen highlights
answer as well as 8,000 characters of page text (SimpleQA). On long technical docs: 60% vs 6% at
500 characters. Their Dynamic Highlights picks tokens across *all* results under one budget, with
95% fewer tokens than full text.

### 6.2 What v2 already does, and what comes next

- **v2:** a long function's card names its best window (`best 245-302`) and shows the lines around the one sharing the most query words.
- **Next:**
  1. score every line of the top-k by query-token overlap plus (later) MaxSim alignment (§4.5)
  2. allocate one line budget across all results (softmax over the fused scores; always keep signatures)
  3. skip lines repeated across results
- **Measure** with Andrew's token metrics (`recall@budget`, `tokens_to_first`), plus a new **gold-hunk coverage**: the share of the patch's changed lines that the shown lines include.

---

## 7. Cheap index (idea 6, RQ2)

**Exa's recipe** (web-scale vector DB post):
1. keep the first 256 dims (Matryoshka)
2. 1 bit per number
3. float query × binary documents
4. rescore the top results with full vectors

Plus IVF clusters instead of HNSW, and filtering before scoring. Their lookup-table scoring uses
4- or 8-dim sub-vectors in registers.

**v2 makes this cheap to study.** Every vector is stored once at full dimension (float16), and
FAISS is derived. So the whole grid runs from one embedding pass:

| Axis | Values |
|---|---|
| dims | 64, 128, 256, 512, full |
| precision | fp16, int8, binary (float query) |
| rescoring | none, top-100, top-500 with fp16 |
| index | flat, IVF (√N lists), HNSW |

- **Expect:** SweRank's Matryoshka table (fine-tuned 0.6B) loses about 1 point at 512 dims, 5.5 at 256 and 15 at 64. Without fine-tuning the loss is larger, which is why idea 4 trains with a Matryoshka loss.
- **Extras:**
  - a static first pass (potion-code, a 16M-parameter lookup model) that proposes candidates for the transformer, on CPU-only laptops
  - IVF for Linux-scale repos (~1M chunks), plus the centroid-drift question of §4.6

---

## 8. Freshness ideas (RQ3)

| Idea | Source | What it gives |
|---|---|---|
| Query-time staleness repair | Exa highlights are computed live | if a hit's file changed since indexing, re-parse it (ms) and return correct lines, flagged `stale_embedding` |
| Resident-model daemon with pipelined stages | exa-d (Ray actors keep the model loaded; GPU embeds while CPU parses) | sub-second updates outside an MCP session |
| Index as of a commit | Exa Snapshot (`snapshotAsOf`, built for leakage control) | eval and agents can search the repo as of a release; anchors respect the cutoff |
| Kill-and-resume convergence test | exa-d's convergence property | a crashed update + resume must equal a full rebuild (v2's epochs make this testable) |
| Static vs dynamic fields | Exa company search | code vectors are static; caller lists and BM25 statistics drift, so refresh them lazily within bounds |

---

## 9. Evaluation add-ons borrowed from Exa

| Add-on | Exa source | Code version |
|---|---|---|
| **Censoring check** | ATLAS keeps 52% of its score when the top 7 of every 10 results are removed; other benchmarks keep 81–89% | in the agent study, drop our tool's top-k: if success barely moves, the benchmark measures grep or memory, not retrieval |
| Closed-book probe | ATLAS memorized share (9% vs 48–61%) | ask a model for the file and function from the issue alone; drop or tag tasks it answers |
| Fixed-candidate paired bootstrap | the reranking post | for reranker comparisons: freeze the top-50, stratify by repo, 10k resamples |
| Scale sensitivity | "dense degrades faster than sparse as the corpus grows" | Acc@k vs corpus size: repo → repo + dependencies → several repos |
| Internal-API hallucination score | exa-code (27.1% vs 33.8% hallucinations) | tasks built from a repo's own APIs; static checks for nonexistent symbols and wrong arity |
| Graded decoys | the 2/8/20/30 candidate structure | per issue: gold, callers/callees, BM25-similar wrong functions, vendored copies, injected-comment decoys |
| Ability-split query sets | Exa evals | exact symbol, error string, behaviour, cross-file, "find all callers" |

---

## 10. Compute plan

| Work | M1 16 GB laptop | Hackathon GPU |
|---|---|---|
| v2 baseline on dev50 (0.5B, fp16) | yes (hours; background) | minutes |
| idea 1 anchors, idea 2 routing, idea 6 grid | yes (embedding passes reuse the vector cache) | faster |
| big fresh repos (vLLM, Kubernetes, Linux) at full scale | chunking yes; embedding too slow | needed |
| E-A2 off-the-shelf ColBERT | yes (149M) | — |
| idea 4 LoRA training, E-A3..A5 | no | needed (A100/H100; 8B only here) |
| 0.6–1.5B reranker at query time | feasible, ~1–2 s per query *(est.)* | fast |

---

## 11. Roadmap

| When | Do | Decide |
|---|---|---|
| Week of Oct 26 | full dev50 v2 results on a fast machine (confirms the weights chosen on 13 tasks); window and header ablations (E-A0); exact-lookup routing first (§1: the cheapest fix) | v2 defaults (decisions D12) |
| Oct 27 checkpoint | report v2 vs MVP vs grep; this proposal | which two ideas to pursue first |
| Oct 27 – Nov 9 | idea 2 (routing signals) + idea 1 step 1 (call sites, tests, commits); E-A1, E-A2 | is multi-vector worth GPU time? (E-A2 gate) |
| Nov 10 – 23 | idea 4 training on GPU (cross-repo LoRA + Matryoshka); E-A3; idea 6 grid; highlights metric | the paper's main claim |
| Nov 24 – Dec 1 | E-A4 / E-A5 if the gates passed; agent study with the best configuration | write-up |

---

## 12. Sources

**Exa**
- [Composing a Search Engine](https://exa.ai/blog/composing-a-search-engine)
- [web-scale vector DB](https://exa.ai/blog/building-web-scale-vector-db)
- [BM25 optimization](https://exa.ai/blog/bm25-optimization)
- [exa-d](https://exa.ai/blog/exa-d)
- [Dynamic Highlights](https://exa.ai/blog/dynamic-highlights)
- [Highlights for agents](https://exa.ai/blog/highlights-for-agents)
- [SOTA reranking](https://exa.ai/blog/sota-reranking)
- [exa-code](https://exa.ai/blog/exa-code)
- [How we do evals](https://exa.ai/blog/evals-at-exa)
- [ATLAS](https://exa.ai/blog/atlas-benchmark)
- [Exa Snapshot](https://exa.ai/blog/exa-snapshot)
- [WebCode](https://exa.ai/blog/webcode)
- [RL search outcomes](https://exa.ai/blog/rl-search-outcomes)
- [Cognitive Revolution podcast](https://www.cognitiverevolution.ai/the-example-engine-how-exa-is-creating-the-ai-librarian-for-the-web-with-will-bryk-ceo-of-exa/)
- [Latent Space podcast](https://www.latent.space/p/exa)

**Multi-vector retrieval**
- ColBERT (2004.12832)
- ColBERTv2 (2112.01488)
- PLAID (2205.09707)
- XTR (2304.01982)
- MUVERA (2405.19504)
- ConstBERT (2504.01818)
- token pooling (2409.14683)
- ME-BERT (2005.00181)
- Poly-encoders (1905.01969)
- Set Transformer (1810.00825)
- CRISP (2505.11471)
- MetaEmbed (2509.18095)
- FLINT (2610.27273)
- Weighted Chamfer (2511.16106)
- late-interaction working notes (2603.26259)
- [LateOn-Code](https://huggingface.co/lightonai/LateOn-Code)
- PyLate (2508.03555)

**Code localization**
- SweRank (2505.07849)
- SweRank+ (2512.20482)
- CoRet (2505.24715)
- LocAgent (2503.09089)
- CORE-Bench (2606.11864)
- CoREB (2605.04615)
- jina-code-embeddings (2508.21290)
- Qwen3-Embedding (2506.05176)
- SPLADE-Code (2603.22008)
- Code Isn't Memory (2606.22417)
- Small Agents with Semantic Search (2610.05099)

**Training**
- NV-Embed (2405.17428)
- LLM2Vec (2404.05961)
- Late chunking (2409.04701)
- CDE (2410.02525)
- [Anthropic Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
