# How codemem works

codemem is a local code search tool for coding agents. You point it at a repository. It cuts
every source file into functions, classes and blocks of top-level code, and remembers three
things about each one:
- its words (keyword search)
- its meaning (embeddings)
- who calls it (call graph)

An agent asks it questions in plain words over MCP, or a script asks over the CLI. It gets back a
short ranked list of places in the code. Everything runs on your machine unless you choose an
embedding API.

**Status.** This page describes the **v3 design**. It is being built on branch
`andre/backend-v3`. The table in §2 says which parts already work. Exact record formats and the
contracts with the MCP tools and the eval are in [data-model.md](data-model.md). Constants and why
they have their values are in [decisions.md](decisions.md). Research directions are in
[advanced-design.md](advanced-design.md), and what we take from Exa is in [exa.md](exa.md).

---

## 1. Why it exists

**The gap.**
- Claude Code and Codex search code with grep. Claude Code tried semantic search and dropped it,
  citing security, privacy, staleness and reliability. Codex has an open feature request for it.
- Cursor kept its semantic index and reports +12.5% agent accuracy, best when used together with
  grep.
- The worries that sank semantic search (privacy, stale results, setup) are design problems, and
  codemem is built around them: local by default, fresh within a second, one-command setup.

**What it is for.** Vague, feature-level questions in a codebase you don't know well:
- "I want to add login auth but have no idea where to start."
- "I want to add OCR to my pipeline. It doesn't support image upload yet."

Keyword search fails on these, because the question shares no words with the code. grep takes
many tries. codemem should find the relevant functions in one or two calls. **grep stays the tool
for exact strings;** codemem works next to it, not instead of it.

**How we judge it.** Three axes, the same as the project's research questions:
- **accuracy:** does it find the right functions?
- **tokens:** does the agent read less to get there?
- **time:** are queries fast, and is an edit searchable within about a second?

**The running example.** The agent gets the issue *"Disabled users stay logged in"*. The fix
belongs in this function in the sample repo (`tests/fixtures/sample_repo`):

```python
# auth/sessions.py
def revoke_session(session_id):          # lines 19-20
    db.sessions.delete(session_id)
```

`grep` for the issue's words fails: `revoke_session` contains none of them. Its neighbours do:
`disable_user()` calls it, and `test_disabled_user_loses_sessions` tests it. We follow this
function through every stage.

---

## 2. The system at a glance

```
          INDEX AND FRESHNESS (only what changed)                         SEARCH (per query)

 file saved ─► 1 watcher ─► dirty files ─► 2 incremental update          agent: "where are
                                │            ├─ 3 chunk (tree-sitter)    sessions revoked?"
   startup / every 5 min /      │            ├─ 4 link calls                   │
   refresh_index ─► reconcile ──┘            ├─ 5 build texts                  ▼
                                             ├─ 6 embed (local or API)   MCP / CLI ─► service
                                             └─ 7 store (SQLite + FAISS)    │  catch up first
                                                           ▲                ▼
                                                           └──────── 8 search ─► ranked cards
```

| # | Component | Module | Job | Status |
|---|---|---|---|---|
| 1 | Watcher | `watcher.py`, `service.py` | turn file events into a set of changed paths; trigger updates | v3 works: changed paths, quiet period and maximum wait, git branch switches, polling fallback. Catch-up before every search: the search hands pending saves to the writer and waits at most its limit; `get_chunk` waits for stage A; background embedding gives way to searches and new saves at its next model call; model calls are sized by text length |
| 2 | Indexer | `indexer.py` | one update function for the first build, reconciles and single saves | v3 works: two stages and a persistent queue, the exact usage ripple, settings tiers, verify mode. Inside a changed file, only new or changed chunks are relinked and re-checked; moved ones get a line-number update |
| 3 | Chunker | `languages/`, `chunker.py` | functions, methods, classes and blocks in nine languages | works; v3 fixes done: Python comments, huge statements split by content, and one comment rule for every language (a new language only declares its comment syntax) |
| 4 | Call graph | `callgraph.py` | link each call to the definitions of that name | works |
| 5 | Texts | `texts.py` | what gets embedded: code with a context header, usage (callers, tests) | works; v3 window fixes done |
| 6 | Embedder | `embedder.py`, `vectorcache.py` | local model by default; any OpenAI-compatible API (v3) | works: local model, or any OpenAI-compatible API (batches, parallel requests, retries; tested against a fake server; a Nebius smoke test runs when `NEBIUS_API_KEY` is set) |
| 7 | Store | `store.py` | SQLite holds everything; FAISS is a derived search index | works; v3 queue, catch-up by vector id and lazy saves done |
| 8 | Search | `search.py`, `render.py` | BM25 + one vector search per text type, merged by rank, rendered as cards | works; v3 catch-up, query clean-up (long queries 30x faster) and neutral weights done |
| 9 | Front-ends | `server.py`, `cli.py`, `prompts.py`, `agents.py` | MCP tools for agents; CLI for people and scripts | works; v3 tools done: `refresh_index`, `kinds` and `tests` filters, a freshness note in results, coverage in `index_status`, `init` that works without `codemem` on PATH, `index --verify` |

