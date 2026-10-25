# codemem

Local, agent-agnostic code search. Point it at a repository in any of nine languages (Python,
JavaScript, TypeScript, Go, Java, C, C++/CUDA, Rust). It indexes every function, class and block
of top-level code, and serves hybrid search (BM25 + embeddings, merged with RRF) to coding agents
over **MCP** and to people and eval scripts through a **CLI**. Your code never leaves the machine
unless you choose an embedding API.

**What it is for:** vague, feature-level questions in a codebase you don't know well, such as
"I want to add login auth, where do I start?" or "add OCR to my upload pipeline". Keyword search
fails on these and grep takes many tries. codemem works next to grep (which stays the tool for
exact strings), not instead of it.

**Status:** the v3 core (incremental updates, freshness, coverage, API embeddings, MCP changes) is
being built on branch `andre/backend-v3`. [docs/architecture.md](docs/architecture.md) §2 says
which parts already work.

| Doc | For |
|---|---|
| [docs/architecture.md](docs/architecture.md) | why it exists and how it works end to end, with one running example |
| [docs/data-model.md](docs/data-model.md) | every stored record, plus the contracts: MCP tools, the eval adapter, the config |
| [docs/decisions.md](docs/decisions.md) | every design choice and constant, why it has its value, and the parked questions |
| [docs/exa.md](docs/exa.md) | what we take from Exa's engineering blog |
| [docs/advanced-design.md](docs/advanced-design.md) | research questions and directions: anchors, routing, multi-vector, training, highlights, compression |

## Install

```bash
uv tool install git+https://github.com/<org>/codemem   # or: pipx install git+...
```

For development:

```bash
uv sync
uv run pytest              # fast suite with a fake embedding model, no download
uv run pytest -m model     # real jina-code-embeddings-0.5b (downloads ~1 GB once)
```

Python 3.11+. Works on Windows, macOS and Linux. In this workspace, run
`source .cache/env.sh` first, so models, caches and indexes stay inside the project.

## Quick start

```bash
cd path/to/repo
codemem init --agents claude          # writes .mcp.json (asks first), then builds the index
codemem search "disabled users stay logged in" --debug
codemem status
```

| Command | What it does |
|---|---|
| `codemem init [PATH] [--agents claude,cursor,codex] [--no-index] [--write-agent-notes] [--dry-run] [-y]` | register with agents, then index |
| `codemem index [PATH] [--full] [--no-cache] [--json]` | build or update the index (`--no-cache`: cold timing) |
| `codemem search QUERY [-k 10] [--signals bm25,code,usage] [--path-prefix DIR] [--kinds function,method] [--language go] [--exclude-tests] [--json] [--debug]` | search |
| `codemem status [PATH] [--json]` | counts, models, indexed commit, staleness |
| `codemem watch [PATH]` | foreground watcher: re-index on save |
| `codemem mcp [PATH]` | MCP server over stdio (what agents launch) |
| `codemem languages` | supported languages and file extensions |

Every command accepts `--index-dir DIR`; the eval harness uses it for per-commit indexes.

### Agents

- **Claude Code:** `init --agents claude` writes a project `.mcp.json`. You can also run
  `claude mcp add codemem -- codemem mcp`.
- **Cursor:** `init --agents cursor` writes `.cursor/mcp.json`.
- **Codex:** `init --agents codex` prints a `~/.codex/config.toml` snippet. It never edits that
  global file.

The MCP server exposes `search_code`, `get_chunk` and `index_status`; v3 adds `refresh_index`
(data-model.md §12.1).
- **Startup:** it answers the handshake at once, and runs the catch-up (or the first full index)
  in the background.
- **Watcher:** it starts a file watcher.
- **First index:** until it's done, search results carry an "indexing, X% done" note.

## Configuration

`~/.codemem/config.toml`, overridden per repo by `<repo>/.codemem.toml`, then by environment
variables (`CODEMEM_HOME`, `CODEMEM_DEVICE`, `CODEMEM_MODEL`, `CODEMEM_STEERING`,
`CODEMEM_VECTOR_CACHE`). Why each default has its value: [docs/decisions.md](docs/decisions.md) §2.

