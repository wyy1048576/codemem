# codemem

Local, agent-agnostic code search. Point it at a repository in any of nine languages (Python,
JavaScript, TypeScript, Go, Java, C, C++/CUDA, Rust) and it indexes every function, class and
block of top-level code, then serves hybrid search (BM25 + embeddings, merged with RRF) to coding
agents over **MCP** and to humans and eval scripts through a **CLI**. Your code never leaves the
machine.

| Doc | For |
|---|---|
| [docs/architecture.md](docs/architecture.md) | how it works, end to end, with one running example |
| [docs/data-model.md](docs/data-model.md) | every stored record: chunks, edges, texts, vectors; ids, lines, hashes, versions |
| [docs/baseline-v2-diff.md](docs/baseline-v2-diff.md) | what changed from the Week 1 MVP, why, and measured impact |
| [docs/decisions-v2.md](docs/decisions-v2.md) | the defaults chosen for v2 and how to reverse them |
| [docs/advanced-design.md](docs/advanced-design.md) | research proposal: anchors, routing, multi-vector, training, highlights, compression |
| [docs/design-notes.md](docs/design-notes.md) | the original Week 1 brief |

## Install

```bash
uv tool install git+https://github.com/<org>/codemem   # or: pipx install git+...
```

For development:

```bash
uv sync
uv run pytest              # fast suite, FakeEmbedder, no model download
uv run pytest -m model     # real jina-code-embeddings-0.5b (downloads ~1 GB once)
```

Python 3.11+. Works on Windows, macOS and Linux. PyTorch from PyPI is CPU-only on Windows,
which is the default device here.

## Quick start

```bash
cd path/to/repo
codemem init --agents claude          # writes .mcp.json (asks first), then builds the index
codemem search "disabled users stay logged in" --debug
codemem status
```

| Command | What it does |
|---|---|
| `codemem init [PATH] [--agents claude,cursor,codex] [--no-index] [--write-agent-notes] [--dry-run] [-y]` | Register with agents, then index |
| `codemem index [PATH] [--full] [--no-cache] [--json]` | Build or incrementally update the index (`--no-cache`: cold timing) |
| `codemem search QUERY [-k 10] [--signals bm25,code,usage] [--path-prefix DIR] [--kinds function,method] [--language go] [--exclude-tests] [--json] [--debug]` | Search |
| `codemem status [PATH] [--json]` | Counts, models, indexed commit, staleness |
| `codemem watch [PATH]` | Foreground watcher: re-index on save |
| `codemem mcp [PATH]` | MCP server over stdio (what agents launch) |
| `codemem languages` | Supported languages and file extensions |

Every command accepts `--index-dir DIR`. The eval harness uses it for per-commit indexes.

### Agents

- **Claude Code:** `init --agents claude` writes a project `.mcp.json`. You can also run
  `claude mcp add codemem -- codemem mcp`.
- **Cursor:** `init --agents cursor` writes `.cursor/mcp.json`.
- **Codex:** `init --agents codex` prints a `~/.codex/config.toml` snippet. It never edits
  that global file.

The MCP server exposes three tools: `search_code(query, k, path_prefix)`, `get_chunk(ref)`
and `index_status()`. On startup it answers the handshake immediately, runs a hash-based
catch-up (or the first full index) in the background, and starts a file watcher. Until the
first index is done, search results carry an "indexing, X% done" note.

## How it works

```
walk source files (9 languages; respects .gitignore; skips vendored/generated/minified)
  -> tree-sitter chunks: functions, methods, classes (as skeletons), top-level code blocks
  -> call graph (name heuristic, per language family)
  -> texts per chunk: code (with a path/scope header; long code split into windows), usage
     (callers/tests), summary (slot)
  -> vectors (jina-code-embeddings-0.5b, fp16 on GPU), reused by text hash from the index or a
     shared cache; stored as float16 rows in SQLite, searched through a derived FAISS index
  -> SQLite: chunks, FTS5 (5 weighted BM25 fields), calls/edges, vectors
search: BM25 top-N + vector top-N per vector type (a chunk scores by its best window)
  -> RRF (k=60) -> filters (kinds, languages, tests) -> result cards
```

- **Incremental updates** re-chunk only changed files (content hash, mtime pre-check), rebuild
  all texts, and store vectors only for texts whose hash changed. Renaming a caller therefore
  refreshes the callee's usage vector and leaves its code vector alone.
- **Ablations:** pick the signals per query (`--signals bm25,usage`). Each vector set can be
  enabled or disabled, or given its own model, in the config.
- **Crash safety:** vectors are committed to SQLite with everything else; the FAISS files are
  derived and rebuilt from the rows (no model needed) when they are missing or out of date.
- **Concurrency:** one writer per index (OS file lock) and SQLite WAL, so searches keep
  working during updates.

### Code map

