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
   sure every earlier save has gone through stage A, and embeds queued chunks itself, for at most
   4 s: the ones among its own keyword results first, then the newest edits.
4. It ranks the code three ways (by keywords, by the meaning of the code, by the meaning of who
   calls it), merges the three rankings, and returns short **cards**: location, name, a few lines.
   If the catch-up couldn't finish in 4 s, the cards end with a note naming the files still being
   processed, so the agent can search again or grep those files.

| Part | Module | Section |
|---|---|---|
| finding files, chunking, call links | `indexer.py`, `chunker.py`, `languages/`, `callgraph.py` | §3 |
| texts and embeddings | `texts.py`, `embedder.py`, `vectorcache.py` | §3 |
| watcher, writer, catch-up | `watcher.py`, `service.py`, `indexer.py` | §4 |
| branch switches and git worktrees | `service.py`, `watcher.py`, `worktrees.py` | §4.6 |
| storage | `store.py` | §5 |
| search and cards | `search.py`, `render.py` | §6 |
| MCP server and CLI | `server.py`, `cli.py`, `prompts.py`, `agents.py` | §7 |
| serving the local model to other codemem processes | `embedserver.py` | §3.5 |
| an endpoint that shares a build's embedding work | `assist.py` | §3.5 |

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
files, and files over 10 MB. It also skips a git worktree of the same repository that lies inside
the checkout: that folder is another checkout, with an index of its own (§4.6).

**Nothing is skipped silently.** Every skipped file is stored with its reason, and `index_status`
lists them, together with counts of ignored folders and of files in no supported language
(README, YAML, SQL…), and the worktrees it left out. A file whose size and modification date
haven't changed is never re-read.

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
                              │ no                            (~/.codemem/cache/vector_cache.db)
                              ▼
                    the embedding model ──► store it in the index and in the cache
```

The cache holds the vectors of the texts embedded on this machine, up to a size cap (§5), so
rebuilds, branch switches and undos cost no model calls. The model is local by default (`jinaai/jina-code-embeddings-0.5b`, on the GPU
when there is one); it can also be any OpenAI-compatible API, or a Python class of your own for
research models (README).

Vectors from different models never mix: each set is named by its model and the settings that
shape it, and a new name re-embeds that set only. For a model kept in a local folder the name
includes a hash of the folder's files, so a fine-tuned model saved over the old one is re-embedded,
never served from the cache.

**The model in memory.** The local model is the largest block of memory codemem holds, and it is
needed only while a text is embedded: a search's query, and the texts of code that changed. On an
M1, with the default model on the GPU, the process takes 0.4 GB with PyTorch imported, 1.7 GB with
the model in memory, and 2.8 to 2.95 GB while it embeds a batch of code texts (measurements:
[decisions.md](decisions.md) §3).

```
                        every embedding restarts the idle time
                                      ┌──────┐
                                      ▼      │
 not in memory ──► loading, in a ──► in memory ──► nothing embedded for ──► freed
       ▲           thread of its own                `model_idle_minutes`      │
       │           (2 to 6 s on an M1)              (0, the default: never)   │
       └──────────────── the next search or save loads it again ◄─────────────┘
```

- **It loads in a thread of its own,** when the server starts and again at the first search or
  save after it was freed, so nothing that can go on without the model waits behind the load. The
  writer keeps applying saves (stage A) and embeds the queue once the model is in memory. A search
  waits for the model within its 4 s; if it is not there by then, the search answers from keywords
  alone and says so (§4.5). The CLI and the eval answer only when complete, so they load the model
  where they need it.
- **It runs in the precision its key names.** The key of a set of vectors names the precision and
  the device of the model that made them: float16 on a GPU, float32 on a CPU
  ([decisions.md](decisions.md) §5). A model is loaded as its file stores it, and the default
  model's file stores bfloat16, so the weights are converted when the model is loaded. For the
  Apple GPU that happens on the CPU, before the move. Converted on that GPU, the blocks of the
  file's format stay in the GPU's allocator for as long as the model lives: it holds 2.16 GB for
  1.01 GB of weights, against 1.09 GB this way. The vectors are the same bit for bit (checked on 4
  queries and 32 code texts). Measured side by side, a load took about 2 s either way.
- **What a burst of calls needed goes back when the burst is over.** A model call needs memory
  beside the weights for its intermediate results: up to 1.2 GB for 16 code texts of about 1,000
  characters. PyTorch's GPU allocator keeps it for the next call, so one batch would leave the
  process at 2.8 GB or more for as long as it runs. Once the model has made no call for 5 s, the
  writer has that cache emptied, with the model kept, and the process is 1.2 GB smaller a second
  later. That happens once after each burst, in a step where the writer has nothing queued, and
  never under a running call: calls less than 5 s apart are one burst. Emptying takes 0.1 s, and
  the batch after it was no slower. The writer's own calls hold at most 3,000 characters and need
  under 20 MB; the 1.2 GB comes from the calls of 16 texts that a build or `refresh_index` makes.
- **It leaves when idle.** The writer frees the model once nothing has been embedded for
  `model_idle_minutes` (60 by default; 0 keeps it): it drops the model, collects what reference
  cycles kept of it, and empties the GPU allocator's cache. The process is back at 0.5 to 0.7 GB
  within a second. The next search or save pays the load again, and a search waits for it, so an
  idle time costs that search time and not results ([decisions.md](decisions.md) §3).
- **Giving memory back is safe against a use that starts at the same moment.** Each embedder
  counts the calls in progress and remembers when the last one ended. It gives memory back only
  when no call is running and the last use is older than the idle time asked for: 5 s for the
  working memory, `model_idle_minutes` for the model. A search counts as a use before it checks
  for the model, so the model cannot leave between that check and the query's embedding. Callers
  that need the model at once load it once. Vector types on the same model share one embedder, so
  they are one model to free.
- **It runs one call at a time.** Two threads in the model at once (the start-up warm-up, the
  writer, a search's query) crashed the process on the Apple GPU: each moves its batches to the
  device through PyTorch's cache of Metal kernels, which is not safe for two threads. And the redo
  of a text that overflowed in float16 converts the weights that another call would be using. So
  the local embedder lets one call in at a time, and a search's query waits for the call that is
  running. In a server that is one of the writer's calls, at most 3,000 characters, or during
  `refresh_index` one of up to 256 texts. A GPU runs one call at a time anyway. A build by
  `codemem index` makes the same 256-text calls in a process of its own, where no search waits.

**One model for several codemem processes.** A codemem that runs the local model holds 1.3 GB of
it in memory on an M1's GPU. Several of them on one machine (one per git worktree, or one per
container of an eval) would each hold a copy, and a container has no GPU to run it on. So the
local model can be served: `codemem serve-embeddings` (`embedserver.py`) puts it behind the same
OpenAI-style endpoint that an embedding API has, and the other processes embed through it with
`[embedding] provider = "openai"`. They never import PyTorch, so a container's codemem also runs
in an environment built without it (README).

```
 codemem in worktree A ──┐
 codemem in worktree B ──┼── POST /v1/embeddings ──► codemem serve-embeddings ──► one model, one GPU
 codemem in a container ─┘      prefix + text              one model call at a time
```

Three choices shape it:

- **The server embeds a text exactly as it is given, and the client says what the text is.** The
  model embeds a query and a document differently: it puts one prompt before a query and another
  before a document. The OpenAI request has no field for that. So the server prints the two
  prompts at start, each client carries them as `query_prefix` and `document_prefix`, and sends
  prompt and text as one string. The request stays the plain OpenAI one, and a client of any other
  OpenAI-style endpoint works the same way. For this to give the vectors the model gives in
  process, the model's prompt must be nothing more than text in front. The server checks that at
  start, with two texts embedded both ways, and refuses a model for which it does not hold. For
  `jina-code-embeddings-0.5b` in float16 on an M1, 20 code texts and 20 questions came out as the
  same numbers both ways. What does move a vector is how texts are grouped into model calls: a
  text embedded alone and in a batch agree to a cosine of 0.999998, in process as through the
  server.
- **An index is tied to a name for its vectors, not to the server's address.** The same server is
  `127.0.0.1` for the host and another address for a container. An API's vectors are named by its
  address unless the config gives them a name, `space`; the server prints one that holds its
  model's settings. An index built through one address then opens through another without
  embedding anything again (decisions.md §5).
- **One thread calls the model.** The local embedder runs one call at a time (above), and the
  server makes every call from one thread, so that it chooses which request goes next. Requests
  queue, and the model takes at most `batch_size` texts at a time. Between calls the request with
  the fewest texts left goes first, so a search's one query waits for a single batch of another
  process's build, not for the build. While no request waits, the same thread gives the model the
  quiet moments the writer gives it: what its calls needed goes back after each burst, and the
  model is freed after `model_idle_minutes` without a request. The next request loads it again and
  waits for the load.

The server holds no index and no state. When it is down, its clients behave as with any API that
is down (decisions.md §2).

**A second source for a build's vectors.** Building is almost all embedding (§10), and on weak
hardware the local model is the slow part. An *assist* (`[embedding.assist]`, `assist.py`) is an
endpoint that serves the same model, a `serve-embeddings` server on a machine with a GPU or a
hosted API, and embeds part of a build's texts while the local model embeds the rest.

```
 one embedding call of a build: up to 256 texts, the longest first

   t1  t2  t3  t4 ...                                          ... t254 t255 t256
   ──────────────────►                                    ◄──────────────────────
   the local model, 16 at a time,                 the endpoint, 32 a request,
   in the caller's thread                         4 requests at once
   (first the texts it would cut)

   the two meet where their measured speeds put them; every vector is stored as the local model's
