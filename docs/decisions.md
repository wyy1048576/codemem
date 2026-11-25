# Running codemem: dependencies, limits, keys and files

This page is for operating codemem: what it depends on and what happens when one of those is
missing or down, the limits it runs with and why they have their values, the keys that decide when
work is redone, and the files it keeps. How the system works is in
[architecture.md](architecture.md).

---

## 1. What depends on what

```
                 ┌─────────────────────────── installed with codemem ────────────────────────────┐
                 │  tree-sitter + 8 grammars ......... reading code (chunks, calls)               │
                 │  SQLite with FTS5 (in Python) ..... storing everything; keyword search         │
                 │  FAISS ............................ the in-memory vector search index         │
  codemem  ────► │  watchdog ......................... file events from the operating system     │
  (Python 3.11+) │  MCP SDK (mcp) + httpx ............ the MCP server; the API client             │
                 │  pathspec, numpy .................. .gitignore rules; vectors                   │
                 ├─────────────────────────── installed with codemem[local] ─────────────────────┤
                 │  sentence-transformers + PyTorch .. running the local embedding model          │
                 └────────────────────────────────────────────────────────────────────────────────┘
                 ┌─────────────────────────── outside codemem ─────────────────────────────────────┐
                 │  Hugging Face ..... the embedding model, downloaded once (~1 GB), then offline  │
                 │  the OS ........... file events (FSEvents, inotify, Windows)                    │
                 │  git (optional) ... the indexed commit; commit messages if you turn them on     │
                 │  an embedding API (optional, off by default) + its key in an environment var    │
                 │  a `codemem serve-embeddings` server (optional): one model for several codemem  │
                 └────────────────────────────────────────────────────────────────────────────────┘

  depends on codemem:  the eval's adapter (eval/src/cmeval/adapters/codemem.py), through the
                       library calls listed in architecture.md §8
```

In normal use (the local model, already downloaded), codemem needs nothing outside your machine.
A codemem that embeds through an API or a `serve-embeddings` server needs that endpoint for its
vectors, and no PyTorch: its environment is 89 MB, against 887 MB with `[local]` (Apple Silicon,
Python 3.11).

---

## 2. Each dependency: why it, and what if it's missing or down

| Dependency | Why this one | If it's missing or down | How you'd notice | Backup |
|---|---|---|---|---|
| **The embedding model**, `jinaai/jina-code-embeddings-0.5b`, from Hugging Face | trained for code search; small enough for a laptop (0.5B); free and private | Before the first download (no network, Hugging Face down, wrong name): searches answer from keywords only, each after a wait of about 4 s, and new edits wait in the queue. Once downloaded, it loads with no network | `index_status` shows the load error. Search notes say the model is "still loading" (a known gap, §8) | Keyword search keeps working. Copy the model cache (`HF_HOME`) from another machine, point `vectors.code.model` at a local folder, or use an API |
| **sentence-transformers + PyTorch** (the `local` extra) | run the model on CUDA, Apple GPUs (MPS) or the CPU | An install without the extra can't run the local model. `codemem index` and `search` stop with one sentence that names what is missing and both ways out. Under the MCP server, an update fails before it changes the index: an existing index keeps its chunks and vectors and answers from keywords, each search after a wait of about 4 s (§8), and a repo with no index gets none | the sentence, on the command line and as the error in `index_status` | `pip install "codemem[local]"`, or an embedding API, or a `serve-embeddings` server |
| **FAISS** (`faiss-cpu`) | exact vector search in memory, fast, no server, wheels for every platform | codemem doesn't start | an import error | none: required |
| **SQLite with FTS5** | ships with Python; transactions; built-in BM25 | without FTS5 (rare custom Python builds) no index can be created | an error on the first index | a standard Python build (python.org, Homebrew, uv) |
| **tree-sitter + grammars** (versions pinned) | one parser and official grammar for each of the nine languages | a language whose grammar fails can't be chunked; a file that fails to parse is indexed from what was recovered | `index_status` lists files with parse errors | none needed per file |
| **watchdog** (OS file events) | the same events API on macOS, Linux and Windows | network drives, WSL or Linux watch limits: no events | a warning in the log; `index_status` says "not watching" | automatic: a full check every 10 s and before each search (0.5 s on vLLM) |
| **git** (optional) | the indexed commit (for `index_status` and the eval), commit messages in usage texts if `include_commits` | no commit shown, no commit messages; everything else works | `indexed commit: -` in `index_status` | none needed |
| **MCP SDK** (`mcp` 2.x, pinned below 3) | the standard MCP server over stdio | the MCP server can't start; the CLI still works | agents can't connect | the CLI |
| **An embedding API** (optional: Nebius, OpenAI, a self-hosted server) | faster first builds of large repos, bigger models | a search waits about 31 s for retries, then fails (a known gap, §8); new edits wait in the queue and are retried | the search error names the provider; `index_status` doesn't flag it yet | none quick: another model means re-embedding everything, since vectors of different models can't mix. The same model at another address keeps the index if the config names the vectors with `space` (§5) |
| **A `codemem serve-embeddings` server** (optional) | one copy of the local model in memory (about 2.2 GB) for several codemem processes: one per git worktree, one per container. Its clients need no PyTorch and no GPU | The same as an API that is down: a search waits about 31 s for retries, then fails; new edits wait in the queue and are retried; `codemem index` stops with the error. Nothing is lost: the server holds no index and no state | the error names the address, `embedding request to 127.0.0.1:8791 failed`; `GET /health` on the server answers `{"status":"ok"}` when it is up | start it again, on any address: an index is tied to its `space`, not to the address. It takes its port first and then loads the model, so requests that arrive meanwhile wait for the model, not for a retry |

