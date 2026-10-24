# From the Week 1 MVP to v2: what changed and why

**Audience:** the codemem team (Andre, Wilson, Andrew).
**Branch:** `andre/backend-v2`, compared against `main` @ `c386c1d`. On `main`, the MVP is Wilson's
Week 1 skeleton plus Andrew's MPS fix and eval harness.
**Short version:**
- The MVP's architecture is good and is kept.
- v2 replaces the parts of the backend that blocked multi-language evaluation, long code and
  the research plan: chunking, embedded texts, vector storage.
- It fixes two latent bugs.
- It keeps every interface that the MCP server and the eval harness use.

---

## 1. Was the MVP "naive RAG"? No.

Credit where it is due. The MVP already had:
- **Hybrid retrieval:** BM25 over code-aware tokens, plus embeddings, fused with RRF.
- **A usage vector:** callers' and tests' names embedded separately. On dev50 this is the single biggest gain: function MRR 0.334 → 0.423.
- **Incremental, hash-based updates** that re-embed only changed texts, a file watcher, and a background catch-up in the MCP server.
- **Deterministic results** (ties ordered by location), crash handling and a clean core/front-end split, all well tested.

On Andrew's dev50 (50 SWE-bench Verified tasks, all Python), `cm-bm25-code-usage` was the best
system at file, class and function level:

| | file MRR | file R@10 | function MRR | function R@10 |
|---|---|---|---|---|
| MVP (`cm-bm25-code-usage`) | 0.628 | 0.848 | 0.423 | 0.456 |
| dev-tuned grep baseline (`grep-fn-plus`) | 0.495 | 0.760 | 0.316 | 0.448 |

None of these differences is significant after Holm correction at n = 46.

**So the case for v2 is not "the MVP is bad". It is that the MVP could not run the next
experiments.**

## 2. What was not good enough

| # | Problem | Why it matters | Evidence |
|---|---|---|---|
| 1 | **Python only.** The chunker, file walk, watcher and test detection all hard-code `.py`. | The eval's target repos are vLLM (Python + C++/CUDA), Linux (C), JDK (Java/C++), Kubernetes (Go), fluentui/backstage (TS). | `chunker.py` imports only `tree_sitter_python`; `walk_python_files` filters `.py`. |
| 2 | **The `file_header` chunk.** All non-function lines stitched together, with the range `1..last line`. | Its lines are nearly the whole file, so the hit is useless to an agent. Its text mixes imports, class attributes and `__main__` code. | Flagged in Andrew's Decision 2. Its card skipped the preview because of this. |
| 3 | **No class chunks.** | The eval grades a class level; class attributes and enum members lived in the file header. | Class level is scored only through methods' containment. |
| 4 | **Long functions silently truncated** at 1,024 tokens (~6,144 characters). | The end of a long function was never embedded, so a bug there was invisible to meaning search. | `indexer.py`: `text[:max_chars]`. |
| 5 | **Raw code embedded without context.** | `def delete(self, key)` is embedded without knowing it is `Table.delete` in `auth/db.py`. | CoRet: a file path prefix alone lifts all-gold recall@5 0.42 → 0.53 on SWE-bench Verified. |
| 6 | **Vectors existed only inside FAISS**, keyed by per-index ids. | No reuse across rebuilds, snapshots or config variants (the eval indexes many commits). Changing Matryoshka `embedding_dim` re-embedded everything. No raw vectors for the RQ2 compression study. Crash recovery needed a fragile per-id sidecar and re-embedded. | `store.py` sidecar reconciliation; the `model_id` includes `@dim`. |
| 7 | **Slow embedding.** fp32, batches of 128 texts in file order. | Indexing is 99% embedding (django ~9 min, sympy ~14 min on an M-series GPU). | Andrew's `index.jsonl`; §5 below. |
| 8 | **BM25 had no path field.** | Issues often name modules ("in the auth middleware"). | |
| 9 | **The data model was implicit.** | No document said what a chunk, edge or vector record holds, or how ids, lines and hashes behave. That makes research changes risky. | |
| 10 | **Latent bug: lines split with `str.splitlines()`.** It also splits on `\f`, `\x1c`–`\x1e` and ` `, while tree-sitter rows count `\n` only. | In any file with a form feed (common in older C and Python), the code text of every later chunk comes from the wrong lines. | The eval labeler already guards against this (`split_lines`). New test `test_form_feed_does_not_shift_lines`. |
| 11 | **Latent gaps.** `.pyi` stubs are code to the eval but were not indexed. The index file never shrank (sympy stayed 388 MB after 13k chunk deletions). The eval adapter hashed a hand-copied list of index-time fields. | A new index-time setting would have let two systems share an index silently. | Andrew's run notes; `INDEX_TIME_FIELDS`. |