**Product shape** (unchanged since Week 1):
- One local Python package and one command, `codemem`, for both the CLI and the MCP server.
- The core library holds all logic; the MCP server and the CLI are thin front-ends over
  `CodememService`.
- While a session runs, the MCP server owns the index and the watcher. A long-running daemon could
  come later, and nothing in the core assumes otherwise.
- It works on Windows, macOS and Linux.

---

## 3. Finding files, and not missing any

`walk_source_files` walks the repository and keeps every file whose extension belongs to a
supported language. There are nine: Python, JavaScript, TypeScript, TSX, Go, Java, Rust, C and
C++ (with CUDA `.cu`). A `.h` file is C unless it uses C++ syntax.

**Skipped by name:**
- paths in `.gitignore` (nested ones too);
- folders like `.git`, `node_modules`, `.venv`, `build`, `dist`;
- vendored or generated paths: `vendor/`, `*.min.js`, `*_pb2.py`, `*.pb.go`.

**Read, then skipped by content:**
- binary files (a NUL byte in the first 8 KB);
- files marked `Code generated … DO NOT EDIT` or `@generated`;
- minified JS/TS (any line over 5,000 characters).

**Coverage (v3).** No file is skipped silently:
- The size cap rises from 1 MB to 10 MB.
- Every skipped file is stored with its reason: too large, generated, minified or binary.
- The walk also counts ignored files and non-code files by extension (`.md`, `.yaml`, …).
- `index_status` and `codemem status` show all of it. For example: "6,235 indexed · 3 skipped
  (2 generated, 1 too large: vllm/x.py 12 MB) · 410 not code (.md 220, .yaml 120, …)".

*Example:* `auth/sessions.py` is Python. It is new, so it goes to the chunker. Later, an
unchanged size and modification time mean it is not even read.

## 4. Chunking

tree-sitter (one engine, one official grammar per language) parses each file into a syntax tree.
A small **language spec** per language (`languages/python.py`, `go.py`, `c_family.py`, …) says
which tree nodes are functions, classes and namespaces, how to read their names, and which nodes
are calls and tests. One generic **walker** (`chunker.py`) follows the same rules for every
language:

1. A function or a class becomes a chunk.
2. A namespace-like wrapper (C++ `namespace`, Rust `mod` and `impl`, TS `namespace`) is not a
   chunk. Its name becomes a prefix of the names inside it (`auth.SessionManager.ExpireOld`).
3. Runs of other top-level statements (imports, constants, script code) become **block** chunks
   of at most 200 lines.
4. In a class, each method becomes its own chunk, and the other lines go into the class's
   **outline** (its skeleton).
5. In a function, only nested named functions become chunks. Lambdas and callbacks stay part of
   the parent.
6. Every call's name and line is recorded for the call graph.

Wrappers that hold definitions are opened: `if TYPE_CHECKING:`, `try/except ImportError`,
`#ifdef`, `extern "C" {}`.

*Example:* `auth/sessions.py` gives:
- a block (lines 1–5: the docstring and imports);
- the functions `new_token`, `create_session` and `revoke_session` (lines 19–20);
- the class `Session` and its method `Session.__init__`.

`revoke_session` is stored with its signature, code, key `auth/sessions.py::revoke_session`, and
its calls: `["delete"]`, from `db.sessions.delete(...)`.

**Length.**
- Functions and classes have no length cap; the syntax decides.
- A long function is still one chunk. Only its *embedding* is split into windows (§6).
- Blocks are capped at 200 lines.

**v3 changes:**
- **Python comments directly above a definition become its doc text.** Today they are dropped.
  Other languages already do this. Line ranges stay the same, because the eval's labeler excludes
  comments.
