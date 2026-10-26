# How codemem works

codemem is a local code search tool for coding agents. It cuts every source file of a repository
into functions, classes and blocks of top-level code, and remembers three things about each: its
words, its meaning, and who calls it. An agent asks it a question in plain words, over MCP (the
protocol coding agents use to call tools), and gets back a short ranked list of places in the
code. Everything runs on your machine unless you choose an embedding API.

This page explains the whole system: what each part does, how, and why. Setup and settings are in
the [README](../README.md); the exact formats and interfaces are in [data-model.md](data-model.md);
running it (dependencies, limits, keys, files) is in [decisions.md](decisions.md); research
directions are in [advanced-design.md](advanced-design.md).

---

## 1. What it is for

Vague, feature-level questions in a codebase you don't know well: *"I want to add OCR to my
pipeline; it doesn't support image upload yet. Where do I start?"* An agent can usually answer this
with grep, but slowly. The question shares no words with the code, so the agent guesses a name,
greps, reads what comes back, and guesses again. Each round costs time and tokens even when it ends
in the right place, and the cost grows with the codebase: in a monolith of 100,000 files, a common
word matches thousands of lines, and a precise one may match none. codemem should find the right
functions in one or two calls. grep stays the tool for exact strings; codemem works next to it.

It is judged on three things: **accuracy** (does it find the right functions?), **tokens** (does
the agent read less to get there?) and **time** (are searches fast, and is an edit searchable
within a second?).

**The running example.** An agent gets the issue *"Disabled users stay logged in"*. The fix
belongs in this function of the sample repo (`tests/fixtures/sample_repo`):

```python
# auth/sessions.py, lines 19-20
def revoke_session(session_id):
    db.sessions.delete(session_id)
```

Grepping the issue's words doesn't reach it, because the function contains none of them. An agent
gets there anyway, the way agents do today: it greps `disable`, reads `disable_user`, and follows
its call to `revoke_session`. That is several rounds of searching and reading for one function.
codemem gets there in one search, because the function's neighbours share the issue's words:
`disable_user()` calls it, and `test_disabled_user_loses_sessions` tests it. This page follows
this function through the whole system.

---

## 2. The big picture