| Module | Role |
|---|---|
| `config.py` | settings, index paths, per-vector-type models, `index_settings()` |
| `schema.py` | `Chunk` dataclass, keys, hashes |
| `languages/` | one spec per language (node types, names, calls, tests) + registry |
| `chunker.py` | generic tree-sitter chunking + call extraction |
| `tokenize.py` | code-aware BM25 tokenization (shared by index and query) |
| `callgraph.py` | call resolution heuristic (isolated so it can be replaced) |
| `texts.py` | text-builder registry: `code`, `usage`, `summary` slot |
| `embedder.py` | `Embedder` interface, sentence-transformers/jina, `FakeEmbedder` |
| `vectorcache.py` | shared content-addressed vector cache |
| `store.py` | SQLite (vectors included) + derived FAISS `IndexIDMap2(IndexFlatIP)`, filters |
| `indexer.py` | full + incremental indexing, timings |
| `search.py` | BM25, vector search, RRF, result cards (pure library function) |
| `service.py` | long-lived owner of an index: background updates, progress, watcher |
| `watcher.py` | watchdog + debounce |
| `prompts.py` | **all** agent-facing text (tool descriptions, instructions, notes) |
| `agents.py` | agent config writers for `init` |
| `server.py`, `cli.py`, `render.py` | thin front-ends |

Library use (for retrieval and eval work):

```python
from codemem.service import CodememService
svc = CodememService("path/to/repo", index_dir="idx/requests@abc123")
svc.update()
resp = svc.search("retry on connection failure", k=10, signals=["bm25", "code"], debug=True)
print(resp.to_dict())
```

## Configuration

`~/.codemem/config.toml`, overridden per repo by `<repo>/.codemem.toml`, then by environment
variables (`CODEMEM_HOME`, `CODEMEM_DEVICE`, `CODEMEM_MODEL`, `CODEMEM_STEERING`).

```toml
device = "auto"              # auto | cpu | xpu | cuda | mps   (auto = cuda, then mps, else cpu)
dtype = "auto"               # auto = float16 on cuda/mps, float32 on cpu
embedding_dim = 256          # optional Matryoshka truncation; omit for full 896 (no re-embedding)
batch_size = 16
max_seq_length = 1024
steering = "light"           # none | light | strong  (agent-study variable)
max_file_size = 1000000
ignore = ["migrations/"]     # extra gitignore-style patterns
use_default_ignore = true    # also skip vendor/, *.min.js, *_pb2.py, *.pb.go, ...
skip_generated = true        # skip "Code generated ... DO NOT EDIT" / "@generated" files
languages = ["python", "go"] # optional; default: every supported language
code_header = true           # path / enclosing-scope header above embedded code
window_chars = 3000          # longer code is split into windows (default from max_seq_length)
vector_cache = "global"      # global | off (reuse vectors across indexes)
kinds = ["function", "method"]  # optional search-time filter; default: every kind
test_weight = 1.0            # search-time: multiply test chunks' scores (0 drops them)

[vectors.code]
model = "jinaai/jina-code-embeddings-0.5b"
[vectors.usage]
model = "jinaai/jina-code-embeddings-0.5b"
enabled = true
[vectors.summary]
enabled = false              # slot only in Week 1

[bm25]
weights = [10.0, 3.0, 5.0, 2.0, 1.0]   # name, path, signature, doc, body (v1 triples accepted)
[rrf]
k = 60
weights = { bm25 = 1.0, code = 1.0, usage = 1.0 }
[usage]
max_defs_per_name = 5
max_items = 20
include_commits = false
```

Changing a vector type's model re-embeds only that vector set; changing `embedding_dim` only
rebuilds the FAISS index from the stored vectors.
`CODEMEM_MODEL=fake` uses the hash-based `FakeEmbedder` everywhere, which is handy for fast
dev runs.

**Intel Arc / XPU:** `device = "xpu"` needs a PyTorch build with XPU support (installed from
PyTorch's XPU wheel index). This is experimental: if `torch.xpu` is unavailable, codemem logs
a warning and falls back to CPU.

**Apple Silicon / MPS:** `device = "mps"` uses the Mac GPU through the standard PyTorch wheel.
`auto` picks it when CUDA is unavailable. On other platforms, codemem logs a warning and falls
back to CPU.

## Index location

`~/.codemem/indexes/<repo-name>-<hash-of-abs-path>/` by default (`CODEMEM_HOME` moves the
base). It contains `index.db`, `vec_<type>.faiss` (+ `.json` with its epoch) and `write.lock`.
The shared vector cache is `~/.codemem/cache/vectors.db`.

## Evaluating

The eval harness lives in `eval/` (see `eval/README.md`). To run codemem v2's systems on the dev
tasks:

```bash
cd eval && uv sync --extra codemem
uv run cmeval run --tasks tasks/swebv-dev50.jsonl --config configs/codemem-v2.toml --run-id my-run
uv run cmeval score my-run            # --tokens estimate if no ANTHROPIC_API_KEY
uv run cmeval report my-run --baseline cm2-bm25 \
    --primary cm2-bm25-code --primary cm2-bm25-code-usage
```

`configs/codemem-v2.toml` holds search-time variants that share one index.
`configs/codemem-v2-ablations.toml` holds index-time ablations, each with its own index.
`configs/baseline-v2.toml` adds the grep baselines (they need ripgrep).
To compare two scored runs task by task:

```bash
uv run python ../scripts/compare_scores.py RUN_A/scores.jsonl.gz SYSTEM_A RUN_B/scores.jsonl.gz SYSTEM_B
```

## License note

`jina-code-embeddings` models are reportedly licensed for **non-commercial** use (CC BY-NC
4.0). That's fine for this course project; check before any other use.
