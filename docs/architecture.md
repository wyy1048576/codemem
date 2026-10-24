# How codemem works (v2)

codemem is a local code search tool for coding agents. You point it at a repository. It cuts
every source file into functions, classes and top-level code blocks, and remembers three things
about each one:
- its words (keyword search)
- its meaning (embeddings)
- who calls it (call graph)

An agent then asks it questions in plain words over MCP, or a script asks over the CLI. It gets
back a short ranked list of places in the code. Everything runs on your machine.

This page walks through the whole system with one example. Exact record formats are in
[data-model.md](data-model.md). What changed from the Week 1 MVP, and why, is in
[baseline-v2-diff.md](baseline-v2-diff.md). Research directions are in
[advanced-design.md](advanced-design.md).

---

## The running example

The agent gets the issue *"Disabled users stay logged in"*. The fix belongs in this function:

```python
# auth/sessions.py
def revoke_session(session_id):          # lines 19-20
    db.sessions.delete(session_id)
```

`grep` for the issue's words fails: `revoke_session` contains none of them. Its neighbours do.
`disable_user()` calls it, and the test `test_disabled_user_loses_sessions` tests it. We follow
this function through every stage.

---

## The pipeline at a glance

```
           INDEX (once, then only what changed)                        SEARCH (per query)

 repo ─► 1 find files ─► 2 chunk ─► 3 call graph ─► 4 texts ─► 5 embed ─► 6 store
                                                                            ▲
 agent ── "disabled users stay logged in" ─► MCP / CLI ─► 7 search ─────────┘ ─► ranked cards
                                                  ▲
 file saved ─► 8 watcher ─► incremental update ───┘
```

| Stage | Module | One line |
|---|---|---|
| 1 find files | `indexer.walk_source_files` | every file in a supported language, minus ignored, vendored, generated |
| 2 chunk | `languages/`, `chunker.py` | tree-sitter splits a file into functions, methods, classes, blocks |
| 3 call graph | `callgraph.py` | link each call to the definitions of that name |
| 4 texts | `texts.py` | the text to embed per chunk: code with a context header; usage (callers, tests) |
| 5 embed | `embedder.py`, `vectorcache.py` | jina-code-embeddings, only for texts never embedded before |
| 6 store | `store.py` | SQLite holds everything; FAISS is a derived search index |
| 7 search | `search.py`, `render.py` | BM25 + vector search per text type, fused with RRF, rendered as cards |
| 8 freshness | `watcher.py`, `service.py` | re-index only the files that changed, about a second after a save |

---

## 1. Finding files

`walk_source_files` walks the repository. It keeps every file whose extension belongs to a
supported language. There are nine:
- Python
- JavaScript, TypeScript, TSX
- Go, Java, Rust
- C, C++ (with CUDA `.cu`)

A `.h` file is C unless it uses C++ syntax.

**It never reads:**
- files `.gitignore` excludes (nested ones too)
- `.git`, `node_modules`, `.venv`, `build`, `dist` and similar folders
- vendored or generated paths: `vendor/`, `*.min.js`, `*_pb2.py`, `*.pb.go` (`use_default_ignore = false` turns this off)
- files over 1 MB, and binary files

**It reads, then skips:** files that say `Code generated … DO NOT EDIT` or `@generated`, and
minified JS/TS. The file is recorded as `skipped` so it is not re-read on the next scan.

*Example:* `auth/sessions.py` is Python. It is new, so it goes to the chunker. On a later run,
an unchanged mtime and size means it is not even read.

## 2. Chunking

tree-sitter parses the file into a syntax tree. A small **language spec** for each language
(`languages/python.py`, `go.py`, `c_family.py`, …) says which tree nodes are functions, classes
and namespaces, how to read their names, and which nodes are calls. One generic **walker**
(`chunker.py`) walks the tree in three modes:

- **Module or namespace body.** Definitions become chunks. Runs of other statements between them become **block** chunks (imports, constants, `if __name__ == "__main__":`).
- **Class body.** Methods become chunks. Every member contributes one line to the class's **skeleton**: `class Table:`, `def insert(self, key, value):`, …
- **Function body.** Only nested named definitions become chunks (`expire_old.is_old`). Lambdas and callbacks stay part of the function.

Wrappers that hold definitions are opened: `if TYPE_CHECKING:`, `try/except ImportError`,
`#ifdef`, `extern "C" {}`. C++ namespaces, Rust `mod`/`impl` and TS `namespace` add a qualifier
to the names inside.

*Example:* `auth/sessions.py` gives:
- a block (lines 1–5: the docstring and imports)
- functions `new_token`, `create_session` and `revoke_session` (lines 19–20)
- class `Session` with its method `Session.__init__`

`revoke_session` is stored with its signature, its code, its key
`auth/sessions.py::revoke_session`, and its calls: `["delete"]` (from `db.sessions.delete(...)`).

The same story in Go (`func (m *Manager) ExpireOld`), TypeScript (`export const disableUser = async () => {}`)
or C (`static int *revoke_session(struct session *s)`) produces the same kinds of chunks. See
`tests/test_languages.py` and the per-language table in data-model.md.