## 3. What changed, module by module

| Area | MVP | v2 | Why |
|---|---|---|---|
| Languages | Python | Python, JavaScript, TypeScript, TSX, Go, Java, C, C++ (+CUDA), Rust, each a small spec in `languages/` with a generic walker | #1 |
| Chunks | function, method, `file_header` | function, method, **class** (embedded as a skeleton), **block** (exact top-level code runs) | #2, #3 |
| Lines | `splitlines()`; decorators included | split on `\n` only; decorators, annotations, attributes, `export` and `template` included; leading doc comments excluded from the range but kept as `docstring` | #10, eval IoU |
| Wrappers | descends into `if`/`try` for defs, drops the rest | opens `if TYPE_CHECKING`, `try/except`, `#ifdef`, `extern "C"`, namespaces; their other statements become blocks | headers wrapped in include guards |
| Tests | any folder named `test`, `tests` or `testing` | per-language rules (`*_test.go`, `#[test]`, `@Test`, gtest `TEST`, `*.test.ts` …); `test/` only at the top or under `src/` | `django/test/` is library code (the eval agrees) |
| Call graph | name match, global | name match within a language family; first call line stored | a C function must not be "called by" a Python method of the same name |
| Code text | raw code | path + enclosing scope header (no line numbers), doc comment for non-Python, the class skeleton for classes; long code split into windows | #4, #5 |
| Usage text | callers' names | same format; block callers ("called at top level in …"); test flag from the language rules | multi-language |
| Vector storage | FAISS only, sidecar per vector type | float16 rows in SQLite (source of truth); FAISS derived, rebuilt from rows when stale; epochs instead of sidecars | #6 |
| Reuse | none | vectors reused by (embedder key, text hash) from the index or a shared cache | #6, #7 |
| Matryoshka | in the model id (re-embeds) | applied when FAISS is built (no re-embedding) | RQ2 |
| Embedder | fp32 | fp16 on CUDA/MPS (fp32 fallback per batch); texts sorted by length globally; query cache | #7 |
| BM25 | name, signature, body (weights 10/5/1) | name, path, signature, doc, body (10/3/5/2/1; v1 triples still accepted) | #8 |
| Search | signals, path prefix | + `kinds` and `languages` filters; tests, classes and blocks at half weight by default (`test_weight`, `kind_weights`); a long chunk scores by its best window | crowding (§5.3) |
| Cards | function cards | + class/block cards, `best a-b` lines, preview focused on the matching lines | agent tokens |
| Ignore | `.gitignore` + fixed dirs | + `vendor/`, minified JS, protobuf outputs, `Code generated … DO NOT EDIT` files | vendored copies crowd results |
| Disk | grew forever | `auto_vacuum = INCREMENTAL`, vacuum after big deletions | #11 |
| Eval seam | adapter hashed a copied field list | adapter hashes `Config.index_settings()`; hits carry language, subkind and best lines | #11 |
| Docs | design brief (Week 1) | architecture.md, data-model.md, decisions-v2.md, this file, advanced-design.md | #9 |

**What did not change on purpose:**
- the MCP tools and their arguments
- `prompts.py` steering levels (wording updated for classes and blocks)
- the CLI commands (new: `codemem languages`, `index --no-cache`, `search --kinds/--language/--exclude-tests`)
- SQLite + FAISS
- the tokenizer
- RRF
- the location-ordered ties
- the eval contract (all 288 eval tests pass unchanged except where noted below)

## 4. Compatibility notes