```toml
device = "auto"              # auto | cpu | xpu | cuda | mps   (auto = cuda, then mps, else cpu)
dtype = "auto"               # auto = float16 on cuda/mps, float32 on cpu
embedding_dim = 256          # optional Matryoshka truncation; omit for the full 896 (no re-embedding)
batch_size = 16
max_seq_length = 1024
steering = "light"           # none | light | strong  (agent-study variable)
max_file_size = 10000000     # larger files are listed as skipped (too_large), never silently
ignore = ["migrations/"]     # extra gitignore-style patterns
use_default_ignore = true    # also skip vendor/, *.min.js, *_pb2.py, *.pb.go, ...
skip_generated = true        # skip "Code generated ... DO NOT EDIT" / "@generated" files
languages = ["python", "go"] # optional; default: every supported language
code_header = true           # path / enclosing-scope header above embedded code
window_chars = 3000          # longer code is split into windows (default from max_seq_length)
vector_cache = "global"      # global | off (reuse vectors across indexes)
kinds = ["function", "method"]  # optional search-time filter; default: every kind
test_weight = 0.5            # search-time; v3 default: 1.0 (neutral)
kind_weights = { class = 0.5, block = 0.5 }  # search-time; v3 default: none
debounce_ms = 500            # the background writer starts once saves stop for this long,
debounce_max_wait_ms = 2000  # or at the latest this long after the first save
catchup_budget_ms = 4000     # a search first applies and embeds pending edits for at most this long

[vectors.code]
model = "jinaai/jina-code-embeddings-0.5b"
[vectors.usage]
model = "jinaai/jina-code-embeddings-0.5b"
[vectors.summary]
enabled = false              # slot only

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

**(v3) Remote embeddings,** opt-in. Any OpenAI-compatible endpoint works. The key is read from
the named environment variable and never stored:

```toml
[embedding]
provider = "openai"
model = "Qwen/Qwen3-Embedding-8B"
base_url = "https://api.studio.nebius.com/v1"   # from your provider's docs
api_key_env = "NEBIUS_API_KEY"
dimensions = 1024
```

Other notes:
- **Changing settings.** Changing a vector type's model re-embeds only that vector set. Changing
  `embedding_dim` only rebuilds the FAISS index from the stored vectors.
- **Fast dev runs.** `CODEMEM_MODEL=fake` uses the hash-based `FakeEmbedder` everywhere.
- **Apple Silicon (MPS):** `device = "mps"` uses the Mac GPU, and `auto` picks it when CUDA is
  unavailable.
- **Intel Arc (XPU):** `device = "xpu"` needs a PyTorch build with XPU support. It is
  experimental and falls back to CPU with a warning.

## Index location

`~/.codemem/indexes/<repo-name>-<hash-of-abs-path>/` by default (`CODEMEM_HOME` moves the base).
It contains `index.db`, `vec_<type>.faiss` (plus a `.json` note with its epoch) and `write.lock`.
The shared vector cache is `~/.codemem/cache/vectors.db`.

## Evaluating

The eval harness lives in `eval/` (Andrew's `cmeval`; see `eval/README.md`). To run codemem's
systems on the dev tasks:

```bash
cd eval && uv sync --extra codemem
uv run cmeval run --tasks tasks/swebv-dev50.jsonl --config configs/codemem-v2.toml --run-id my-run
uv run cmeval score my-run            # --tokens estimate if no ANTHROPIC_API_KEY
uv run cmeval report my-run --baseline cm2-bm25 --primary cm2-bm25-code --primary cm2-full
```

Configs:
- `configs/codemem-v2.toml` holds search-time variants that share one index. Each system pins its
  weights, so a name keeps its meaning if the defaults change.
- `configs/codemem-v2-weights.toml` holds the weightings v2's defaults were chosen from.
- `configs/codemem-v2-ablations.toml` holds index-time ablations, each with its own index.
- `configs/baseline-v2.toml` adds the grep baselines (they need ripgrep).

**The full dev50** runs on Andrew's machine or a CUDA GPU in under an hour. The M1 is about 14×
slower:

```bash
uv run cmeval run --tasks tasks/swebv-dev50.jsonl --config configs/codemem-v2.toml --run-id dev50-v2
uv run cmeval score dev50-v2
uv run python ../scripts/compare_scores.py results/2026-10-23-dev50-final/scores.jsonl.gz cm-bm25-code-usage \
    $CMEVAL_HOME/runs/dev50-v2/scores.jsonl cm2-full
```

`compare_scores.py` compares any two scored runs task by task.

## Team

- **Andre:** backend, retrieval, research.
- **Andrew:** evaluation (`eval/`).
- **Wilson:** the Week 1 MVP, and the MCP front-end's portability (to be compared with v3).

## License note

`jina-code-embeddings` models are reportedly licensed for **non-commercial** use (CC BY-NC 4.0).
That's fine for this course project; check before any other use.