```

Five choices shape it:

- **One index, under the local model's name.** The vectors of both sources are stored under the
  local embedder's key, so an index built with an assist is the index the local model alone would
  build, and switching the assist on or off re-embeds nothing. The price is that the endpoint has
  to give the same vectors, and nothing in an OpenAI-style reply says whether it does. So there is
  a check before the endpoint gets any text: seven fixed texts are embedded both ways and each
  pair must agree to a cosine of 0.99995 (the reason for the number is in decisions.md §3). The
  endpoint's vectors are scaled to length 1 first: a provider need not normalize, and the same
  model's vector at another length is the same vector. One that cannot be scaled, all zeros or
  with a number that is not finite, refuses the endpoint. The texts are chosen to make the ways a
  provider can differ show up: code in two languages, a usage text, plain words, other alphabets,
  and one text filled to the local model's limit to the token, in which no two lines are about
  the same thing. An endpoint that cuts a text earlier than the local model reads less of that
  one. Another model behind the name, another precision and a prompt added on the provider's side
  move every pair. An endpoint that fails the check gets no text, and `status` says why in one
  sentence. `codemem status --check-assist` runs the check alone and prints each text's cosine
  and the two vectors' lengths, so a provider can be tried without a build.
- **A text the local model cuts stays local.** The local model reads `max_seq_length` (1,024)
  tokens of a text and drops the rest. A hosted model usually reads many times that, and nothing
  in its reply says where it stopped, so for a longer text the two sources would give different
  vectors. Each call's texts are therefore counted once with the local model's own tokenizer, as
  the model counts them: its prompt and the text as one string, with the tokens the tokenizer
  adds. A text over the limit stays at the local model's end of the row, where the endpoint does
  not reach. A text of exactly the limit is read whole and may go; one token more stays. This is
  why the check needs no text over the limit: the endpoint is compared on the longest text it is
  ever handed. The count runs on a copy of the tokenizer. A tokenizer holds whether it cuts as a
  setting that each call sets, and a count on the model's own could switch the cutting off under
  a call that is embedding in another thread. A plain ASCII text with fewer characters than the
  limit is not tokenized for this, since a token is one character at least. The tokenizer comes
  with the model, so a large call that arrives while the model is loading waits for the load, as
  its first local batch would, and the endpoint gets its first texts after it.
- **The split is inside the embedder.** The indexer makes one call per group of texts and gets
  all vectors back in order, as without an assist (§4.1); neither of its stages knows about the
  endpoint. Inside
  the call the texts are a row that both sources work through from opposite ends. The local model
  takes its usual batches from the front, in the caller's thread, so the model lock and the idle
  clock see what they saw before, and a shared call is one use of the model. The endpoint takes
  from the back.
- **The local model never waits for the endpoint.** The endpoint takes a text only if it is
  expected back before the local model would have reached it, by two measured speeds: the local
  model's seconds per character, and the endpoint's over everything it has in the air at once.
  That holds for a server with one model, where requests wait for each other, and for an API that
  answers them side by side. A slow endpoint so takes little. A request that fails puts its texts
  back in the row. When the local model has nothing else left and a request is out, it
  embeds that request's texts itself, at once if it would be done first, else once the request is
  overdue by the time the local model needs for them; the first result counts. A request that
  hangs so costs a call about twice that time, not its timeout. An endpoint that failed rests, 1 s
  and then twice as long each time up to 60 s, and is compared again before it gets work.
- **Small calls stay local.** A call of one local batch or less (16 texts) never reaches the
  endpoint: an edit, a search's catch-up and a model warm-up run as they do without an assist,
  and so does the 4 s limit of §4.2. Queries are always embedded locally, so a search depends on
  no network. What is shared is a build's large calls, which `codemem index` and `codemem init`
  make. A first build that the MCP server makes in the background runs in the writer's small
  calls (§4.2) and is not shared.

Measured with stand-in models that take a set time per character, so the numbers are the
mechanism's and not a model's (1,024 code texts in calls of 256, vectors of 896 numbers, the
endpoint a `serve-embeddings` server in its own process, an M1 at load average 4):

| The endpoint, against the local model's speed | Build speed, against the local model alone | Of the two speeds added |
|---|---|---|
| a quarter | 1.26 times | 99% |
| half | 1.46 times | 97% |
| equal | 1.87 times | 97% |
| twice | 2.49 times | 99% |
| four times | 3.42 times | 103% |
| eight times | 3.57 times | 95% |
| not there | 1.00 times | |
| stops answering after a quarter of the texts | 1.11 times | |

The speeds are measured in characters, as the indexer measures a model call. With a stand-in
whose time went by text and not by length, the estimates were off and an endpoint a quarter as
fast was left with 5% of the texts, for 1.05 times the speed: less than its share, never a loss.

With an assist, the texts of a build are sent to the endpoint, and `status` says so.

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
  arrives, and runs stage A alone while the model is loading (§3.5). A search runs stage B itself
  during its catch-up, for its own keyword results first and then for the newest queued chunks
  (§4.2).
- **In the CLI and the eval,** `update()` runs stage A and then all of stage B before it returns
  (batches of 512 chunks; model calls of 256 texts, longest first), and writes the search index to
  disk, so the index is complete when it returns. `codemem search` runs both stages itself when
  it finds the index behind the checkout (§4.6).

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
     │                         │ (pauses its embedding)              │ ③ stage B: its own keyword
     │                         │                                     │   results, then the newest
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
- **③ Stage B for what this search needs.** The writer pauses at its next model call, and the
  search embeds the queue itself until its 4 s are up. It starts with the queued chunks among its
  own keyword results, best rank first, and goes on with the rest, newest edits first. Each model
  call is sized to finish in time: at most 3,000 characters, and none is started if the measured
  model speed says it would end past the limit. A model that is still loading (§3.5) is waited
  for within the same 4 s; the search does not load it itself, and embeds nothing if the model is
  not in memory by then.

  **Why its own keyword results first.** A queued chunk has an old vector or none. The merge (§6)
  then ranks it by its keywords alone, below chunks that all three rankings agree on, even when it
  is the best keyword match. After a branch switch the queue holds exactly the code the switch
  brought in, which is what the agent tends to ask about next.

  Measured on vLLM right after a switch between two commits a week apart, with 12,355 chunks
  queued and a fake model. Each of 150 searches asked for one function the switch had added, by
  the words of its name:

  | The queue when the search ranks | The function is among the first 3 results | among the first 10 |
  |---|---|---|
  | nothing embedded | 8% | 48% |
  | the search's own keyword results embedded first | 56% | 78% |
  | everything embedded | 55% | 79% |

  A search found a median of 7 queued chunks among its 50 keyword results (16 or fewer in 9 of 10
  searches). That is 6 texts to embed (17 or fewer): 0.7 s and 2 s at the real model's 8.5 texts
  a second on the M1, so it fits the 4 s. Functions the switch only changed ranked the same in all
  three rows: their old vectors still serve.
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

**When the queue is too long to wait for.** With more than 1,000 chunks queued (a branch switch, a
formatter run, the first embedding of a repo), step ③ covers the search's own keyword results and
nothing else. The search then answers with the same kind of note (`1800 code chunks in 240 files
(vllm/a.py, ...) are still being embedded ...`), and the writer embeds the rest in the background.
While a new index gets its first structure, a search answers at once and says the index is still
being built. A new index that starts as a copy of another checkout's is waited for instead (§4.6).

**`get_chunk`** does ① and ② only: the code, lines and links it shows are current. One case has a
note instead: a new worktree's index that is still a copy of another checkout's (§4.6).

### 4.3 The watcher and the writer

The **watcher** turns file events into changed paths. It collects them until saves stop for 0.5 s,
or for at most 2 s while saves keep coming, then hands them to the writer in one batch. A change to
`.gitignore`, `.codemem.toml` or the git branch, or more than 2,000 paths at once, asks for a full
check of the repo instead. While git is rewriting files (a checkout or a merge), updates wait for
it, up to 10 s. A save in a worktree that lies inside the checkout is ignored: it belongs to that
worktree's index (§4.6).

The **writer** is one thread, the only thing that writes the index while codemem runs, so updates
never race. Besides running the two stages (§4.1), it:
- writes the search index to disk after 30 s without changes, at shutdown and on `refresh_index`,
  not on every save (on a large repo that would block searches for seconds);
- runs a full check every 5 minutes, in case an event was missed (every 10 s, and before each
  search, when file events don't work);
- tries a failed step again (stage A, stage B, a model's load) after 1 s, then after twice as long
  each time, up to a minute, and a failed stage A at once when a new save or search arrives. The
  error is logged with its traceback once and stays in `index_status` until the step works. A
  step that cannot work, such as a local model whose packages are not installed, is thus not
  tried every second for as long as the server runs;
- gives each model a quiet moment in a step where nothing is queued: what its calls needed besides
  it goes back 5 s after the last call, and the model itself is freed after `model_idle_minutes`
  without embedding (§3.5).

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
| a change too big to embed in 4 s (a branch switch, a formatter run) | a search embeds its own keyword results, then answers with what the index has and a note naming the files still being embedded, so the agent can grep them; the writer embeds the rest in the background, newest first |
| two agent sessions on one repo | one writes at a time (a lock file); each picks up the other's vectors without re-embedding |
| OS file events don't work (network drives, WSL) | a warning, a full check every 10 s, and a full check before each search (0.5 s on vLLM) |
| a search or `get_chunk` in a new worktree, before the copied index is checked (§4.6) | it waits for that check within its 4 s; past that it answers from the copy, and a note says that this can be the other checkout's code |
| a search while the model is loading (when the server starts, or after the model was freed for being idle) | it waits within its 4 s, then answers from keywords alone and says so |
| a search while a search index is still loading, or is being rebuilt from the stored vectors (§5) | the same: it waits within its 4 s, and not for a rebuild that will take longer; then keywords alone, and the note |
| a save while the model is loading | it is applied at once (stage A); its vectors follow when the model is in memory |
| the model can't be loaded (a wrong name, no network for its first download) | saves are still applied and searches answer from keywords, at once: a search does not wait for a load that has failed, and its note says why. The load is tried again after 1 s, then after twice as long each time, up to a minute, and `index_status` shows the error until it works |
| the embedding API or the `serve-embeddings` server is down | the same as a model that can't be loaded: searches answer from keywords and their note names the address that does not answer; edits stay queued and are embedded when it is back. Only the first search to find the endpoint down waits for its request's retries, about 31 s. After that each search asks the endpoint once, and the writer on the schedule above, so the first search after it is back ranks by meaning again. `codemem index` and `codemem search` stop after the retries with one line that names the address (decisions.md §2) |

### 4.6 Branch switches and worktrees

**One index per checkout, not per branch.** A checkout is a folder that holds the repository's
files: the main one, or one made by `git worktree add`. Its index follows whatever commit the
folder is on. An index per branch would cost its disk again for every branch, and embedding again
after every switch would cost model time. codemem does neither. A switch updates the checkout's one
index in place, and every vector that was computed on this machine before comes back from the
vector cache (§3.5).

**What a switch does.** `git checkout` is, for the index, a burst of saves:

```
 git checkout B
        │   the watcher sees HEAD change and asks for a full check; the writer first waits
        │   for git to finish writing files
        ▼
 a full check ........ every file by size and date, then by content hash
        ▼
 STAGE A ............. only for the files whose content differs: re-chunk, relink, queue.
        │              From here on keywords, names, lines and call links are those of B
        ▼
 STAGE B ............. a vector for every queued text that changed: from this index (the same
                       text under another chunk), else from the vector cache, else from the model