- **Blocks over 200 lines are split by lines,** even inside one statement. Today one giant
  statement stays one block: a 1,668-line dict in `vllm/envs.py`.

## 5. The call graph, and usage

Every call a chunk makes is stored as a callee **name**. Names are linked to the functions,
methods and classes that define them, within one language family (C with C++, JavaScript with
TypeScript). A name defined more than five times (`get`, `run`) is ignored, because it would link
everything to everything.

Each link is one row (caller → callee), so both directions are cheap to read:
- `get_chunk` shows a chunk's callers and callees, so the agent can navigate.
- The **usage text** lists a chunk's callers and tests, and is embedded for search (§6).

*Example:* `disable_user` and `logout` call `revoke_session`, and
`test_disabled_user_loses_sessions` calls it too.

This is a deliberately simple heuristic, isolated in `callgraph.resolve_edges`, so that a resolver
using imports and scopes can replace it later.

## 6. Texts and embeddings

Each chunk gets one text per **vector type**. Each type is embedded and searched separately;
they are never mixed into one vector.

- **code:** a context header, then the code.
  - The header gives the embedder what raw code lacks: the file path and the enclosing class or
    namespace.
  - Outside Python, the doc comment comes next.
  - A class embeds its outline, not its full code, because its methods are chunks of their own.
- **usage:** who calls the chunk and which tests reach it. This is the "anchor text" idea from
  web search: what others say about a page often describes it better than the page itself.
  ```
  revoke_session in auth/sessions.py
  called by logout in api/routes.py
  called by disable_user in auth/users.py
  tested by test_disabled_user_loses_sessions in tests/test_users.py
  ```
  Only chunks that something calls or tests have one. On vLLM that's 35k of 102k chunks.
- **summary:** an empty slot for LLM summaries. It is switched off and produces nothing.

**Windows.**
- A code text longer than the model reads well (about 3,000 characters for 1,024 tokens) is split
  into windows of whole lines, overlapping by 3 lines.
- Each window is one more vector of the same chunk. The chunk scores by its best window, and the
  card shows that window's lines.
