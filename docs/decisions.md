# Decisions, constants and open questions

This page records every design choice and every number in codemem that would otherwise look
arbitrary: what it is, why it has that value, where it came from, and how sure we are. If the
team disagrees with one, change it here first, then in the code.

**Status words:**
- **measured:** chosen by an experiment;
- **provisional:** chosen on little data, to be re-checked;
- **hand-picked:** a reasonable value nobody has tuned;
- **inherited:** carried over from Wilson's Week 1 MVP;
- **from the literature:** a published default.

---

## 1. Design decisions

### From v2 (Oct 23–24): still in force

| # | Decision | Why | How to reverse |
|---|---|---|---|
| D1 | **Revamp the backend in place, not a rewrite.** Keep the front-ends and every API the eval adapter uses. | The MVP's architecture was sound and was the best system on dev50; its limits were in chunking, texts and vector storage. | n/a |
| D2 | **SQLite + FAISS; vectors are float16 rows in SQLite; FAISS is derived.** | One source of truth, so recovery needs no model. Raw vectors also allow compression experiments without re-embedding. | Swap `FaissVectorStore` behind the `VectorStore` interface. |
| D3 | **Chunk kinds are function, method, class and block.** The MVP's stitched `file_header` chunk is gone. | The header's range covered nearly the whole file. Blocks have exact lines, and classes match the eval's class level. | `kinds = ["function", "method"]` hides classes and blocks at search time. |
| D4 | **A class chunk spans the whole class but embeds and BM25-indexes its outline.** | It matches class gold exactly without duplicating every method's text. | `_code_body` in `texts.py`, `upsert_chunk` in `store.py`. |
| D5 | **Long code is split into windows; a chunk scores by its best window.** | The MVP silently cut off anything past about 1,024 tokens. | A huge `window_chars` restores truncation. |
| D6 | **The code text gets a context header** (path, enclosing scope; never line numbers). | `def delete(self)` alone says nothing about where it lives. CoRet: a path prefix alone lifts recall@5 0.42 → 0.53. | `code_header = false`. |
| D7 | **A shared vector cache, on by default.** | Rebuilds, commits and config variants re-embed only new texts. | `vector_cache = "off"` or `--no-cache` (needed for cold timings). |
| D8 | **Official tree-sitter wheels; nine languages.** | They cover the target repos (vLLM, Linux, JDK, Kubernetes, fluentui, backstage). | Add a spec in `languages/`. |
| D9 | **Skip vendored, generated and minified code by default; keep `third_party/`.** | Copies crowd results and cost embedding time; `third_party/` often holds real project code. | `use_default_ignore = false`, `skip_generated = false`. |
| D10 | **codemem never writes the eval labeler's language tables.** | The labeler is the ruler. If one person writes both, the same mistakes cancel out. | n/a |
| D12 | **Search-time defaults are tuned on dev tasks only;** the test split stays untouched. | Andrew's rule: tune on dev, report on test. | n/a |
| D13 | **Block keys include a content hash** (`path::<block>@hash8`). | Blocks have no names, and position-based keys would shift. | `_Walker.block` in `chunker.py`. |
| D14 | **Calls resolve within a language family only** (C with C++, JS with TS). | A Python method must not "call" a C function of the same name. | `callgraph.resolve_edges`. |
| D15 | **Test detection follows each language's conventions**, not "any folder named test". | `django/test/` and `sympy/testing/` are library code, and the eval agrees. | `LanguageSpec.test_dirs`. |
| D16 | **float16 embeddings on GPUs; rows that overflow are recomputed in float32.** | Roughly halves memory and time. The dtype is part of the embedder key. | `dtype = "float32"`. |
| D17 | **Long-function cards show the best window's lines.** | The agent should read the matching part first; a first step towards highlights. | Rendering only. |
| D18 | **Kinds and tests can be weighted, not only filtered** (`kind_weights`, `test_weight`). | A weight moves only the chunks it targets; a filter changes every list before fusion. **The default values changed in v3 (D24).** | Set the weights to 1.0. |

D11 (local commits, no push) now applies to `andre/backend-v3`.

### From v3 (Oct 24–)

