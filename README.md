# codemem

Local, agent-agnostic code search. Point it at a Python repository and it indexes every
function, then serves hybrid search (BM25 + embeddings, merged with RRF) to coding agents
over **MCP** and to humans and eval scripts through a **CLI**. Your code never leaves the machine.

Design and decisions: [docs/design-notes.md](docs/design-notes.md).

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
codemem init --agents claude          # writes .mcp.json + the reindex skill (asks first), then indexes
codemem search "disabled users stay logged in" --debug
codemem status
```

| Command | What it does |
|---|---|
| `codemem init [PATH] [--agents claude,cursor,codex] [--no-index] [--write-agent-notes] [--dry-run] [-y]` | Register with agents, then index |
| `codemem index [PATH] [--full] [--json]` | Build or incrementally update the index |
| `codemem search QUERY [-k 10] [--signals bm25,code,usage] [--path-prefix DIR] [--json] [--debug]` | Search |
| `codemem status [PATH] [--json]` | Counts, models, indexed commit, staleness |
| `codemem watch [PATH]` | Foreground watcher: re-index on save |
| `codemem mcp [PATH]` | MCP server over stdio (what agents launch) |

Every command accepts `--index-dir DIR`. The eval harness uses it for per-commit indexes.

### Agents

- **Claude Code:** `init --agents claude` writes a project `.mcp.json` and the skill
  `.claude/skills/codemem-reindex/SKILL.md`, which tells the agent when to reindex (below).
  You can also run `claude mcp add codemem -- codemem mcp`.
- **Cursor:** `init --agents cursor` writes `.cursor/mcp.json`.
- **Codex:** `init --agents codex` prints a `~/.codex/config.toml` snippet. It never edits
  that global file.

The MCP server exposes four tools: `search_code(query, k, path_prefix)`, `get_chunk(ref)`,
`index_status()` and `reindex()`. On startup it answers the handshake immediately and runs a
hash-based catch-up (or the first full index) in the background. Until the first index is
done, search results carry an "indexing, X% done" note.

### When the index updates

The MCP server does **not** re-index on save. The agent decides when:

- `index_status()` lists the files that differ from the index (from any source: the agent,
  the user, git), most depended-on first. For each one it gives `inbound_files` (how many
  other files call into it), `inbound_calls` and `percentile` (share of indexed files that
  fewer other files call into), plus `total_files` and whether git HEAD moved.
- `reindex()` updates the index and returns what changed. It re-embeds only changed texts,
  so its cost grows with the size of the change.
- The `codemem-reindex` skill tells the agent how to weigh how much changed against how
  central the changed files are. Its text lives in `prompts.py`.

`watch = true` in the config brings back re-index on save (watchdog, 400 ms debounce).
`codemem watch` always watches. Don't run `codemem index` while an MCP server is running on
the same index: the server keeps searching the vectors it loaded.

## How it works

```
walk .py files (respects .gitignore) -> tree-sitter chunks (one per function/method + file header)
  -> call graph (name heuristic) -> texts per chunk: code, usage (callers/tests)
  -> embed each text type into its own FAISS index (jina-code-embeddings-0.5b)
  -> SQLite: chunks, FTS5 (pre-tokenized, weighted BM25), calls/edges, embedding hashes