- On vLLM, 95.4% of chunks fit in one window.
- **v3:** every window after the first names its function in its header (today windows 2..n
  don't). Windows are also split evenly, so a 126-line function becomes three windows of about 42
  lines instead of 64 + 63 + 5.

**Embedding.** Before calling the model, codemem looks a text's hash up in this index, then in a
shared **vector cache** on disk (`~/.codemem/cache/vectors.db`). That cache holds every text ever
embedded on the machine, so rebuilds, branch switches, undos and other commits of the same repo
cost no model calls.

| Provider | When | Notes |
|---|---|---|
| **local** (default) | always available | `jinaai/jina-code-embeddings-0.5b`, 896 numbers per vector, float16 on a GPU (CUDA or Apple MPS), float32 on CPU; separate task prompts for queries and code |
| **openai** (v3) | opt-in, in the config | any OpenAI-compatible endpoint (Nebius, OpenAI, Together, a self-hosted vLLM or TEI server, Ollama). The key comes from an environment variable. Batching, parallel requests, retries, and an optional shorter vector size |

The same model always embeds both the index and the queries. The cache key includes the provider,
model and settings, so vectors from different setups never mix. Remote embedding sends code to
the provider, so it is never on by default, and `index_status` says when it is on.

## 7. Storage

One folder per index, by default `~/.codemem/indexes/<repo>-<hash of the repo path>/`:
- **`index.db`** (SQLite) holds everything:
  - files and chunks;
  - a 5-field BM25 index (name, path, signature, doc, body);
  - calls and links;
  - every vector, as a float16 row.
- **`vec_code.faiss` and `vec_usage.faiss`** are exact search indexes **derived** from those rows.
  If one is missing, stale or corrupt, it is rebuilt from the rows without the model (2 s on
  vLLM).

**Why SQLite plus FAISS, and not a vector database.**
- Nothing to install or run.
- Most of what we store is not vectors, and it needs lookups, joins and keyword search.
- Transactions keep each update atomic.
- The stored vectors are the source of truth, so FAISS can always be rebuilt, and compression
  experiments need no re-embedding.

The vector index sits behind a small interface (`VectorStore`), so it can be swapped for Qdrant,
an HNSW index or another engine later. Exact search takes about 10 ms for 109k vectors.

**Consistency.** SQLite has real transactions; FAISS doesn't. Three rules keep FAISS correct:
1. FAISS changes are applied only after the SQLite commit.
2. Its version number (the epoch) is updated last.
3. It is trusted only when its version matches SQLite's.

A crash therefore costs at most a rebuild, never wrong results. One process writes at a time (a
lock file), and searches keep working during updates (SQLite WAL).

## 8. Freshness: the v3 core

**What v2 does.** After each save, the watcher waits 0.4 s, then runs a full update that does
four things over the whole repo:
- checks every file;
- relinks every call;
- rebuilds every text to compare hashes;
- rewrites the FAISS files.

It re-embeds only changed texts, but the rest costs 8 s per save on vLLM, and 6.8 s with nothing
changed. A search in the meantime sees the old index.

**v3, in one picture:**

```
 file saved ──▶ watcher ──▶ changed paths       (in memory; a crash loses nothing:
                               │                 the startup reconcile finds the same files)
             ┌─────────────────┴────────────────────┐
             ▼                                      ▼
   background writer: 0.5 s after the     search: hand every save seen so far to the
   last save (at most every 2 s while     writer and wait for its stage A, then embed
   saves keep coming)                     the queue, newest edits first; at most 4 s
             │                            in all; then answer
             └──────────────┬───────────────────────┘
                            ▼
   stage A, structure (milliseconds): chunks, keywords, calls, links, and the queue of
       chunks whose texts may have changed (dirty_texts, in the same SQLite transaction)
   stage B, vectors (the slow part): rebuild the queued texts, embed only the changed
       ones, store them, clear their queue rows

 safety nets: startup reconcile · reconcile every 5 min · refresh_index tool · polling fallback
```

**The guarantee.** A search reflects every file saved before it started: keywords and links
always, and ranking by meaning whenever the queue fits in the catch-up budget
(`catchup_budget_ms`, 4 s). That covers ordinary edits: a one-function edit took 0.11–0.17 s
with the real model on the sample repo. A bigger change (a branch switch, a reformat) gets what
fits, newest edits first, and the response counts what is still queued (shown to the agent from
phase 2). While a chunk has no vector yet, it can only score through keywords, so it ranks lower
than it will once embedded.

**The incremental update.** It is one function for the first build, a reconcile and a single
save. **Stage A**, in one SQLite transaction:
1. **Find the changed files.** For the watcher's paths, or by scanning everything, compare size
   and date, then the content hash.
2. **Remember their old state:** chunk ids, the names they define, and their outgoing links.
3. **Re-chunk** those files, and match old and new chunks by key (`path::qualname`):
   - identical chunks are left alone;
   - chunks that only moved (same content, new lines, say after a line was added above them)
     get their line numbers shifted, and nothing else;
   - new and changed chunks are written in full.

   If moved chunks changed their order (functions swapped), they count as changed: usage texts
   list callers by line.
4. **Relink only what can change:**
   - the calls made by new or changed chunks;
   - every call anywhere to a name that was added or removed (this includes the 5-definitions
     limit).
5. **Queue the chunks whose texts may have changed** (`dirty_texts`: a chunk id and the commit's
   sequence number):
   - the new or changed chunks;
   - what they call, and what deleted chunks called (their usage texts list them);
   - any chunk whose callers changed.

   So the work follows the edit, not the file: a one-character edit in a 50,000-function file
   queues 1 chunk (it queued all 50,000 before Oct 25). What remains is parsing the file
   (1.2 s for 2.3 MB), which needs tree-sitter's incremental parsing to avoid (parked).

**Stage B**, in batches; the write lock is not held while the model runs:

6. **Rebuild the queued chunks' texts** and compare their hashes with the stored vectors. Only
   changed texts need a vector.
7. **Embed those:** from this index, then the shared cache, then the model. Newest edits go first.
8. **Store the vectors** of chunks whose sequence number hasn't changed meanwhile (a chunk edited
   again stays queued for its newest version), and clear their queue rows. Patch FAISS in memory,
   and write it to disk later (after 30 s idle, on shutdown, and on `refresh_index`).

**Why the ripple is small.** A usage text lists a chunk's *callers*. So a change in file A
reaches only the usage texts of what A calls. The functions that call A don't change: their code
is their own, and their usage lists their own callers.

*Measured:* renaming `revoke_session` to `end_session` across 4 files re-embedded 9 of 33 texts.
Only one of them, `Table.delete`'s usage, sat outside the changed files.