```
   agents, through the MCP server     people and scripts, CLI         the eval, its adapter
                 └────────────────────────────────┬────────────────────────────────┘
                                                  ▼
┌─ CodememService (service.py): owns one index ────────────────────────────────────────────────────┐
│ ┌─ Watcher ────────────┐    ┌─ Writer ───────────────┐    ┌─ Catch-up ─────────────┐             │
│ │ OS file events,      │    │ one thread, the only   │    │ before every search:   │             │
│ │ batched until saves  │ ──►│ one that writes: runs  │    │ waits for stage A of   │             │
│ │ stop for 0.5 s       │    │ the indexer for each   │    │ earlier saves, embeds  │             │
│ │ (2 s at most)        │    │ batch of paths         │    │ the newest edits;      │             │
│ └──────────────────────┘    └────────────────────────┘    │ 4 s at most            │             │
│                                                           └────────────────────────┘             │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
                                           │ the writer runs the indexer        │ then searches
                                           ▼                                    ▼
┌─ Indexer (indexer.py) ─────────────────────────────────────────────┐    ┌─ Search ───────────────┐
│ STAGE A: structure. One SQLite transaction, milliseconds           │    │ (search.py, render.py) │
│   Walker ───────► Chunker ─────────► Call graph ────► queue        │    │                        │
│   which files     tree-sitter +      links calls      the chunks   │    │ keyword list (BM25)    │
│   changed         language specs     by name          to re-embed  │    │ + code-vector list     │
│                                                                    │    │ + usage-vector list    │
│ STAGE B: meaning. In batches, newest edits first                   │    │ ─► merge by rank       │
│   Texts ─────────► Embedder ──────────────────► vectors            │    │ ─► cards, and a note   │
│   the code text,   from the cache if it has them,                  │    │    naming any files    │
│   the usage text   else the local model, API or plugin             │    │    still pending       │
└────────────────────────────────────────────────────────────────────┘    └────────────────────────┘
                                  │ writes                                             │ reads
                                  ▼                                                    ▼
┌─ Store (store.py) ───────────────────────────────────────────────────────────────────────────────┐
│ SQLite, the source of truth: files · chunks · keywords (FTS5) · calls and links · vectors ·      │
│ the queue between stage A and stage B                                                            │
│ in memory: the search index (FAISS), built from the stored vectors                               │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Each box is a part of the system, and the arrows are the order things happen in. Follow one
save and one search:

1. You save `auth/sessions.py`. The **watcher**, which listens to the operating system's file
   events, notes the path.
2. Half a second after the saves stop, the **background writer** (one thread; nothing else writes
   the index) updates the index in two stages:
   - **stage A, structure:** it re-reads the file's functions, updates their keywords and call
     links, and puts the functions whose meaning may have changed on a **queue**. Milliseconds.
   - **stage B, meaning:** it sends the queued functions' texts through the embedding model (the
     model that turns text into vectors, lists of numbers where similar meanings lie close
     together). This is the slow part, so it runs after stage A, in batches.
3. The agent searches *"disabled users stay logged in"*. The search first **catches up**: it makes
   sure every earlier save has gone through stage A, and embeds the newest queued edits itself,
   for at most 4 s.
4. It ranks the code three ways (by keywords, by the meaning of the code, by the meaning of who
   calls it), merges the three rankings, and returns short **cards**: location, name, a few lines.
   If the catch-up couldn't finish in 4 s, the cards end with a note naming the files still being
   processed, so the agent can search again or grep those files.

| Part | Module | Section |
|---|---|---|
| finding files, chunking, call links | `indexer.py`, `chunker.py`, `languages/`, `callgraph.py` | §3 |
| texts and embeddings | `texts.py`, `embedder.py`, `vectorcache.py` | §3 |
| watcher, writer, catch-up | `watcher.py`, `service.py`, `indexer.py` | §4 |
| storage | `store.py` | §5 |
| search and cards | `search.py`, `render.py` | §6 |
| MCP server and CLI | `server.py`, `cli.py`, `prompts.py`, `agents.py` | §7 |

All logic lives in one library; the MCP server and the CLI are thin front-ends over one object,
`CodememService`, which owns an index. While an agent session runs, its MCP server owns the index,
the watcher and the writer. §11 maps every step above to the functions that do it.

---

## 3. What the index knows about a function

Everything codemem knows about `revoke_session` comes from one **chunk** (one searchable unit: a
function, method, class or block of top-level code):

```
 auth/sessions.py
 ┌────────────────────────────────────┐
 │ def revoke_session(session_id):    │ ──► chunk  auth/sessions.py::revoke_session, lines 19-20
 │     db.sessions.delete(session_id) │
 └────────────────────────────────────┘
                     │
     ┌───────────────┼──────────────────┬──────────────────────────┬──────────────────────────────┐
     ▼               ▼                  ▼                          ▼                              ▼
  keywords        call links          code text                  usage text                    (both texts
  revoke,         calls:              path + scope + doc,        revoke_session in ...           become
  session,          Table.delete      then the code              called by logout in ...         vectors)
  delete, ...     called by:                                     called by disable_user in ...
                    disable_user,                                tested by test_disabled_...
                    logout, a test
```

Stage A computes the left half (the chunk, its keywords, its call links). Stage B computes the
right half (the texts and their vectors). The rest of this section takes them in that order.

### 3.1 Finding files

codemem indexes every file in a supported language: Python, JavaScript, TypeScript, TSX, Go,
Java, Rust, C and C++ (with CUDA). It skips what `.gitignore` excludes, folders like
`node_modules` and `.venv`, vendored or generated code (`vendor/`, `*.min.js`, `*_pb2.py`), binary
files, and files over 10 MB.

**Nothing is skipped silently.** Every skipped file is stored with its reason, and `index_status`
lists them, together with counts of ignored folders and of files in no supported language
(README, YAML, SQL…). A file whose size and modification date haven't changed is never re-read.

### 3.2 Chunks

tree-sitter (a parser with one official grammar per language) turns each file into a syntax tree.
A small **language spec** per language (`languages/python.py`, `go.py`, …) says which tree nodes
are functions, classes, calls, tests and comments. One generic walker (`chunker.py`) turns the tree
into chunks with the same rules everywhere:

```
 auth/sessions.py                     chunks
 ┌──────────────────────────────┐
 │ """Session storage."""       │ ─┐
 │ import secrets               │  ├─► block      the docstring and imports, lines 1-5
 │ from . import db             │ ─┘
 │                              │
 │ def new_token(): ...         │ ───► function   new_token
 │ def create_session(...): ... │ ───► function   create_session
 │ def revoke_session(...): ... │ ───► function   revoke_session, lines 19-20
 │                              │
 │ class Session:               │ ───► class      Session (embeds only its outline)
 │     def __init__(...): ...   │ ───► method     Session.__init__
 └──────────────────────────────┘
