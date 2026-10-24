# Decisions for the v2 backend

These are decisions taken while rebuilding the backend (Oct 23–24, 2026). Each one gives the
reason and how to reverse it. If the team disagrees with one, change it here first, then in the
code.

| # | Decision | Why | How to reverse |
|---|---|---|---|
| D1 | **Revamp the backend in place, not a rewrite.** Keep the MCP server, CLI, service, prompts and agent registration, and every API the eval adapter uses. | The MVP's architecture was sound and is the best system on dev50. Its limits were in chunking, texts and vector storage, not in the front-ends. | n/a |
| D2 | **SQLite + FAISS stay; vectors become float16 rows in SQLite; FAISS is derived.** | One source of truth, so crash recovery needs no model. Raw vectors also enable RQ2 compression experiments (truncate, int8, binary) without re-embedding. | Swap `FaissVectorStore` behind the `VectorStore` interface. |
| D3 | **Chunk kinds are function, method, class, block. The stitched `file_header` chunk is gone.** | The header's range (`1..last line`) covered nearly the whole file and stitched non-adjacent lines into one text. Blocks have exact lines, and classes match the eval's class level. | `kinds = ["function", "method"]` hides classes and blocks at search time. |
| D4 | **A class chunk spans the whole class but embeds and BM25-indexes its skeleton.** | It matches class gold exactly, without duplicating every method's text. | Change `_code_body` in `texts.py` and `upsert_chunk` in `store.py`. |
| D5 | **Long code is split into windows; a chunk scores by its best window.** | The MVP silently truncated anything past ~1,024 tokens. | `window_chars = 1000000` restores truncation (an ablation config exists). |
| D6 | **The code text gets a context header (path, enclosing scope).** | A method like `delete(self)` alone says nothing about where it lives. The CoRet paper found the path prefix alone lifts all-gold recall@5 from 0.42 to 0.53. | `code_header = false` (ablation config exists). |
| D7 | **A shared vector cache, on by default.** | Rebuilds, commit replays and config variants re-embed only new texts. | `vector_cache = "off"` or `codemem index --no-cache` (use it for cold timings in RQ3). |
| D8 | **Official per-language tree-sitter wheels; nine languages** (Python, JS, TS, TSX, Go, Java, C, C++ incl. CUDA, Rust). | Same packaging style as the eval's `tree-sitter-python`. They cover the target repos: vLLM, Linux, JDK, Kubernetes, fluentui, backstage. | Add a spec in `languages/` and a grammar dependency. |
| D9 | **Skip vendored, generated and minified code by default.** `third_party/` is kept. | Copies of the same functions crowd results and cost embedding time. `third_party/` often holds real project code (vLLM). | `use_default_ignore = false`, `skip_generated = false`. |
| D10 | **codemem does not write the eval labeler's language tables.** | The labeler is the ruler. If one person writes both, the same mistakes cancel out and stay invisible. data-model.md documents codemem's conventions for an independent cross-check. | n/a |
| D11 | **Local commits on `andre/backend-v2`; no push.** | Pushing is the user's call. | `git push -u origin andre/backend-v2` |
| D12 | **Search-time defaults (test weight, kinds, BM25 weights) are chosen on dev50 only.** The test split stays untouched. | Andrew's rule: tune on dev, report on test. | See "Dev50 choices" below. |
| D13 | **Block keys include a content hash** (`path::<block>@hash8`). | Blocks have no names, and position-based keys would shift whenever a block is inserted above. No edge points to a block, so re-keying costs only that block's vector. | Change `_Walker.block` in `chunker.py`. |
| D14 | **Calls resolve within a language family only** (C with C++, JS with TS). | A Python method must not become a "caller" of a C function that happens to share its name. | `callgraph.resolve_edges` ignores the family if the tuples have none. |
| D15 | **Test detection follows common conventions**, not the MVP's "any folder named test". | `django/test/` and `sympy/testing/` are library code, and the eval agrees. | `LanguageSpec.test_dirs` / `top_test_dirs`. |
| D16 | **float16 embeddings on GPUs (CUDA, MPS); overflowing rows are recomputed in float32.** | Roughly halves memory and time. The dtype is part of the embedder key, so fp16 and fp32 vectors never mix. | `dtype = "float32"`. |
| D17 | **Long-function cards show the best window's lines, focused on the line sharing most query words.** | An agent should read the matching part first. This is a cheap first step towards Exa-style highlights. | Card rendering only; the hit's lines stay the whole function (the eval grades those). |

## Dev50 choices (D12)

Pending the local dev50 run with `eval/configs/codemem-v2.toml`; filled in by
[baseline-v2-diff.md](baseline-v2-diff.md) once scores are in.