## 3. The call graph

Every call a chunk makes is stored as a callee **name**. After each update, names are linked
to the functions, methods and classes that define them, within one language family (C with C++,
JavaScript with TypeScript). A name defined more than five times (`get`, `run`) is ignored, because
it would link everything to everything.

*Example:* `disable_user` calls `revoke_session`, and `logout` calls it too. The test
`test_disabled_user_loses_sessions` calls `disable_user`. These edges feed stage 4.

This is a deliberately simple baseline heuristic, isolated in `callgraph.resolve_edges` so a
smarter resolver (imports, scopes) can replace it.

## 4. Texts

Each chunk gets one text per **vector type**. Each type becomes its own vector set, so search can
use them separately:

- **code.**
  - A two-line header gives the embedder the context that raw code lacks: the file path, and the enclosing class or namespace.
  - Then, outside Python, the doc comment (it sits above the code span). Then the code.
  - A class embeds its skeleton, not its full code: its methods are already chunks of their own.
- **usage.** Who calls the chunk and which tests reach it. This is the "anchor text" idea from web search: what others say about a page often describes it better than the page itself.

  ```
  revoke_session in auth/sessions.py
  called by logout in api/routes.py
  called by disable_user in auth/users.py
  tested by test_disabled_user_loses_sessions in tests/test_users.py
  ```
- **summary.** A slot for LLM summaries. Not built yet.

A code text longer than the embedder reads well (about 3,000 characters for 1,024 tokens) is
split into overlapping **windows** of whole lines. Each window is its own vector. The MVP cut such
texts off silently, so the end of a long function could never be found by meaning.

## 5. Embedding

The default model is `jinaai/jina-code-embeddings-0.5b` (896 dimensions). It uses separate task
prompts for queries and for code. On a GPU (CUDA, or MPS on a Mac) it runs in float16.

**codemem only embeds texts it has never seen.** Every text has a hash, and before calling the
model it looks the hash up:
1. in this index (the same text elsewhere in the repo)
2. in a shared **vector cache** (`~/.codemem/cache/vectors.db`, also used by other indexes and earlier builds)

Rebuilding an index, or indexing a different commit of the same repo, therefore embeds only what
is new. Texts are embedded longest first, so each batch has similar lengths and wastes less padding.

*Example:* the first index embeds `revoke_session`'s code and usage texts. Adding a blank line
above it changes neither text (texts contain no line numbers), so nothing is re-embedded.

## 6. Storing

One folder per index (default `~/.codemem/indexes/<repo>-<hash>/`):
- **`index.db`** (SQLite) holds everything: files, chunks, a 5-field BM25 index (name, path, signature, doc, body), calls, edges, and every vector as a float16 row.
- **`vec_code.faiss` and `vec_usage.faiss`** are exact inner-product search indexes **derived** from those rows. If one is missing, stale or corrupt, it is rebuilt from the rows in seconds, without the model.
- **Matryoshka truncation** (`embedding_dim = 256`) is applied when this index is built, so changing it re-embeds nothing.

One process writes at a time (a lock file). Searches keep working during updates (SQLite WAL).

## 7. Searching

For the query *"Disabled users stay logged in"*:

1. **BM25.** The query is tokenized the same way the code was (identifiers split, whole identifiers kept). FTS5 ranks chunks, with matches in the name worth most, then the signature, then the path, the doc and the body.
2. **Vectors.** The query is embedded once per model. Each vector type returns its top chunks. A chunk with several windows counts its best window.
3. **Fusion.** Reciprocal rank fusion (RRF): every list gives each chunk `1 / (60 + rank)`, and the sums decide.
4. **Weights and filters.**
   - By default, the fused score of test code, classes and blocks is halved (`test_weight = 0.5`, `kind_weights = {class = 0.5, block = 0.5}`). They are useful context, but rarely what a query is about, and on dev they crowded out the target functions. A weight moves only the chunks it targets, so nothing is hidden (decisions-v2.md, D12).
   - Optional filters: `path_prefix`, `kinds` (for example only functions and methods), `languages`, and `test_weight = 0` (drops test code).
   - A filter removes chunks from every signal's list *before* fusion, which can reorder the rest. A weight applies after fusion. So prefer weights unless something must never be shown.
5. **Cards.** Ties are ordered by location, never by internal ids, so the same code gives the same order on every machine. Each result becomes a short card:

```
1. auth/sessions.py:19-20  revoke_session  [id 17]
   def revoke_session(session_id):
   |     db.sessions.delete(session_id)
```

*Example:* BM25 alone cannot find `revoke_session`, since no words are shared. But its usage
text mentions `disable_user` and `test_disabled_user_loses_sessions`, so the usage vectors rank
it high, and RRF carries it into the top results.

For a long function the card adds `best 245-302` and shows the lines that match the query, not
the top of the function.

## 8. Keeping the index fresh

`Indexer.update()` is the only way to index. A full build is an update over an empty index.
Each update:
1. Finds changed files by mtime and size, then by content hash.
2. Re-chunks only those files, and matches old and new chunks by **key** (`path::qualname`). Unchanged chunks keep their ids.
3. Recomputes the call graph (cheap) and every text, and stores vectors only for texts whose hash changed.