```

- **Every function or class is a chunk;** its methods are chunks of their own, so a class
  embeds only its **outline** (its header and one line per member). Lambdas and callbacks stay
  part of the function around them.
- **Top-level statements between definitions form blocks** of at most 200 lines; a longer run,
  even a single huge statement, is cut by lines.
- **A namespace is not a chunk** (C++ `namespace`, Rust `mod` and `impl`): its name becomes part
  of the qualified names inside it, as in `auth.SessionManager.ExpireOld`.
- **A comment just above a definition becomes its doc text,** like a docstring. It is not part
  of the line range: a range covers the definition and its decorators only, which is also how
  the eval grades results.
- **Each chunk has a key** that survives edits: `auth/sessions.py::revoke_session`. A block, having
  no name, is keyed by a hash of its code.
- **Tests are marked** by each language's conventions: test folders and file names
  (`test_*.py`, `*_test.go`, `*.spec.ts`, …) and test definitions (`test_*`, `@Test`,
  `#[test]`, gtest `TEST(...)`).

### 3.3 Call links

While chunking, codemem records the names each chunk calls. It then links every called name to
the functions, methods and classes that define it. Each link is stored once, as caller → callee,
and can be read in both directions:

```
     logout ─────────────┐
     (api/routes.py)     │
                         ▼
     disable_user ──► revoke_session ──► Table.delete
     (auth/users.py)  (auth/sessions.py)  (auth/db.py)
                         ▲
     test_disabled_      │
     user_loses_    ─────┘
     sessions (tests/test_users.py)

     each arrow is one row (caller ──► callee)
     revoke_session's callers = the arrows into it    → its usage text (§3.4)
     both directions                                  → get_chunk shows callers and callees
```

Two limits keep links meaningful. A name defined more than five times in the repo (`get`, `run`)
is not linked, because it would connect everything to everything. And links stay within a
language family (C with C++, JavaScript with TypeScript), so a Python method never "calls" a C
function of the same name. Linking by name is deliberately simple, and isolated in one function
(`callgraph.resolve_edges`) so that a resolver that follows imports can replace it.

### 3.4 Texts

Each chunk gets up to two texts, and each is embedded and searched on its own:

- **The code text** is the code, with a short header giving what the code alone doesn't say: its
  file path, its enclosing class, and its doc text.
- **The usage text** says who calls the chunk and which tests reach it, one line each (at most
  20, half kept for tests). What others say about a piece of code often describes it better than
  the code does; web search calls this anchor text. Only chunks that something calls or tests
  have one.

  ```
  revoke_session in auth/sessions.py
  called by logout in api/routes.py
  called by disable_user in auth/users.py
  tested by test_disabled_user_loses_sessions in tests/test_users.py
  ```

A code text longer than the model reads well (about 3,000 characters) is cut into overlapping
**windows** of whole lines, each its own vector; a search scores the chunk by its best window
and shows that window's lines. Texts hold no line numbers, so code that only moves down a file
keeps its texts and vectors.

### 3.5 Vectors

Turning a text into a vector costs model time, so codemem first looks for one it already has:

```
 a changed text ──► same text already in this index? ──── yes ──► reuse it
                              │ no
                              ▼
                    in the vector cache on this machine? ── yes ──► reuse it
                              │ no                            (~/.codemem/cache/vectors.db)
                              ▼
                    the embedding model ──► store it in the index and in the cache
```

The cache holds every text ever embedded on the machine, so rebuilds, branch switches and undos
cost no model calls. The model is local by default (`jinaai/jina-code-embeddings-0.5b`, on the GPU
when there is one); it can also be any OpenAI-compatible API, or a Python class of your own for
research models (README).

Vectors from different models never mix: each set is named by its model and the settings that
shape it, and a new name re-embeds that set only. For a model kept in a local folder the name
includes a hash of the folder's files, so a fine-tuned model saved over the old one is re-embedded,
never served from the cache.

---

## 4. Keeping the index fresh: the two-stage indexer

This is the core of codemem's design. An agent searches right after its own edits, so that is
exactly when the index must be current; but turning code into vectors is far too slow to redo the
whole repo on every save. codemem solves both with two ideas:
- **every update runs in two stages:** a fast one for structure, which every search waits for,
  and a slow one for meaning, which runs behind it (§4.1);
