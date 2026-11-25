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
  codemem  ────► │  sentence-transformers + PyTorch .. running the local embedding model          │
  (Python 3.11+) │  watchdog ......................... file events from the operating system     │
                 │  MCP SDK (mcp) + httpx ............ the MCP server; the API client             │
                 │  pathspec, numpy .................. .gitignore rules; vectors                   │
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
vectors. It never imports sentence-transformers or PyTorch, so it also runs in an environment
built without the two (README, "One model for several codemem processes"): 46 packages and 81 MB,
against 887 MB for the environment `uv sync` builds (Apple Silicon, Python 3.11, uv 0.12.19).

---

## 2. Each dependency: why it, and what if it's missing or down

| Dependency | Why this one | If it's missing or down | How you'd notice | Backup |
|---|---|---|---|---|
| **The embedding model**, `jinaai/jina-code-embeddings-0.5b`, from Hugging Face | trained for code search; small enough for a laptop (0.5B); free and private | Before the first download (no network, Hugging Face down, wrong name): searches answer from keywords only, and new edits are applied and wait in the queue for their vectors. The load is tried again after 1 s, then after twice as long each time, up to a minute. Once downloaded, it loads with no network | `index_status` shows the load error. Search notes say the model is "still loading" (a known gap, §8) | Keyword search keeps working. Copy the model cache (`HF_HOME`) from another machine, point `vectors.code.model` at a local folder, or use an API |
| **sentence-transformers + PyTorch** | run the model on CUDA, Apple GPUs (MPS) or the CPU | They are imported only when the local model is used. In an environment built without them, for a client of an API or of a served model, the local model can't run: `codemem index` and `search` stop with one sentence that names what is missing, what to install and what to set instead. Under the MCP server, an update fails before it changes the index: an existing index keeps its chunks and vectors and answers from keywords, and a repo with no index gets none. The update is tried again after 1 s, then after twice as long each time, up to a minute, and its traceback is logged once | the sentence, on the command line and as the error in `index_status` | `pip install torch sentence-transformers`, or an embedding API, or a `serve-embeddings` server |
| **FAISS** (`faiss-cpu`) | exact vector search in memory, fast, no server, wheels for every platform | codemem doesn't start | an import error | none: required |
| **SQLite with FTS5** | ships with Python; transactions; built-in BM25 | without FTS5 (rare custom Python builds) no index can be created | an error on the first index | a standard Python build (python.org, Homebrew, uv) |
| **tree-sitter + grammars** (versions pinned) | one parser and official grammar for each of the nine languages | a language whose grammar fails can't be chunked; a file that fails to parse is indexed from what was recovered | `index_status` lists files with parse errors | none needed per file |
| **watchdog** (OS file events) | the same events API on macOS, Linux and Windows | network drives, WSL or Linux watch limits: no events | a warning in the log; `index_status` says "not watching" | automatic: a full check every 10 s and before each search (0.5 s on vLLM) |
| **git** (optional) | the indexed commit (for `index_status` and the eval), commit messages in usage texts if `include_commits` | no commit shown, no commit messages; everything else works | `indexed commit: -` in `index_status` | none needed |
| **MCP SDK** (`mcp` 2.x, pinned below 3) | the standard MCP server over stdio | the MCP server can't start; the CLI still works | agents can't connect | the CLI |
| **An embedding API** (optional: Nebius, OpenAI, a self-hosted server) | faster first builds of large repos, bigger models | a search waits about 31 s for retries, then fails (a known gap, §8); new edits wait in the queue and are retried | the search error names the provider; `index_status` doesn't flag it yet | none quick: another model means re-embedding everything, since vectors of different models can't mix. The same model at another address keeps the index if the config names the vectors with `space` (§5) |
| **A `codemem serve-embeddings` server** (optional) | one copy of the local model in memory (1.3 GB on an M1's GPU) for several codemem processes: one per git worktree, one per container. Its clients need no PyTorch and no GPU | The same as an API that is down: a search waits about 31 s for retries, then fails; new edits wait in the queue and are retried; `codemem index` stops with the error. Nothing is lost: the server holds no index and no state | the error names the address, `embedding request to 127.0.0.1:8791 failed`; `GET /health` on the server answers `{"status":"ok"}` when it is up | start it again, on any address: an index is tied to its `space`, not to the address. It takes its port first and then loads the model, so requests that arrive meanwhile wait for the model, not for a retry |

---

## 3. Operational choices, and why

The values codemem runs with, and why each was picked. All of these are settings
(README, "Configuration") except where the last column says constant.

| Choice | Value | Why | Change with |
|---|---|---|---|
| **where embeddings come from** | the local model | private, free, works offline; an API is opt-in, for speed or bigger models | `[embedding] provider`, `vectors.*.model` |
| **device and precision** | CUDA, else the Apple GPU, else CPU; float16 on a GPU, float32 on a CPU | float16 halves memory and time on a GPU and keeps the same top 10 (cosine ≥ 0.9997); a row that overflows is redone in float32. The model runs in this precision whatever its file stores. The default model's file stores bfloat16, which an M1's CPU runs 15 times slower than float32 on code texts (below) | `device`, `dtype` |
| **the model in memory** | kept for as long as codemem runs | On an M1 the model is 1.3 GB of the process (table below). Freeing it after some idle minutes gives that back, and the next search or save then starts a load: 2 to 6 s, longer the busier the machine. Meanwhile a search waits at most its 4 s and then answers from keywords, and an edit is found by keywords only. It stays by default so that no search pays that. A machine short of memory, or one with several agent sessions open, sets a number of minutes | `model_idle_minutes` (0 = keep) |
| **what a batch needed beside the model** | given back 5 s after the last model call | Up to 1.2 GB on an M1's GPU, which PyTorch keeps for the next batch otherwise. Giving it back takes 0.1 s and cost the next batch nothing that could be measured, so it needs no setting. 5 s keeps the calls of one batch, and a search's catch-up after a save, in one burst | constant (`TRIM_AFTER_IDLE`) |
| **how long a search may catch up** | 4 s | Chosen on Oct 25 (Andre). A one-function edit takes 0.1–0.5 s, and 4 s covers about 30 average texts at the M1's 8.5 texts a second. A `git pull` or a formatter run is what hits the cap; then the search returns what the index has and its note names the files still pending, so the agent can search again or grep them. A wasted grep turn costs an agent more than the wait | `catchup_budget_ms` |
| **what a search embeds first** | the queued chunks among its own keyword results, best rank first; then the newest edits | a queued chunk is ranked by keywords alone, so it sinks in the merge; embedding the search's own candidates puts them back (architecture.md §4.2) | constant |
| **when the queue is too long to wait for** | more than 1,000 queued chunks: a search embeds its own keyword results only, and reports the rest | the rest is minutes of embedding; a note beats a 4 s wait that changes little. During the first structure pass of a new index a search answers at once | constant |
| **one index per checkout** | the main checkout and every git worktree have their own index folder, named after the folder's path; a branch switch updates it in place | an index per branch would cost its disk for every branch; the vector cache already makes a switch back free of model calls (architecture.md §4.6) | `--index-dir` |
| **a new checkout's index** | starts as a copy of another checkout's index of the same repository: one built at the same commit, else the main checkout's, else the most recently updated; only one built with the same settings | building it from nothing chunks every file again: on vLLM the first current search came after 76 s, against 4 to 8 s from a copy (architecture.md §4.6) | automatic for the default index folder; never for `--index-dir` |
| **the index of a removed worktree** | deleted at the next codemem start in any checkout of that repository | a worktree's index is a full index on disk; agents make and remove worktrees all the time (§6 has the rule) | automatic for the default index folder |
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

**What the model costs in memory.** Measured on Nov 25, 2026 on an M1 (16 GB, macOS 26.6,
PyTorch 2.14.1, sentence-transformers 6.1.0, transformers 5.20.2) with
`jinaai/jina-code-embeddings-0.5b` on the GPU in half precision, 16 texts per model call. The
footprint is what Activity Monitor shows for the process. The machine was busy with other work
(a load average of 5 to 11 on its 8 cores), so the times are upper bounds.

| The process, after... | Footprint | Of it, held by the GPU's allocator |
|---|---|---|
| importing codemem | 0.08 GB | |
| importing PyTorch and sentence-transformers | 0.41 GB | |
| loading the model and embedding a query | 1.71 GB | 1.09 GB, for 1.01 GB of weights |
| embedding 256 code texts of about 1,000 characters | 2.80 to 2.95 GB | 2.29 GB |
| giving the batch's working memory back, the model kept | 1.59 to 1.74 GB | 1.09 GB |
| freeing the model | 0.52 GB | none |
| loading it again and embedding a query | 1.71 GB | 1.09 GB |

- **The weights are 1.0 GB** (494 million numbers of 2 bytes). **A call of 16 code texts needs up
  to 1.2 GB more** for its intermediate results. PyTorch keeps that for the next call, and codemem
  has it given back once the model has made no call for 5 s. The call that gives it back takes
  0.1 s. The batch after it was no slower: 256 code texts took 84 s right after it and 87 s with
  nothing given back, and batches of 32 took 10.0 s and 10.4 s (four of each, in turn). Between
  runs the part of the footprint outside the GPU's allocator differed by up to 0.15 GB, hence the
  two ranges in the table.
- **Through the MCP server's own path** (the sample repo with 64 functions of about 1,000
  characters added). The writer embeds saved code in calls of at most 3,000 characters, which
  need under 20 MB beside the model: after 32 functions the process was at 1.75 GB. `refresh()`
  embeds 16 texts a call: after 32 more functions the process was at 2.84 GB, and at 1.76 GB 6 s
  later. With `model_idle_minutes` at 3 s it went from 1.76 GB to 0.65 GB within a second of the
  writer freeing the model. The system gives GPU memory back 0.2 to 0.8 s after PyTorch releases
  it (30 trials with 1 GB of tensors), not at the moment of the call.
