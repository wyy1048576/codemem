# codemem

Local code search for coding agents. Point it at a repository in any of nine languages (Python,
JavaScript, TypeScript, Go, Java, C, C++/CUDA, Rust). It indexes every function, class and block
of top-level code, and answers plain-language questions with a short ranked list of places in the
code, through **MCP** for agents and a **CLI** for people and scripts. Your code never leaves the
machine unless you choose an embedding API.

**What it is for:** vague, feature-level questions in a codebase you don't know well, such as
"I want to add login auth, where do I start?" or "add OCR to my upload pipeline". Keyword search
fails on these and grep takes many tries. codemem works next to grep, which stays the tool for
exact strings.

| Doc | For |
|---|---|
| [docs/architecture.md](docs/architecture.md) | how the whole system works and why, with diagrams and one running example |
| [docs/data-model.md](docs/data-model.md) | the contracts: exact record formats, MCP tool outputs, what the eval adapter relies on, the config schema, plugin interfaces |
| [docs/decisions.md](docs/decisions.md) | running it: dependencies and what happens when one is down, limits, keys, files |
| [docs/advanced-design.md](docs/advanced-design.md) | exploratory: research directions (anchors, routing, multi-vector, training, highlights, compression) |
| [docs/exa.md](docs/exa.md) | exploratory: what we take from Exa's engineering blog |

## Install

```bash
uv tool install git+https://github.com/<org>/codemem   # or: pipx install git+...
```

For development:

```bash
uv sync
uv run pytest              # fast suite with a fake embedding model, no download
uv run pytest -m model     # the real jina-code-embeddings-0.5b (downloads ~1 GB once)
```

Python 3.11+, on Windows, macOS or Linux. In this workspace, run `source .cache/env.sh` first, so
models, caches and indexes stay inside the project.

## Quick start

```bash
cd path/to/repo
codemem init --agents claude          # registers the MCP server (asks first), then builds the index
codemem search "disabled users stay logged in" --debug
codemem status
```

| Command | What it does |
|---|---|
| `codemem init [PATH] [--agents claude,cursor,codex] [--no-index] [--write-agent-notes] [--dry-run] [-y]` | register with agents, download the model, then build the index (`--no-index` skips the build) |
| `codemem index [PATH] [--full] [--no-cache] [--verify] [--json]` | build or update the index (`--no-cache`: cold timing; `--verify`: compare with a fresh build) |
| `codemem search QUERY [-k 10] [--signals bm25,code,usage] [--path-prefix DIR] [--kinds function,method] [--language go] [--tests include\|exclude\|only] [--json] [--debug]` | search |
| `codemem status [PATH] [--json]` | what is indexed, pending or skipped, which model, the indexed commit |
| `codemem watch [PATH]` | a foreground watcher: re-index on save |
| `codemem mcp [PATH]` | the MCP server over stdio (what agents launch) |
| `codemem languages` | supported languages and file extensions |

Every command accepts `--index-dir DIR`; the eval uses it for one index per commit.

## Using it from an agent

- **Claude Code:** `init --agents claude` writes a project `.mcp.json`. Or run
  `claude mcp add codemem -- codemem mcp`.
- **Cursor:** `init --agents cursor` writes `.cursor/mcp.json`.
- **Codex:** `init --agents codex` prints a `~/.codex/config.toml` snippet; it never edits that
  file.
- **No `codemem` command on PATH** (installed in a virtualenv): `init` registers
  `<that python> -m codemem mcp` instead, which works while that environment exists.

The agent gets four tools: `search_code` (plain-language or identifier search), `get_chunk` (one
result in full, with its callers and callees), `index_status` and `refresh_index`. Every search
first catches up on your latest saves, so an agent finds the code it just wrote
([architecture.md §4](docs/architecture.md)).

## Configuration

`~/.codemem/config.toml`, overridden per repo by `<repo>/.codemem.toml`, then by environment
variables (`CODEMEM_HOME`, `CODEMEM_DEVICE`, `CODEMEM_MODEL`, `CODEMEM_STEERING`,
`CODEMEM_VECTOR_CACHE`). The defaults, and why they have their values, are in
[decisions.md §3](docs/decisions.md); what each change redoes is in §5 there.

```toml
device = "auto"              # auto | cpu | cuda | mps | xpu   (auto = cuda, then mps, else cpu)
dtype = "auto"               # auto = float16 on cuda/mps, float32 on cpu
embedding_dim = 256          # optional: shorter vectors (Matryoshka); omit for the full 896
batch_size = 16              # texts per model call
max_seq_length = 1024        # tokens per embedded text; longer code is split into windows
max_file_size = 10000000     # larger files are listed as skipped, never silently
ignore = ["migrations/"]     # extra gitignore-style patterns
use_default_ignore = true    # also skip vendor/, *.min.js, *_pb2.py, *.pb.go, ...
skip_generated = true        # skip files marked "Code generated ... DO NOT EDIT" or "@generated"
languages = ["python", "go"] # default: every supported language
code_header = true           # put the path and enclosing class above the embedded code
vector_cache = "global"      # global = reuse vectors across indexes on this machine | off
vector_backend = "faiss"     # the in-memory search index; a plugin class can replace it (below)
kinds = ["function", "method"]  # search-time filter; default: every kind
test_weight = 1.0            # search-time: lower it to rank tests lower
kind_weights = { class = 1.0, block = 1.0 }  # search-time: lower them to rank classes or blocks lower
steering = "light"           # none | light | strong: how strongly agents are told to use codemem
debounce_ms = 500            # the index updates once saves stop for this long,
debounce_max_wait_ms = 2000  # or at the latest this long after the first save
catchup_budget_ms = 4000     # how long a search may spend catching up on recent saves

[vectors.code]
model = "jinaai/jina-code-embeddings-0.5b"   # a Hugging Face name, or a local model folder
[vectors.usage]
model = "jinaai/jina-code-embeddings-0.5b"

[bm25]
weights = [10.0, 3.0, 5.0, 2.0, 1.0]   # name, path, signature, doc, body
query_terms = 32             # queries drop stopwords; 0 keeps every word
common_share = 0.0           # a query over query_terms words also drops words found in more than
                             # this share of chunks: faster, less accurate
[rrf]
k = 60
weights = { bm25 = 1.0, code = 1.0, usage = 1.0 }
[usage]
max_defs_per_name = 5        # a name defined more often than this is not linked
max_items = 20               # caller and test lines per usage text
include_commits = false      # add recent commit messages to usage texts (needs git)
```

