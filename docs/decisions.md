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
                 │  an assist endpoint (optional): a second source for a build's vectors           │
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
| **The embedding model**, `jinaai/jina-code-embeddings-0.5b`, from Hugging Face | trained for code search; small enough for a laptop (0.5B); free and private | Before the first download (no network, Hugging Face down, wrong name): searches answer from keywords only, and new edits are applied and wait in the queue for their vectors. The load is tried again after 1 s, then after twice as long each time, up to a minute. Once downloaded, it loads with no network | `index_status` shows the load error, and so does the note of each search that answers from keywords: `Note: codemem cannot embed right now (...)` | Keyword search keeps working. Copy the model cache (`HF_HOME`) from another machine, point `vectors.code.model` at a local folder, or use an API |
| **sentence-transformers + PyTorch** | run the model on CUDA, Apple GPUs (MPS) or the CPU | They are imported only when the local model is used. In an environment built without them, for a client of an API or of a served model, the local model can't run: `codemem index` and `search` stop with one sentence that names what is missing, what to install and what to set instead. Under the MCP server, an update fails before it changes the index: an existing index keeps its chunks and vectors and answers from keywords, and a repo with no index gets none. The update is tried again after 1 s, then after twice as long each time, up to a minute, and its traceback is logged once | the sentence, on the command line and as the error in `index_status` | `pip install torch sentence-transformers`, or an embedding API, or a `serve-embeddings` server |
| **FAISS** (`faiss-cpu`, 1.15.1 or newer) | exact vector search in memory, fast, no server, wheels for every platform; it also makes and compares the compact index's codes (RaBitQ), which is checked against FAISS 1.15.1 (`scripts/check_faiss_calls.py`) | codemem doesn't start. In an environment that still has a FAISS older than 1.15.1, `auto` always uses the exact index, and `vector_backend = "compact"` is refused | an import error; for a named compact index, one sentence naming the FAISS version; for `auto`, a line in the log at info level, and `codemem status` gives the reason | none: required. For the compact index: a newer `faiss-cpu` |
| **SQLite with FTS5** | ships with Python; transactions; built-in BM25 | without FTS5 (rare custom Python builds) no index can be created | an error on the first index | a standard Python build (python.org, Homebrew, uv) |
| **tree-sitter + grammars** (versions pinned) | one parser and official grammar for each of the nine languages | a language whose grammar fails can't be chunked; a file that fails to parse is indexed from what was recovered | `index_status` lists files with parse errors | none needed per file |
| **watchdog** (OS file events) | the same events API on macOS, Linux and Windows | network drives, WSL or Linux watch limits: no events | a warning in the log; `index_status` says "not watching" | automatic: a full check every 10 s and before each search (0.5 s on vLLM) |
| **git** (optional) | the indexed commit (for `index_status` and the eval), commit messages in usage texts if `include_commits` | no commit shown, no commit messages; everything else works | `indexed commit: -` in `index_status` | none needed |
| **MCP SDK** (`mcp` 2.x, pinned below 3) | the standard MCP server over stdio | the MCP server can't start; the CLI still works | agents can't connect | the CLI |
| **An embedding API** (optional: Nebius, OpenAI, a self-hosted server) | faster first builds of large repos, bigger models | Under the MCP server, searches answer from keywords with a note that says why: at once while the endpoint is known not to answer, and after the request's retries, about 31 s, for the first search that finds out (a known gap, §8). New edits are applied and wait in the queue for their vectors. Each search asks the endpoint once more, and the writer asks it after 1 s, then after twice as long each time, up to a minute: vectors are used again from the first request that gets its answer. On the command line, `codemem index` and `codemem search` stop after the retries, with exit status 1 and the error in one line; `codemem search --signals bm25` and `codemem status` need no endpoint | the note of a search, the line of a command and the error in `index_status` name the address: `embedding request to api.example.com failed: ...` | none quick: another model means re-embedding everything, since vectors of different models can't mix. The same model at another address keeps the index if the config names the vectors with `space` (§5) |
| **A `codemem serve-embeddings` server** (optional) | one copy of the local model in memory (1.3 GB on an M1's GPU) for several codemem processes: one per git worktree, one per container. Its clients need no PyTorch and no GPU | The same as an API that is down: searches answer from keywords and say why, new edits wait in the queue and are embedded when it is back, and `codemem index` stops with the error. Nothing is lost: the server holds no index and no state | the error names the address, `embedding request to 127.0.0.1:8791 failed`; `GET /health` on the server answers `{"status":"ok"}` when it is up | start it again, on any address: an index is tied to its `space`, not to the address. It takes its port first and then loads the model, so requests that arrive meanwhile wait for the model, not for a retry |
| **An assist endpoint** (optional: a `serve-embeddings` server on another machine, or a hosted API that serves the same model) | a first build is hours of model time on a weak machine, and a second source embeds part of it meanwhile. With stand-in models a build ran 1.26 to 3.4 times as fast, for an endpoint a quarter to four times as fast as the local model (architecture.md §3.5) | **Down, slow or over its rate limit:** the build goes on at the local model's speed. A request that fails gives its texts back within the same call, one that is late has them taken back, and the endpoint rests before it is tried again (§3). Measured with stand-in models: 1.00 times the local model's speed with an endpoint that is not there, 1.11 times with one that stops answering after a quarter of the texts. **Not the same vectors** (another model, precision or prompt, or texts cut earlier than the local model cuts them): it gets no text at all | the line `assist: …` of `codemem status` and `index_status` says that it shares the work, or in one sentence why not; the same sentence is logged once as a warning | none needed: the local model embeds everything, as without an assist |

---

## 3. Operational choices, and why

The values codemem runs with, and why each was picked. All of these are settings
(README, "Configuration") except where the last column says constant. Wherever this document gives
a time for the search index, it is from an M1 laptop with FAISS on one thread, which is how
codemem runs it on macOS; on Linux and Windows FAISS uses every core (architecture.md §5).

| Choice | Value | Why | Change with |
|---|---|---|---|
| **where embeddings come from** | the local model | private, free, works offline; an API is opt-in, for speed or bigger models | `[embedding] provider`, `vectors.*.model` |
| **device and precision** | CUDA, else the Apple GPU, else CPU; float16 on a GPU, float32 on a CPU | float16 halves memory and time on a GPU and keeps the same top 10 (cosine ≥ 0.9997); a row that overflows is redone in float32. The model runs in this precision whatever its file stores. The default model's file stores bfloat16, which an M1's CPU runs 15 times slower than float32 on code texts (below) | `device`, `dtype` |
| **the model in memory** | freed after 60 minutes without embedding | On an M1 the model is 1.3 GB of the process (table below). Freeing it after an idle time gives that back, and the next search or save then starts a load: 2 to 6 s, longer the busier the machine. A search waits for that load, for up to 20 s, so an idle time costs the next search time and not results; past that it answers from keywords with a note. An edit made meanwhile is found by keywords until the model is back. An hour keeps the model through a working session, and gives its memory back after a real break and in the sessions nobody is using. 0 keeps it for as long as codemem runs. The eval sets 0 (`CODEMEM_MODEL_IDLE_MINUTES=0` in a run's container), so that no run differs by whether an unload fell into it | `model_idle_minutes` (0 = keep) |
| **what a batch needed beside the model** | given back 5 s after the last model call | Up to 1.2 GB on an M1's GPU, which PyTorch keeps for the next batch otherwise. Giving it back takes 0.1 s and cost the next batch nothing that could be measured, so it needs no setting. 5 s keeps the calls of one batch, and a search's catch-up after a save, in one burst | constant (`TRIM_AFTER_IDLE`) |
| **how long a search may catch up** | 4 s | Chosen on Oct 25 (Andre). A one-function edit takes 0.1–0.5 s, and 4 s covers about 30 average texts at the M1's 8.5 texts a second. A `git pull` or a formatter run is what hits the cap; then the search returns what the index has and its note names the files still pending, so the agent can search again or grep them. A wasted grep turn costs an agent more than the wait | `catchup_budget_ms` |
| **what a search embeds first** | the queued chunks among its own keyword results, best rank first; then the newest edits. Nothing, if the model is not in memory within the search's 4 s | a queued chunk is ranked by keywords alone, so it sinks in the merge; embedding the search's own candidates puts them back (architecture.md §4.2). An agent's search never loads the model itself (architecture.md §3.5) | constant |
| **when the queue is too long to wait for** | more than 1,000 queued chunks: a search embeds its own keyword results only, and reports the rest | the rest is minutes of embedding; a note beats a 4 s wait that changes little. During the first structure pass of an index built from nothing a search answers at once; the first check of a copied index is waited for (architecture.md §4.6) | constant |
| **one index per checkout** | the main checkout and every git worktree have their own index folder, named after the folder's path; a branch switch updates it in place | an index per branch would cost its disk for every branch; the vector cache already makes a switch back free of model calls (architecture.md §4.6) | `--index-dir` |
| **a new checkout's index** | starts as a copy of another checkout's index of the same repository: one built at the same commit, else the main checkout's, else the most recently updated; only one built with the same settings. Until its first full check has run it holds the other checkout's code: the MCP tools wait for that check within their 4 s, and past that their answer says that it comes from the copy | building it from nothing chunks every file again: on vLLM the first current search came after 76 s, against 4 to 8 s from a copy (architecture.md §4.6) | automatic for the default index folder; never for `--index-dir` |
| **the index of a removed worktree** | deleted at the next codemem start in any checkout of that repository | a worktree's index is a full index on disk; agents make and remove worktrees all the time (§6 has the rule) | automatic for the default index folder |
| **`codemem search` and a checkout that moved** | a full check before every search; if files differ, the index is updated first: stage A, then the vectors of the search's own keyword results, then the other queued vectors for at most 20 s (none of them with more than 1,000 chunks queued). The command says what it does, and what is left for `codemem index`. It never rebuilds: an index built with other settings or by another model is left as it is, with a note | no server watches for a command that runs once, so without the check a search after `git switch` would answer from the branch that was left. The command waits for the update as it waits for the model, and no longer than a caller with a time limit of its own would (an agent's shell tool: often 30 to 120 s). A rebuild takes minutes to hours and drops the old vectors first, which nobody expects of a search. The check costs what `codemem status` costs: 0.02 s on flask (architecture.md §4.6) | constant |
| **a worktree inside another checkout** | left out of that checkout's index: the scan skips the folder, the watcher ignores the saves in it, and `index_status` lists it. Only a linked worktree of the same repository counts: a submodule and a repository of another project are read | agent hosts put worktrees in `<repo>/.claude/worktrees/`. Read as plain folders they give the main index a second copy of every function, and a search returns each one twice. The worktree has an index of its own (architecture.md §4.6) | automatic |
| **grouping saves** | 0.5 s after the last save, at most 2 s after the first | one editor action writes several files; the maximum stops a long burst from postponing indexing | `debounce_ms`, `debounce_max_wait_ms` |
| **safety full check** | every 5 min (every 10 s without file events) | catches a missed event; one check costs 0.3–0.5 s on vLLM | constants |
| **writing the search index to disk** | after 30 s idle, at shutdown, on `refresh_index` | writing it on every save blocked searches for 2.2 s on vLLM (520 MB of files, with 4 bytes per number); the CLI and the eval write at once, because the eval measures the index size | constant |
| **the vector cache** | on, shared by every index on the machine | rebuilds, branch switches and other commits cost no model calls | `vector_cache = "off"` |
| **the search index** | `auto`: the exact index while the exact indexes of an index's vector types fit a memory budget together, the compact one when they do not | the exact index returns exactly the best vectors, reads nothing from disk, and is the faster one on an index that fits (6.2 ms a search against 8.5 at 31k vectors). It keeps 1,856 bytes for a vector of 896 numbers: 371 MB at 200,000. The compact index keeps a third (131 MB), returned the same top 10 and top 50 in all 4,608 searches on 31k real vectors and in 352 of 352 on a whole pandas index, and at 200,000 vectors searches in 0.92 times the exact index's time; it needs the index file in the system's file cache to be fast (architecture.md §5). The pick is made when the search indexes are loaded, and holds while the index is open | `vector_backend = "faiss"` or `"compact"` |
| **the memory the exact search indexes may take** | 2% of the machine's memory, at least 128 MB: 344 MB on a machine of 16 GB, which is 185,000 vectors of 896 numbers | chosen on Nov 25 (Andre): accuracy and time first, within memory a machine can spare. vLLM (145,000 vectors, 269 MB) and pandas (49,770, 92 MB) stay exact on a laptop of 16 GB; an index of 200,000 vectors (371 MB) is compact there and exact from 24 GB up. An index that is compact goes back to exact only under 80% of the budget, so one near it does not change at every start | `vector_memory_mb` |
| **an index built in one place and opened in another** | both places name the search index. The eval sets `CODEMEM_VECTOR_BACKEND=faiss` for the build of a task's index and for every run on it | `auto` picks by the memory of the place it runs in. A build on a host, with all its memory, saves the exact index; a run in a container limited to 16 GB picks the compact one above 185,000 vectors, and rebuilds it from the stored vectors at every start, because each run opens a copy of what the build saved. On an index of 100,000 vectors (M1) that rebuild took 5 s with FAISS on 4 threads and 13 s on one, and the searches asked meanwhile were answered from keywords, with the note. With the index named, the run read the saved copy in 0.4 s and its first search had the vectors. The cost is the exact index's memory in the container: 1.1 GB at 600,000 vectors | `CODEMEM_VECTOR_BACKEND`, or `vector_backend` in a config file that both places read |
| **the compact index's codes** | every number of the vector: a 1-bit code that a search scans, and a 4-bit code that ranks the scan's best | shorter codes lost the top 10 for questions (256 numbers: 49% of searches at 200 candidates). With the 1-bit code alone the worst search lost 14 of its top 50 at 200 candidates, 6 at 500, and none only at 2,000, which is 2,000 rows read per search. 2 bits need 500 candidates. 8 bits keep what 4 keep, at twice the memory and three times the coding time | `[compact] dim`, `bits` |
| **candidates the compact index scores exactly** | 200, and at least 4 per result asked for | with the 4-bit code, 200 and 500 candidates returned the same results in every search, and each candidate is a row read from SQLite | `[compact] rescore` |
| **the vector cache's size cap** | 8 GB (8 × 10⁹ bytes) | Past the cap the least recently used vectors are deleted. A cap that is too low costs model time again and again (0.02 to 0.5 s per text on the M1); a high one only costs disk. A vector of the default model takes 1.9 KB in the cache, so 8 GB holds about 4.2 million of them, 29 times vLLM's 145,000: the file stays a size a laptop disk can spare, and nothing is deleted before many repos have filled it | `vector_cache_max_gb` (0 = no cap) |
| **the vector cache's age limit** | 30 days | A cached vector that nothing has used for 30 days is deleted, so the cache does not keep for ever what a machine once embedded: other branches, other commits, repos that are gone. An index counts as a user of the vectors it holds: once a day an update, or a running session in a quiet moment, marks them as used (for vLLM's 145,000: 0.4 s to read their hashes and 0.2 to 0.7 s to mark them, measured on its real cache of 194,000 vectors). So a repo in use keeps its whole share, and a rebuild of it stays free however old its code is. Deleting is slower: all 194,000 at once took 12.5 s, which a running session spreads over its quiet moments, one second at a time. 7 days would give back little more and make a return to a branch after a holiday cost model time | `vector_cache_max_age_days` (0 = never) |
| **file size cap** | 10 MB | hand-written files can reach megabytes (TypeScript's `checker.ts`); larger ones are generated data | `max_file_size` |
| **vendored and generated code** | skipped | copies crowd results and cost embedding time; `third_party/` is kept, as it is often the project's own code | `use_default_ignore`, `skip_generated` |
| **text length per vector** | 1,024 tokens (about 3,000 characters) | keeps CPU indexing tractable; longer code is split into windows, so nothing is lost | `max_seq_length` |
| **API requests** | 64 texts each, 4 at a time, 60 s timeout; 6 tries, waiting 1, 2, 4, 8, 16 s (or the server's Retry-After, up to 60 s) | provider rate limits and brief outages | `[embedding] batch_size`, `max_concurrency`, `timeout_s`; tries are a constant |
| **what an assist endpoint has to show** | every one of seven probe texts at a cosine of 0.99995 or more with the local model's vector, after its vectors are scaled to length 1 | Its vectors go into the index as the local model's, so "the same model" has to be measured. A provider need not normalize, and a vector's length says nothing about the model, so only the direction is compared. The bar sits between what is known to be harmless and what is known not to be. The same model on this machine's CPU in float32 and on its GPU in float16 agrees to 0.999996, and no score moves by more than 0.0007. In bfloat16 against float16 the agreement is 0.99978, and 2 of 20 top-10 lists change. In distance between two vectors that is 0.003 and 0.021; the bar is at 0.010. A `serve-embeddings` server on the same kind of device gives the same numbers (1.000000) | constant (`SAME_VECTORS`) |
| **what an assist endpoint shares** | embedding calls of more than `batch_size` (16) texts: the calls of a build by `codemem index` or `codemem init` | an edit, a search's catch-up and a model warm-up are calls of one batch or less. They stay with the local model, so the 4 s catch-up and the writer's short calls behave as without an assist. Queries are never sent | `batch_size` |
| **which texts of a shared call an assist endpoint may get** | those the local model reads whole: at most `max_seq_length` (1,024) tokens with the model's prompt and the tokenizer's own tokens, counted with the local model's tokenizer | the local model cuts a longer text, and a hosted model that reads further would give another vector for it. A text of exactly the limit may go; one token more stays local. An embedder that cannot say which texts it cuts (a plugin without `cut`) gets no assist | `max_seq_length` |
| **an assist endpoint's requests** | 32 texts each, 4 at a time, 30 s timeout; sent once | a request that fails is not sent again: its texts go back to the local model within the same call, and the endpoint rests | `[embedding.assist] batch_size`, `max_concurrency`, `timeout_s` |
| **an assist endpoint that failed** | rests 1 s, then twice as long after each further failure, up to 60 s; after a rate limit, for its Retry-After | a build must not stall on an endpoint that is down. After the rest its vectors are compared again before it gets work, since what answers then may be another server; after a rate limit it gets work again as it is | constants (`FIRST_PAUSE_S`, `LONGEST_PAUSE_S`) |
| **the embedding server's address** | `127.0.0.1`, port 8791 | the loopback address is reachable from this machine only; containers on Docker Desktop reach it as `host.docker.internal`. Another address is a choice to expose the model, made with `--host` | `codemem serve-embeddings --host`, `--port` |
| **the embedding server's key** | none | on the loopback address every client is a process of this machine. With `CODEMEM_SERVE_KEY` set in the server's environment, every request but `GET /health` must carry it as `Authorization: Bearer`; the server warns at start when it listens beyond the loopback address without one | the environment variable `CODEMEM_SERVE_KEY`, for the server and for each client (`api_key_env`) |
| **the embedding server's model calls** | one at a time, at most `batch_size` (16) texts each; between calls the request with the fewest texts left goes first | the local model runs one call at a time anyway (architecture.md §3.5); one thread makes them all, so the server chooses which request goes next. A search's single query then waits for one batch of another client's build, not for the build. Texts of several requests may share a call | `batch_size` in the server's config |
| **what one server costs a client** | 2 to 4 ms a query; 1.2 to 2.1 ms a text in a build | measured with a model that takes no time, for vectors of 896 numbers, on an M1 that other jobs kept busy (load average 13 to 21; `scripts/check_served_vectors.py --overhead`). Almost all of it is writing and reading the numbers as JSON text, 5.1 MB for 256 vectors. The model itself takes about 118 ms a text on the M1 (architecture.md §10) | not a setting |
| **callers and callees named on a card** | up to 3 per card, the ones closest to the query by their stored code vectors; a callee with more than 100 callers left out; none for a search by keywords alone | measured on Nov 26 on the eval's vLLM and pandas tasks, the issue as the query, on the half of the tasks no setting was chosen on: a gold function was on a card or among the 10 results for 117 of 175 vLLM tasks against 99 among the results alone, and 108 of 162 pandas tasks against 94; with the issue's first line as the query 89 against 58 and 88 against 70; on the 16 vague pandas requests 9 against 8. It costs 16 to 18 names a search and 4 to 9 ms (median; 19 ms at the 90th percentile on vLLM). Used to rank instead, as a fourth list or as a lift, the graph gained a few tasks on one repo and lost a few on the other, as random neighbours did (architecture.md §6). The cap: calls are linked by name, so on vLLM three methods named `append` have 4,362 callers each, really `list.append`; 100 is about the 99th percentile of callers per callee there, and it reached as many tasks as every edge with fewer names | `card_relations` (0 = none); the cap is a constant (`RELATION_MAX_CALLERS`) |
| **the results after the cards** | the next 20, by name only (location and name) | on the same held-out tasks, naming results 11 to 30 put a gold function on the page for 116 of 175 vLLM tasks (99 in the 10 cards), 108 of 162 pandas tasks (94), 12 of 16 vague requests (8): as many as the related names, but other tasks; with both, 127 and 117. A name costs one line, a card about 13. On the 381 vLLM issues (the whole issue as the query, k = 10), search_code's answer is 5,801 characters on average (95th percentile 7,660) without the related names and the next results, and 9,332 (11,713) with both at their defaults; on the 17 vague pandas requests 5,125 (6,865) and 7,967 (9,426) | `more_results` (0 = none) |
| **names passed apart from the query** | a fourth list of the merge, keywords only, weight 1 | an agent's short query drops the identifiers its task names. With the issue's first line as the query and the issue's own identifiers as `names` (a median of 37 on vLLM, 13 on pandas), a gold function reached the top 10 for 88 of 175 held-out vLLM tasks against 58, and 81 of 162 pandas tasks against 70; 11 of 16 vague requests against 8. The weight was chosen on the other half among 0.25 to 1. With the whole issue as the query as well, they gained vLLM 11 tasks and cost pandas 7 of 179 gold files in the top 10. That many names take a keyword search of their own: 376 ms median on vLLM, 58 ms on pandas | `[rrf] weights = { names = 0 }` turns the list off |
| **test code among the cards** | as any other code, unless the caller passes `tests`; the option to keep tests out of the cards and name the best 5 after them (`tests_apart`) is off | Andre decides this one with numbers. On the held-out halves of the eval's tasks, with the option on, a gold function was in the 10 cards for 103 of 175 vLLM tasks against 99, 100 of 162 pandas tasks against 94, and 11 of 16 vague requests against 8; with the issue's first line as the query 67 against 58 and 80 against 70. One of the 5 named tests calls a gold function for 47 of 175 vLLM tasks and 31 of 162 pandas tasks, but for only 4 and 1 whose gold function the cards miss. Today 1.9 (vLLM) to 2.9 (pandas) of the 10 cards are tests, 3.2 to 4.6 for short queries. The eval's gold labels are never tests (pandas: 1 of 488 gold files, vLLM 13 of 604), so any demotion of tests scores better there by construction. Naming the tests costs a second search over test chunks only: 40 to 140 ms for a short query, about as long as the first for a whole issue | `tests_apart`, `tests_apart_count`; a `tests` argument wins |
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
| `FOLLOW_EMBED_SECONDS` | 20 s | `service.py` | how long `codemem search` embeds the rest of a change before it answers; its own keyword results come first and are not counted |
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
| `RETRIES`, `BACKOFF_S` | 6, 1 s doubling | `embedder.py` | API retries. After a request that got no vectors in all 6, each request is sent once until one gets its vectors again |
| `DEFAULT_PORT` | 8791 | `embedserver.py` | where `serve-embeddings` listens unless `--port` says otherwise |
| `MAX_BODY_BYTES`, `MAX_INPUTS` | 16 MB, 2,048 texts | `embedserver.py` | the largest request the embedding server reads; a larger one gets HTTP 413 unread. codemem's own requests are 64 texts, about 0.2 MB |
| `IDLE_TIMEOUT_S` | 60 s | `embedserver.py` | the embedding server closes a connection that sends nothing for this long |
| `SAME_VECTORS` | cosine 0.99995 | `assist.py` | what each of an assist endpoint's probe vectors must reach against the local model's, once scaled to length 1 |
| `FIRST_PAUSE_S`, `LONGEST_PAUSE_S` | 1 s, 60 s | `assist.py` | how long an assist endpoint rests after a failure, doubling in between |
| `FIRST_CHECK_WAIT_S` | 2 s | `assist.py` | how long the first large call of a build waits for the endpoint's answer to the probe; an answer that comes later is used by the calls after it |
| `LEAST_PATIENCE_S` | 0.5 s | `assist.py` | until the local model's speed is measured, the earliest moment it takes a late request's texts back |
| `SAME_VECTOR` | cosine 0.9999 | `embedserver.py` | at start the embedding server embeds two texts as a query and as a document, in process and as prefix plus text; below this agreement it refuses to serve the model |
| `CACHE_UPKEEP_EVERY`, `CACHE_UPKEEP_SECONDS` | 6 h, 1 s | `service.py` | in a quiet moment the writer of a running session keeps the vector cache: it marks the vectors its index holds as used (once a day), drops what is past the age limit, and enforces the cap, deleting for 1 s at a time until nothing is left. An update (`codemem index`, a start) does the same when it ends, without the time limit |
| `IDLE_RELOAD_WAIT` | 20 s | `service.py` | how long a search waits for a model that was freed for being idle to be in memory again; past it the search answers from keywords with a note |
| `RETRY_FIRST`, `RETRY_MAX` | 1 s, 60 s | `service.py` | the writer tries a failed step again (an update, embedding, a model's load, an embedding endpoint that does not answer) after 1 s, then after twice as long each time, up to a minute |
| `TRIM_AFTER_IDLE` | 5 s | `embedder.py` | a model that has made no call for this long gives back what its calls needed beside it; calls closer together are one burst |
| `QUIET_CHECK_S` | 1 s | `embedserver.py` | with no request for this long, the embedding server's queue gives its model a quiet moment |
| barrier wait | 0.25 s | `service.py` | how long a search waits for its marker file's event |
| git wait | 10 s | `service.py` | how long an update waits for a running git command |
| write lock wait | 30 s | `store.py` | how long a second writer process waits before giving up |
| `_REPLACE_TRIES`, `_REPLACE_WAIT` | 6 tries, 0.02 s | `store.py` | a rename of a save that is refused with a permission error is tried again after 0.02 s, then after twice as long each time: 0.62 s in all. Windows refuses a rename while another handle holds the file open; the numbers are not measured on Windows |
| `COPY_LOCK_WAIT` | 300 s | `worktrees.py` | how long a start waits for another process that is copying an index into the same folder |
| `_PAGE_SIZE` | 32 KB | `vectorcache.py` | the vector cache's page size (architecture.md §5) |
| `_TARGET` | 90% of the cap | `vectorcache.py` | where an eviction stops |
| `_CHECK` | 1% of the cap | `vectorcache.py` | how much a process puts into the cache between two looks at its size; the first put of a process always looks |
| `_EVICT_SECONDS`, `_EVICT_ROWS` | 0.25 s, 256 entries | `vectorcache.py` | the eviction one put may do, and the entries deleted per transaction |
| last use | one write a day per entry | `vectorcache.py` | an entry used again on the same day (UTC) keeps its time |
| `_BUSY_SECONDS`, `_RETRY_SECONDS` | 60 s, 60 s | `vectorcache.py` | how long a cache call waits for another process's lock; how long the cache is left alone after a call failed |
| `_IMPORT_ROWS` | 2,000 rows | `vectorcache.py` | rows read at a time when a cache file with one row per vector is imported |
| `k` cap | 50 | `server.py` | results per MCP search |
| `COMPACT_MAX_DIM` | 4,096 numbers | `config.py` | the longest code of the compact index: every FAISS call it makes was run under a memory checker for each length from 1 to 130 and around each of 192, 256, 384, 512, 768, 896, 1,024, 1,536, 2,048, 3,072 and 4,096. Longer vectors are coded on their first 4,096 numbers, with a warning in the log when the index is made |
| `_PER_RESULT` | 4 candidates | `store.py` | the compact index scores exactly at least this many candidates for each result asked for (and never fewer than `[compact] rescore`) |
| `_RANKED` | 4,000 codes | `store.py` | how many of the 1-bit scan's best the fine codes rank again, at least. The deepest place a search's exact top 50 reached in the scan's order: 1,901 on 31k real vectors, and on the real pandas and vLLM indexes 661 and 976 for questions about the repo, 2,021 and 2,178 for a question about another repo. 2,000 lost one result in each of those two; 4,000 holds them all. Each code ranked costs 0.3 µs with FAISS 1.16.0, so 2,000 more cost a search 0.5 ms (1.4 µs and 2.6 ms with FAISS 1.15.1 on ARM, which has no vectorized code for it) |
| `_RANKED_ONE_IN` | 50 | `store.py` | on a larger index the fine codes rank one in this many of the vectors a search may return (4,000 at 200,000): the depth a search needs grew more slowly than the index in samples of 4k to 31k vectors |
| `_RANKED_PER_CANDIDATE` | 4 | `store.py` | and at least this many for each candidate to score, which matters above 500 candidates |
| `_QUERY_BITS` | 4 bits | `store.py` | how finely FAISS rounds the query for its estimates; 8 bits kept one more search in 268 at half again the scan time, and an unrounded query takes 18 to 37 times the exact scan |
| `_VECTOR_READ_CACHE_KB` | 2,000 KB | `store.py` | the page cache of the connection that reads candidates' vectors, one per thread. 4, 8 and 16 MB were no faster and kept 13 to 31 MB more |
| `_ROTATION_SEED` | 20261125 | `store.py` | names the rotation the compact codes are made after. Another value makes every saved `.rabitq` file unreadable: each is then rebuilt from `index.db` |
| the exact index's memory | 2 bytes a number and 64 bytes beside them, per vector | `store.py` (`FaissVectorStore.bytes_per_vector`) | what `auto` adds up against the budget. Measured: a process keeps 1,853 bytes per vector of 896 numbers at 200,000 vectors (1,792 for the numbers, 8 for the id, 32 for where the vector came from, 21 in FAISS's id map) |
| `_BUDGET_ONE_IN`, `_BUDGET_FLOOR` | 50, 128 MB | `config.py` | `vector_memory_mb = 0`: the budget is one fiftieth (2%) of the machine's memory, and never less than 128 MB |
| `_ASSUMED_MEMORY` | 16 GB | `config.py` | the memory a machine is taken to have where it cannot be read (it is read with `sysconf` on macOS and Linux, where a container's lower limit counts, and with `GlobalMemoryStatusEx` on Windows) |
| `_BACK_TO_EXACT` | 0.8 | `store.py` | `auto`: an index that is compact goes back to exact only when the exact indexes would take less than this share of the budget |

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
- **An assist endpoint is no part of any key or setting.** What it embeds is stored under the
  local embedder's key, and `[embedding.assist]` is not in the index settings. Setting it,
  changing it or removing it redoes nothing, and an index built with it equals one built without
  it. That is only right if the endpoint gives the local model's vectors, which the check before
  its first text is for (§3).
- **The API key, the server's key and an assist's key** are never part of anything: only the name
  of the environment variable is in the config, and the key is read at each request. It is never
  written to the index, the logs or `index_status`.
- **The search index is in the index settings only where a configuration names it.** `auto` is
  not, and neither is its budget: an index keeps its settings, and the eval its index key,
  whichever search index it gets. `faiss`, `compact` and a plugin are named, and so are the
  `[compact]` options that differ from their defaults, where the backend can use them.

**When you change a setting, what is redone:**

| Change | Redone | Cost |
|---|---|---|
| the model, the embedder, new weights in a model folder, `dtype`, the device | that vector type is re-embedded | a full embedding (vLLM: about 5 h on the M1), unless the cache has it |
| an API's `model`, `dimensions`, `document_prefix` or `space`; its address when no `space` is set; between the model in process and the same model served | that vector type is re-embedded | the same |
| an API's address when a `space` is set | nothing | none |
| `[embedding.assist]`, any of it | nothing | none; the endpoint is compared with the local model again before it gets work |
| `embedding_dim`, `vector_backend`, the `[compact]` options, and `vector_memory_mb` when it changes what `auto` picks | the search index is rebuilt from the stored vectors, in the background (architecture.md §5) | 0.5 to 5 s for an exact index of 50,000 to 200,000 vectors, 12 to 70 s for a compact one; searches answer from keywords meanwhile |
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
| `~/.codemem/indexes/<repo>-<hash>/index.db` | the index | ~640 MB | rebuilt by the next update: the structure in about 70 s, vectors from the cache. The `vec_*` files beside it name the database they were saved from, so they are not read into the new one: the search indexes are rebuilt from its rows |
| `~/.codemem/indexes/<repo>-<hash>/vec_*.faiss` | the exact index's saved copies | 1,800 bytes per vector of 896 numbers (~260 MB) | rebuilt from `index.db` in about 2 s |
| `~/.codemem/indexes/<worktree>-<hash>/` | the index of a git worktree: a full index of its own | ~640 MB, ~900 MB once its search indexes are saved | copied again from another checkout's index at the next start there (1 to 2 s on vLLM, then one full check) |
| `~/.codemem/indexes/<worktree>-<hash>/worktree.json` | which worktree the folder serves, and its repository | tiny | written again at the next start in that worktree; until then the folder is not deleted when the worktree is removed |
| `~/.codemem/indexes/<repo>-<hash>/vec_*.rabitq` | the compact index's saved copies: vector ids and codes | 596 bytes per vector (119 MB at 200,000 vectors); 128 bytes at `bits = 1` | rebuilt from `index.db`, in the background: 32 to 70 s at 200,000 vectors |
| `~/.codemem/cache/vector_cache.db` | the vector cache: the vectors computed on this machine, the least recently used ones only while the cap has room, and none that no index has needed for 30 days | 1.9 KB per vector (272 MB for vLLM's 145,000), at most the cap: 8 GB | **costly:** the next rebuild of each repo re-embeds everything (vLLM: about 5 h). The one file worth keeping. To make it smaller, lower `vector_cache_max_gb` or `vector_cache_max_age_days` and run `codemem index`: the least recently used vectors go first. To delete it, stop every codemem process first: a running one keeps writing to the deleted file, and those vectors are lost |
| `~/.codemem/cache/vector_cache.db-wal`, `-shm` | SQLite's write-ahead log of the cache, and the log's index | the log is cut back to 64 MB after it has been copied into the cache file | they are part of the cache while a process runs: delete them only together with it, and only when no codemem process runs |
| `~/.codemem/cache/vectors.db` | a vector cache with one row per vector | 4.7 KB per vector | codemem imports it into `vector_cache.db` when the cache is next opened, then deletes it (34,218 vectors: 1.6 s). While a process still writes it, it stays and is imported again at each start. Deleted by hand before the import, its vectors are embedded again when needed |
| `~/.codemem/model_hashes.json` | hashes of local model folders' files | tiny | each local model folder is read once more (about 1 s per GB) |
| `~/.codemem/assist/probe-<hash>.npz` | the seven probe texts of an assist's check, the local model's vectors for them and its document prompt, one file per embedder key | about 40 KB (25 KB of vectors, the rest the texts) | the local model finds the text that fills its limit and embeds the seven once more, at the next check |
| `~/.codemem/assist/checks.json` | what the last check of each assist endpoint found, per local model, for `codemem status` | tiny | `codemem status` says "not checked yet" until the next check |
| the Hugging Face model cache (`HF_HOME`) | the downloaded model | ~1 GB | downloaded again at the next start (needs the network) |
| `~/.codemem/config.toml`, `<repo>/.codemem.toml` | your settings | | yours to keep |

`CODEMEM_HOME` moves `~/.codemem`; in this project `.cache/env.sh` keeps every cache, model and
index inside the project folder.

**codemem deletes one kind of folder by itself:** the index of a git worktree that is gone. Every
start in a checkout of a repository looks at the index folders of that repository's worktrees and
deletes one only if all of this holds:

1. it is a real folder (not a link) directly inside `~/.codemem/indexes/`;
2. it holds a `worktree.json`, which codemem writes only into the default index folder of a
   linked worktree, never into a main checkout's or into a folder given with `--index-dir`. A
   start in a folder that has become another kind of checkout (a clone where a worktree used to
   be) removes the record;
3. that record names the repository codemem was started in;
4. the folder's name is the one codemem gives the recorded worktree;
5. the worktree's folder certainly does not exist. A folder that codemem has no permission to
   look at counts as existing;
6. git no longer lists the worktree. After `git worktree remove` it does not. A folder that
   is missing for another reason (a drive that is not mounted, `rm -rf`) is still listed, and
   its index stays until `git worktree prune` or git's own clean-up drops it. Two spellings of
   one path that differ only in letter case count as the same folder. If git's list cannot be
   read, nothing is deleted.

Then it deletes the files codemem itself writes there (`index.db` and its SQLite side files,
`vec_*`, `write.lock`, `worktree.json`) and removes the folder if it is empty. Any other file
stays, with the folder. An index that a codemem process is writing at that moment is left for a
later start. Indexes of main checkouts, and of repositories that were deleted whole, are never
deleted: remove them by hand.

---

## 7. Network and privacy

codemem goes over the network in three cases only:
- **downloading the model** from Hugging Face, once (`HF_HUB_OFFLINE=1` stops even the update
  check afterwards);
- **an embedding API**, only if you configure one. That sends your code to the provider, and
  `index_status` says so. A `serve-embeddings` server is such an endpoint: the code goes to the
  machine it runs on;
- **an assist endpoint**, only if you configure one. The texts of a build's large embedding calls
  go there, and seven fixed probe texts that hold none of your code. Queries, the texts of small
  calls, and texts longer than the local model reads do not. `codemem status --check-assist`
  sends the seven probe texts only. `index_status` names the endpoint and says that code is sent
  to it.

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
| the first search after an embedding endpoint stops answering | it waits for its own request's retries, about 31 s, before it answers from keywords; the searches after it answer at once | send a search's query once, with the search's own 4 s as its time limit |
| `refresh_index` while the embedding endpoint does not answer | with chunks queued it ends in a tool error without a reason; the structure is updated before that, and `index_status` shows the error | return what changed and what is queued, with the reason |
| the loading note speaks of start-up only | after the model was freed for being idle, a search that answers from keywords still says "the first search after codemem starts" | reword the note in `prompts.py` |
| PyTorch is always installed | about 0.8 GB, even for a codemem that only embeds through an API or a `serve-embeddings` server | make the local model an optional install; needs a one-line change in the eval's dependencies. Such a client's environment can be built without the two packages by hand (README, "One model for several codemem processes") |
| an MCP server answers for the checkout it was started in | an agent that works in another git worktree of the repo, but calls a server started in the main checkout, searches the main checkout's code and gets no note | start a server in each worktree. Whether agent hosts do that for their subagents is not documented; it needs a test with a real agent |
| a new worktree's index is copied before the MCP handshake | on vLLM the server answers its first message 1 to 2 s later; an agent host with a short start-up limit could give up on a much larger repo or a busy disk | open the index in the background, or clone the file where the file system can (APFS: no time, no extra disk) |
| every worktree has a full index on disk | vLLM: ~640 MB each, ~900 MB with its saved search indexes | vectors stored once per machine, so an index holds only structure |
| the local embedder gives jina's two prompts to every model | a model without jina's prompt names (`nl2code_query`, `nl2code_document`) is embedded with jina's prompt texts in front, which it was not trained with. `serve-embeddings` prints the same two texts as its clients' prefixes, so a served model matches the model in process | the model's own `query` and `document` prompts, else `query_prefix` and `document_prefix`. The key of those models then has to change, and the document prefix becomes an index-time setting of local indexes |
| an assist shares only a build's large calls | a first build that the MCP server's writer does in the background is made of calls of at most 16 texts and 3,000 characters, so the endpoint gets none of it. Build with `codemem index` or `codemem init`, which embed in calls of 256 texts | larger background calls while no search waits, or sharing a small call by measured speed |
| an assist endpoint gets no text longer than the local model reads | a code text is a window of whole lines sized at 3 characters for each token of the limit, and a usage text can be twice as long, so the texts over the limit are the dense and the long ones. Their share of a repository has not been counted, and the local model embeds all of them | count them on a real repository with the model's tokenizer; share them with an endpoint that is shown to cut where the local model does (a `serve-embeddings` server with the same settings) |
| the time to count a call's tokens is not measured for the default model | each large call tokenizes its longer texts once more than the model does, on a copy of the tokenizer that is made at each model load | time one call of 256 texts and the copy, and read the copy's size, on a quiet machine |
| the indexer keeps one speed estimate for shared and local calls | a call is timed as a whole, so after a shared call the estimate is the two sources' speed together, and after a small call it is the local model's alone. In a process that makes both (an MCP server after `refresh_index`, `codemem watch` after its first update), a search's catch-up can start a small call that the estimate says fits its 4 s and that ends after them: by less than one small call's time, and only until a few small calls have moved the estimate. `refresh_index` (60 s) makes large calls: one that follows small calls is judged slower than it is and may not be started, and one that follows shared calls runs past the 60 s by a share of its own time when the endpoint has stopped answering. None of it has been timed | one estimate for calls of at most `batch_size` texts and one for larger calls, in `Indexer._compute` |
| an assist has only met stand-in models | the check, the split and the failure handling are tested with fake models and a `serve-embeddings` server. The token count was compared with a small BERT model's own cutting on a CPU. No hosted provider was called, and the default model shared no build | a build with the real model against a `serve-embeddings` server on a second machine, and `codemem status --check-assist` against a hosted API with its key |
| the embedding server's client reads vectors as JSON text | 1.2 to 2.1 ms a text in a build (§3): 1 to 2% of the model's time on the M1, and a larger share the faster the model is. A search does not notice it | the server also answers `encoding_format = "base64"`, which costs 0.06 to 0.12 ms a text in the same measurement; have the client ask for it |
| a running server applies a lowered cache cap slowly | it evicts for 0.25 s per put, so a cache far over the lowered cap shrinks over many puts | `codemem index` brings it under the cap in one go; let the server do the same when it is idle |
| the compact index after a restart | each search reads its candidates' rows from the disk, about 30 ms more, until the system's file cache holds them | read the vector rows once in the background at start, so the file cache holds them |
| the compact index's agreement is measured on one model, on indexes of up to 145,000 vectors | on a larger index, or another model's vectors, the best 4,000 (or one in 50) of the 1-bit scan may hold less of a search's exact top 50 | measure it on each eval repo and each model (`scripts/check_search_indexes.py`) |
| the compact index and a query with nothing near it | on 200,000 synthetic vectors such a query got its exact top 10 in 78% of searches and 92% of its top 50; FAISS's own scan of the fine codes gets all of it at 3 to 4 times the exact index's time | scan deeper when the scan's cut lies close to the candidates' cut, or a setting that hands the fine codes to FAISS's own scan |
| `vector_backend = "compact"` on a small index | a search takes 4.5 ms against the exact index's 3.0 on pandas's 43,000 code vectors, and 3.9 against 2.4 ms on vLLM's 35,000 usage vectors (FAISS 1.16.0): ranking 4,000 codes and reading 200 vectors take about 3 ms, whatever the index's size. The two indexes meet at about 100,000 vectors | nothing is needed: `auto` uses the compact index only where the exact one does not fit the memory budget |
| `auto` picks when the search indexes are loaded | an index that grows past the budget in a running server stays exact, and over the budget, until the next start or the next update that saves | pick again when the server has been idle, and rebuild in the background |
| `auto` knows its last pick only from the saved copies' notes | a vector type that lost all its vectors keeps the files of its last save, and they do not count while it has none. If it gets vectors again before `auto` next picks, and those files are compact while the other types were saved as exact since, `auto` takes the index for compact: between 80% and 100% of the budget it then picks compact for an index that was exact. With no save at all there is nothing to know the last pick from | write the pick into `meta` in the transaction of each save, and read it from there; or remove the saved copy of a type without vectors when an update saves |
| the saved file of a plugin search index that is no longer in use stays | a save removes the saved copy of another backend when it knows that backend's file name: the exact and the compact index, and the plugin in use. After a change from a plugin that saves its index to another backend, the plugin's `vec_<type><suffix>` files stay in the index folder; nothing reads them | delete them by hand; or keep each backend's suffix in the note, in a form that cannot name another file |
| the compact index is checked on macOS on Apple silicon only | FAISS's RaBitQ code on Linux and on x86 has not run under the tests. And on macOS the tests run FAISS on one thread, as codemem does there. On more threads its calls ran in `scripts/check_faiss_calls.py` (8, and 2), and both indexes were built once on 2 threads from 20,000 vectors, in batches of 4,096: the same bytes and the same results as on one thread | run the three test runs (README) and `scripts/check_faiss_calls.py` there, and `scripts/check_search_indexes.py` on a real index |