So renaming `disable_user` re-embeds:
- the renamed function
- `revoke_session`'s **usage** text (its caller's name changed)

and not `revoke_session`'s code.

- **The watcher** (watchdog) calls this about 0.4 s after the last save.
- **The MCP server** runs a catch-up update at startup, in the background: the handshake is never blocked, and search answers "indexing, X% done" until it finishes.

## 9. Front-ends: how an agent uses it

One command provides both the CLI and the MCP server:

| Command | Purpose |
|---|---|
| `codemem init --agents claude,cursor,codex` | registers the MCP server (`.mcp.json`, `.cursor/mcp.json`, a printed Codex snippet), then indexes |
| `codemem index` / `search` / `status` / `watch` | for humans, scripts and debugging (`--json`, `--debug` for per-signal ranks) |
| `codemem mcp` | what agents launch, over stdio |
| `codemem languages` | lists supported languages and extensions |

The MCP server exposes three tools:
- `search_code(query, k, path_prefix)`
- `get_chunk(ref)`: full code plus callers and callees. A long class returns its skeleton and member list.
- `index_status()`

All agent-facing wording (tool descriptions, server instructions, notes for `CLAUDE.md`) lives in
`prompts.py`, at three steering strengths for the agent study.

## 10. How the eval harness uses it

The eval harness (`eval/`, cmeval) talks to codemem only through
`eval/src/cmeval/adapters/codemem.py`:
- it builds or updates an index for each task's commit
- it searches with each task's issue text
- it grades the returned **line ranges** against the fix

Things that keep this honest:
- **Index sharing.** `Config.index_settings()` lists every setting that changes the index. Systems that differ only in search-time settings (signals, filters, weights) share one index. Systems that differ in anything else get their own.
- **Determinism.** Updates and rebuilds must give the same results (the harness checks this). Ties never depend on ids.
- **Fair ruler.** The harness's gold labeler is a separate implementation, so a codemem bug cannot hide itself.

Configs:
- `eval/configs/codemem-v2.toml`: v2's search-time variants, one index
- `eval/configs/codemem-v2-ablations.toml`: index-time ablations
- `eval/configs/baseline-v2.toml`: everything, plus the grep baselines

## 11. Performance notes

- **Indexing time is almost all embedding.** Chunking and SQLite take seconds even for large repos.
- **Large repos** (vLLM, Kubernetes, the Linux kernel) need a CUDA GPU for the first build: a 0.5B model on an M1 runs roughly one function every few hundredths of a second. Updates after that are small.
- **Speed knobs** while developing:
  - `embedding_dim` (search speed and memory)
  - `max_seq_length` (indexing speed)
  - the vector cache (rebuilds)
  - `CODEMEM_MODEL=fake` (no model at all)
- **Search** costs one query embedding (about 30–100 ms on a laptop GPU) plus exact vector search, which is fast below about a million vectors.

## 12. Module map

| Module | Role |
|---|---|
| `config.py` | settings, paths, `index_settings()`, defaults for ignore rules |
| `schema.py` | the `Chunk` record |
| `languages/` | one spec per language + registry (`language_for_path`, `supported_languages`) |
| `chunker.py` | the generic tree-sitter walker |
| `tokenize.py` | code-aware tokenization, shared by indexing and queries |
| `callgraph.py` | name-based call resolution (replaceable) |
| `texts.py` | text builders (`code`, `usage`, `summary` slot) and windows |
| `embedder.py` | `Embedder` interface, jina via sentence-transformers, `FakeEmbedder` |
| `vectorcache.py` | the shared content-addressed vector cache |
| `store.py` | SQLite + derived FAISS, filters, recovery |
| `indexer.py` | full and incremental updates |
| `search.py`, `render.py` | hybrid search and cards |
| `service.py` | long-lived owner of an index: background updates, progress, watcher |
| `watcher.py` | watchdog + debounce |
| `server.py`, `cli.py`, `prompts.py`, `agents.py` | MCP server, CLI, agent-facing text, agent registration |

## Glossary

| Term | Meaning |
|---|---|
| **chunk** | one searchable unit: a function, method, class or block of top-level code |
| **block** | consecutive top-level statements between definitions (imports, constants, module code) |
| **skeleton** | a class's outline: its header plus one line per member |
| **vector type** | one kind of text that gets embedded (`code`, `usage`); each is its own vector set |
| **part / window** | one embedded piece of a long text; a chunk scores by its best part |
| **BM25** | keyword ranking: shared words count, rare words count more |
| **embedding** | a list of numbers capturing meaning, so similar meanings are close even with no shared words |
| **RRF** | reciprocal rank fusion: merges ranked lists by summing `1 / (60 + rank)` |
| **Matryoshka** | embeddings whose first numbers work on their own, so vectors can be shortened |
| **embedder key** | the identity of an embedding space (model, prompt, length, dtype, device) |
| **MCP** | the protocol coding agents use to call tools |