- **every search catches up first:** it makes sure all earlier saves have been through the fast
  stage, embeds what it can of the slow one within 4 s, and says exactly what it couldn't (§4.2).

**Why this ends staleness.** A search result can be stale in three ways, and each one is closed:

| A result could be stale because... | What prevents it |
|---|---|
| the index never heard of a save | the watcher sees every save; each search first confirms that every earlier file event has arrived, or asks for a full check of the repo when file events don't work; full checks also run at startup, every 5 minutes, and on `refresh_index` |
| the structure is out of date: a deleted function, an old name, old line numbers | each search waits for stage A of every earlier save. It takes milliseconds, so keywords, names, paths, call links and the code `get_chunk` shows are always current |
| the meaning is out of date: ranking by vectors of the old code | the search embeds the newest edits itself before ranking. A one-function edit takes 0.1–0.5 s against a 4 s limit, so ordinary edits are always in |

**And when it can't catch up in time** (a branch switch, a formatter run, a model still loading),
the agent is never misled silently. The search still answers with everything the index has, and
ends with a note that names the files still being processed and tells the agent to search again or
use grep for them. grep reads the files themselves, so it is always current: it covers exactly the
gap, and only for those files.

**Why not something simpler.** Two designs were measured and rejected:
- *Re-indexing the whole repo on each save* (re-check every file, relink every call, rebuild every
  text) takes 8.5 s per save on a large repo (vLLM), and about as long when nothing changed.
- *Letting the agent decide when to re-index* serves old code and old line numbers, with no
  warning, until it does. Measured on vLLM: 5.45 s and two extra tool calls from a save to a fresh
  result, against 0.47 s inside one search.

### 4.1 The two stages

```
 changed files (from the watcher, or from a full check)
        │
        ▼
 ┌──────────────────────────── STAGE A: structure ─────────────────────────────┐
 │ one SQLite transaction; milliseconds per changed file                       │
 │  1. find the files that really changed (size and date, then the hash)       │
 │  2. re-chunk them, and match old and new chunks by key                      │
 │  3. update their keyword rows, and relink only the calls that can change    │
 │  4. queue every chunk whose texts may have changed                          │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │ the queue (dirty_texts): one row per chunk, with the
                                        │ sequence number of the update that queued it, committed
                                        │ in the same transaction as the structure
                                        ▼
 ┌──────────────────────────── STAGE B: meaning ───────────────────────────────┐
 │ in batches, newest edits first; the model runs outside the write lock       │
 │  1. rebuild each queued chunk's texts (code, usage)                         │
 │  2. keep only the texts whose hash changed                                  │
 │  3. get their vectors: from this index, the vector cache, or the model      │
 │  4. store them, unless the chunk was edited again meanwhile (then it stays  │
 │     queued for its newest version), and clear its queue row                 │
 │  5. patch the in-memory search index                                        │
 └─────────────────────────────────────────────────────────────────────────────┘
```

**What each stage gives a search.** Once stage A has run for an edit, the edit is searchable by
keywords (names, signatures, paths, code), its call links are current, and `get_chunk` shows the
new code at its new lines; a deleted function is gone. Until stage B has run for it, an edited
function is still ranked by meaning through its old vectors, and a new one not at all. That gap is
what a search's note reports (§4.2).

**Why two stages.** Structure is cheap, and every search needs it. Vectors need the model: 0.02 to
0.5 s per text on the M1, so a branch switch can mean minutes of work. Splitting the two lets a
search always wait for the structure, and only as long as it can afford for the vectors. The queue
is what makes the split safe:
- it is committed in the same transaction as the structure, so a crash between the stages loses
  nothing: the next start embeds what was left;
- each row carries the sequence number of the update that queued it, so a vector computed for an
  older version of a chunk is never stored over a newer one;
- "is anything pending?" is one count of the queue.

**Who runs the stages.**
- **In an agent session** (the MCP server), the background writer (§4.3) runs both: stage A for
  each batch of saved paths, and stage B in between, 64 queued chunks at a time, in slices of at
  most 5 s. It pauses at its next model call whenever a search wants the model or a new save
  arrives. A search runs stage B itself for the newest queued chunks during its catch-up (§4.2).
- **In the CLI and the eval,** `update()` runs stage A and then all of stage B before it returns
  (batches of 512 chunks; model calls of 256 texts, longest first), and writes the search index to
  disk, so the index is complete when it returns.