- **Times.** Importing PyTorch 19 s, the first load 5.4 s, freeing 1.3 s, loading again 5.5 s, at
  a load average of 8 to 11 (8 cores). A load follows the machine's load: the same day it took
  about 2 s at a load average of 3 to 5 and 3 to 5 s at 6 to 7. The first search after the model
  was freed took 3.5 s and had every signal at a load average of 5; at 8 to 11 it took 4.1 s and
  answered from keywords, and the model was back 7.0 s after that search began. A search that
  waits for the model (the CLI) took 2.2 s and 3.8 s.
- **On the CPU** the model runs in float32, and the process takes 2.4 GB with it loaded: the
  weights are 2.0 GB there. Freeing the model brings it to 0.7 GB. 20 short queries, one at a
  time, took 3.7 s, and 32 code texts of about 1,000 characters, four a call, took 36 s (on the
  GPU: 1.9 s and 9.1 s). Left in the bfloat16 that its file stores, the same model took 18 s and
  533 s: 5 and 15 times as long. The two were measured in turn in one process, so that the
  machine's other work slowed both alike. In bfloat16 the process takes 0.4 GB, because the
  weights stay mapped from the file.

---

## 4. Constants

Values in the code, not in the config.

| Constant | Value | Where | What it controls |
|---|---|---|---|
| `CATCHUP_MAX_CHUNKS` | 1,000 | `service.py` | above this many queued chunks, a search embeds its own keyword results only, and reports the rest |
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
| `RETRY_FIRST`, `RETRY_MAX` | 1 s, 60 s | `service.py` | the writer tries a failed step again (an update, embedding, a model's load) after 1 s, then after twice as long each time, up to a minute |
| `TRIM_AFTER_IDLE` | 5 s | `embedder.py` | a model that has made no call for this long gives back what its calls needed beside it; calls closer together are one burst |
| `QUIET_CHECK_S` | 1 s | `embedserver.py` | with no request for this long, the embedding server's queue gives its model a quiet moment |
| barrier wait | 0.25 s | `service.py` | how long a search waits for its marker file's event |
| git wait | 10 s | `service.py` | how long an update waits for a running git command |
| write lock wait | 30 s | `store.py` | how long a second writer process waits before giving up |
| `COPY_LOCK_WAIT` | 300 s | `worktrees.py` | how long a start waits for another process that is copying an index into the same folder |
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
- **The precision and the device in the local key are the ones the model runs in.** The weights
  are converted to that precision when the model is loaded, whatever the model's file stores:
  `auto` is float16 on a GPU and float32 on a CPU. Equal keys promise the same model and weights,
  the same longest text, the same arithmetic and the same kind of device.
- **The device is part of the local key,** because GPU and CPU results differ slightly. Moving an
  index between a GPU machine and a CPU machine re-embeds it, and the vector cache of one doesn't
  serve the other. How slightly, for 20 short queries and 32 code texts on an M1: the CPU's
  float32 vectors and the GPU's float16 vectors have a cosine of at least 0.999996, no score (a
  query's cosine with a text) differs by more than 0.0007, and every query has the same ten best
  of the 32 texts, 19 of 20 in the same order. bfloat16 on the CPU is further from both: a cosine
  of at least 0.9998, scores within 0.0055, the same best text for every query and the same ten
  best for 18 of 20.
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
| search settings (weights, filters, `rrf`, `candidates`, `catchup_budget_ms`, `steering`), `model_idle_minutes` | nothing | none |

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
| `~/.codemem/indexes/<worktree>-<hash>/` | the index of a git worktree: a full index of its own | ~640 MB, ~900 MB once its search indexes are saved | copied again from another checkout's index at the next start there (1 to 2 s on vLLM, then one full check) |
| `~/.codemem/indexes/<worktree>-<hash>/worktree.json` | which worktree the folder serves, and its repository | tiny | written again at the next start in that worktree; until then the folder is not deleted when the worktree is removed |
| `~/.codemem/cache/vectors.db` | every vector ever computed on this machine | grows about 4.5 KB per vector, never shrinks | **costly:** the next rebuild of each repo re-embeds everything (vLLM: about 5 h). The one file worth keeping |
| `~/.codemem/model_hashes.json` | hashes of local model folders' files | tiny | each local model folder is read once more (about 1 s per GB) |
| the Hugging Face model cache (`HF_HOME`) | the downloaded model | ~1 GB | downloaded again at the next start (needs the network) |
| `~/.codemem/config.toml`, `<repo>/.codemem.toml` | your settings | | yours to keep |

`CODEMEM_HOME` moves `~/.codemem`; in this project `.cache/env.sh` keeps every cache, model and
index inside the project folder.

**codemem deletes one kind of folder by itself:** the index of a git worktree that is gone. Every
start in a checkout of a repository looks at the index folders of that repository's worktrees and
deletes one only if all of this holds:

1. it is a real folder (not a link) directly inside `~/.codemem/indexes/`;
2. it holds a `worktree.json`, which codemem writes only into the default index folder of a
   linked worktree, never into a main checkout's or into a folder given with `--index-dir`;
3. that record names the repository codemem was started in;
4. the folder's name is the one codemem gives the recorded worktree;
5. the worktree's folder no longer exists;
6. git no longer lists the worktree. After `git worktree remove` it does not. A folder that
   is missing for another reason (a drive that is not mounted, `rm -rf`) is still listed, and
   its index stays until `git worktree prune` or git's own clean-up drops it.

Then it deletes the files codemem itself writes there (`index.db` and its SQLite side files,
`vec_*`, `write.lock`, `worktree.json`) and removes the folder if it is empty. Any other file
stays, with the folder. An index that a codemem process is writing at that moment is left for a
later start. Indexes of main checkouts, and of repositories that were deleted whole, are never
deleted: remove them by hand.

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
| the model fails to load | each search answers from keywords at once, and its note says the model is "still loading" | say that it failed |
| the loading note speaks of start-up only | after the model was freed for being idle, a search that answers from keywords still says "the first search after codemem starts" | reword the note in `prompts.py` |
| the vector cache only grows | about 4.5 KB per vector, forever | a "last used" date per entry, and a size cap |
| PyTorch is always installed | about 0.8 GB, even for a codemem that only embeds through an API or a `serve-embeddings` server | make the local model an optional install; needs a one-line change in the eval's dependencies. Such a client's environment can be built without the two packages by hand (README, "One model for several codemem processes") |
| an MCP server answers for the checkout it was started in | an agent that works in another git worktree of the repo, but calls a server started in the main checkout, searches the main checkout's code and gets no note | start a server in each worktree. Whether agent hosts do that for their subagents is not documented; it needs a test with a real agent |
| a main checkout's index reads git worktrees placed inside it | worktrees in `.claude/worktrees/` add a copy of every function to the main index, unless `.gitignore` covers them | ignore that folder, or make the walk skip linked worktrees |
| a new worktree's index is copied before the MCP handshake | on vLLM the server answers its first message 1 to 2 s later; an agent host with a short start-up limit could give up on a much larger repo or a busy disk | open the index in the background, or clone the file where the file system can (APFS: no time, no extra disk) |
| every worktree has a full index on disk | vLLM: ~640 MB each, ~900 MB with its saved search indexes | vectors stored once per machine, so an index holds only structure |
| the local embedder gives jina's two prompts to every model | a model without jina's prompt names (`nl2code_query`, `nl2code_document`) is embedded with jina's prompt texts in front, which it was not trained with. `serve-embeddings` prints the same two texts as its clients' prefixes, so a served model matches the model in process | the model's own `query` and `document` prompts, else `query_prefix` and `document_prefix`. The key of those models then has to change, and the document prefix becomes an index-time setting of local indexes |
| the embedding server's client reads vectors as JSON text | 1.2 to 2.1 ms a text in a build (§3): 1 to 2% of the model's time on the M1, and a larger share the faster the model is. A search does not notice it | the server also answers `encoding_format = "base64"`, which costs 0.06 to 0.12 ms a text in the same measurement; have the client ask for it |