```

Measured on vLLM (6,235 files, 102k chunks, 145k vectors) between two commits a week apart: 478
commits, and 1,651 of the indexed files differ. The model is a fake one, so the seconds are
codemem's own work:

| Switch | Files re-chunked, dropped | Chunks added, changed, deleted | Vectors written | of them by the model | Stage A | Stage B |
|---|---|---|---|---|---|---|
| A → B, the first visit to B | 1,291, 360 | 1,347, 3,714, 7,025 | 10,228 | 9,054 | 18 s | 27 s |
| B → A, a commit seen before | 1,635, 16 | 7,025, 3,714, 1,347 | 18,556 | 0 | 27 s | 22 s |
| A → B again | 1,291, 360 | 1,347, 3,714, 7,025 | 10,228 | 0 | 18 s | 10 s |

The M1 was shared with other jobs, so each time is the fastest of the runs of that leg. On the
busy machine half of the 18 runs of stage A took more than 45 s, and the slowest 100 s. Another
22,335 chunks only moved inside their files and kept everything else. The real model adds its
time to the first visit only: 9,054 texts are about 18 minutes at the M1's 8.5 texts a second, in
the background, while keyword search already answers for B. On every later visit the vectors come
from the cache.

**A switch with no server running.** `codemem search` is a command that runs once: no watcher
tells it that the checkout moved. So it starts with a full check that changes nothing, the one
`codemem status` makes. If no file differs from the index, it searches. If files differ (a
switch, a pull, edits), it brings the index to the checkout first, and says so on stderr:

```
the index is behind this checkout (52 files changed, 12 deleted, git HEAD moved); updating it first
```

- **It waits for stage A,** as it waits for the model: the names, lines and keywords of its
  answer are the checkout's.
- **Then stage B:** first the vectors its own keyword results need (§4.2), then the other
  queued ones for at most 20 s, and none of them with more than 1,000 chunks queued. So the
  command answers within the time limit a caller may have (an agent's shell tool). What is left
  is named after the results, with the command that embeds it:

  ```
  note: 4384 code chunks in 240 files (vllm/a.py, ...) are not embedded yet: keyword matches for
  them are current, ranking by meaning may be out of date. Run `codemem index` to embed them.
  ```
- **A search by keywords alone** (`--signals bm25`) runs stage A and loads no model.
- **It only follows the files.** An index that was built with other settings, or by another
  model, would be rebuilt or embedded again by an update, and its old vectors dropped first.
  A search never starts that: `codemem index` does.
- **If the index cannot be updated,** for that reason or because another codemem process holds
  its write lock for more than 30 s, the search answers from the index as it is. It says that the
  index is behind the checkout, why it was not updated, and to run `codemem index`.

On flask a search right after a switch across 853 commits (64 files differ) takes 1.1 s, against
0.4 s when nothing differs (a fake model, the vectors in the cache). The check itself costs what
`codemem status` costs: 0.02 s there.

**Switching back before the vectors are done** leaves no work for the branch that was left:
- a chunk that exists only on that branch is deleted by stage A of the switch back, and its place
  in the queue with it;
- a chunk that changed and changed back still has its old vector, so stage B sees an unchanged
  text hash and only drops it from the queue;
- a chunk the first switch deleted comes back as a new chunk, and its vector comes from the cache;
- a model call that is running finishes, and it is the last one: before every call the writer
  asks whether new changes arrived, and applies them first. One call is at most 3,000 characters,
  about 0.6 s on the M1, and its vectors go to the cache for the next visit.

**What the vector cache is worth here.** The index alone remembers little of a commit it left:
deleting a chunk deletes its vectors, and a new vector replaces the old one. With
`vector_cache = "off"`, coming back embeds again every text the switch removed or replaced. On the
vLLM switch above that is 17,398 texts, 12% of the index's vectors and about 34 minutes of model
time on the M1. It is 10,138 when the switch back comes before B's vectors were computed, because
the vectors stage B had not replaced yet are still in place.

**Each git worktree is a checkout of its own.** Its index folder is named after its path, so two
worktrees never share an index, and a codemem started inside a worktree (an MCP server, the CLI)
serves that worktree, with its own watcher and writer. Each such process also holds the embedding
model, unless they share one through `codemem serve-embeddings` (§3.5).

**A worktree inside another checkout stays out of that checkout's index.** Agent hosts put
worktrees inside the main checkout, in `.claude/worktrees/<name>/`. Read as plain folders, they
would give the main index a second copy of every function, and a search would return each one
twice. So:
- the scan of a checkout skips every folder that is a linked worktree of the checkout's own
  repository, and `index_status` lists the folders it left out;
- the watcher ignores the saves in such a folder, and its `.gitignore` and `.codemem.toml`;
- the worktree's own index is not affected: a codemem started inside it indexes it as it would
  anywhere else.

The rule is narrow. A folder counts only if its `.git` file leads to a git folder that shares this
repository's own (git writes that link for every `git worktree add`). A submodule, a repository of
another project and a worktree of another repository are read as part of the checkout. A folder
that cannot be looked into (the user may not enter it), or whose `.git` file is not text, does not
count either: the question never stops a scan, which goes on as for any other folder.

**A new worktree's index starts from a copy.** Without one, codemem would chunk every file again
just to find that almost all of them equal the main checkout's.

```
 codemem starts in a checkout that has no index
        │
        ▼
 another checkout of the repository has one, built with the same settings?
        │   in this order: one built at the commit this checkout is on, the main
        │   checkout's, the most recently updated
        ▼
 copy its index.db ....... one SQLite backup: a consistent snapshot, even while the other
        │                  checkout's server is writing. The saved search index is not copied;
        │                  it is rebuilt from the vector rows
        ▼
 forget the file dates ... the copy keeps every file's content hash
        ▼
 the first full check .... reads every file, and re-chunks only those whose content differs