**Embeddings through an API** (off by default). Any OpenAI-compatible endpoint works: Nebius,
OpenAI, Together, a self-hosted vLLM or TEI server, Ollama. The key is read from the named
environment variable at each request and never stored:

```toml
[embedding]
provider = "openai"                 # local (default) | openai
model = "Qwen/Qwen3-Embedding-8B"   # used for every vector type, documents and queries alike
base_url = "https://api.studio.nebius.com/v1"
api_key_env = "NEBIUS_API_KEY"      # "" = no key (a local server)
dimensions = 1024                   # optional: shorter vectors
query_prefix = "Instruct: Given a code search request, retrieve the relevant code\nQuery: "
batch_size = 64                     # texts per request
max_concurrency = 4                 # requests in flight
```

This sends your code to the provider, and `codemem status` says so. With an API,
`[vectors.*] model` is not used. A smoke test against Nebius: `NEBIUS_API_KEY=… uv run pytest -m api`.

**Your own model, embedder or search index**, for experiments such as a fine-tuned encoder or an
HNSW index:

```toml
vector_backend = "mypkg.vectors:HnswStore"   # default "faiss" (exact search)

[vectors.code]
model = "/models/my-code-encoder"            # a local folder
embedder = "mypkg.embed:MyEmbedder"          # optional; default: sentence-transformers
version = "run-7"                            # optional label for the weights
```

- **A model in a local folder** is named by a hash of its files, so new weights saved over the
  folder are re-embedded at the next update and never served from the vector cache. Each file is
  read once (about 1 s per GB) and its hash kept in `~/.codemem/model_hashes.json`. `version`
  names the weights yourself instead.
- **An embedder** is a subclass of `codemem.embedder.Embedder` with `dim`, `embed_documents` and
  `embed_queries`, built as `MyEmbedder(model, config)`. codemem normalizes its vectors. A model
  that sentence-transformers can load needs no embedder, only `model`.
- **A search index** is a subclass of `codemem.store.VectorStore` with `upsert`, `remove`, `search`,
  `ids` and `__len__`, built as `HnswStore(dim)`. `search` returns at most k `(id, score)` pairs,
  best first, with real similarity scores, and only ids in `allowed_ids` when it is given. Saving
  it is optional (`to_bytes` / `from_bytes`, and a file `suffix`); one that isn't saved is rebuilt
  from the stored vectors at each start. Switching re-embeds nothing.
- `tests/test_plugins.py` has a small numpy search index and a wrapped embedder to copy from.

**Other notes:**
- `CODEMEM_MODEL=fake` uses a fast, meaningless hash-based model everywhere, for tests and timing.
- On Apple Silicon, `auto` picks the Mac GPU (`mps`). `device = "xpu"` (Intel Arc) needs a
  PyTorch build with XPU support, and falls back to the CPU with a warning.

## Where things are stored

An index lives in `~/.codemem/indexes/<repo-name>-<hash of its path>/` (`CODEMEM_HOME` moves
`~/.codemem`), and every vector computed on the machine in `~/.codemem/cache/vectors.db`. What each
file holds and what is safe to delete: [decisions.md §6](docs/decisions.md).

## Evaluating

The eval harness lives in `eval/` (Andrew's `cmeval`; see `eval/README.md`). codemem's systems are
in `eval/configs/codemem-v3.toml`: they share one index and differ only at search time (keywords
only, keywords and code, everything, and weight variants). The grep baselines are in
`configs/grep.toml` (they need ripgrep).

```bash
cd eval && uv sync --extra codemem
uv run cmeval run --tasks tasks/swebv-dev50.jsonl --config configs/codemem-v3.toml --run-id my-run
uv run cmeval score my-run            # add --tokens estimate without an ANTHROPIC_API_KEY
uv run cmeval report my-run --baseline cm3-bm25 --primary cm3-bm25-code --primary cm3-full
uv run python ../scripts/compare_scores.py <scores A> <system A> <scores B> <system B>   # task by task
```

The full dev50 takes under an hour on a CUDA GPU, and about 14 times longer on an M1.

## Team

- **Andre:** backend, retrieval, research.
- **Andrew:** evaluation (`eval/`).
- **Wilson:** the first version of codemem, the plugin interfaces, and the MCP front-end.

## License note

The `jina-code-embeddings` models are reportedly licensed for **non-commercial** use (CC BY-NC
4.0). That's fine for this course project; check before any other use.