### 4.2 A search catches up first, within 4 s

The agent saves `auth/sessions.py` and searches 0.2 s later:

```
   watcher                  writer                               search
     │ file event              │                                     │ starts
     │ (collects paths; waits  │                                     │ ① are all earlier events in?
     │  0.5 s for quiet)       │                                     │   (writes a marker file and
     │                         │                                     │    waits for its event)
     │                         │ ◄── ② hands over the waiting path ──│
     │                         │ stage A: re-chunk, relink, queue    │   ...waits
     │                         │ what needs new vectors (ms) ───────►│
     │                         │ (pauses its embedding)              │ ③ stage B for the newest
     │                         │                                     │   queued chunks
     │                         │                                     │ ④ ranks and answers, with a
     │                         │ stage B: embeds whatever is left    │   note if anything is left
     │                         ▼                                     ▼
                             └───────────── at most 4 s from the search's start ─────────────┘
```

- **① Have all earlier saves been seen?** File events arrive in order, so once the marker file's
  own event is back (it waits at most 0.25 s), every earlier save has been noticed. Without
  working file events, the search asks for a full check of the repo instead.
- **② Stage A for them.** The search hands the writer any path it hasn't taken yet, and waits for
  that stage A. Only the writer applies changes, so a slow stage A (a huge file, a checkout still
  writing files) can't hold the search past its 4 s: it stops waiting and reports those files.
- **③ Stage B for the newest edits.** The writer pauses at its next model call, and the search
  embeds the queue itself, newest edits first, until its 4 s are up. Each model call is sized to
  finish in time: at most 3,000 characters, and none is started if the measured model speed says
  it would end past the limit.
- **④ Answer with what the index has, and say what is missing.** The search always returns
  results. If something didn't make it, the last line names it, so the agent can search again or
  grep those files:

  ```
  Note: 3 code chunks in 1 file (auth/sessions.py) are still being embedded: keyword matches for
  them are current, ranking by meaning may be out of date. Search again in a few seconds, or use
  grep for those files.
  ```

  The note can say three things: files saved moments ago that are still in stage A
  (`2 files saved moments ago are still being indexed, so results may miss their latest edits`);
  chunks still waiting for stage B, with the files they are in (above); or that codemem couldn't
  confirm in time that it had seen the latest saves.

**When a search doesn't wait at all.** During the first build of an index, and when more than
1,000 chunks are queued (a change too big to embed in 4 s), the search skips ③ and answers at
once, with the same kind of note (`1800 code chunks in 240 files (vllm/a.py, ...) are still being
embedded ...`).

**`get_chunk`** does ① and ② only: the code, lines and links it shows are always current.

### 4.3 The watcher and the writer

The **watcher** turns file events into changed paths. It collects them until saves stop for 0.5 s,
or for at most 2 s while saves keep coming, then hands them to the writer in one batch. A change to
`.gitignore`, `.codemem.toml` or the git branch, or more than 2,000 paths at once, asks for a full
check of the repo instead. While git is rewriting files (a checkout or a merge), updates wait for
it, up to 10 s.

The **writer** is one thread, the only thing that writes the index while codemem runs, so updates
never race. Besides running the two stages (§4.1), it:
- writes the search index to disk after 30 s without changes, at shutdown and on `refresh_index`,
  not on every save (on a large repo that would block searches for seconds);