**Verify mode.** The old global recomputation stays as a check (`codemem index --verify` and the
tests). It reports any difference between the incremental result and a from-scratch result.

**What can go wrong, and what happens:**

| Situation | What happens |
|---|---|
| a search during an update | SQLite readers see the state before or after a transaction, never half |
| a crash at any point | SQLite rolls back; FAISS is rebuilt if its version is behind; the startup reconcile re-finds pending files |
| two agent sessions on one repo | the lock file serializes writers; a search waits only up to its budget |
| a search while the background writer is applying a save | the search waits for it, within its budget: every hand-over of saves is numbered, and the search waits until the writer has committed its number |
| stage A takes longer than the budget (a huge file, a checkout still writing) | only the writer applies saves, so the search stops waiting at its budget and reports those files as pending |
| a backlog of embeddings when the agent searches | the writer hands over the model at its next call; the search embeds the newest edits first and stops at its budget. Model calls hold at most 3,000 characters outside a build, and one isn't started if the measured model speed says it would end past the budget |
| a crash between stage A and stage B | the queue rows were committed with the edit, so the next start embeds them |
| a git checkout is still writing files | updates wait for it (up to 10 s; a search only up to its budget, then it reports those files as pending) |
| a file changes while being indexed | its event lands in the dirty set again |
| `.gitignore`, `.codemem.toml` or the git branch changes | a full reconcile |
| a chunker or settings upgrade | stored settings differ from the current ones; only what the setting affects is redone: vectors, texts, links, or a rebuild with vectors from the cache (D23) |
| OS file events don't work (network drives, WSL, Linux watch limits) | a warning, then a reconcile every 10 s; each search asks for a full check first (0.5 s on vLLM), so it still includes every earlier save |
| the watcher can't confirm in time that it has seen every earlier save (a heavily loaded machine) | the search answers, but says "unconfirmed" instead of "complete" |

## 9. Search

For the query *"disabled users stay logged in"* (measured on the sample repo):

1. **BM25.** The query is split into words the same way the code was. SQLite's FTS5 ranks the
   chunks that share words: a match in a name counts most, then signature, path, doc and body.
   `revoke_session` shares no word, so it is not found here. The test is, by its name.
2. **Vectors.** The query is embedded once, then compared with every code vector and, separately,
   every usage vector. `revoke_session` is 10th by code and 2nd by usage.
3. **Merge by rank (RRF).** Each list adds 1 / (60 + rank) to a chunk's score. Ranks, not raw
   scores, are merged, because BM25 and dot products aren't comparable.
4. **Filters and weights.**
   - Filters: `path_prefix`, `kinds`, `languages`, tests. They apply inside each list.
   - **v3: weights are neutral by default.** v2 halved tests, classes and blocks, which our eval
     rewarded only because tests are never its answers.
5. **Cards.** Ties are ordered by location, so the order is the same on every machine. Each
   result becomes a short card: location, name, id, signature and a few lines. A long function
   shows its best window.

```
3. auth/sessions.py:19-20  revoke_session  [id 14]
   def revoke_session(session_id):
   |     db.sessions.delete(session_id)
```

**v3 latency fix.** BM25 joins every query word with OR, so a 250-word query took 1.1 s on vLLM.
The query now drops stopwords and keeps at most the 32 rarest words. The index is unchanged.

## 10. Front-ends: how an agent uses it

| Command | Purpose |
|---|---|
| `codemem init --agents claude,cursor,codex` | registers the MCP server, then builds the index |
| `codemem index` / `search` / `status` / `watch` | for people, scripts and debugging (`--json`, `--debug`) |
| `codemem mcp` | what agents launch, over stdio |
| `codemem languages` | supported languages and extensions |

**MCP tools:**

| Tool | Does |
|---|---|
| `search_code(query, k=10, path_prefix, kinds, tests)` | ranked cards; catches up on pending edits first (v3: `kinds`, `tests`) |
| `get_chunk(ref)` | full code plus callers and callees; a long class gives its outline and members |
| `index_status()` | ready or indexing, counts, freshness, coverage, embedder |
| `refresh_index()` (v3) | full reconcile now; for after `git checkout` or `git pull` |