```

- **Every candidate gives a correct index;** the order only decides how many files the first check
  re-chunks. An index built at the same commit differs by uncommitted edits only. Failing that,
  worktrees are usually cut from the main checkout. "Most recently updated" comes last: it says
  how fresh an index is, not how close its code is to the new checkout's.
- **Content decides, not dates.** A file in the new worktree can have the size and date the copied
  index recorded and still differ. So the copy forgets every date, and the first check hashes every
  file. From there on it is the same update as a branch switch, and it ends in the same index as a
  fresh build (tests check this for changed, added, moved and deleted files).
- **A copy is not yet this checkout's index.** Until that first check has run, it holds the other
  checkout's code: functions that are not in this checkout, and other lines for the ones that are.
  So `codemem search` asks for `codemem index` first. The MCP server's `search_code` and
  `get_chunk` wait for the check within their 4 s, as they wait for stage A of a save (§4.2).
  Near its source the check takes well under a second, and the first answer is this checkout's.
  Where it takes longer than the wait (a worktree far from its source, a large repository), the
  answer comes from the copy and begins with a note that says so:

  ```
  Note: codemem's index for this checkout started as a copy of another checkout's index, and
  codemem is still comparing it with the files here. Until that is done, what it returns can be
  the other checkout's code: names, line numbers and code may differ from the files in this
  checkout. Ask again in a few seconds, or read the files themselves.
  ```

  Measured on flask, in a worktree 853 commits from the main checkout (52 files to re-chunk, 12
  to drop): in 6 starts, the `search_code` and the `get_chunk` sent right after the handshake
  answered 1.4 to 2.3 s after the server's start, for this checkout, and no answer held a
  function of the other commit.

Measured on vLLM (6,235 files, 102k chunks; a fake model; an M1 shared with other jobs), in a new
worktree with one function added:

| The worktree's index | First fully current search, after codemem starts |
|---|---|
| copied from the main checkout's | 4 to 8 s, as `codemem index` then `codemem search` and as the MCP server alike |
| built from nothing, every vector already in the cache | 76 s |

Of the 4 to 8 s, the copy takes 1 to 2 s (641 MB), the full check 1 to 3 s, and rebuilding the
search index from the vector rows 2 to 4 s. The copy runs before the MCP server answers its
first message. A worktree's index is a full index on disk: 641 MB here, and 901 MB once its search
index is saved.

**The index of a removed worktree is deleted** at the next start of codemem in any checkout of the
same repository. The rule is narrow on purpose (decisions.md §6): a folder is deleted only if
codemem recorded it as a worktree's index, the worktree's folder is gone, and git no longer lists
the worktree.

---

## 5. Storage

```
 ~/.codemem/indexes/<repo>-<hash>/
 ├── index.db ............ SQLite, the source of truth
 │     files        every file seen: hash, size, date, and why it was skipped, if it was
 │     chunks       every chunk (§3.2)
 │     fts          keywords: the word lists of five fields per chunk, no copy of the text (§6)
 │     calls        the names each chunk calls
 │     edges        the links, caller ──► callee (§3.3)
 │     vectors      every vector, as float16 numbers, with its chunk, window and text hash
 │     dirty_texts  the queue between stage A and stage B
 │     meta         the settings the index was built with, the git commit, version counters
 ├── vec_code.faiss ...... saved copies of the in-memory search indexes,  ┐ rebuilt from the
 ├── vec_usage.faiss         one per text type (.rabitq: a compact one)   ┘ vectors table if lost
 ├── write.lock .......... one writer at a time
 └── worktree.json ....... in a git worktree's index: which worktree it serves (§4.6)

 ~/.codemem/cache/vector_cache.db ... the vector cache, shared by every index on the machine
       embedder     one row per embedder key: its id and its vector length
       entry        (embedder id, text hash) ──► slot, time of last use       the key table
       vec_<id>     slot ──► text hash, vector       one table per embedder, slots 1..n, no gaps