**For Wilson (MCP / CLI):**
- `file_header` is gone. Cards for blocks and classes look different (`<imports>`, `Table (struct)`).
- `get_chunk` on a long class returns its skeleton plus a member list.
- A v1 index is rebuilt automatically on first use (schema version 2).

**For Andrew (eval):**
- The adapter now calls `Config.index_settings()`. `INDEX_TIME_FIELDS` remains as a fallback for codemem 0.1.
- New configs: `eval/configs/codemem-v2.toml` (search-time variants on one index), `codemem-v2-weights.toml`, `codemem-v2-ablations.toml`, `baseline-v2.toml`.
- Every codemem system in them pins its search-time weights, so a name keeps its meaning if the defaults change. `cm2-full` is the default; `cm2-bm25*` are the unweighted signal ablations that mirror v1's `cm-*`.
- `.pyi` is now indexed.
- codemem's per-language chunk conventions are in [data-model.md](data-model.md) §3.
- **I did not touch the labeler.** It must stay an independent ruler, so its other-language tables are yours to write and cross-check.
- Card texts changed slightly (blocks, classes, `best` lines), so token metrics are not comparable across versions without re-counting.

**For Andre (research):**
- Every vector is stored at full dimension in float16, so RQ2's compression grid needs no re-embedding.
- New vector types (anchors, summaries) are a text builder away.
- Multi-vector parts are already the storage shape.

## 5. Measured impact

### 5.1 Tests
- **codemem:** 87 → 125 fast tests (all pass), plus the 3 real-model tests (`pytest -m model`, pass). New tests cover:
  - every language (`tests/test_languages.py`)
  - a multi-language repo (Go + TS + C, with vendored, generated and protobuf files skipped)
  - windows, headers, the vector cache, Matryoshka changes without re-embedding
  - crash and corrupt-index recovery without the model
  - v1 index migration
  - search filters and weights
- **cmeval:** 288 passed / 19 skipped (no ripgrep on this machine) before; 289 passed / 19 skipped after (one new adapter test).

### 5.2 Speed (`requests` v2.32.3, same M1 laptop, jina-code-0.5b on MPS)

`scripts/smoke_real_model.py`, one run each, on the same laptop
(`docs/benchmarks/2026-10-24-requests-m1-v1-vs-v2.json`):

| | MVP (main) | v2 |
|---|---|---|
| chunks | 702 (function, method, file_header) | 801 (+86 classes, 48 blocks instead of 35 headers) |
| vectors embedded | 884 | 1,047 (windows, classes, more usage texts) |
| full index | **468.8 s** | **224.1 s** |
| seconds per vector | 0.53 | 0.21 |
| no-op update | 0.103 s | 0.095 s |
| query latency (median) | 71 ms | 58 ms |

- **2.1× faster to build**, despite 18% more vectors. The gain comes from float16 on the GPU and length-sorted batches.
- **Rebuilding with a warm vector cache costs no model calls at all.** The same holds for a config variant that shares texts.
- **Non-embedding phases on vLLM** (6,236 files, 102k chunks: Python, C++/CUDA, Rust): chunking runs at about 1,250 chunks/s on one core. Memoized tokenization halved the write phase.

### 5.3 Accuracy on dev50

**Why only a subset ran here.** The local M1 embeds about 14× slower than the machine of
Andrew's MVP run:

| | v2 on the M1 | MVP on Andrew's machine |
|---|---|---|
| seaborn build | 1,034 s | 62 s |
| vectors | 3,672 | 3,096 |

The full dev50 would take about a day here, so:

- **Locally (indicative only):** the 13 tasks of the four small repos (requests, flask, seaborn, pytest), with every v2 search-time variant sharing one index. Results are below.
- **Hand-off (decisive):** the full 50 tasks on Andrew's machine or a CUDA GPU. Expect under an hour. Run:

  ```bash
  cd eval && uv sync --extra codemem
  uv run cmeval run --tasks tasks/swebv-dev50.jsonl --config configs/codemem-v2.toml --run-id dev50-v2
  uv run cmeval run --tasks tasks/swebv-dev50.jsonl --config configs/codemem-v2-weights.toml --run-id dev50-v2-weights
  uv run cmeval score dev50-v2 && uv run cmeval score dev50-v2-weights
  for s in cm2-full cm2-bm25-code-usage; do
    uv run python ../scripts/compare_scores.py results/2026-10-23-dev50-final/scores.jsonl.gz cm-bm25-code-usage \
        $CMEVAL_HOME/runs/dev50-v2/scores.jsonl $s
  done
  ```

  The second run reuses every vector through the cache, so it costs minutes. **Regression gate:** v2's default (`cm2-full`) must be at least the MVP's `cm-bm25-code-usage`, within the paired bootstrap interval, on file and function MRR. If the full dev50 disagrees with the weights chosen below, change them (D12).

#### Local subset: 13 dev tasks (requests 5, pytest 5, seaborn 2, flask 1)

- Same model (jina-code-embeddings-0.5b) and device type (MPS) as the MVP run. v2 stores float16 vectors.
- 12 of the tasks have function gold and 11 have class gold.
- Differences are paired (v2 − MVP, same tasks), with cmeval's bootstrap 95% interval.
- With 12 tasks, one task moving changes function MRR by up to 0.08. **Read these numbers as indicative only.**
- Runs: `2026-10-24-dev50-v2` (`configs/codemem-v2.toml` before the weights existed, so with none) and `2026-10-24-subset-weights` (`configs/codemem-v2-weights.toml`).
- Their metrics, reports and the update-vs-rebuild check are in `eval/results/2026-10-24-subset-v2/`, `2026-10-24-subset-weights/` and `2026-10-24-subset-b4/`. The MVP numbers come from `eval/results/2026-10-23-dev50-final/`, restricted to the same tasks.

| | MVP `cm-bm25-code-usage` | v2, no weights | v2 default (`cm2-full`) | default − MVP [95% CI] |
|---|---|---|---|---|
| file MRR | 0.520 | 0.546 | 0.555 | +0.035 [+0.003, +0.072] |
| file R@10 | 0.846 | 0.846 | 0.923 | +0.077 [0.000, +0.231] |
| class MRR | 0.333 | 0.391 | 0.400 | +0.066 [−0.003, +0.167] |
| function MRR | 0.355 | 0.386 | 0.410 | +0.055 [−0.004, +0.135] |
| function R@10 | 0.417 | 0.500 | 0.625 | +0.208 [0.000, +0.417] |
| function success@10 | 0.333 | 0.417 | 0.583 | +0.250 [0.000, +0.500] |

- **No difference is significant.** The smallest Wilcoxon p is 0.125 (file MRR).
- **Per task** (function level, default vs MVP):
  - better on 4 tasks: requests-1921 rank 16 → 2, pytest-10081 27 → 7, flask-5014 28 → 17, requests-1142 3 → 2;
  - worse on 2: seaborn-3069 22 → 48, requests-1766 4 → 5;
  - the same on 6.
- **Per signal** (each v2 system vs the MVP system with the same signals):
  - BM25 alone is unchanged (function MRR 0.206 vs 0.203).
  - Adding the code vector is where v2's text changes show (path header, windows, class skeletons): class MRR 0.189 → 0.295 [+0.003, +0.275], function MRR 0.312 → 0.347 [+0.005, +0.074], function R@10 0.417 → 0.625.
- **The tuned grep baseline ties v2 here.** `grep-fn-plus` scores function MRR 0.408 and file MRR 0.541 on these 13 tasks, with intervals of ±0.3. On the full dev50 it trailed the MVP (0.316 vs 0.423), so these small repos are not representative.
- **Regression gate on the subset: passed.** v2's default is at least the MVP on file and function MRR; the intervals' lower ends are −0.004 or higher. The full dev50 decides.

#### Search-time weights (the choice is recorded in [decisions-v2.md](decisions-v2.md), D12)

All systems share one index. "Better / worse" counts tasks against no weights (`cm2-ref`) at the file, class and function level.