**Steering.** All agent-facing wording (tool descriptions, server instructions, notes for
`CLAUDE.md`) lives in `prompts.py`, at three strengths: `none`, `light`, `strong`. Getting
agents to use the tool at all is the real adoption problem. So the text stays short (server
instructions under 2,048 characters, outputs well under 10k tokens), and the agent study measures
how often agents call it.

**Portability (v3).**
- **Launch command.** `codemem init` writes one that works however codemem was installed: the
  `codemem` command if it's on PATH, otherwise `python -m codemem mcp`.
- **No first-use stall.** `init` downloads the model with a progress bar.
- **Logs never go to stdout,** which carries only protocol messages.
- **Tool names stay stable.**

## 11. How the eval uses it

The eval (`eval/`, Andrew's `cmeval`) talks to codemem only through
`eval/src/cmeval/adapters/codemem.py`. For each task it:
1. builds or updates an index at the task's commit;
2. searches with the issue text;
3. grades the returned line ranges against the fix.

Three things keep it fair:
- **Index sharing:** `Config.index_settings()` lists every setting that changes the index, and
  systems share an index only when those are equal.
- **Update vs rebuild:** the B4 check requires both to give the same results.
- **An independent ruler:** the labeler is a separate implementation, so a codemem bug can't hide
  itself.

**v3 doesn't change the eval.** One change is highlighted for later: today's queries are whole
issue texts and its answers are bug fixes, so it can't show the vague-question use case (§1).
The contract is in [data-model.md](data-model.md) §12.

## 12. Performance

Measured on the M1 laptop (jina 0.5B on the GPU). vLLM: 6,235 files, 102k chunks, 145k vectors.

| | v2 (measured) | v3 target |
|---|---|---|
| save → searchable, one-function edit, vLLM | 8 s + queueing | < 1 s |
| update with nothing changed, vLLM | 6.8 s | < 0.5 s |
| search, 10-word query, vLLM | 0.27 s (embedding the query: 0.15 s) | < 0.3 s |
| search, 250-word query, vLLM | 1.64 s (BM25: 1.1 s) | < 0.7 s |
| exact vector search, 109k vectors | 9–10 ms | same |
| full build, `requests` (801 chunks) | 224 s (the MVP: 469 s) | same |
| rebuild with a warm vector cache | no model calls | same |

**Indexing is almost all embedding.** On the M1 that's about 0.2 s per text, so the first build
of a large repo needs a CUDA GPU or an embedding API. Updates after that are small.

## 13. Module map

| Module | Role |
|---|---|
| `config.py` | settings, paths, `index_settings()`, ignore defaults |
| `schema.py` | the `Chunk` record |
| `languages/` | one spec per language, plus the registry |
| `chunker.py` | the generic tree-sitter walker |
| `tokenize.py` | code-aware tokenization, shared by indexing and queries |
| `callgraph.py` | name-based call resolution (replaceable) |
| `texts.py` | text builders (`code`, `usage`, `summary` slot) and windows |
| `embedder.py` | the `Embedder` interface: local sentence-transformers, API (v3), fake for tests |
| `vectorcache.py` | the shared vector cache |
| `store.py` | SQLite and the derived FAISS, filters, recovery |
| `indexer.py` | the one update function |
| `search.py`, `render.py` | hybrid search and cards |
| `service.py` | long-lived owner of one index: updates, freshness, watcher |
| `watcher.py` | file events, debounced |
| `server.py`, `cli.py`, `prompts.py`, `agents.py` | MCP server, CLI, agent-facing text, agent registration |

## Glossary

| Term | Meaning |
|---|---|
| **chunk** | one searchable unit: a function, method, class or block of top-level code |
| **block** | consecutive top-level statements between definitions (imports, constants, script code) |
| **skeleton / outline** | a class's header plus one line per member |
| **vector type** | one kind of embedded text (`code`, `usage`); each is its own vector set |
| **window / part** | one embedded piece of a long text; a chunk scores by its best one |
| **dirty set** | files changed since the last update, not yet indexed |
| **reconcile** | a scan of the whole repo (sizes and dates, then hashes) that finds changed files |
| **BM25** | keyword ranking: shared words count, rare words count more |
| **embedding** | a list of numbers capturing meaning, so similar meanings are close even with no shared words |
| **RRF** | reciprocal rank fusion: merges ranked lists by summing 1 / (60 + rank) |
| **epoch** | the version number that tells whether a FAISS index matches SQLite |
| **embedder key** | the identity of an embedding space (provider, model, settings) |
| **MCP** | the protocol coding agents use to call tools |
