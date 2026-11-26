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
| [docs/plan/overview.md](docs/plan/overview.md) | the next phase: the plan, its three tracks and the dates. Nothing in it is built yet |
| [CONTRIBUTING.md](CONTRIBUTING.md) | how we work: who has which track, what to read first, the work log |

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
codemem init --agents claude          # registers the MCP server and adds a note to CLAUDE.md (asks first), then builds the index
codemem search "disabled users stay logged in" --debug
codemem status
```

| Command | What it does |
|---|---|
| `codemem init [PATH] [--agents claude,cursor,codex] [--no-index] [--no-agent-notes] [--write-hooks] [--dry-run] [-y]` | register with agents, add the agent note, download the model, then build the index (`--no-index` skips the build) |
| `codemem index [PATH] [--full] [--no-cache] [--verify] [--json]` | build or update the index (`--no-cache`: cold timing; `--verify`: compare with a fresh build) |
| `codemem search QUERY [-k 10] [--signals bm25,code,usage] [--path-prefix DIR] [--kinds function,method] [--language go] [--tests include\|exclude\|only] [--json] [--debug]` | search |
| `codemem status [PATH] [--json]` | what is indexed, pending or skipped, which model, the indexed commit |
| `codemem watch [PATH]` | a foreground watcher: re-index on save |
| `codemem mcp [PATH]` | the MCP server over stdio (what agents launch) |
| `codemem serve-embeddings [PATH] [--host 127.0.0.1] [--port 8791]` | serve the local embedding model to other codemem processes, over HTTP ("One model for several codemem processes", below) |
| `codemem languages` | supported languages and file extensions |
| `codemem hook` | two Claude Code hooks that point the agent at `search_code` when it has no lead (see below) |

The commands that use an index accept `--index-dir DIR`; the eval uses it for one index per commit.

## Using it from an agent

- **Claude Code:** `init --agents claude` writes a project `.mcp.json`, with `"alwaysLoad": true`.
  Claude Code otherwise keeps an MCP server's tools behind a tool-search step, where the agent
  sees only their names; with it, codemem's tools and their descriptions are there from the first
  turn. `claude mcp add codemem -- codemem mcp` registers the server without that setting.
- **Cursor:** `init --agents cursor` writes `.cursor/mcp.json`.
- **Codex:** `init --agents codex` prints a `~/.codex/config.toml` snippet; it never edits that
  file.
- **No `codemem` command on PATH** (installed in a virtualenv): `init` registers
  `<that python> -m codemem mcp` instead, which works while that environment exists.
- **The agent note.** `init` also appends a short "Code search" note to `CLAUDE.md` (Claude
  Code) or `AGENTS.md` (Cursor, Codex), which tells the agent when to call `search_code`. It is
  part of what `init` shows and asks about before writing, it leaves the rest of the file as it
  is, and a second `init` does not add it again. `--no-agent-notes` skips it, and so does
  `steering = "none"`.
- **Claude Code, optional: two hooks that point the agent at codemem when it has no lead.**
  `init --write-hooks` adds them to the repo's `.claude/settings.json`. It keeps every other
  setting and hook in that file, and running it again does not add them twice. Or add them by
  hand:

  ```json
  {"hooks": {
    "PreToolUse": [{"matcher": "Grep|Glob|mcp__codemem__search_code",
      "hooks": [{"type": "command", "command": "codemem hook", "timeout": 10}]},
      {"matcher": "Bash", "hooks": [
        {"type": "command", "if": "Bash(rg *)", "command": "codemem hook", "timeout": 10},
        {"type": "command", "if": "Bash(grep *)", "command": "codemem hook", "timeout": 10},
        {"type": "command", "if": "Bash(find *)", "command": "codemem hook", "timeout": 10}]}],
    "PostToolUse": [{"matcher": "Grep|Glob|Read|mcp__codemem__(search_code|get_chunk)",
      "hooks": [{"type": "command", "command": "codemem hook", "timeout": 10}]}]}}
  ```

  - **The first search.** The first Grep or Glob of a session is refused once, and the agent is
    told to call `search_code` unless it already has an exact name, path or error string. The
    repeated call goes through. Nothing happens if `search_code` was called first. A shell command
    that runs `rg`, `grep` or `find` counts as a search here too. That is a check for the word,
    not a reading of the command: `pytest | grep FAILED` can count, which costs one refusal in a
    session, and a search written some other way does not. The `if` lines make Claude Code start
    the command only for those shell commands, so tests, git and builds are not slowed down.
  - **The lost trail.** Nothing is refused. After a Grep or Glob that found nothing, matched more
    than 50 files, or was the third search in a row with no Read, `search_code` or `get_chunk` in
    between, the agent gets a one-line reminder to try `search_code`. The two searches after a
    reminder get none. Shell commands take no part in this one.

  Either hook works without the other. The PowerShell tool is not covered. The command
  takes about 0.2 s, and the second hook also runs after every Read.

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
model_idle_minutes = 0       # free the local model after this many minutes without a search or an
                             # edit (1.3 GB on an M1); the next one loads it again. 0 keeps it

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
dimensions = 1024                   # optional: shorter vectors; a longer reply is cut to this length
query_prefix = "Instruct: Given a code search request, retrieve the relevant code\nQuery: "
document_prefix = ""                # before each document
space = ""                          # optional: a name for these vectors, in place of the address (below)
batch_size = 64                     # texts per request
max_concurrency = 4                 # requests in flight
```