- runs a full check every 5 minutes, in case an event was missed (every 10 s, and before each
  search, when file events don't work);
- retries a failed stage A, and shows its error in `index_status`.

### 4.4 How stage A touches only what changed

```
 ① find changed files   size and date first, then the content hash
         │
 ② remember their old state: chunk ids, the names they define, their links
         │
 ③ re-chunk and match old and new chunks by key
         │     same content, same lines   →  left alone
         │     same content, moved        →  line numbers shifted, nothing else
         │                                   (unless definitions were reordered: then changed)
         │     new or changed             →  rewritten
         ▼
 ④ relink only what can change: calls made by new or changed chunks, and every call to a name
         │   that appeared or disappeared (including a name crossing the five-definitions limit)
         ▼
 ⑤ queue the chunks whose texts may have changed: new or changed chunks, what they call
             (and what deleted chunks called), and any chunk whose callers changed
```

The work follows the edit, not the file: a one-character change in a 50,000-function file queues
one chunk. What an edit to the running example re-embeds:

| Edit | Re-embedded |
|---|---|
| lines added above `revoke_session` | nothing (its line numbers are shifted) |
| its body edited, or the comment above it | its code text |
| it is renamed in all 4 files | 9 of the repo's 33 texts: the changed files' code texts, its new usage text, and `Table.delete`'s usage text |

**Why so little.** A usage text lists callers. So an edit in a file reaches, outside that file,
only the usage texts of what it calls. Functions that call into the file keep their texts: their
code is their own, and their usage lists their own callers.

**Two checks keep incremental updates honest.** The index records the settings it was built
with; when the config differs, only what that setting affects is redone (a new model re-embeds,
a new chunker rebuilds). And `codemem index --verify` recomputes every link and text from scratch
and reports any difference.

### 4.5 When things go wrong

| Situation | What happens |
|---|---|
| a crash at any point | SQLite rolls back; the queue was committed with the structure, so the next start embeds what was left; a full check at startup finds files saved meanwhile |
| a search during an update | it sees the index before or after a transaction, never half of one |
| a change too big to embed in 4 s (a branch switch, a formatter run) | searches answer at once with what the index has, and a note naming the files still being embedded, so the agent can grep them; the writer embeds them in the background, newest first |
| two agent sessions on one repo | one writes at a time (a lock file); each picks up the other's vectors without re-embedding |
| OS file events don't work (network drives, WSL) | a warning, a full check every 10 s, and a full check before each search (0.5 s on vLLM) |
| a search while the model is still loading (about 7 s at startup) | it waits within its 4 s, then answers from keywords alone and says so |

---

## 5. Storage

```
 ~/.codemem/indexes/<repo>-<hash>/
 ├── index.db ............ SQLite, the source of truth
 │     files        every file seen: hash, size, date, and why it was skipped, if it was
 │     chunks       every chunk (§3.2)
 │     fts          keywords: five fields per chunk (§6)
 │     calls        the names each chunk calls
 │     edges        the links, caller ──► callee (§3.3)
 │     vectors      every vector, as float16 numbers, with its chunk, window and text hash
 │     dirty_texts  the queue between stage A and stage B
 │     meta         the settings the index was built with, the git commit, version counters
 ├── vec_code.faiss ...... saved copies of the in-memory search indexes,  ┐ rebuilt from the
 ├── vec_usage.faiss         one per text type                            ┘ vectors table if lost
 └── write.lock .......... one writer at a time

 ~/.codemem/cache/vectors.db ... the vector cache, shared by every index on the machine
```

**Why SQLite, and not a vector database.** Most of what is stored isn't vectors and needs lookups,
joins and keyword search; SQLite has them, needs no server, and makes each update one atomic
transaction. Vectors are stored in it as plain rows, so the search index is only a derived copy,
which can always be rebuilt without the model (2 s on vLLM).

**The search index** compares a query vector with every stored vector of a type, using FAISS (a
vector search library) in its exact mode: about 10 ms over 109k vectors. It sits behind a small
interface (`VectorStore`), so an approximate index (HNSW or IVF, which trade a little accuracy for
speed on very large repos) can replace it through the config; a switch re-embeds nothing.

**Keeping the copy in step with SQLite.** The in-memory index changes only after a commit, so it
never holds a vector that could be rolled back. Every commit that changes a type's vectors also
bumps that type's version number in `meta`, and an index that is behind catches up by comparing
vector ids: vectors are never changed in place, only added and deleted, so the ids that differ are
the whole difference. That covers a saved copy from before a crash, and another process's writes.
Searches never wait for writes (SQLite's WAL mode lets readers continue while one process writes).

---

## 6. Search

```
 "disabled users stay logged in"
        │
        ├──► keywords (BM25) ────────► 1. test_disabled_user_loses_sessions   (no revoke_session:
        │                                                                       it shares no word)
        ├──► code vectors ───────────► ... 10. revoke_session
        │
        └──► usage vectors ──────────► ...  2. revoke_session  (its callers match)
                       │
                       ▼
        merge by rank: each list adds 1 / (60 + rank) to a chunk's score
                       │
                       ▼
        filters and weights ──► ties broken by location ──► cards
```

1. **Keywords.** BM25 (the standard keyword ranking: shared words count, rare words count more)
   over five fields per chunk, weighted by where a word matches: name 10, signature 5, path 3, doc
   text 2, code 1. Identifiers are split into words and also kept whole, so `revoke_session`
   matches `revoke`, `session` and `revoke_session`. Query stopwords ("the", "in") are dropped.
2. **Meaning.** The query is embedded once, then compared with every code vector and, separately,
   every usage vector.
3. **Merge by rank** (reciprocal rank fusion). Ranks are merged, not raw scores, because keyword
   scores and vector similarities aren't comparable. Each list contributes its top 50.
4. **Filters and weights.** A folder (`path_prefix`), kinds (functions only, say), languages and
   tests (include, exclude or only) filter each list. Tests, classes and blocks score like
   everything else by default, since vague questions often need them; weights can lower them.
5. **Cards.** Equal scores are ordered by location, so every machine gives the same order:

```
3. auth/sessions.py:19-20  revoke_session  [id 14]
   def revoke_session(session_id):
   |     db.sessions.delete(session_id)
```

A card gives the location, the name, an id for `get_chunk`, the signature, the first doc line and
a few lines of code; for a long function, the best-matching window.

**Long queries stay fast.** BM25 joins every query word with OR, so a whole issue text is costly.
Dropping stopwords keeps a 250-word query on vLLM at 0.36 s of BM25 with no loss in accuracy.

---

## 7. MCP server and CLI

```
 agent (Claude Code, Cursor, Codex)
        │   MCP over stdio
        ▼
 codemem mcp ──► CodememService ──► the index
                  ├─ writer and watcher, in the background
                  └─ the embedding model, loaded in the background at startup
```

At startup the server answers the agent's handshake at once, then, in the background, checks the
repo against the index (or builds it the first time), starts the watcher and loads the model.

| Tool | Does |
|---|---|
| `search_code(query, k, path_prefix, kinds, tests)` | catches up (§4.2), then returns up to `k` cards (10 by default, 50 at most), with a note if something is still pending |
| `get_chunk(ref)` | the full code of a chunk, by id, `path:line` or `path::qualname`, with its callers and callees |
| `index_status()` | what is indexed, what is pending or skipped and why, which model, and any error |
| `refresh_index()` | a full check now, for changes the watcher can't see |

All the wording an agent reads (tool descriptions, server instructions) lives in `prompts.py`, at
three strengths (`none`, `light`, `strong`): getting agents to use the tool at all is the real
adoption problem, and the agent study varies it.

The CLI is for people and scripts: `codemem init` registers the MCP server with your agents,
downloads the model and builds the index; `codemem index`, `search` and `status` do what they say.

---

## 8. How the eval uses it

```
 cmeval (eval/) ──► adapter (eval/src/cmeval/adapters/codemem.py) ──► codemem, as a library
   for each task:     1. build or update an index at the task's commit (waits until done)
                      2. search with the issue text
                      3. grade the returned line ranges against the lines the fix changed
```

The eval calls the library directly, not the MCP server: an update finishes before any search, so
there is nothing to catch up on.

**What keeps it fair.** Systems that differ only in search settings share one index: the adapter
keys indexes by every setting that changes an index (`Config.index_settings()`). An index updated
to a commit must give the same results as one built there from scratch. And the labeler that
turns a fix into gold line ranges is a separate implementation, so a codemem bug can't grade itself.

**What the adapter relies on**, so it must stay stable: `config_from_dict`,
`CodememService(...).update()` returning its statistics, `search()` and its cards' lines and
ranks, `format_results()` (the eval counts the tokens of exactly what an agent would read),
`Config.index_settings()` and the fake models used in tests.

**What it doesn't measure yet.** Its queries are whole issue texts and its answers are bug fixes;
codemem is for short, vague feature questions. A vague-question eval is the next step.

---

## 9. Extending it

| To add | Write |
|---|---|
| a language | a spec in `languages/` (which nodes are functions, classes, calls, tests, comments) |
| a kind of embedded text | a text builder in `texts.py` |
| an embedding model | nothing, if sentence-transformers can load it; else an embedder class (README) |
| a search index | a `VectorStore` subclass (README) |
| smarter call links | a replacement for `callgraph.resolve_edges` |

---

## 10. Performance

On an M1 laptop. vLLM: 6,235 files, 102k chunks, 145k vectors. Update times use a fake model, so
they show codemem's own work; the real model adds about 0.1 s per changed text.

| | Measured |
|---|---|
| a one-function edit, until searchable (vLLM) | 0.11 s (0.48 s for the first edit in a process) |
| a full check, nothing changed (vLLM) | 0.3–0.5 s |
| a search of 10 words / 250 words (vLLM) | 0.12 s / 0.63 s |
| a save then a search, through MCP, real model (sample repo) | 0.13–0.4 s, the edit included |
| a full build of vLLM, fake model | 72 s |

**Building is almost all embedding.** The local model embeds about 8.5 texts a second on the M1,
so the first build of a large repo (vLLM: 145k texts, about 5 hours) wants a CUDA GPU or an
embedding API. After that, updates are small.

---

## 11. The code, end to end

**An update** (a save during an agent session):

```
 watcher.py  RepoWatcher (watchdog's OS events) ─► _Handler.on_any_event ─► RepoWatcher.seen()
                                                                        ─► Debouncer (0.5 s quiet)
                                                                                 │
 service.py  CodememService.notify(paths) ◄──────────────────────────────────────┘
               └─ the writer thread: _run() ─► _step()
                    │
                    ├─ STAGE A  _apply_changes() ─► indexer.py  Indexer.structure()
                    │             ├─ scan_paths() or scan()       which files changed (size, date, hash)
                    │             ├─ chunker.py chunk_source()    tree-sitter + the languages/ specs
                    │             ├─ _apply_file()                store.upsert_chunk / move_chunks / delete_chunks
                    │             ├─ _relink()                    callgraph.py resolve_edges() on the affected calls
                    │             └─ store.mark_dirty()           the queue (dirty_texts)
                    │
                    └─ STAGE B  Indexer.embed_pending()           batches of queued chunks, newest first
                                  ├─ _take()      store.dirty_batch() ─► texts.py build_parts() ─► text hashes
                                  ├─ _compute()   this index ─► vectorcache.py VectorCache ─► embedder.py
                                  │               make_embedder(...).embed_documents()
                                  └─ _put()       store.put_vectors() ─► the in-memory search index
```

**A search** (`search_code` over MCP):

```
 server.py   search_code() ─► service.py CodememService.search()
                                ├─ catch_up()   RepoWatcher.barrier() ─► hand over unapplied paths
                                │               ─► wait for the writer's stage A
                                │               ─► Indexer.embed_pending() for the newest edits, until 4 s
                                └─ search.py search()
                                      ├─ bm25_match() ─► store.bm25_search()
                                      ├─ make_embedder(...).embed_queries() ─► store.vector_search(), per text type
                                      └─ rrf() ─► filters and weights ─► cards
             ◄─ render.py format_results() + freshness_note()     the cards, and the note if anything is pending
```

**Other entry points:**
- `codemem mcp` ─► `server.run_stdio()` ─► `CodememService.start()` (a full check, the writer, the
  watcher, model loading) ─► `build_server()` serves the four tools over stdio.
- `get_chunk` ─► `CodememService.get_chunk()`: the catch-up without stage B, then the chunk with its
  callers and callees. `index_status` ─► `CodememService.status()`. `refresh_index` ─►
  `CodememService.refresh()`.
- The CLI (`cli.py main()`): `codemem index` runs `Indexer.update()`, which is stage A, then all of
  stage B, then writing the search index to disk; `--verify` runs `Indexer.verify()`. `codemem
  init` registers the server with agents (`agents.py`, `launch_command()`).
- The eval's adapter calls `CodememService.update()` and `search.search()` directly (§8).

**Modules:**

| Module | Role |
|---|---|
| `config.py` | settings and their defaults, `index_settings()`, paths, ignore rules, the weights version of a model folder |
| `schema.py` | the `Chunk` record |
| `languages/` | one spec per language, and the registry |
| `chunker.py` | the generic tree-sitter walker |
| `tokenize.py` | splitting code and queries into words, the same way for both |
| `callgraph.py` | linking calls to definitions by name |
| `texts.py` | the code and usage texts, and windows |
| `embedder.py` | the embedders: local, API, plugin, and a fake one for tests |
| `plugins.py` | loads `"module:Class"` plugins named in the config |
| `vectorcache.py` | the shared vector cache |
| `store.py` | SQLite, the in-memory search index, filters, consistency |
| `indexer.py` | the update function: finding files, stage A, stage B, verify mode |
| `service.py` | `CodememService`: the writer thread, the catch-up, the watcher, status |
| `watcher.py` | file events, batched |
| `search.py`, `render.py` | search, and the cards and notes an agent reads |
| `server.py`, `cli.py`, `__main__.py`, `prompts.py`, `agents.py` | the MCP server, the CLI (also `python -m codemem`), agent-facing text, agent registration |