search: BM25 top-N + vector top-N per enabled set -> RRF (k=60) -> result cards
```

- **Incremental updates** re-chunk only changed files (content hash, mtime pre-check), rebuild
  all texts, and re-embed only the texts whose hash changed. Renaming a caller therefore
  refreshes the callee's usage vector and leaves its code vector alone.
- **Ablations:** pick the signals per query (`--signals bm25,usage`). Each vector set can be
  enabled or disabled, or given its own model, in the config.
- **Crash safety:** each `vec_<type>.faiss` has an `ids.json` sidecar. If an update is
  interrupted, the next run detects the mismatch and re-embeds what's missing.
- **Concurrency:** one writer per index (OS file lock) and SQLite WAL, so searches keep
  working during updates.

### Code map

| Module | Role |
|---|---|
| `config.py` | settings, index paths, per-vector-type models, model version hashes |
| `plugins.py` | loads `"module:Class"` plugins named in config |
| `schema.py` | `Chunk` dataclass, keys, hashes |
| `chunker.py` | tree-sitter Python chunking + call extraction |
| `tokenize.py` | code-aware BM25 tokenization (shared by index and query) |
| `callgraph.py` | call resolution heuristic (isolated so it can be replaced) |
| `texts.py` | text-builder registry: `code`, `usage` |
| `embedder.py` | `Embedder` interface, sentence-transformers/jina, `FakeEmbedder` |
| `store.py` | SQLite + `VectorStore` backend (default FAISS `IndexIDMap2(IndexFlatIP)`) |
| `indexer.py` | full + incremental indexing, timings |
| `search.py` | BM25, vector search, RRF, result cards (pure library function) |
| `service.py` | long-lived owner of an index: background updates, reindex, pending changes, watcher |
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
embedding_dim = 256          # optional Matryoshka truncation; omit for full 896
batch_size = 16
max_seq_length = 1024
steering = "light"           # none | light | strong  (agent-study variable)
max_file_size = 1000000
ignore = ["migrations/"]     # extra gitignore-style patterns
watch = false                # true: the MCP server re-indexes on save

[vectors.code]
model = "jinaai/jina-code-embeddings-0.5b"
[vectors.usage]
model = "jinaai/jina-code-embeddings-0.5b"
enabled = true

[bm25]
weights = [10.0, 5.0, 1.0]   # name, signature, body
[rrf]
k = 60
weights = { bm25 = 1.0, code = 1.0, usage = 1.0 }
[usage]
max_defs_per_name = 5
max_items = 20
include_commits = false
```

Changing a vector type's model (or `embedding_dim`) rebuilds only that vector set.
`CODEMEM_MODEL=fake` uses the hash-based `FakeEmbedder` everywhere, which is handy for fast
dev runs. It wins over a custom `embedder`.

### Swapping models, embedders and the vector store

```toml
vector_backend = "faiss"     # or "mypkg.vectors:LanceStore"; changing it re-embeds everything

[vectors.code]
model = "C:/models/my-code-encoder"   # hub name or local folder (use an absolute path)
embedder = "mypkg.embed:MyEmbedder"   # optional; default is sentence-transformers
version = "v3"                         # optional; see below
```

- **Embedder:** a subclass of `codemem.embedder.Embedder` (`dim`, `embed_documents`,
  `embed_queries`, L2-normalized float32 output), built as `MyEmbedder(model, config)`.
  A model that loads with sentence-transformers needs only `model`, no `embedder`.
- **Model version:** each vector set records a model id
  (`model[@embedding_dim][#version][+embedder]`). If it changes, that set is re-embedded.
  For a local model folder, `version` defaults to a hash of the folder's file contents, so
  retrained weights saved over the same folder are picked up on the next update. The hash
  is the same on every machine. File hashes are cached in `~/.codemem/model_hashes.json`, so
  each checkpoint is read once. Hub names get no version unless you set one.
- **Vector backend:** a subclass of `codemem.store.VectorStore`. It implements `upsert`,
  `remove`, `search`, `ids`, `__len__`, `save(path)`, `load(path)` and sets `suffix` (the
  saved name is `vec_<type><suffix>`, a file or a folder). `search` must return at most k
  `(id, score)` pairs, best first, with real similarity scores, filtered to `allowed_ids`
  when given. BM25, chunks and the call graph stay in SQLite. See `tests/test_plugins.py` for a
  small numpy backend and embedder.

**Intel Arc / XPU:** `device = "xpu"` needs a PyTorch build with XPU support (installed from
PyTorch's XPU wheel index). This is experimental: if `torch.xpu` is unavailable, codemem logs
a warning and falls back to CPU.

**Apple Silicon / MPS:** `device = "mps"` uses the Mac GPU through the standard PyTorch wheel.
`auto` picks it when CUDA is unavailable. On other platforms, codemem logs a warning and falls
back to CPU.

## Index location

`~/.codemem/indexes/<repo-name>-<hash-of-abs-path>/` by default (`CODEMEM_HOME` moves the
base). It contains `index.db`, `vec_<type>.faiss` (+ `.ids.json`; another backend uses its
own suffix) and `write.lock`.

## License note

`jina-code-embeddings` models are reportedly licensed for **non-commercial** use (CC BY-NC
4.0). That's fine for this course project; check before any other use.