| # | Decision | Why | How to reverse |
|---|---|---|---|
| D19 | **One update function for the first build, reconciles and single saves.** Full and incremental updates follow the same code path, and a verify mode recomputes everything as a check. | One path to get right (Exa's exa-d: "backfills and incremental updates follow the same codepath"). The differential tests compare it with verify mode. | n/a |
| D20 | **Usage text lists callers and tests only, not callees.** | Usage was the biggest measured gain (dev50 function MRR 0.334 → 0.423, MVP). Listing only callers keeps the ripple of an edit to one hop along outgoing calls. | Add callee lines in `build_usage` (parked experiment, §3). |
| D21 | **Searches catch up on pending edits first, within a time budget.** | Agents search right after their own edits; waiting for the agent to finish would give the stalest index exactly then. | `catchup_budget_ms = 0` (keywords and links still catch up; nothing is embedded first). |
| D22 | **The MCP server writes FAISS files lazily;** the CLI and the blocking `update()` still write at once. | Rewriting 520 MB per save cost 2.2 s and blocked searches. The eval measures the index size right after `update()`. | `save=True` everywhere. |
| D23 | **Stored index settings are compared at every update; a difference invalidates only what that setting affects.** Four tiers: vectors (re-embed that type), texts (rebuild every text, re-embed the changed ones), links (relink every call), rebuild (chunker version, file selection, BM25 tokenization, block size: wipe and rebuild, with vectors from the cache). | With incremental updates, a chunker or text upgrade would otherwise never reach unchanged files. The tiers keep a model change from re-chunking the repo, and a relink from re-embedding it. | n/a |
| D24 | **Neutral search weights by default** (tests, classes and blocks no longer halved). | The v2 weights won on our eval only because its answers are never tests and rarely whole classes. Real questions ("add OCR to uploads") often need both. | `test_weight = 0.5`, `kind_weights = {class = 0.5, block = 0.5}`. |
| D25 | **The eval code is not changed in v3;** eval changes are highlighted, not made. | The redesign is about the core. A regression check on the existing tasks is enough to show nothing got worse. | n/a |
| D26 | **Remote embeddings are opt-in, through any OpenAI-compatible API.** Keys come only from an environment variable named in the config, and the local model stays the default. | It's private and free by default. Large first builds can use a provider (Nebius, OpenAI, a self-hosted server) when speed matters more than privacy. | `[embedding] provider = "local"`. |
| D27 | **PyTorch stays a required dependency for now.** | Making it an optional extra (`codemem[local]`) needs a one-line change in the eval's `pyproject.toml`. Deferred, and highlighted for Andrew. | Move `sentence-transformers` and `torch` to an extra. |
| D28 | **No file is skipped silently.** The size cap is 10 MB, every skipped file is stored with its reason, and non-code files are counted. | A 1 MB cap hides real hand-written files (TypeScript's `checker.ts`), and size skips left no trace. | `max_file_size`. |
| D29 | **Python comments directly above a definition become its doc text;** line ranges are unchanged. | They were dropped entirely, while the other languages already kept them. The eval labeler excludes comments from ranges. | n/a |
| D30 | **Windows name their function, and are split evenly.** | Windows 2..n didn't say which function they belong to, and the last window could be a few lines. | `texts._split_code`. |
| D31 | **Blocks over 200 lines are split by lines, even inside one statement.** | One 1,668-line dict was one block with 32 windows. | `chunker.flush`. |
| D32 | **BM25 queries drop stopwords and keep at most the 32 rarest words.** The index is unchanged. | Long queries OR-ed every word: 1.1 s on vLLM for 250 words. Common words carry almost no weight anyway. | `bm25_query_terms = 0`. |
| D33 | **The manual refresh is an MCP tool (`refresh_index`), not a skill or a hook.** | A Claude skill works only in Claude Code; an MCP tool works in every agent. Catch-up makes it rarely needed. | n/a |
| D34 | **Searches go first.** While a search catches up, the background writer hands over the model at its next call, and the queue is embedded newest edits first. A search also waits for edits the writer has taken but not committed yet: hand-overs are numbered, and only the writer applies them, so a slow stage A can't hold a search past its limit. | The agent's next search is about its own latest edit. Measured (Oct 25): a search 0.7 s after a save missed it while the writer was still applying it, and a 2 s limit took 3.1 s because it was only checked between batches. | n/a |

---

## 2. Constants

| Constant | Value | Where | Origin | Status | Why |
|---|---|---|---|---|---|
| embedding model | `jinaai/jina-code-embeddings-0.5b` | `config.DEFAULT_MODEL` | inherited | provisional | code-specific, small enough for a laptop, private; every result so far uses it. To compare: jina 1.5B, Qwen3-Embedding 0.6B/4B/8B, voyage-code-3 |
| vector size | 896 (the model's full size) | model | inherited | measured | `embedding_dim` can shorten it (Matryoshka) without re-embedding |
| max tokens per text | 1,024 | `max_seq_length` | inherited | hand-picked | keeps CPU indexing tractable |
| window size | 3 × (1,024 − 32) = 2,976 characters | `effective_window_chars()` | v2 | hand-picked | about 3 characters per token, leaving room for the header |
| window overlap | 3 lines | `window_overlap_lines` | v2 | hand-picked | a statement cut at a window edge appears whole in one of the two |
| block length cap | 200 lines | `max_block_lines` | v2 | hand-picked | a result should point at a readable range |
| file size cap | 10 MB (was 1 MB) | `max_file_size` | v3 | hand-picked | see D28 |
| minified line length | 5,000 characters | `indexer.skip_reason` | v2 | hand-picked | hand-written code never has lines that long |
| generated-marker window | first 2 KB | `indexer.skip_reason` | v2 | hand-picked | generators write the marker at the top |
| binary check | NUL byte in the first 8 KB | `indexer.skip_reason` | v2 | hand-picked | the common heuristic (git uses the same idea) |
| BM25 field weights | name 10, path 3, signature 5, doc 2, body 1 | `bm25_weights` | name/signature/body inherited (10/5/1); path 3 and doc 2 added in v2 | hand-picked | names are the strongest signal; v1's 10/5/1 is within one dev task of these |
| BM25 query cap | 32 rarest words | search | v3 | hand-picked | see D32 |
| RRF k | 60 | `rrf_k` | inherited | from the literature (Cormack et al. 2009) | the paper's default, found insensitive; untuned for us |
| candidates per list | 50 | `candidates` | inherited | hand-picked | enough depth for RRF; the eval asks for 50 results too |
| definitions per name | 5 | `max_defs_per_name` | inherited | hand-picked | names like `get` or `run` would link everything to everything |
| usage lines | 20, half reserved for tests | `max_usage_items` | inherited (tests reserve: v2) | hand-picked | keeps the usage text within one window |
| test and kind weights | 1.0 (was 0.5) | `test_weight`, `kind_weights` | v3 | see D24 | neutral |
| result count | 10; the MCP tool caps it at 50 | `server.search_code` | inherited | hand-picked | |
| preview | 12 lines, 800 characters | `preview_lines`, `preview_chars` | inherited | hand-picked | short cards; the eval counts their tokens |
| quiet period / maximum wait | 0.5 s / 2 s (was 0.4 s, no maximum) | watcher | v3 | provisional | groups the writes of one action; the maximum stops a long burst from postponing indexing forever |
| catch-up budget | 4 s (was 2 s) | `catchup_budget_ms` | v3 | provisional, Andre's call (Oct 25); tune later | a one-function edit took 0.11–0.17 s with the real model (sample repo). The local model embeds about 8.5 texts per second on the M1 (0.02 s for a short function, 0.5 s for a long one), so 4 s covers about 30 average texts. Agents edit a few files per step; a `git pull` or a formatter run is the case that hits the cap. An extra grep turn costs the agent more than waiting (ripgrep itself: 0.12 s on vLLM) |
| model call outside a build | at most `batch_size` texts (16) and 3,000 characters | `service._CALL_CHARS` | v3 | measured | on the M1, 16 long texts took 7 s in one call and about 0.2 s per 1,000 characters overall; 3,000 characters is about 0.6 s. A call isn't started when the measured speed (a moving average) says it would end past the deadline |
| periodic reconcile | every 5 minutes | service | v3 | hand-picked | catches missed events; costs one scan (0.3 s on vLLM) |
| polling fallback | every 10 s | service | v3 | hand-picked | only when OS file events fail |
| burst threshold | 2,000 paths, then a full reconcile | watcher | v3 | hand-picked | at that size a scan is simpler and no slower |
| FAISS save | after 30 s idle, on shutdown, on refresh | service | v3 | hand-picked | see D22 |
| embedding batch | 16 texts (local); 64 texts, 4 parallel requests (API) | `batch_size`, `[embedding]` | inherited / v3 | hand-picked | |
| model call group in a build | 256 texts, longest first | `indexer._EMBED_GROUP` | v2 | measured | length-sorted batches waste less padding (2.1× faster builds) |
| precision | float16 on CUDA and MPS, float32 on CPU | `dtype = "auto"` | v2 | measured | float16 vs float32: cosine ≥ 0.9997, same top 10 |
| query cache | 512 queries | `embedder._QUERY_CACHE_SIZE` | v2 | hand-picked | the eval asks the same query of several systems |
| steering | `light` | `steering` | inherited | hand-picked | a variable of the agent study |

---

## 3. Parked questions

These are known gaps or ideas, deliberately not handled yet. Each needs a decision before it is
built.

| Question | Why it's parked | What would decide it |
|---|---|---|
| **Comments on their own between definitions** (blank lines around, no code) are dropped. | Some are real explanations; many are license headers or section banners, which would add noise. | A rule, for example "attach to the next definition if within N lines; skip license headers", checked on a few repos. |
| **Class-level comments** (between methods) are not in the class outline, so they are not searchable. | Outlines are meant to be short. | The same rule as above, measured on class-level results. |
| **Callee descriptions in the caller's text** ("calls `ocr_image`: extracts text from an image"). | It may help vague questions, but edits would then ripple to callers too (D20). | An ablation in the tuning phase, with the ripple cost measured. |
| **Non-code files** (README, docs, YAML, SQL) are not searchable. | They need a plain-text chunker and a different card. | User demand ("where is the config for X"); the coverage report shows how much is missing. |
| **Import-aware call links:** prefer the same class, then the same file, then the imported module. | Name matching is crude, but it works across nine languages. | Usage-text precision on a sample, then retrieval results. |
| **Result grouping:** show a class once with its matching methods; list tests under the function they test. | With neutral weights, tests, classes and blocks can crowd the top 10 again. | Measure crowding with neutral weights first. |
| **File-level cards** for "where do I start" questions. | Today a file ranks by its best chunk. | The vague-question eval (below). |
| **A vague-question eval** (highlighted, Andrew's area): one sentence per dev task in a user's voice, written from the issue only, with the same gold; the feature-request tasks as the closest match. | v3 doesn't change the eval (D25). | Needed before tuning, otherwise tuning keeps optimizing for issue texts. |
| **Tuning:** RRF k, per-list weights, BM25 field weights, candidates. | Tuning on today's eval would optimize for issue texts. | The vague-question eval. |
| **Embedding model comparison** (jina 0.5B and 1.5B, Qwen3-Embedding 0.6B/4B/8B, voyage-code-3), **with the window size** (`max_seq_length` 1k, 2k, 4k, 8k tokens, whole functions). | Needs the API embedder (v3) and the vague-question eval. Both models read 32k tokens; the 1,024 cap is for laptop speed, and through an API the tokens cost the same either way. Only about 5% of vLLM's chunks are long enough to be affected. | The first tuning experiment. Keep 1,024 until then. |
| **PyTorch as an optional extra** (D27). | Needs a one-line eval change. | Andrew's agreement. |
| **Vector cache cleanup:** the cache only grows (about 4.5 KB per vector). | Small so far: 123 MB. | A "last used" date per entry, then a size cap. |

---

## 4. Evidence behind the v2 choices

These are the 13 small-repo dev tasks (requests 5, pytest 5, seaborn 2, flask 1), run on the M1
with the same model as the MVP. With 12 tasks at function level, one task moving changes function
MRR by up to 0.08, so **read these as indicative only.** Runs are in `eval/results/2026-10-24-*`.

| | MVP | v2, no weights | v2 with weights (v2 default) |
|---|---|---|---|
| file MRR | 0.520 | 0.546 | 0.555 |
| class MRR | 0.333 | 0.391 | 0.400 |
| function MRR | 0.355 | 0.386 | 0.410 |
| function R@10 | 0.417 | 0.500 | 0.625 |

- No difference is significant (smallest Wilcoxon p = 0.125).
- About half of v2's lead over the MVP came from the weights. Those were tuned to the eval's blind
  spot (D24), so v3's regression check compares against **v2 without weights**.
- **What the weights did:** tests ×0.5 alone was never worse on any task, and lifted function
  R@10 from 0.500 to 0.625. Adding classes and blocks ×0.5 improved 2, 2 and 4 tasks at file,
  class and function level. Dropping tests entirely (weight 0) made 3 tasks worse, because a filter
  reorders every list before fusion.
- **Update vs rebuild (B4):** passed. 13/13 tasks had the same top 10, and 1,394 metric values were
  equal on a same-commit pair.
- **Speed** (`requests`, M1): a full build took 224 s, against 469 s for the MVP. The gain comes
  from float16 and length-sorted batches. Rebuilding with a warm cache needs no model calls.
- **The full dev50** (Andrew's machine or a CUDA GPU) decides. The commands are in `README.md`.