```

**Why SQLite, and not a vector database.** Most of what is stored isn't vectors and needs lookups,
joins and keyword search; SQLite has them, needs no server, and makes each update one atomic
transaction. Vectors are stored in it as plain rows, so the search index is only a derived copy,
which can always be rebuilt without the model (2 s on vLLM).

**The times in this section** are from an M1 laptop (8 cores, 16 GB), with FAISS on one thread.
On macOS codemem gives OpenMP one thread, and so FAISS and PyTorch, whatever `OMP_NUM_THREADS` or
`MKL_NUM_THREADS` say: the two each bring their own copy of OpenMP, and on more threads the copies
crash the process. When this changes a value, codemem says so once on stderr
(`codemem/__init__.py`). On Linux and Windows FAISS uses every core, and none of these times was
taken that way.

**The search index** is a copy of one vector type's stored vectors, held in memory in a form
that is fast to search. It is derived from the rows, so it can be rebuilt at any time, and it sits
behind a small interface (`VectorStore`), so the config chooses it (`vector_backend`) and a change
re-embeds nothing. Two come with codemem, an exact one and a compact one. The default, `auto`,
picks between them: **the exact index while it fits a memory budget, the compact one when it
does not.**

- **Why exact first.** The exact index compares a query with every vector, so it returns exactly
  the best ones, and it reads nothing from disk. On an index that fits the budget it is also the
  faster of the two: 6.2 ms a search against 8.5 at 31k vectors.
- **Why compact for the rest.** The exact index keeps every vector in memory: 1,856 bytes for a
  vector of 896 numbers, 371 MB for 200,000 of them. The compact index keeps a third of that,
  returned the same results in every measured search (below), and on a large index is the faster
  one: 0.92 times the exact index's time at 200,000 vectors.
- **The rule.** When an index's search indexes are loaded or built, codemem adds up what the
  exact indexes of all its vector types would take: for each vector, 2 bytes a number and 64
  bytes beside them (measured: 1,853 bytes a vector of 896 numbers). If the sum fits the budget,
  every type gets the exact index. If not, every type gets the compact one.
- **The budget** is `vector_memory_mb`. At 0, the default, it is 2% of the machine's memory, and
  at least 128 MB:

  | The machine | Its memory, as it reports it | The budget | Vectors of 896 numbers that stay exact |
  |---|---|---|---|
  | 6 GB or less | up to 6.4 GB | 128 MB | 69,000 |
  | 16 GB | 17.2 GB | 344 MB | 185,000 |
  | 24 GB | 25.8 GB | 515 MB | 278,000 |
  | 48 GB | 51.5 GB | 1,031 MB | 555,000 |

  So on a laptop of 16 GB an index of pandas (49,770 vectors, 92 MB) or of vLLM (145,000 vectors,
  269 MB) is exact, and one of 200,000 vectors (371 MB) is compact; from 24 GB up that one is
  exact too. Memory is read from the operating system; on Linux a lower limit set on the
  process's container counts. Where it cannot be read, 16 GB is assumed.
- **When the pick is made.** Once, when the first search index of a process is loaded or built,
  and it holds while the index is open: an index that grows past the budget while the service
  runs stays exact until the next start. An update that ends by saving the search indexes (the
  CLI's, the eval's) applies the rule again first, so a large index is compact, in memory and on
  disk, when the run that built it ends.
- **No flapping at the boundary.** An index that is compact goes back to exact only when the
  exact indexes would take less than 80% of the budget.
- **When the pick differs from the saved copy,** the search index is rebuilt from the stored
  vectors, as for any change of backend (see "Loading a search index" below).
- **`codemem status` says which one is in use and why**, with the memory of each vector type:

  ```
  search index: exact (faiss)
    auto: the exact index takes 92 MB, within the budget of 344 MB (2% of this machine's 17.2 GB)
    code: 43,187 vectors, about 80 MB in memory
    usage: 6,583 vectors, about 12 MB in memory
  ```
- **Naming one.** `vector_backend = "faiss"` is always the exact index, for whoever wants no disk
  read at search time whatever the size. `"compact"` is always the compact one. `"module:Class"`
  plugs in another: an approximate index (HNSW or IVF, which trade a little accuracy for speed
  on very large repos) is a class away.
- **An index built in one place and opened in another names one too.** The pick follows the
  memory of the place codemem runs in. So a build on a host and a start in a container with a
  memory limit can pick differently for the same index, and the container then rebuilds the
  search index at every start that begins from the build's files. The environment variable
  `CODEMEM_VECTOR_BACKEND` names the search index without a config file. The end-to-end eval
  sets it to `faiss` for the build of a task's index and for every run on it
  (`eval/src/cmeval/e2e_index.py`).
- **An older FAISS.** The compact index needs FAISS 1.15.1, which codemem's dependencies ask
  for. In an environment that still has an older one, `auto` always picks the exact index;
  `vector_backend = "compact"` is refused with one sentence.

**The exact index** (`faiss`) compares a query vector with every stored vector of a type, using
FAISS (a vector search library) in its exact mode: about 10 ms over 109k vectors. It keeps each
number in 2 bytes, like the stored rows: 196 MB for vLLM's code vectors, against 393 MB at 4
bytes, at the same speed. Vectors are scaled back to length 1 as they enter the index and rounded
to 2 bytes again, so every backend gets the same numbers. Keeping 4 bytes would change scores by
at most 0.0003: on 40 real-model queries, 38 top-10 lists came out in the same order, and the
other two swapped results that were practically tied.

**The compact index** (`compact`) returns what the exact index returns, from a third of the
memory. Two checks, each against the exact index:

- On 30,977 real code vectors it returned the same top 10 and top 50 in every one of 4,608
  searches: 268 real questions (the eval's issue texts) and 500 code vectors, each with no filter
  and with filters that keep 10% and 1% of the chunks, each for 10 and for 50 results.
- On a whole index of pandas (43,187 code vectors and 6,583 usage vectors, embedded by the real
  model), with the eval's 352 pandas issue texts as questions: the same top 10 and top 50 for
  both vector types, and the same 10 results of the whole search in the same order, in 352 of 352
  searches.

Every score it returns is the exact one. At 200,000 vectors it keeps 131 MB in memory against
371 MB, and a search takes 0.92 times as long as with the exact index; at 31k vectors, 1.4 to 1.8
times as long (8.5 ms against 6.2), which is why `auto` leaves a small index exact.

It keeps two codes of each vector in memory instead of the vector, and reads from SQLite only the
vectors it has to compare exactly. A search has three steps:

```
 the query vector ("disabled users stay logged in")
      │
      ▼  1. scan the 1-bit codes, in memory: 120 bytes a vector        13 ms at 200,000 vectors
      │     keep the best 4,000 (of the allowed ones, when a filter is given)
      ▼  2. rank those by their 4-bit codes: 468 bytes a vector         7.5 ms
      │     keep the best 252
      ▼  3. read those vectors from SQLite, score them exactly            2 ms
      │
      ▼  the best vectors, each with its real similarity
```

- **The codes** are RaBitQ's, made and compared by FAISS. The vector is scaled to length 1 and
  turned by a fixed random rotation. The 1-bit code keeps one bit per number (is it above zero?),
  plus 8 bytes that correct the estimate: 120 bytes for 896 numbers. The fine code keeps `bits`
  bits per number, 4 by default: 468 bytes. Together 588 bytes, against 1,792 for the vector.
- **Why two codes.** An estimate from the 1-bit code is cheap (0.07 µs, half an exact
  comparison) and rough: it can tell the best few thousand vectors from 200,000 others, but it
  cannot order them. An estimate from the 4-bit code puts the exact top 50 among its best 200,
  but FAISS takes 1.6 to 2 µs for one on this CPU: 12 times an exact comparison. So the 1-bit
  codes choose, and the 4-bit codes rank only what was chosen.
- **Step 3 makes every score exact.** It reads the candidates' stored vectors and computes the
  real similarity. A score that leaves the index differs from the exact index's by less than
  0.000001, so result lists can be merged by score.
- **How many.** Step 1 keeps the best 4,000 codes; one in 50 of the vectors the search may
  return, when that is more (beyond 200,000 vectors); and never fewer than 4 for each candidate
  of step 2. Step 2 keeps `rescore` (200), and at least 4 for each result asked for. A search
  asks for the best 50 chunks, which is 51 vectors when every chunk has one, so 204 are read
  (252 in the index of the picture, whose chunks have 1.25 vectors each).
- **When steps are skipped.** If no more vectors qualify than step 3 would read (a small index,
  or a filter that leaves few), all of them are read and scored, and the result is the exact
  index's. If no more qualify than step 1 would keep, step 2 ranks them all.
- **Why step 1 keeps 4,000.** For each of the 768 real searches on 31k vectors we looked up how
  far down the 1-bit scan's order its exact top 50 lie. The deepest lay at place 1,901. Half the
  question searches need only the best 206, 99% of them the best 1,356, and a top 10 never lay
  deeper than place 247. On a random half, quarter and eighth of the vectors the deepest places
  were 952, 1,484 and 533: the depth grows more slowly than the index, so one in 50 leaves a
  larger index more room. On two real indexes the depth depends on the question:

  | Index | Questions about the repo: the deepest place | Questions about another repo: the deepest place |
  |---|---|---|
  | pandas, 43,187 code vectors | 661 | 2,021 |
  | vLLM, 109,562 code and 35,167 usage vectors | 976 | 2,178 |

  A question about something the repo does not hold has weak matches that lie close together,
  and the 1-bit code orders them badly. With 2,000 kept, one such search on each index lost one
  result of its top 50 (ranks 45 and 44; no top 10 was touched). With 4,000 all 704 such searches
  on vLLM return the exact top 50, as do the 762 with vLLM's own questions. The 2,000 more codes
  cost a search 0.5 ms with FAISS 1.16.0.
- **Why FAISS does not scan the fine codes itself.** FAISS can scan a multi-bit index in one
  call. It then takes the full estimate of every code whose first bit leaves it a chance against
  the best found so far: a tenth of the codes when 200 candidates are asked for, a fifth to a
  quarter for 500. A search took 2.1 and 3.6 times as long as with the exact index on the 31k
  real vectors, and 3.0 and 3.9 times at 200,000. Rounding the query to 2 or 8 bits instead of
  4 changes that by about a tenth, and no FAISS setting turns it off. Which codes get the full
  estimate also depends on the order they are scanned in.
- **Why the rotation.** How well one bit per number works depends on how a model spreads its
  numbers. After a random rotation the error of the estimate has the same bound for any vectors.
  On our real questions the exact top 10 was among the 200 best 1-bit codes in 99.3% of searches
  with the rotation, and in 96.3% without.
- **Why the centre is zero.** RaBitQ can subtract an average vector before it takes the bits, and
  FAISS learns that average from the vectors it is shown. A learned average ties every code to the
  vectors the index held at that moment: an index patched edit by edit and one rebuilt from its
  rows would hold different codes, and could return different results. With the centre fixed at
  zero, a code depends only on its own vector. A learned centre did not help at 896 numbers (98.5%
  against 99.3%); at 512 numbers it added 3 points.
- **The order of the codes never matters.** Copies of one vector have the same codes, and so the
  same estimates. A cut through them, in step 1 or in step 2, takes them all. So the candidates
  depend only on the vectors an index holds: one patched edit by edit, one rebuilt from its rows
  and one that holds the same vectors under other ids return the same results (768 searches on
  two indexes whose ids differ: no difference at any setting). The codes are also kept in the
  order of their vector ids, so two indexes with the same rows hold the same bytes.
- **Filters** become one bit per vector, which FAISS tests while it scans.
- **Deleted rows.** If another process deletes a candidate's row before this process has caught
  up, the vector is left out and the search takes more candidates.

**What each setting keeps.** The same 30,977 vectors, through `Store.vector_search`, against the
exact index, with no filter (under a filter every row keeps at least as much). The worst search
is the one that lost most of its top 50.

| `bits`, `rescore` | Codes, bytes per vector | Questions: searches with the exact top 10 | Their top 50, on average | Their worst search | Code vectors: the worst search |
|---|---|---|---|---|---|
| **4, 200** (the defaults) | 588 | 100% | 100% | 50 of 50 | 50 of 50 |
| 4, 500 | 588 | 100% | 100% | 50 of 50 | 50 of 50 |
| 8, 200 | 1,036 | 100% | 100% | 50 of 50 | 50 of 50 |
| 2, 500 | 364 | 100% | 100% | 50 of 50 | 50 of 50 |
| 2, 200 | 364 | 100% | 99.94% | 48 of 50 | 50 of 50 |
| 1, 2,000 | 120 | 100% | 100% | 50 of 50 | 50 of 50 |
| 1, 1,000 | 120 | 100% | 99.96% | 48 of 50 | 50 of 50 |
| 1, 500 | 120 | 100% | 99.75% | 44 of 50 | 50 of 50 |
| 1, 200 | 120 | 99.3% | 97.2% | 36 of 50, and 9 of its top 10 | 48 of 50 |

Questions are the hard case. Their best matches score about 0.33 to 0.40, and the 200th best
0.23: the gap is as small as the error of a 1-bit code. Code vectors find near copies of
themselves (0.73 to 0.93), which any code keeps.

- **One bit is the small option** (`bits = 1`): 160 bytes per vector in all, 33 MB at 200,000
  vectors. It has no fine code, so only the count of candidates protects the results: the top
  10 is safe from 500 candidates up, the whole top 50 at 2,000. Each candidate is a row read from
  SQLite. 2,000 of them take 12 to 18 ms when the rows are in the system's file cache, which is
  three times the exact index's whole search at 31k vectors, and about 0.2 s when they are not.
- **Two bits** need 500 candidates to keep everything.
- **Eight bits** keep what four keep, at twice the memory, and take three times as long to
  code.

**The codes cover every number of the vector** (`dim = 0`), because a code of the first numbers
loses results that no count of candidates brings back. Share of searches with the exact top 10,
1-bit codes:

| Numbers coded | Bytes per vector | Questions: 100 candidates | 200 | 500 | Code vectors: 100 | 200 | 500 |
|---|---|---|---|---|---|---|---|
| 128 | 24 | 13% | 26% | 46% | 90% | 96% | 98% |
| 256 | 40 | 30% | 49% | 75% | 98% | 99.2% | 100% |
| 512 | 72 | 65% | 80% | 94% | 100% | 100% | 100% |
| 896 (all) | 120 | 93% | 99.3% | 100% | 100% | 100% | 100% |

A fine code does not make up for the missing numbers: 256 numbers with a 4-bit code kept the top
10 in 91% of question searches at 200 candidates, and 512 numbers in 99.3%.

A code covers at most 4,096 numbers. Vectors longer than that are coded on their first 4,096,
and the index logs a warning when it is made, once: its searches can miss what only the other
numbers tell apart. With 2,100 vectors of 8,192 numbers whose first half was noise, none of 12
searches returned what the exact index returned; with vectors alike over their whole length,
all 12 did. The exact index compares every number, and `embedding_dim` cuts the vectors
themselves.

**What it costs**, on an M1 with 16 GB that was running other jobs (so times are medians, n = 50),
with FAISS on one thread:

| At 200,000 vectors of 896 numbers | Exact | Compact, as `auto` uses it (4 bits, 200 candidates) | Compact, `bits = 1`, `rescore = 500` |
|---|---|---|---|
| in memory, per vector: the index | 1,800 bytes | 588 + 8 (its id) | 120 + 8 |
| in memory, per vector: where it came from | 32 | 32 | 32 |
| the process's memory after loading (what it keeps) | 371 MB | 131 MB | 33 MB |
| the saved file, per vector | 1,800 bytes | 596 | 128 |
| start from the saved file | 0.9 s | 0.5 s | 0.4 s |
| start from the rows | 2.5 s | 32 s | 4 s |
| one search, each backend in a process of its own: median (95th percentile) | 32.5 ms (41) | 23.3 ms (29) | 15.5 ms (18) |
| of which the scan / the ranking / the read | all scan | 13.2 / 7.5 / 2.1 ms | 10.9 / none / 3.7 ms |
| one search under a filter that keeps 10% | 13.0 ms | 13.8 ms | 11.7 ms |
| 100 vectors added / deleted | 129 / 27 ms | 33 / 16 ms | 8 / 14 ms |
| one search, the backends taking turns in one process | 23.9 ms | 22.1 ms, 0.92 times the exact index's | 14.8 ms, 0.61 times |
| the same at 31k real vectors | 7.1 ms | 12.8 ms, 1.8 times | 8.4 ms, 1.2 times |

In a process of its own each backend meets the load of its own minute. In the last two rows they
take turns, query by query, so that the load slows them alike; no backend then keeps its codes in
the processor's cache from one search to the next. Four more things to know about the cost:
- **On a small index the exact one is faster.** Steps 2 and 3 take about 3 ms whatever the
  index's size, and on a small index the faster scan before them saves less than that. With
  FAISS 1.16.0, which the lock file pins, and the two indexes taking turns: 3.0 ms against 4.5
  on pandas's 43,187 real code vectors, 2.4 against 3.9 ms on vLLM's 35,167 usage vectors, and
  8.1 against 7.5 ms on vLLM's 109,562 code vectors. The two meet at about 100,000 vectors. The
  table above was taken with FAISS 1.15.1, whose RaBitQ code has no vectorized form for ARM
  processors: with 1.16.0 both indexes are about 1.5 times faster on an M1, and one 4-bit
  estimate takes 0.3 µs and not 1.4.
- **Coding takes time.** A start from the rows codes every vector: 32 s at 200,000,
  against 2.5 s for the exact index. The saved file avoids it.
- **The rows must be in the operating system's file cache.** When they are not (after a restart),
  a search reads its candidates from the disk: about 30 ms more for 252 rows, for each
  search, until the pages it needs have been read once. More candidates cost more: 500 took 60
  ms more, and 2,000 at 1 bit 0.2 s.
- **The rows are read through a connection of their own**, one per thread, with a page cache of 2
  MB. Read through the store's main connection they would fill its 64 MB cache: 400 searches at
  200,000 vectors grew the process by 62 to 80 MB that way, and by 0 to 16 MB this way, at the
  same speed. That connection is in autocommit mode, so each read sees every committed
  row and holds no snapshot open between searches; inside a write transaction or a read snapshot
  of the store, the rows are read through the main connection instead.

**Where it can differ from the exact index.**
- The measurements above are one model, on indexes of up to 145,000 vectors. On another model's
  vectors, or on an index several times larger, the best 4,000 (or one in 50) of the 1-bit scan
  may hold less of a search's top 50. Its top 10 has more room: it never lay deeper than place
  581 in any sample.
- A query with nothing near it. On 200,000 synthetic vectors, queries that have about 100 near
  neighbours each got the exact top 50 in every search. Queries that have none (their best
  match scores 0.14 and their 4,000th best 0.07, so a thousand vectors lie within a 1-bit code's
  error of the 50th) got the exact top 10 in 78% of searches, and 92% of their top 50. With
  1-bit codes and 500 candidates it is 16% and 59%. FAISS's own scan of the 4-bit codes gets all
  of it, at 3 to 4 times the exact index's time. A filter can put a query in the same place: one
  that keeps a tenth of the chunks leaves about 10 of those 100 neighbours, the rest of the top
  50 is then decided the same way, and 97.6% of it was kept. Real questions are not like this:
  their best matches score 0.33 to 0.40, the 200th best 0.23, and under the same filters every
  real search kept its whole top 50.

The compact index is saved as `vec_<type>.rabitq` (the ids and both codes: 596 bytes per vector),
so a start reads it instead of coding every vector again.

**A mistake in a FAISS call can end the process** instead of raising an error, and that would take
the MCP server with it. So the compact index checks whatever it hands to FAISS first: the length
and number type of every array, the size of every filter, that both of its FAISS indexes hold one
code per vector id, and that no number is a NaN or an infinity (such a vector is coded as zeros
and never returned). Its saved file carries a checksum, and is given to FAISS only when the
checksum, the options and the rotation are the expected ones. What FAISS was not checked with is
refused with a message: a code of more than 4,096 numbers when the config is read, a FAISS older
than 1.15.1 when the index is opened.

**A call that raises** (FAISS cannot get memory) must not leave the two FAISS indexes with
different codes. A change is several calls: codes are added to each index, and for an id that
is held already or is older than the newest held, codes are dropped and moved as well. New
codes that one index took are taken off again when the other fails. Dropping and moving is
done on copies of the two indexes, which replace them once every call has worked. Either way
the index holds what it held before, the write raises, and the store adds the vectors again
when it next catches up with the rows.

**Loading a search index.** A search index is saved beside `index.db` and read back at the next
start: 0.9 s for the exact index of 200,000 vectors, 0.5 s for the compact one. It is rebuilt
from the stored vectors instead when the saved copy cannot be used: there is none, it is another
backend's (the rule picks the other index, or the config names another), its bytes are not the
bytes that were saved, the database has gone back to a state from before the copy, or its note
lacks the database, the save's id or the checksum that a start checks. That last case is every
copy saved by a codemem that did not write them: the first start on such an index rebuilds its
search index, once. On an M1 that was running other jobs, an
exact index took 0.5 to 1.5 s to rebuild at 50,000 vectors and 2.5 to 5 s at 200,000. A compact
index has to code every vector: 12 to 20 s at 50,000 and 32 to 70 s at 200,000, with FAISS on
one thread.

Nobody waits for a rebuild:
- **It runs in the background.** The MCP server loads the model and the search indexes side by
  side when it starts. A rebuild holds no lock while it reads and codes, so writes, `get_chunk`
  and `index_status` go on; what was written meanwhile is added at the end, by vector id.
- **A search that comes first answers from keywords.** It waits for the model and the search
  indexes only within its 4 s, and not at all for a rebuild that will not end in time (its pace
  tells). It then returns keyword results and a note that says so, as it does while the model
  loads. Measured at 200,000 vectors, on the same loaded machine: a search asked 0.2 s after
  the start returned its keyword results in 0.9 s, while the compact index was being rebuilt;
  searches used the vectors from the moment it was ready, 83 s after the start. Had the rebuild
  held the lock, that first search would have waited for all of it (66 s in the same
  measurement), and so would the commit of a vector written meanwhile. At 50,000 vectors an
  exact index is rebuilt within the wait: the first search took 1.1 to 1.3 s and already had the
  vectors.
- **The CLI and the eval pay it in the update, not in a search.** An update that ends by saving
  leaves every vector type with the file the next start reads: a type whose file is missing,
  behind the rows or another backend's is loaded or rebuilt, and written. Their searches wait for
  an index that is still loading: they return results by meaning, always.
- **A write does not start one.** Vectors written to a type whose index is not in memory are left
  for its first use, which reads the file and adds the rows it lacks. Only a type's very first
  vectors start its index, so that a build's index grows batch by batch.

**Where each vector came from** (its chunk, its part, its lines) is kept in memory as one 32-byte
row per vector, in an array sorted by vector id: 6.4 MB at 200,000 vectors, for either index. A
chunk with several vectors scores its best one. When chunks have several vectors, the store asks
the index for proportionally more vectors, so that the best 50 chunks are complete after one scan.
An SQLite index over these columns (about 25 bytes per vector on disk) lets a start read them
without touching the pages that hold the vectors: 0.2 s instead of 0.8 s at 200,000 vectors.

**A query without a direction** (a vector of zeros) gets no results by meaning, from any index.
Every stored vector scores 0 against it, and equal scores are taken whole, so that their order
never depends on where a cut falls: the search would go on until it had seen every vector. On
the pandas index (43,187 code vectors) that took the compact index 4.1 s and 561,431 row reads.
The store answers such a query with nothing and asks no index.

**Keeping the copy in step with SQLite.** The in-memory index changes only after a commit, so it
never holds a vector that could be rolled back. Every commit that changes a type's vectors also
bumps that type's version number in `meta`, and an index that is behind catches up by comparing
vector ids: vectors are never changed in place, only added and deleted, so the ids that differ are
the whole difference. That covers a saved copy from before a crash, and another process's writes.
Searches never wait for writes (SQLite's WAL mode lets readers continue while one process writes).

A saved copy is read only into the database it was saved from. Each `index.db` carries a random
`database_id` in `meta`, and the copy's note names it. A copy whose note names another database,
or none, is rebuilt from the rows. Vector ids start again at 1 in a new `index.db`, so without the
name the copy of a deleted one would be matched, id by id, against vectors it was not made from.

A saved copy is read only by the state of the database it was saved from, or a later one.
Matching by vector id is right while no id is used twice, and a database that goes back uses
them twice: an `index.db` put back from a backup, or one that lost its last commits in a power
cut (commits are not synced to the disk one by one), hands out again the ids of the rows it
lost, for other vectors. The version number does not show it, because it counts up again. So
each save writes a random `save_id` into the copy's note and into `meta`, and a start reads the
copy only when the two are equal. `meta` goes back with the database: after a step back they
differ, and the search index is rebuilt from the rows. The id is committed after the index was
copied from memory, so a state that holds it comes after every vector of the copy. A save
writes the file under a temporary name first; one short transaction then sets the id, renames
the file and writes the note. A save that is stopped part of the way leaves the earlier copy,
or one that a start refuses.

A saved copy is read only if its bytes are the bytes that were saved. Its note holds a checksum
of the file (CRC-32), and a start compares the two before the index is given the file. A file
that differs is rebuilt from the rows, with one warning in the log: a damaged file, one that
was cut short, and the file of another index under this one's note. FAISS itself reads an exact
index with a flipped bit as it is. In a test with 2,500 vectors the damaged vector then scored
up to 2,427 (a similarity cannot pass 1), and a flipped bit in a size field made the start
allocate past 500 MB for a file of 0.3 MB.

A note never chooses a file. Whoever can write to the index folder can write a note, and the
file a note describes is read at a start and deleted when a save replaces it. So that file is
always `vec_<type><suffix>` in the index folder, with the suffix of the note's backend. A note
that names anything else, a path among them, counts as no note.

**The vector cache** maps (embedder key, text hash) to a vector: 2 bytes per number, at the
model's full length. It is one SQLite file for the whole machine, and every codemem process
reads and writes it. Each part of its layout has a reason. The numbers are from 200,000 synthetic
vectors of 896 numbers unless a line says otherwise. The times are medians of one run on an M1
that other jobs kept busy (load average 12 to 16 on its 8 cores). Three more runs gave times up
to twice as long, and up to three times for the eviction of the oldest tenth.

- **One vector table per embedder.** All vectors of an embedder have one length, so the rows of
  its table have one size and fill their pages: 18 vectors of 896 numbers on a page. On disk a
  vector of 1,792 bytes takes 1,877 bytes, its key included (31,477 vectors of the default
  model). A single table with the key as text in every row takes 4,690 bytes for the same vector,
  because every row spills onto a 4 KB page of its own.
- **Slots without gaps.** When entries are deleted, the last rows of the table are written into
  the freed slots, and the pages at the table's end become free. So the file shrinks by what was
  deleted, wherever the deleted entries were: a tenth of the entries, spread over the whole file,
  takes it from 377 MB to 339 MB. Without the move a page is free only once every row on it is
  gone: the same deletion in a plain table of the same rows, 369 MB, gives back nothing.
- **The time of last use sits in the key table,** not next to the vector. Marking entries as used
  then rewrites key pages, which hold about a thousand entries each, and never a page of vectors.
  An index on that time lists the least recently used entries, so eviction does not scan the
  cache.
- **A read is one statement:** a lookup in the key table, then one in the vector table, both in
  one snapshot. A reader therefore never follows a slot that an eviction is moving. A read writes
  nothing. Marking entries as used is a call of its own (`touch`), and it writes an entry once a
  day at most.
- **Pages are read through SQLite's page cache, not a memory map.** A map reads 200 vectors in
  0.9 ms where the page cache takes 2.2 ms. But an I/O error on a mapped file ends the process,
  and an error in an ordinary read only costs a cache miss.
- **Pages of 32 KB.** A page holds a whole number of rows, so the space lost depends on the
  vector's length. The table shows the bytes on disk above the vector's own bytes, keys included,
  and the time to read 200 vectors by key (100,000 vectors of 896 numbers; the fastest of 450
  reads, then the median):

  | Numbers per vector | 16 KB pages | 32 KB pages | 64 KB pages |
  |---|---|---|---|
  | 768 | +10.2% | +5.1% | +5.5% |
  | 896 | +4.6% | +4.8% | +5.0% |
  | 1,024 | +16.9% | +9.4% | +6.3% |
  | 2,048 | +34.8% | +15.8% | +8.5% |
  | 4,096 | +100.9% | +34.3% | +15.6% |
  | 200 keyed reads | 1.5 ms, 2.7 ms | 1.9 ms, 2.5 ms | 2.9 ms, 3.4 ms |

  At 32 KB the default model's vectors cost what they cost at 16 KB, every other length costs
  less, and three vectors of 4,096 numbers fit a page where 16 KB holds one. An undisturbed read
  takes a quarter longer than at 16 KB; on the busy machine the medians did not differ. At 64 KB
  a read takes half as long again as at 32 KB, and every change writes more, because a page is
  rewritten whole.

**What the cache costs in time.** Reading 200 random vectors by key takes 2.3 ms (4.3 ms for 19
reads in 20). A process's first read, which also opens the file, takes 3.1 ms, and 35 ms when
the file's pages are not in memory yet. A put of 256 vectors takes 5.8 ms. Marking 200 entries as
used takes 4.6 ms, and 0.4 ms when they were already marked today.

**The size cap** (`vector_cache_max_gb`, 8 GB by default: [decisions.md](decisions.md) §3). When
the file passes it, the least recently used entries are deleted until the file is under 90% of
the cap. An entry is used when stage B puts it, finds it, or a caller marks it. Three rules keep
this out of the way:
- a put looks at the file's size once per 1% of the cap it has written, not every time;
- a put that finds the file over the cap evicts for a quarter of a second at most, because a
  search may be waiting for that put. The next puts go on, and a blocking update (`codemem
  index`) finishes the job before it returns;
- an eviction works in transactions of 256 entries, so other processes read and write in between.

Deleting the oldest tenth of 200,000 vectors takes 1.1 s. A tenth spread over the whole file
takes 2.8 s, because almost every deleted row sits on a page of its own, and that page is
rewritten. Eviction loses nothing for good: an evicted vector is embedded again when its text
comes back.

**The age limit** (`vector_cache_max_age_days`, 30 by default). An entry that nothing has used for
that long is deleted, in the same transactions of 256 entries, and its pages go back to the file
system. Stage B alone would make that the wrong rule: it uses an entry only when an index lacks
the vector, so the entries of a repo's unchanged code would look unused from the day they were
made. So an index counts as a user of the vectors it holds. Where an update ends, and every 6
hours in a quiet moment of a running session, `Indexer.cache_upkeep` marks them as used, drops
what is past the limit, and enforces the cap. The marking is done once a day per index, which
remembers the day in its `meta`: for vLLM's 145,000 vectors it reads their hashes from an index
on `vectors` in 0.4 s and marks them in 0.2 to 0.7 s. What ages out is therefore what no index
on the machine has needed for 30 days: branches and commits nobody came back to, and repos that
are gone. A running session deletes for a second at a time, so a save never waits long behind
it; all 194,000 vectors of a real cache took 12.5 s to delete.

**When the cache file cannot be used** (another program holds it, it is read-only, it is damaged),
every call answers as an empty cache would. It logs one warning and leaves the file alone for a
minute. The index update goes on, with vectors from the model.

**A cache file with one row per vector** (`cache/vectors.db`, a single table keyed by text) is
read into the cache when the cache is first opened: 2,000 rows at a time, in key order,
skipping what is already there. So an import that was interrupted, or that two processes run at
once, still ends complete. The file is deleted once everything is committed and synced to disk,
and only if nothing was added to it meanwhile: while another process still writes it, it stays,
and each start imports what is in it. 34,218 vectors (148 MB) take 1.6 s and become 60 MB.

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

At startup the server opens its index and answers the agent's handshake. In a new git worktree
it first copies another checkout's index (§4.6). Then, in the background, it checks the repo
against the index (or builds it the first time), starts the watcher and loads the model.

| Tool | Does |
|---|---|
| `search_code(query, k, path_prefix, kinds, tests)` | catches up (§4.2), then returns up to `k` cards (10 by default, 50 at most), with a note if something is still pending |
| `get_chunk(ref)` | the full code of a chunk, by id, `path:line` or `path::qualname`, with its callers and callees |
| `index_status()` | what is indexed, what is pending or skipped and why, which model and whether it is in memory, and any error |
| `refresh_index()` | a full check now, for changes the watcher can't see |

All the wording an agent reads (tool descriptions, server instructions) lives in `prompts.py`, at
three strengths (`none`, `light`, `strong`): getting agents to use the tool at all is the real
adoption problem, and the agent study varies it.

The CLI is for people and scripts: `codemem init` registers the MCP server with your agents,
downloads the model and builds the index; `codemem index`, `search` and `status` do what they say
(`search` first brings the index to the checkout if files changed since its last update, §4.6);
`codemem serve-embeddings` serves the local model to other codemem processes (§3.5).

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
| a search index | a `VectorStore` subclass (README); `FaissVectorStore` and `CompactVectorStore` in `store.py` are the two that come with codemem |
| smarter call links | a replacement for `callgraph.resolve_edges` |

---

## 10. Performance

On an M1 laptop, where FAISS runs on one thread (§5). vLLM: 6,235 files, 102k chunks, 145k
vectors. Update times use a fake model, so they show codemem's own work; the real model adds about
0.1 s per changed text.

| | Measured |
|---|---|
| a one-function edit, until searchable (vLLM) | 0.11 s (0.48 s for the first edit in a process) |
| a full check, nothing changed (vLLM) | 0.3–0.5 s |
| a search of 10 words / 250 words (vLLM) | 0.12 s / 0.63 s |
| a save then a search, through MCP, real model (sample repo) | 0.13–0.4 s, the edit included |
| a full build of vLLM, fake model | 72 s |
| a switch between two commits a week apart, 1,651 files differ (vLLM): stage A, then stage B with every vector in the cache | 18–27 s, then 10–22 s, in the fastest runs on a busy machine (§4.6) |
| the first current search in a new worktree (vLLM): its index copied / built from nothing | 4–8 s / 76 s (§4.6) |
| loading the real model on the GPU, PyTorch already imported | about 2 s at a load average of 3 to 5 (8 cores), 3 to 5 s at 6 to 7, 5.5 s at 8 to 11 |
| the first search after the model was freed, real model (sample repo) | 3.5 s with every signal at a load average of 5; 4.1 s from keywords at 8 to 11 (the model was back 7.0 s after the search began). A search that waits for the model: 2.2 s and 3.8 s |
| giving a batch's working memory back, real model on the GPU | the call takes 0.1 s; 256 code texts took 84 s right after it and 87 s with nothing given back, and batches of 32 took 10.0 s and 10.4 s (four of each, in turn) |
| the real model on the CPU, in float32 | 20 short queries in 3.7 s and 32 code texts of about 1,000 characters in 36 s, against 1.9 s and 9.1 s on the GPU |
| 200 vectors read by key from the vector cache (200,000 vectors) | 2.3 ms |

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
                                  │               (with an assist: assist.py AssistedEmbedder shares the call)
                                  └─ _put()       store.put_vectors() ─► the in-memory search index
```

**A search** (`search_code` over MCP):

```
 server.py   search_code() ─► service.py CodememService.search()
                                ├─ catch_up()   RepoWatcher.barrier() ─► hand over unapplied paths
                                │               ─► wait for the writer's stage A
                                │               ─► _models_ready(): the model is in memory, or loads in time
                                │               ─► _embed_first(): Indexer.embed_pending() for the queued
                                │                  chunks among _keyword_results()
                                │               ─► Indexer.embed_pending() for the newest edits, until 4 s
                                └─ search.py search()
                                      ├─ bm25_match() ─► store.bm25_search()
                                      ├─ make_embedder(...).embed_queries() ─► store.vector_search(), per text type
                                      └─ rrf() ─► filters and weights ─► cards
             ◄─ render.py format_results() + freshness_note()     the cards, and the note if anything is pending
```

**Other entry points:**
- `codemem mcp` ─► `server.run_stdio()` ─► `CodememService()` ─► `CodememService.start()` (a full
  check, the writer, the watcher, model loading) ─► `build_server()` serves the four tools over
  stdio.
- `CodememService()` without an index folder (the MCP server, the CLI) ─► `worktrees.py
  prepare_index()`: `removable_indexes()` and `remove_index()` for worktrees that are gone, then
  `copy_source()` and `copy_index()` if this checkout has no index, then `record_worktree()`.
- `get_chunk` ─► `CodememService.get_chunk()`: the catch-up without stage B, then the chunk with its
  callers and callees. `index_status` ─► `CodememService.status()`. `refresh_index` ─►
  `CodememService.refresh()`.
- The model's life (§3.5): `CodememService.prewarm()` loads it, in a thread that `start()` or
  `_models_ready()` starts; `_models_ready()` is what a search and the writer ask before they
  embed, and it marks the model as used (`Embedder.touch()`). `embedder.release_idle()`, called
  for each embedder in the writer's quiet step and by the embedding server's queue, asks it to
  `unload()` or to `trim()`, which the embedder's count of calls in progress (`embedder._Uses`)
  allows only while none is running. `service._Retry` spaces out the writer's tries after a failure.
- The CLI (`cli.py main()`): `codemem index` runs `Indexer.update()`, which is stage A, then all of
  stage B, then writing the search index to disk; `--verify` runs `Indexer.verify()`. `codemem
  init` registers the server with agents (`agents.py`, `launch_command()`).
- `codemem serve-embeddings` ─► `embedserver.serve()`: `local_embedder()` picks the config's local
  model, `describe()` loads it and checks its prefixes, and `EmbeddingServer` answers
  `POST /v1/embeddings` through `ModelQueue`, the one thread that calls `Embedder.embed_texts()`.
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
| `embedserver.py` | `serve-embeddings`: an embedder behind an OpenAI-style HTTP endpoint, for other codemem processes |
| `assist.py` | an endpoint that shares a build's embedding work with the local model: the check, the split, the rests |
| `plugins.py` | loads `"module:Class"` plugins named in the config |
| `vectorcache.py` | the shared vector cache |
| `store.py` | SQLite, the in-memory search index, filters, consistency |
| `indexer.py` | the update function: finding files, stage A, stage B, verify mode |
| `service.py` | `CodememService`: the writer thread, the catch-up, the watcher, status |
| `watcher.py` | file events, batched |
| `worktrees.py` | the checkouts of a repository; copying an index for a new one; deleting the index of a removed worktree |
| `search.py`, `render.py` | search, and the cards and notes an agent reads |
| `server.py`, `cli.py`, `__main__.py`, `prompts.py`, `agents.py` | the MCP server, the CLI (also `python -m codemem`), agent-facing text, agent registration |