This sends your code to the provider, and `codemem status` says so. With an API,
`[vectors.*] model` is not used. A smoke test against Nebius: `NEBIUS_API_KEY=… uv run pytest -m api`.

**An index belongs to the address it was built through, unless you name its vectors.** The index
remembers who made its vectors: the address in `base_url`, the model, `dimensions` and the
document prefix. Change one and the vectors are embedded again. `space` is a name that takes the
place of the address:

```toml
space = "qwen8b-1024"               # up to 64 characters, no spaces, no "|"
```

Two configurations with the same `space`, model, `dimensions` and document prefix share vectors,
whatever their `base_url`. Setting it is a promise that every address you use under that name
returns the same vectors for the same text: the same model and weights, at the same precision.
codemem cannot check that. Use it when a provider moves to a new host, when a second provider
serves the same model, and when one server is reached at different addresses (next section).

**One model for several codemem processes.** Each codemem that runs the local model keeps it in
memory, 1.3 GB on an M1's GPU. With several git worktrees, or several containers, run the model
once and let every codemem embed through it:

```bash
codemem serve-embeddings            # on 127.0.0.1:8791
```

It serves the local model your config selects (`[vectors.*] model`, `device`, `dtype`,
`max_seq_length`) in the same OpenAI style as an API, and prints the settings a client needs:

```toml
[embedding]
provider = "openai"
base_url = "http://127.0.0.1:8791/v1"
model = "jinaai/jina-code-embeddings-0.5b"
space = "st-L1024-float16-mps"
query_prefix = "Find the most relevant code snippet given the following query:\n"
document_prefix = "Candidate code snippet:\n"
```

Put that section in `~/.codemem/config.toml`, or in a repo's `.codemem.toml`, of every codemem
that should use the server. The server itself always serves the local model, so the section may
sit in the config file the server reads too. Keep all of it:

- **The two prefixes are how a query differs from a document.** The server embeds each text exactly
  as it is sent, and the client puts the model's prompt in front. A query and a document then get
  the same vectors as with the model in process: for `jina-code-embeddings-0.5b` in float16 on an
  M1 the numbers are identical (`scripts/check_served_vectors.py` checks any model and device).
- **`space` names the model's settings on the server:** its runtime, longest text, precision and
  device. It lets an index built through one address be used through another.

*In containers.* The server runs on the host, where the GPU is. Each container has a codemem and
the same section, with the host's address, as the container sees it, in `base_url`:

| Docker | The server listens on | `base_url` in the container |
|---|---|---|
| Docker Desktop (macOS, Windows) | the loopback address, the default | `http://host.docker.internal:8791/v1` |
| Docker Engine on Linux | the gateway address of the containers' network: `codemem serve-embeddings --host 172.18.0.1` | `http://172.18.0.1:8791/v1` |

`docker network inspect <network> -f '{{(index .IPAM.Config 0).Gateway}}'` prints the gateway
address. The address plays no part in the index: one built on the host opens in a container
without embedding anything again, because both sides carry the same `space`.

*A client without the model's packages.* A codemem that embeds through the server, or through an
API, never imports PyTorch or sentence-transformers. Its environment can be built without the two,
which keeps a container image small. uv leaves named packages out of an install, with everything
only they need:

```bash
printf 'torch\nsentence-transformers\n' > no-local-model.txt
uv pip install --excludes no-local-model.txt git+https://github.com/<org>/codemem   # or: uv tool install --excludes ...
```

That environment is 46 packages and 81 MB on an Apple Silicon Mac, against 887 MB for the one
`uv sync` builds. A codemem in it that is asked for the local model stops with one sentence: what
is missing, what to install, and what to set instead.

*A key.* The server listens on the loopback address unless `--host` says otherwise, and asks for
no key. To ask for one, start it with the key in the environment variable `CODEMEM_SERVE_KEY`;
the printed section then has `api_key_env = "CODEMEM_SERVE_KEY"`, and each client needs the same
variable in its own environment. The key is never written to a file or a log.

The server holds no index and no other state, so it can be restarted at any time. What happens
while it is down, and its limits: [decisions.md §2 and §3](docs/decisions.md).

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
  `serve-embeddings` serves it too.
- On Apple Silicon, `auto` picks the Mac GPU (`mps`). `device = "xpu"` (Intel Arc) needs a
  PyTorch build with XPU support, and falls back to the CPU with a warning.

## Where things are stored

An index lives in `~/.codemem/indexes/<repo-name>-<hash of its path>/` (`CODEMEM_HOME` moves
`~/.codemem`), and every vector computed on the machine in `~/.codemem/cache/vectors.db`. What each
file holds and what is safe to delete: [decisions.md §6](docs/decisions.md).

Each git worktree is a checkout with an index of its own: run codemem inside it. The index starts
as a copy of another checkout's index, so it is ready in seconds, and it is deleted after the
worktree is removed ([architecture.md §4.6](docs/architecture.md)).

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