---

## 3. Operational choices, and why

The values codemem runs with, and why each was picked. All of these are settings
(README, "Configuration") except where the last column says constant.

| Choice | Value | Why | Change with |
|---|---|---|---|
| **where embeddings come from** | the local model | private, free, works offline; an API is opt-in, for speed or bigger models | `[embedding] provider`, `vectors.*.model` |
| **device and precision** | CUDA, else the Apple GPU, else CPU; float16 on a GPU | float16 halves memory and time and keeps the same top 10 (cosine ≥ 0.9997); a row that overflows is redone in float32 | `device`, `dtype` |
| **how long a search may catch up** | 4 s | Chosen on Oct 25 (Andre). A one-function edit takes 0.1–0.5 s, and 4 s covers about 30 average texts at the M1's 8.5 texts a second. A `git pull` or a formatter run is what hits the cap; then the search returns what the index has and its note names the files still pending, so the agent can search again or grep them. A wasted grep turn costs an agent more than the wait | `catchup_budget_ms` |
| **when a search doesn't wait at all** | more than 1,000 queued chunks, or a first build | that is minutes of embedding; answering at once with a note beats a 4 s wait that changes little | constant |
| **grouping saves** | 0.5 s after the last save, at most 2 s after the first | one editor action writes several files; the maximum stops a long burst from postponing indexing | `debounce_ms`, `debounce_max_wait_ms` |
| **safety full check** | every 5 min (every 10 s without file events) | catches a missed event; one check costs 0.3–0.5 s on vLLM | constants |
| **writing the search index to disk** | after 30 s idle, at shutdown, on `refresh_index` | writing it on every save blocked searches for 2.2 s on vLLM (520 MB of files, with 4 bytes per number); the CLI and the eval write at once, because the eval measures the index size | constant |
| **the vector cache** | on, shared by every index on the machine | rebuilds, branch switches and other commits cost no model calls | `vector_cache = "off"` |
| **file size cap** | 10 MB | hand-written files can reach megabytes (TypeScript's `checker.ts`); larger ones are generated data | `max_file_size` |
| **vendored and generated code** | skipped | copies crowd results and cost embedding time; `third_party/` is kept, as it is often the project's own code | `use_default_ignore`, `skip_generated` |
| **text length per vector** | 1,024 tokens (about 3,000 characters) | keeps CPU indexing tractable; longer code is split into windows, so nothing is lost | `max_seq_length` |
| **API requests** | 64 texts each, 4 at a time, 60 s timeout; 6 tries, waiting 1, 2, 4, 8, 16 s (or the server's Retry-After, up to 60 s) | provider rate limits and brief outages | `[embedding] batch_size`, `max_concurrency`, `timeout_s`; tries are a constant |
| **the embedding server's address** | `127.0.0.1`, port 8791 | the loopback address is reachable from this machine only; containers on Docker Desktop reach it as `host.docker.internal`. Another address is a choice to expose the model, made with `--host` | `codemem serve-embeddings --host`, `--port` |
| **the embedding server's key** | none | on the loopback address every client is a process of this machine. With `CODEMEM_SERVE_KEY` set in the server's environment, every request but `GET /health` must carry it as `Authorization: Bearer`; the server warns at start when it listens beyond the loopback address without one | the environment variable `CODEMEM_SERVE_KEY`, for the server and for each client (`api_key_env`) |
| **the embedding server's model calls** | one at a time, at most `batch_size` (16) texts each; between calls the request with the fewest texts left goes first | nothing guards a call of the local model against a second thread, so one thread makes them all. A search's single query then waits for one batch of another client's build, not for the build. Texts of several requests may share a call | `batch_size` in the server's config |
| **what one server costs a client** | 2 to 4 ms a query; 1.2 to 2.1 ms a text in a build | measured with a model that takes no time, for vectors of 896 numbers, on an M1 that other jobs kept busy (load average 13 to 21; `scripts/check_served_vectors.py --overhead`). Almost all of it is writing and reading the numbers as JSON text, 5.1 MB for 256 vectors. The model itself takes about 118 ms a text on the M1 (architecture.md §10) | not a setting |
| **agent-facing wording** | `light` | the middle of the agent study's three strengths | `steering` |

---

## 4. Constants

Values in the code, not in the config.

| Constant | Value | Where | What it controls |
|---|---|---|---|
| `CATCHUP_MAX_CHUNKS` | 1,000 | `service.py` | above this many queued chunks, a search answers without embedding first |
| `_BATCH` | 64 chunks | `service.py` | the background writer's stage B batch; a fresh edit waits behind at most one |
| `_CALL_CHARS` | 3,000 characters | `service.py` | the largest model call outside a build, so one call can't overrun a search's 4 s |
| `SAVE_AFTER_IDLE` | 30 s | `service.py` | writing the search index to disk |
| `RECONCILE_EVERY`, `POLL_EVERY` | 300 s, 10 s | `service.py` | the safety full check, with and without file events |
| `BURST_PATHS` | 2,000 paths | `service.py` | more changed paths at once become a full check |
| `_LONG_CLASS_LINES` | 80 lines | `service.py` | `get_chunk` shows a longer class as its outline and members |
| `_EMBED_GROUP`, `_BATCH_CHUNKS` | 256 texts, 512 chunks | `indexer.py` | model calls and stage B batches during a build (texts sorted longest first) |
| `_RACY_SECONDS` | 2 s | `indexer.py` | a file saved this close to a full check is re-hashed at the next one |
| skip checks | NUL in the first 8 KB; `@generated` in the first 2 KB; a JS/TS line over 5,000 characters | `indexer.skip_reason` | binary, generated and minified files |
| `_SIGNATURE_CHARS` | 120 | `texts.py` | how much of the signature a later window's header shows |
| `_QUERY_CACHE_SIZE` | 512 queries | `embedder.py` | query vectors kept in memory |
| `RETRIES`, `BACKOFF_S` | 6, 1 s doubling | `embedder.py` | API retries |
| `DEFAULT_PORT` | 8791 | `embedserver.py` | where `serve-embeddings` listens unless `--port` says otherwise |
| `MAX_BODY_BYTES`, `MAX_INPUTS` | 16 MB, 2,048 texts | `embedserver.py` | the largest request the embedding server reads; a larger one gets HTTP 413 unread. codemem's own requests are 64 texts, about 0.2 MB |
| `IDLE_TIMEOUT_S` | 60 s | `embedserver.py` | the embedding server closes a connection that sends nothing for this long |
| `SAME_VECTOR` | cosine 0.9999 | `embedserver.py` | at start the embedding server embeds two texts as a query and as a document, in process and as prefix plus text; below this agreement it refuses to serve the model |
| barrier wait | 0.25 s | `service.py` | how long a search waits for its marker file's event |
| git wait | 10 s | `service.py` | how long an update waits for a running git command |
| write lock wait | 30 s | `store.py` | how long a second writer process waits before giving up |
| `k` cap | 50 | `server.py` | results per MCP search |

---

## 5. Keys: what decides when work is redone

Three identities decide whether codemem can reuse what it has:

```
 embedder key ──── names a set of vectors ──────────────► a new key: that vector type is re-embedded
   local    <model>[#<weights hash>] | doc | L<max tokens> | <dtype> | <device>
   API      api:<space, else host> | <model> | dims=<n> | doc=<hash of the document prefix>
   plugin   <model>[#<weights>] | plugin=<module:Class> | L<max tokens> | <dtype> | <device>

 index settings ── what an index was built with ─────────► a difference redoes what it affects (below)

 eval index key ── hash of the index settings, the ──────► which eval systems share one index
                   codemem version and the device
```

- **The weights hash** is computed for a model in a local folder: a hash of the folder's files, so
  new weights saved over old ones get a new key. A model named on Hugging Face has none (its name
  names its weights). `vectors.<type>.version` sets a label instead.
- **The device is part of the local key,** because GPU and CPU results differ slightly. Moving an
  index between a GPU machine and a CPU machine re-embeds it, and the vector cache of one doesn't
  serve the other.
- **An API's vectors are named by its address, or by `[embedding] space` when that is set.** With
  the address in the key, the same server reached as `127.0.0.1` on the host and as
  `host.docker.internal` in a container is two embedders, and so is a provider after it changes
  its host name. A `space` takes the address out of the key and out of the index settings: two
  configurations with the same `space`, model, `dimensions` and document prefix share an index and
  the vector cache. The rule for what is in the name: everything that changes a stored vector
  (who serves it, the model, the length, the document prefix) and nothing else (not the query
  prefix, the key's variable, or the request sizes). Whoever sets a `space` promises that every
  address used under it returns the same vector for the same text; codemem has no way to check.
- **`serve-embeddings` prints the `space` for its clients:** `st-` for the sentence-transformers
  runtime, then the weights version if the model has one, the longest text, the precision and the
  device, for example `st-L1024-float16-mps`. These are the parts of the local key that the
  model's name does not carry, so servers that print the same `space` serve the same vectors. A
  client that should share an index across two devices gives both configurations one `space` of
  its own choosing.
- **An index built with the model in process and one built through a server have different keys**
  (`jinaai/…|doc|L1024|float16|mps` and `api:st-L1024-float16-mps|jinaai/…|dims=full|doc=861b2167`),
  although the vectors are the same numbers. Moving an index from one to the other embeds it once
  more. Processes that are to share an index all embed through the server, the host's too.
- **The API key and the server's key** are never part of anything: only the name of the
  environment variable is in the config, and the key is read at each request. It is never written
  to the index, the logs or `index_status`.

**When you change a setting, what is redone:**

| Change | Redone | Cost |
|---|---|---|
| the model, the embedder, new weights in a model folder, `dtype`, the device | that vector type is re-embedded | a full embedding (vLLM: about 5 h on the M1), unless the cache has it |
| an API's `model`, `dimensions`, `document_prefix` or `space`; its address when no `space` is set; between the model in process and the same model served | that vector type is re-embedded | the same |
| an API's address when a `space` is set | nothing | none |
| `embedding_dim`, `vector_backend` | the search index is rebuilt from the stored vectors | seconds |
| text settings (`max_seq_length`, `code_header`, `window_chars`, `window_overlap_lines`, `max_usage_items`, `include_commits`) | every text is rebuilt; only changed ones are re-embedded | depends on how many change |
| `max_defs_per_name` | every call is relinked | seconds; usage texts that change are re-embedded |
| file selection or chunking (`ignore`, `languages`, `max_file_size`, `use_default_ignore`, `skip_generated`, `max_block_lines`), BM25 tokenization | the index is rebuilt | the structure (vLLM: about 70 s), vectors from the cache |
| search settings (weights, filters, `rrf`, `candidates`, `catchup_budget_ms`, `steering`) | nothing | none |

**Version stamps.** Upgrading codemem can redo work too: `SCHEMA_VERSION` (4, `store.py`) changes
the tables or the keyword tokens, and an older index is wiped and rebuilt (a newer one is refused); `CHUNKER_VERSION` (2)
and `TEXT_FORMAT_VERSION` (3, both `config.py`) work like the chunking and text settings above.

---

## 6. Files: what to keep and what is safe to delete

Nothing codemem keeps is irreplaceable: the repository is the source of truth. The question is
only what each file costs to recreate.

| File | What | Size (vLLM) | If deleted |
|---|---|---|---|
| `~/.codemem/indexes/<repo>-<hash>/index.db` | the index | ~640 MB | rebuilt by the next update: the structure in about 70 s, vectors from the cache |
| `~/.codemem/indexes/<repo>-<hash>/vec_*.faiss` | saved copies of the search indexes | ~260 MB | rebuilt from `index.db` in about 2 s |
| `~/.codemem/cache/vectors.db` | every vector ever computed on this machine | grows about 4.5 KB per vector, never shrinks | **costly:** the next rebuild of each repo re-embeds everything (vLLM: about 5 h). The one file worth keeping |
| `~/.codemem/model_hashes.json` | hashes of local model folders' files | tiny | each local model folder is read once more (about 1 s per GB) |
| the Hugging Face model cache (`HF_HOME`) | the downloaded model | ~1 GB | downloaded again at the next start (needs the network) |
| `~/.codemem/config.toml`, `<repo>/.codemem.toml` | your settings | | yours to keep |

`CODEMEM_HOME` moves `~/.codemem`; in this project `.cache/env.sh` keeps every cache, model and
index inside the project folder.

---

## 7. Network and privacy

codemem goes over the network in two cases only:
- **downloading the model** from Hugging Face, once (`HF_HUB_OFFLINE=1` stops even the update
  check afterwards);
- **an embedding API**, only if you configure one. That sends your code to the provider, and
  `index_status` says so. A `serve-embeddings` server is such an endpoint: the code goes to the
  machine it runs on.

Searches, updates and everything else stay on your machine.

**`codemem serve-embeddings` listens for requests.** By default on the loopback address, which
other machines cannot reach. It embeds whatever text it is sent and keeps none of it: no index and
no cache. Its log holds request lines with their status (with `-v`) and the error of a model call
that failed, never a header, so never a key. Listening on another address exposes the model to
whoever can reach that address; `CODEMEM_SERVE_KEY` asks for a key then (§3).

---

## 8. Known gaps

| Gap | Effect | Fix |
|---|---|---|
| an API outage | each search waits about 31 s, then fails; `index_status` shows no error | fall back to keywords at once, with a note, and show the error in `index_status` |
| the model fails to load | each search waits about 4 s (the first took 7.5 s in a test), and the note says the model is "still loading" | say it failed, and stop waiting for it |
| the vector cache only grows | about 4.5 KB per vector, forever | a "last used" date per entry, and a size cap |
| the local embedder gives jina's two prompts to every model | a model without jina's prompt names (`nl2code_query`, `nl2code_document`) is embedded with jina's prompt texts in front, which it was not trained with. `serve-embeddings` prints the same two texts as its clients' prefixes, so a served model matches the model in process | the model's own `query` and `document` prompts, else `query_prefix` and `document_prefix`. The key of those models then has to change, and the document prefix becomes an index-time setting of local indexes |
| the embedding server's client reads vectors as JSON text | 1.2 to 2.1 ms a text in a build (§3): 1 to 2% of the model's time on the M1, and a larger share the faster the model is. A search does not notice it | the server also answers `encoding_format = "base64"`, which costs 0.06 to 0.12 ms a text in the same measurement; have the client ask for it |