| system | settings | file MRR | class MRR | function MRR | function R@10 | tasks better / worse (file; class; function) |
|---|---|---|---|---|---|---|
| `cm2-ref` | no weights | 0.546 | 0.391 | 0.386 | 0.500 | |
| `cm2-t05` | tests ×0.5 | 0.554 | 0.398 | 0.394 | 0.625 | 2/0; 1/0; 2/0 |
| `cm2-t05-c05` | tests, classes ×0.5 | 0.554 | 0.399 | 0.408 | 0.625 | 2/0; 2/0; 3/0 |
| **`cm2-t05-c05-b05`** | **tests, classes, blocks ×0.5 (the new default)** | **0.555** | **0.400** | **0.410** | **0.625** | **2/0; 2/0; 4/0** |
| `cm2-t03-c03-b03` | tests, classes, blocks ×0.3 | 0.555 | 0.400 | 0.411 | 0.625 | 2/0; 2/0; 4/0 |
| `cm2-fn-t05` | functions and methods only, tests ×0.5 | 0.575 | 0.425 | 0.421 | 0.625 | 3/1; 2/1; 4/0 |
| `cm2-t0` | tests dropped | 0.573 | 0.397 | 0.338 | 0.625 | 2/0; 1/0; 1/3 |
| `cm2-t05-v1bm25` | tests ×0.5, v1 BM25 weights | 0.555 | 0.397 | 0.396 | 0.625 | 2/0; 1/0; 3/0 |

- **Weights never lost a task; filters did.**
  - Dropping tests (weight 0) or filtering kinds removes chunks from each signal's candidate list *before* RRF. That changes the per-signal ranks of the remaining chunks, so they can reorder: 3 function-level losses for `cm2-t0`.
  - Weights apply after fusion and move only the chunks they target.
- **0.5 and 0.3 tie,** so the milder 0.5 became the default.
- **Functions only has the highest means,** but it lost a task at file and class level, and it hides classes and top-level code from agents. It stays a variant (`kinds = ["function", "method"]`).
- **BM25 field weights:** v1's 3-field weights and v2's 5-field weights are within one task of each other. v2's are kept, because the path and doc fields matter for the other languages.
- **Cost:** the whole weights pass (8 systems × 13 tasks, all 13 indexes rebuilt) took 99.8 s, because every vector came from the cache.

#### Update vs. rebuild (B4) and float16

- **B4: PASS** for all 7 systems (`cmeval compare 2026-10-24-dev50-v2 2026-10-24-subset-rebuild`).
  - 13/13 tasks have the same top 10, and the largest metric difference is 0.0000 (the rule is ≥ 95% and < 0.01).
  - The update run used codemem `31c0f99` and the rebuild `18d3b77`. In between are only a speed fix and weights that defaulted to 1.0.
  - A same-commit pair also matches: the update-mode `cm2-ref` of the weights run vs the rebuild, both `18d3b77`. All 13 top 10s are identical and in the same order, and all 1,394 metric values are equal.
- **What B4 checks with the cache on.** Both modes get the same vector for the same text, so this checks the update logic (chunk diffing, texts, store, FAISS rebuild), not embedding noise between batches. `CODEMEM_VECTOR_CACHE=off` includes that, at full embedding cost.
- **Rebuild speed:** rebuilding all 13 indexes with a warm cache took 92.8 s for the whole run, against 5,852 s for the first run, which embedded everything.
- **float16 vs float32** (MPS, 200 random code texts from `requests`): cosine min 0.99969, mean 0.99987. The top 10 for a query are the same 10 chunks.

## 6. Known limitations of v2

- **Name-based call graph** (as in the MVP). Common method names (`get`, `run`) and dynamic dispatch are missed or ambiguous.
- **No module-level "file card".** File-level ranking comes from the best chunk of each file.
- **Blocks are keyed by content**, so editing a block re-keys it. Nothing points to blocks, so this costs only the block's own vector.
- **Language coverage:**
  - C++ templates and macros are parsed with tree-sitter's error recovery, so heavily macro'd code (CUDA `__global__`, kernel `SYSCALL_DEFINE`) is chunked by what parses.
  - Ruby, PHP, C#, Kotlin and Scala are not yet supported.
- **The eval labeler is still Python-only.** Function- and class-level scores exist only for Python tasks until Andrew adds language tables.
- **Large repos need a CUDA GPU for the first full build.** Updates after that are small.
