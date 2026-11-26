# codemem data model and contracts

The exact formats and interfaces, for anyone changing codemem, its eval, or an integration with an
agent:
- what each stored record holds, and the rules for keys, line numbers and hashes (§1–§9);
- the version stamps that must change when a format does (§10);
- what can grow without breaking indexes (§11);
- the interfaces other code relies on: the MCP tools, the eval adapter, the configuration, the
  plugin classes and the embedding server (§12).

How the system works, and why, is in [architecture.md](architecture.md).

| Part | Code |
|---|---|
| chunks | `schema.py` |
| how chunks are cut | `languages/` and `chunker.py` |
| what gets embedded | `texts.py` |
| storage | `store.py` (SQLite and the search index) and `vectorcache.py` |
| the embedding server | `embedserver.py` |

---

## 0. The running example

```python
# auth/sessions.py
def revoke_session(session_id):          # line 19
    db.sessions.delete(session_id)       # line 20

# auth/users.py
def disable_user(user):
    ...
    revoke_session(sid)                  # disable_user calls revoke_session

# tests/test_users.py
def test_disabled_user_loses_sessions():
    disable_user(user)                   # a test calls disable_user
```

The issue is *"Disabled users stay logged in"*. `revoke_session` shares no words with it; its
callers do. That is why codemem stores the call graph next to the code.

---

## 1. The picture

```
repo file ──► File row (status + reason)
   │
   └─ tree-sitter ──► Chunks (function | method | class | block)
                         │
                         ├─ Calls (callee names seen in the chunk) ──► Edges (resolved: caller → callee)
                         ├─ FTS row (5 BM25 fields)
                         └─ Texts per vector type ──► Parts ──► Vector rows (float16) ──► search index (derived)

 Queue rows (dirty_texts): chunks whose texts may be out of date, written by stage A, cleared by stage B
```

| Record | One per | Notes |
|---|---|---|
| File | file the walk saw with a supported extension | skipped files included, with a reason; partly parsed files are marked |
| Chunk | thing a search can return | |
| Call | distinct callee name in a chunk | unresolved |
| Edge | caller–callee pair | resolved |
| Vector row | embedded text part | |
| Queue row | chunk whose texts may be out of date | the to-do list from stage A to stage B (§8) |
| Search index | vector type | in memory, rebuildable at any time from the vector rows |

---

## 2. File

| Field | Meaning | Example |
|---|---|---|
| `path` | repo-relative, forward slashes | `auth/sessions.py` |
| `language` | from the extension; `.h` is sniffed (C unless it uses C++ syntax) | `python` |
| `content_hash` | sha256 of the bytes, first 20 hex chars | `9f2c…` |
| `mtime`, `size` | the quick pre-check: equal mtime and size means unchanged, so the file isn't read | |
| `status` | `ok` or `skipped` | `ok` |
| `reason` | for `skipped`: `too_large`, `generated`, `minified` or `binary`; for `ok`: `parse_errors` when tree-sitter could only partly parse the file (what it recovered is indexed) | `too_large` |

**Which files are read:**
- Every extension of a supported language (`codemem languages`).
- Never read:
  - paths in `.gitignore`;
  - `ALWAYS_SKIP_DIRS` (`.git`, `node_modules`, `.venv`, `build`, `dist`, …);
  - `DEFAULT_IGNORE` (`vendor/`, `*.min.js`, `*_pb2.py`, `*.pb.go`, …);
  - a folder that is a git worktree of the checkout's own repository (architecture.md §4.6). A
    submodule and a repository of another project are read.
- **Stored as skipped with a reason**, so the next scan doesn't read them again:
  - files over `max_file_size` (10 MB);
  - binary files (a NUL byte in the first 8 KB);
  - files marked `Code generated … DO NOT EDIT` or `@generated` (in the first 2 KB);
  - JS/TS files with a line over 5,000 characters.
- **Coverage:** ignored files and files in unsupported languages have no row. They are counted in
  `meta.coverage` (by folder and by extension) at each full check. The worktrees left out are
  counted there too, with up to 10 of their folders.

---

## 3. Chunk

A chunk is what a search returns and what the eval grades by its lines.

### 3.1 Kinds

| `kind` | What it covers | Example in the running repo |
|---|---|---|
| `function` | a named function (nested ones too) | `revoke_session`, lines 19–20 |
| `method` | a function inside a class or impl block, or one qualified by its type (Go receiver, C++ `A::b`) | `Table.delete` |
| `class` | a class-like type: class, struct, interface, enum, trait, union, record | `Table`, lines 4–15 |
| `block` | a run of top-level code between definitions: imports, constants, module statements | `auth/db.py` lines 18–19: `sessions = Table()` |

`subkind` refines the kind:
- **classes:** `class`, `struct`, `interface`, `enum`, `trait`, `record`, …
- **functions:** `constructor`, `destructor`, `macro`, `arrow` (`const f = () => {}`), `assigned`
  (`exports.f = function () {}`), `test_macro` (gtest `TEST(A, B)`)
- **blocks:** `imports` or `statements`

**Not chunks:**
- **Anonymous functions** (lambdas, callbacks). Their lines belong to the enclosing chunk, the same
  rule as the eval's labeler.
- **Declarations without a body** (C prototypes, TS overloads, interface methods). They live in a
  block or in their class's outline.

### 3.2 Fields

| Field | Rule | Example |
|---|---|---|
| `chunk_id` | integer, local to one index, stable while the key is stable | `17` |
| `key` | `path::qualname`; duplicates in a file get `#2`, `#3` in source order | `auth/sessions.py::revoke_session` |
| | blocks: `path::<scope.><block>@<hash8 of the code>` | `auth/db.py::<block>@a41f09c2` |
| `path`, `language` | as for the file | |
| `kind`, `subkind` | §3.1 | `function`, `""` |
| `name` | the definition's own name; for blocks, a label (`imports` or the first line, ≤ 60 chars) | `revoke_session` |
| `qualname` | enclosing scopes and the name, joined by `.` (§3.3) | `SessionManager.expire_old.is_old` |
| `class_name` | innermost enclosing class, receiver or impl type | `SessionManager` |
| `parent_key` | key of the enclosing chunk (class or function), else null | |
| `start_line`, `end_line` | 1-based, inclusive (§3.4) | `19`, `20` |
| `signature` | the definition's text up to its body, on one line | `def revoke_session(session_id):` |
| `docstring` | Python: the docstring. Other languages: the comment block right above (markers stripped) | |
| `lead_comment` | in languages whose docstring is inside the definition (the spec's `docstring_in_code`; Python): the comment lines directly above the definition (no blank line between), markers stripped. Elsewhere those comments are the `docstring` | `Revoke one session; used on logout.` |
| `code` | the exact source lines `start_line..end_line` | |
| `skeleton` | classes only: header plus one line per member (field text or method signature) | `class Table:\n    def insert(self, key, value):` |
| `content_hash` | sha256 of `code`, first 20 hex chars | |
| `is_test` | test file, or a test by its own name or attribute (§3.6) | `false` |
| `calls`, `call_lines` | callee names in first-seen order, and the line of each first call | `["delete"]`, `[20]` |

### 3.3 Qualified names by language

| Language | Scopes that add a qualifier | Example |
|---|---|---|
| Python | classes, enclosing functions | `SessionManager.expire_old.is_old` |
| JS / TS | classes, TS namespaces, enclosing functions | `SessionManager.expireOld.isOld`, `Auth.inner` |
| Go | the method's receiver type | `Manager.ExpireOld` |
| Java | classes (nested ones too) | `SessionManager.Inner.helper` |
| C | none | `revoke_session` |
| C++ | namespaces, classes, out-of-line `A<T>::b` (template arguments dropped) | `auth.SessionManager.ExpireOld` |
| Rust | `mod`, `impl` type (`impl Trait for T` gives `T.m`) | `Manager.expire_old` |

### 3.4 Line rules

These match the eval labeler for Python (identical scores at IoU 0.3/0.5/0.7 on dev50). For the
other languages they are codemem's own rule, written down so the labeler can cross-check them
independently.

- **Lines are counted the way tree-sitter counts them: split on `\n` only.**
- **The range starts at the definition node,** including:
  - decorators (Python decorated definitions, TS member decorators);
  - annotations (Java `modifiers`);
  - attributes (Rust `#[test]`);
  - `export`, `template <…>`, and the whole `const f = …` statement.
- **Leading comments are never in the range,** in any language. Their text goes to `docstring`, or
  to `lead_comment` where the docstring is inside the code (Python). One rule for every language: a
  new language only declares its comment syntax. (A 15-line kernel-doc comment above a 5-line
  function would otherwise halve the IoU.)
- **A node that ends at column 0 ends on the previous line** (the labeler's rule). Examples:
  `#define X 1\n`, `///` comments.

### 3.5 Classes and blocks

- **A class chunk spans the whole class,** matching the eval's class gold exactly. It embeds and
  BM25-indexes its **outline** (skeleton), not its full code: the methods are chunks of their own,
  and would otherwise be duplicated and crowd results.
- **A block is a maximal run of non-definition statements** at module or namespace level, with
  its exact lines:
  - Runs are cut at statement boundaries every `max_block_lines` (200). A single statement longer
    than that is cut by lines, so no block exceeds 200 lines. Piece boundaries depend on the
    content, so an inserted line doesn't re-key every later piece; each piece keeps only its own
    calls.
  - Comments directly above a definition belong to that definition, not to the block.
  - A wrapper that holds definitions (`if TYPE_CHECKING:`, `try/except ImportError`, `#ifdef`,
    `extern "C"`) is opened. Its definitions become chunks and its other statements become blocks.
    A wrapper without definitions is an ordinary statement.

### 3.6 Tests

`is_test` is true when the path is a test path, or the definition is a test by name or attribute:

| Language | Test files | Test definitions |
|---|---|---|
| all | a directory `tests/`, `__tests__/`, `testdata/`, `spec/` or `specs/` anywhere; `test/` or `testing/` at the top or under `src/` (so `django/test/` is code) | |
| Python | `test_*.py`, `*_test.py`, `conftest.py` | name `test_*` or `test` |
| JS / TS | `*.test.*`, `*.spec.*`, `__mocks__/` | (file rule only) |
| Go | `*_test.go` | `TestX`, `BenchmarkX`, `FuzzX`, `ExampleX` |
| Java | `*Test.java`, `*Tests.java`, `*IT.java`, `Test*.java` | `@Test`, `@ParameterizedTest`, … |
| Rust | `*_test.rs` | `#[test]`, `#[tokio::test]`, `#[rstest]` |
| C / C++ | `*_test.c(c/pp)`, `*_unittest.cc`, `test_*.c(c/pp)`, `*Test.cpp` | gtest `TEST`, `TEST_F`, `TEST_P`, … |

### 3.7 Unchanged, moved or changed

When a file is re-chunked, each new chunk is matched to the old one with the same key:
- **unchanged:** every stored field except its id and position is equal (key, path, language,
  kind, subkind, name, qualname, class, parent, signature, docstring, lead comment, content hash,
  outline, test flag). It is left alone.
- **moved:** the same, but its start and end lines both shifted by the same amount. Only its line
  numbers (and those of its calls) are updated. If moved chunks changed their order, they count as
  changed, because usage texts list callers by line.
- **changed** or **new:** written in full, relinked, and queued for stage B.

---

## 4. Calls and edges

- **Call** `(caller_id, callee_name, line)`: one row per distinct callee name in a chunk.
  - The line is the first call site, and `a.b.c()` counts as `c`.
  - Python decorators count for the decorated function.
  - Calls inside nested named definitions count for those definitions.
  - Indexed by `callee_name`, so "every call to name X" is one lookup.
- **Edge** `(caller_id, callee_id)`: a call links to every function, method or class with that
  name **in the same language family** (`c`+`cpp`, `javascript`+`typescript`+`tsx`; the other
  languages alone).
  - Names defined more than `max_defs_per_name` (5) times are not linked (`get`, `run`).
  - Self-calls are dropped.
  - Indexed by caller and by callee, so both directions are one lookup.
- **The heuristic lives in one function,** `callgraph.resolve_edges`. It can be replaced by
  import- or scope-aware resolution without touching anything else.
- **Blocks can be callers** (a `describe(...)` block in a JS test file), but never callees.
- **What an edit can change:**
  - the edges *from* the changed files' chunks;
  - the edges *to* any name whose set of definitions changed (added, deleted, or crossing the
    five-definitions limit).

  Nothing else.

---

## 5. Texts and vectors

### 5.1 Vector types and their texts

Each vector type is embedded separately into its own vector set, and its signal can be switched
on and off at search time (`--signals bm25,code,usage`).

**`code`:** a context header in the language's comment syntax, then the doc text, then the code.
The doc text is the comment block above the definition: its `docstring`, or its `lead_comment`
where the docstring is inside the code (Python). A class uses its outline instead of its code.

```
# auth/sessions.py
def revoke_session(session_id):
    db.sessions.delete(session_id)
```

```
// auth/sessions.go
// RevokeSession deletes one session from the store.
func RevokeSession(id string) {
	store.Delete(id)
}
```

- A method's header adds `# in SessionManager`.
- **The header never contains line numbers,** so code moving down a file changes no text and
  re-embeds nothing.
- `code_header = false` turns the header off (an ablation).

**`usage`:** who calls the chunk and which tests reach it. Built for functions, methods and classes
that have callers; never for blocks.

```
revoke_session in auth/sessions.py
called by logout in api/routes.py
called by disable_user in auth/users.py
tested by test_disabled_user_loses_sessions in tests/test_users.py
```

- Up to `max_items` (20) lines, with half the room kept for tests.
- Callers are sorted by path, then line.
- A caller that is a block is written `called at top level in <path>` (or `tested in <path>`).
- With `include_commits`, the subjects of the file's recent commits are added
  (`changed in commit: ...`).
- It depends only on the chunk's own name and path and on its callers. **So an edit in file A can
  change only the usage texts of what A's chunks call, plus A's own.**

### 5.2 Parts (windows)

- A `code` text longer than `window_chars` (default 3 × (`max_seq_length` − 32) = 2,976
  characters) is split into windows of whole lines, overlapping by `window_overlap_lines` (3).
- Each window repeats the header plus `# part i/n`. Windows after the first also carry the chunk's
  one-line signature: `# part 2/3 of def extract_precompiled_and_patch_package(...)`.
- The number of windows is chosen first, then the lines are split evenly, so no window is a tiny
  leftover.

### 5.3 Vector row

| Field | Meaning |
|---|---|
| `vector_id` | the search index's id; never reused |
| `chunk_id`, `vec_type`, `part`, `n_parts` | which text of which chunk; unique on `(chunk_id, vec_type, part)` |
| `start_off`, `end_off` | lines this part covers, **relative to the chunk's start line** |
| `text_hash` | sha256 of the embedded text, first 20 hex chars |
| `embedder` | the embedder key (§5.4) |
| `dim`, `data` | the vector at the model's full size, float16 |

- **A chunk's score for one vector type is the maximum over its parts.** The card reports that
  part's lines as `best_lines`.
- **The shape is deliberately multi-vector.** Line- or token-level vectors (advanced-design.md)
  would be more rows of the same table, scored by a different aggregation.

### 5.4 Embedder key

The identity of an embedding space. Equal keys mean interchangeable vectors; a different key
re-embeds that vector type only.

| Embedder | Key | Example |
|---|---|---|
| local | `model[#version] \| doc \| L<max_seq_length> \| <dtype> \| <device>` | `jinaai/jina-code-embeddings-0.5b\|doc\|L1024\|float16\|mps` |
| API, by its address | `api:<host> \| <model> \| dims=<d> \| doc=<hash of the document prefix>` | `api:api.studio.nebius.com\|Qwen/Qwen3-Embedding-8B\|dims=1024\|doc=0` |
| API, by its `space` | `api:<space> \| <model> \| dims=<d> \| doc=<hash of the document prefix>` | `api:st-L1024-float16-mps\|jinaai/jina-code-embeddings-0.5b\|dims=full\|doc=861b2167` |
| plugin | `model[#version] \| plugin=<module:Class> \| L<max_seq_length> \| <dtype> \| <device>` (dtype and device as configured) | `/models/enc#3fa2b1c9d0e1\|plugin=mypkg.embed:MyEmbedder\|L1024\|auto\|auto` |
| fake (tests) | `fake:<dim> \| doc` | `fake:64\|doc` |

- **The weights version** (`#version`) is `vectors.<type>.version` if set, else, for a model in a
  local folder, the first 12 hex characters of a sha256 over every file's relative path and
  content (dot files and folders skipped), else nothing. A model named on Hugging Face has none.
- **An API's key holds who serves the vectors:** `[embedding] space` when it is set, else the host
  and port of `base_url`. `<d>` is `dimensions`, or `full`; the document prefix is the first 8 hex
  characters of its sha256, or `0` for none. With a `space`, the address is in no part of an
  index's identity, so configurations that differ only in `base_url` use the same vectors.
- **The precision and the device of a local key** are the ones the model runs in. The weights
  are converted to `<dtype>` when the model is loaded, whatever the model's file stores; `auto`
  gives float16 on a GPU and float32 on a CPU.
- **Not part of the key:** `embedding_dim` (applied when the search index is built, so changing
  it re-embeds nothing), the query prefix (it only affects queries), and the API key.

### 5.5 Reuse

Before calling the model for a text, codemem looks for `(embedder key, text_hash)`:
1. in this index (the same text elsewhere in the repo);
2. in the shared **vector cache**, `$CODEMEM_HOME/cache/vector_cache.db` (§7), which holds the
   vectors computed on this machine. Past its size cap the least recently used ones are deleted;
   a text whose vector was deleted goes to the model again. A vector found there and a vector put
   there both count as used.

`IndexStats` reports `embedded` (vectors written for changed texts), `model_embedded` (of which the
model computed), `reused` and `cache_hits`; and, for the structure, `chunks_added`,
`chunks_updated`, `chunks_moved`, `chunks_deleted`, `relinked` and `queued`. `vector_cache = "off"`
or `--no-cache` turns the shared cache off (for cold timings).

---

## 6. BM25 fields

Each chunk has one FTS5 row. Every field is pre-tokenized by `tokenize.py`: identifiers are split,
the whole identifier is kept too, and everything is lowercased. SQLite matches the weights to the
columns **by position**, so the column order in the table, in `upsert_chunk` and in `BM25_FIELDS`
must stay the same.

The table keeps the word lists and each row's length, but no copy of the text (`content = ''`):
search reads only scores and row ids. Removing a row, when its chunk changes or goes, passes the
five fields again, recomputed from the chunk row before it changes (`Store._fts_fields`). They
must come out exactly as when they were added, so the token options are index settings and a
change to `tokenize.py`'s output bumps `SCHEMA_VERSION`.

| # | Field | Content | Weight |
|---|---|---|---|
| 1 | `name` | qualname + name | 10 |
| 2 | `path` | the file path | 3 |
| 3 | `signature` | signature | 5 |
| 4 | `doc` | docstring / doc comment, plus `lead_comment` | 2 |
| 5 | `body` | code (classes: the outline) | 1 |

- A 3-value weight list `(name, signature, body)` from older configs is accepted. It maps to
  `(name, 0, signature, body, body)`.
- **Query side only:** stopwords are dropped (`[bm25] query_terms = 0` keeps every word). With
  `common_share` above 0, a query longer than `query_terms` words also drops the words found in
  more than that share of chunks, using document counts from the `fts_vocab` table. The stored
  rows never change.

---

## 7. On disk

```
<index dir>/                         default ~/.codemem/indexes/<repo>-<hash8 of the repo path>/
  index.db                           SQLite (WAL): meta, files, chunks, fts (word lists only, + fts_vocab), calls, edges, vectors,
                                     dirty_texts (the queue)
  vec_code.faiss, vec_code.json      a saved copy of the search index + a note {epoch, dim, count, embedder,
  vec_usage.faiss, vec_usage.json    database, save_id, backend, file, crc32}; another backend saves
                                     vec_<type><suffix>, or nothing.
                                     `database` is the `database_id` of the index.db the copy was saved from.
                                     `save_id` is a random token of the save, also in `meta` (§8).
                                     `crc32` is the checksum of the copy's file, whatever the backend.
                                     `backend` is the search index the file holds (`faiss`, `compact` or a
                                     plugin's name), whether a configuration named it or `auto` picked it.
                                     `file` is the copy's name: vec_<type><suffix> of that backend, and
                                     nothing else (§8).
                                     FAISS files hold an IndexIDMap2 over an fp16 IndexScalarQuantizer
                                     (inner product, 2 bytes per number); a file of 4-byte numbers
                                     (IndexFlatIP) is converted when loaded
  vec_code.rabitq, vec_usage.rabitq  the compact index's copy, and in its note `options`: the [compact]
                                     table it was made with. The file is one line of JSON {dim, code_dim,
                                     bits, count, rotation, index_bytes, crc32}, then `count` vector ids
                                     (8 bytes each, little-endian), then one FAISS IndexRaBitQ (inner
                                     product, centre zero) of the 1-bit codes and, when `bits` is above 1,
                                     a second one of the `bits`-bit codes. Each holds one code per id, in
                                     the order of the ids, and `index_bytes` lists their sizes. `rotation`
                                     names the rotation the codes were made after, and `crc32` is the
                                     checksum of everything after the first line
  write.lock                         one writer at a time (OS file lock)
  worktree.json                      only in the default index folder of a linked git worktree:
                                     {"worktree": its folder, "repository": the git folder its checkouts share};
                                     the folder is deleted once that worktree is gone (decisions.md §6)
$CODEMEM_HOME/cache/vector_cache.db  shared vector cache: (embedder key, text_hash) -> float16 vector (below)
$CODEMEM_HOME/model_hashes.json      each local model file's [size, mtime_ns, sha256], so it is read once
```

**The vector cache file** is SQLite (WAL) with pages of 32 KB, `auto_vacuum = INCREMENTAL` and
`user_version` 1. A file whose `user_version` differs is not read or written.

| Table | Columns | Holds |
|---|---|---|
| `embedder` | `id`, `key` (unique), `dim` | one row per embedder key (§5.4), with the length of its vectors. A vector of another length is not stored under that key |
| `entry` (no rowid) | `embedder`, `hash`, `slot`, `used`; primary key (`embedder`, `hash`); index `entry_used` on `used` | one row per cached vector: where it is, and when it was last used (Unix seconds) |
| `vec_<embedder id>` | `slot` (the rowid), `hash`, `data` | the vectors of one embedder, each as `dim` float16 numbers, in slots 1..n without gaps |

- **`hash`** is the text hash (§5.3) as bytes: its 20 hex characters become 10 bytes. A key that
  is not lowercase hex in pairs is stored as the text it is.
- **Slots stay 1..n.** When entries are deleted, the rows in the last slots are written into the
  freed ones, and `entry.slot` follows in the same transaction. A slot number is therefore only
  good inside one statement: readers go from key to vector in a single query.
- **`used`** is set when the entry is put, and again when it is found or marked, at most once per
  day (UTC).
- A file `$CODEMEM_HOME/cache/vectors.db` with one table `cache(embedder, text_hash, dim, data)`
  is imported when the cache is opened, and then deleted, unless rows were added to it during
  the import.

`meta` keys:
- `schema_version` (3);
- `database_id`: a random token that names this database file. The store sets it when it opens a
  database that has none; a copy made to start another index drops the row and so gets its own;
- `repo_path`, `indexed_commit`, `indexed_at`;
- `codemem_version`, `index_settings`, `last_update` (the last `IndexStats`);
- `coverage`: ignored and non-code counts, and `worktrees`: how many git worktrees inside the
  checkout the scan left out (`count`), and up to 10 of their folders (`examples`);
- `last_scan_at`: when the last full check started (files saved within 2 s of it are re-hashed next
  time);
- `dirty_seq`: the queue's sequence number, one per stage-A commit;
- `cache_marked_day`: the day (days since 1970, UTC) on which this index last marked the vectors it
  holds as used in the vector cache, so that it does so once a day (§7);
- per vector type: `vec.<type>.embedder`, `vec.<type>.full_dim`, `vec.<type>.dim_setting`,
  `vec.<type>.epoch`, and `vec.<type>.save_id`: the random token of the last save of that type's
  search index, which the saved copy's note holds too (§8).

**An index that starts as a copy** of another checkout's (architecture.md §4.6) is that
`index.db` as one SQLite backup, with every `files.mtime` set to 0 and without the `meta` rows
`indexed_at`, `last_scan_at`, `last_update`, `coverage` and `repo_path`. `vec_*` files that an
index deleted by hand left in the folder are removed first: a saved search index is matched to
the vector rows by id, and the copy has another index's ids. An index without
`indexed_at` has not been compared with its checkout's files yet, and one that has rows all the
same is such a copy: it holds the other checkout's code. `codemem search` asks for
`codemem index` first. The MCP server's `search_code` and `get_chunk` wait for the first full
check within `catchup_budget_ms`; past that they answer from the copy, with a note that says so
(§12.1).

The eval harness writes its own marker files into the index folder. codemem never deletes files
it doesn't own.

---

## 8. Consistency and recovery

- **SQLite is the source of truth.** A vector row is committed in the same transaction as its
  bookkeeping.
- **The search index is derived. It is kept correct by these rules:**
  1. every transaction that changes a vector type's rows bumps `vec.<type>.epoch`;
  2. the in-memory index is patched only after the commit, and its epoch is set last;
  3. an index that is behind catches up by vector id: vector rows never change in place (a new
     vector is a new row, and ids are never reused), so the ids missing on either side are the
     whole difference. This applies to a saved copy (used if its database, dim, embedder, backend
     and backend options match, whatever epoch it was saved at; a note without `backend` counts
     as FAISS) and to another process's writes.
  4. a saved copy is read only into the database it was saved from. Its note names that
     database's `database_id`; a note that names another, or none, means a rebuild from the rows.
     Vector ids start again at 1 in a new `index.db`, so the copy of a deleted one would match
     other vectors by id.
  5. a saved copy is read only if its bytes are the bytes that were saved. Its note holds their
     CRC-32, which is compared before the backend is given the file. A file that differs (damaged,
     cut short, or another index's file under this note), or a note without a checksum, means a
     rebuild from the rows. A file that differs is also a warning in the log.
  6. a saved copy is read only by the state of the database it was saved from, or a later one.
     Each save writes a random `save_id` into the note and into `meta` (`vec.<type>.save_id`),
     and commits it after the index was copied. A note whose `save_id` is not the one in `meta`,
     or a note without one, means a rebuild from the rows. That is the case after `index.db` was
     put back from a copy, or lost its last commits in a power cut: such a database hands out
     again the vector ids of the rows it lost, and its epoch counts up again.
  7. a note never chooses a file. A start reads, and a save or the removal of a vector type
     deletes, only `vec_<type><suffix>` in the index folder, the suffix being that of the note's
     backend. A note whose `file` is anything else (a path, another file of the folder), or one
     that is not a JSON object, counts as no note.
- **Which search index** (`vector_backend`): the one a configuration names, or for `auto` the
  exact index while the exact indexes of every vector type fit the budget together
  (`vector_memory_mb`), and the compact one for every type when they do not (architecture.md §5).
  - `auto` picks when the first search index of a process is loaded or built, and the pick holds
    while the store is open;
  - an index whose saved copies are compact goes back to exact only under 80% of the budget. The
    copies that count are those of the vector types that have vectors;
  - where the installed FAISS cannot make the compact index, `auto` picks the exact one.
- **Loading the search index:**
  - a vector type's index is read from its saved copy, or rebuilt from the rows when the copy
    cannot be used (rules 3 to 7, or no copy);
  - loading holds no lock. One thread loads a type; the others that need it wait for that thread.
    Rows written meanwhile are applied when the index is installed, by vector id;
  - a write to a type whose index is not in memory does not load it: the index is loaded at its
    first use, from rows that include the write. A type's first vectors start its index;
  - the MCP server loads the search indexes in the background when it starts. A search that
    comes before they are in memory waits within `catchup_budget_ms`, then answers from keywords
    alone with a note (§12.1); the CLI and the eval wait for the index.
- **Saving the search index:**
  - the data is written under a temporary name. One short transaction then writes the save's
    `save_id` into `meta`, renames the data file into place and writes the note, also by a
    rename. A save that is stopped leaves the earlier copy, or one that fails rule 5 or 6. The
    transaction waits its turn like any write to `index.db`, and keeps two processes' saves apart;
  - Windows refuses a rename while another handle holds the file open (a second codemem process
    that reads the saved copy at its start, a virus scanner). Each of the two renames is then
    tried again, six times within 0.6 s, before the save fails;
  - a save that fails (a full disk, or 30 s without its turn behind another process's write) is
    logged and given up. The server's writer goes on, the earlier copy stays what a start reads,
    and the next change to the index is saved again;
  - the MCP server saves lazily (after 30 s idle, on shutdown, on refresh), while the CLI and the
    blocking `update()` save at once;
  - an update that saves (`update()`, the CLI) first makes the saved copies what the next start
    reads: `auto` picks again, and a type whose copy is missing, behind the rows or another
    backend's is loaded or rebuilt, and saved. The saved copy of another backend is removed;
  - the index is copied while holding the lock and written after releasing it, so searches don't
    wait;
  - a backend that returns no bytes is not saved; it is rebuilt from the rows at each start;
  - the compact backend's file is read only if its checksum, its options and its rotation are the
    ones expected, its ids are in order, and the FAISS indexes inside are the ones its first line
    describes. Anything else is rebuilt from the rows.
- **The queue (`dirty_texts`: chunk id, sequence number).** Stage A writes a row for every chunk
  whose texts may have changed, in the same transaction as the change. Stage B rebuilds those
  texts, embeds the changed ones, and deletes a row only if its number is unchanged (a chunk edited
  again meanwhile stays queued). A crash between the stages leaves the rows, so the next start
  finishes the work. "Is anything pending?" is a count of this table.
- **Settings check:** at each update, `meta.index_settings` is compared with the current
  `Config.index_settings()`. A difference redoes only what that setting affects: vectors (re-embed
  that type), texts (rebuild every text, re-embed the changed ones), links (relink every call), or
  a rebuild (chunker version, file selection, BM25 tokenization, block size; vectors of unchanged
  texts come back from the cache). `vector_backend`, `vector_memory_mb` and the `[compact]`
  options redo nothing stored: the search index rebuilds itself from the rows. Without this check, a chunker or text
  change would never reach files that don't change.
- **What goes wrong, and what happens:**
  - A crash before saving: the saved file is behind and catches up by id at the next load. A corrupt
    or missing file is rebuilt from the rows. No model call, no re-embedding, either way.
  - A process sees an epoch change made by another process: it catches up by id before searching.
  - `index.db` goes back to an earlier state under a search index that was saved later: the two
    `save_id`s differ, and the index is rebuilt from the rows.
  - FAISS fails in the middle of a change to a compact index: the index is left as it was before
    the change, and the write raises after its commit. The index is then one epoch behind, and
    catches up by id before the next search.
  - Another process deletes vectors while a compact index is searching: the rows it can no longer
    read are left out of the result, and the search takes more candidates to fill it.
- **Large deletions** give pages back to the OS (`auto_vacuum = INCREMENTAL`).

---

## 9. Identity across edits and commits

What stays the same when code changes, and what is recomputed:

| Change | Chunk key | Texts | Re-embedded |
|---|---|---|---|
| lines added above `revoke_session` | same | same (no line numbers in texts) | nothing |
| body of `revoke_session` edited | same | its code text | its code vector |
| the comment above a Python function edited | same | its code text (the doc text) | its code vector |
| `revoke_session` renamed everywhere (4 files) | old key deleted, new key added | changed files' code texts; the new name's usage; callees' usage (`Table.delete`) | 9 of 33 texts in the sample repo (measured) |
| file moved | new keys | changed (the header has the path) | the file's chunks, plus what they call (usage) |
| a block edited | new key (content hash) | changed | that block |
| `embedding_dim`, `vector_backend`, `vector_memory_mb` or a `[compact]` option changed | same | same | nothing (the search index is rebuilt, when the change gives it another form) |

---

## 10. Version stamps

| Stamp | Where | Changes when | Effect |
|---|---|---|---|
| `SCHEMA_VERSION` (4) | `store.py` | tables or columns change, or `tokenize.py`'s output does | an older index is wiped and rebuilt, with a warning (cheap with the vector cache); a newer one is refused, never wiped |
| `CHUNKER_VERSION` (2) | `config.py` | chunking changes (kinds, ranges, keys, calls) | part of `index_settings()`: the index is rebuilt, with vectors of unchanged texts from the cache |
| `TEXT_FORMAT_VERSION` (3) | `config.py` | a text builder's output changes | part of `index_settings()`: every text is rebuilt and the changed ones re-embedded, and the eval keeps the indexes apart |
| embedder key | `embedder.py` | automatic: another model, weights, settings or device | the vector type with a new key is re-embedded |
| weights version | `config.model_version` | automatic for a local model folder, or set `version` | part of the model id and the embedder key |
| `vector_backend` | config | another search index | in `index_settings()` only when it is not `auto`: an index built before there was a choice keeps its settings, and the eval keeps systems that name a backend apart; nothing is re-embedded |
| `[compact]` (`bits`, `dim`, `rescore`) | config | other codes, or another number of candidates | in `index_settings()` as `compact`: only the options that differ from their defaults, and only when the backend is `auto` or `compact`; nothing is re-embedded |
| `vector_memory_mb` | config | another budget for `auto` | search-time: not in `index_settings()`; the search index is picked again, and rebuilt if the pick changes |
| the vector cache's `user_version` (1) | `vectorcache.py` | the cache file's tables or page size change | a cache file with another number is left untouched and counts as unavailable: vectors come from the model |

`Config.index_settings()` lists every index-time setting. The eval adapter hashes it, with the
codemem version and the device, into its `index_key`, so two systems share an index only when
nothing that changes the index differs. Defaults add nothing to it, so existing indexes and their
eval keys stay valid when a new option appears.

---

## 11. What is fixed, and what can grow

**Fixed** (changing these breaks eval comparability or stored indexes):
- the kinds and their names;
- the line rules;
- the key rules;
- the vector row shape (one row per part, float16 at full size);
- the embedder-key semantics.

**Can grow without a schema change:**
- **new vector types**, such as anchors (call-site lines, commit messages, past issues): each needs
  a text builder and nothing else;
- **new embedders and search indexes**, as plugins named in the config (§12.4);
- **new part schemes:** line- or token-level vectors;
- **new aggregations:** max, MaxSim, top-k mean.

**Needs a schema change:**
- typed edges (`imports`, `inherits`, `tests`);
- stored call-site lines for anchor text (today only the first call line is kept).

---

## 12. Contracts

### 12.1 MCP tools (what agents rely on)

The tool names stay stable, so other front-ends can be compared.

| Tool | Arguments | Returns |
|---|---|---|
| `search_code` | `query: str`, `k: int = 10` (capped at 50), `path_prefix: str \| None`, `kinds: list[str] \| None`, `tests: "include" \| "exclude" \| "only"`, `names: list[str] \| None` (function, class, method or file names the caller knows or guesses: a fourth list of the merge, by keywords alone; without them the search is unchanged) | numbered cards (below), each naming its closest callers and callees, then the next results by name, and a closing `Note:` when the search could not include every save or embedding. An opening `Note:` while a new index is being built, or is still a copy of another checkout's |
| `get_chunk` | `ref`: a chunk id, `path:line` or `path::qualname` | the full code (a class of 80 lines or more: its outline and members), plus callers and callees as `name (path:lines)`. An opening `Note:` when it is read from a copy of another checkout's index that is not checked yet |
| `index_status` | none | state and progress, counts, models, local or remote embeddings, an assist endpoint and whether it shares the work or why not, whether the embedding model is in memory, the search index in use (exact or compact, why, and about how much memory each vector type takes), the indexed commit, staleness, pending files and chunks, whether the watcher works, coverage (skipped files and why), the last error |
| `refresh_index` | none | runs a full check now and waits up to 60 s for embeddings: `Checked every file in 0.5 s: 2 files changed, ...` |

**A card:**

```
3. auth/sessions.py:19-20  revoke_session  [id 14]
   def revoke_session(session_id):
   |     db.sessions.delete(session_id)
   related: disable_user (auth/users.py:5), logout (api/routes.py:10), Table.delete (auth/db.py:11)
```

`N. path:start-end  name  [id X]` (a long function adds `best a-b`, its best window's lines), then
the signature (not for blocks), the first doc line, and up to 6 preview lines. Then one `related:`
line: up to `card_relations` (3) of the result's callers and callees, the ones closest to the query
by their stored code vectors, as `qualified name (path:start line)`. A neighbour that is itself one
of the results is not named, nor a callee with more than 100 callers (whose callers are not
followed either), nor a chunk the search's filters leave out. A result with no such neighbour has
no line, and so has every result of a search by keywords alone. In `SearchResponse.to_dict()` each
card has `related`: a list of `chunk_id`, `qualname`, `path`, `start_line` and `relation` (`calls`
or `called by`).

**The next results, by name.** After the cards, a block names the results k+1 to k+M
(`more_results`, 20 by default; 0 for none), one line each, `path:start line  name`, no preview:

```
More results, by name (ask get_chunk for any of them):
auth/users.py:5  disable_user
api/routes.py:1  <imports>
```

They come from the same merge as the cards, in its order, so the cards are those of a search
without them. Each list gives `candidates` (50), so k + M up to 50 is always there in an index with
that many chunks; past that, the block holds what the lists have. `SearchResponse.more` holds them
(`to_dict()`: `more`, each with `chunk_id`, `path`, `start_line`, `end_line`, `qualname`, `kind`,
`subkind`, `name`, `score`). On the 381 vLLM issues (the whole issue as the query, k = 10), search_code's answer is 5,801 characters on average (95th percentile 7,660) without the related names and the next results, and 9,332 (11,713) with both at their defaults; on the 17 vague pandas requests 5,125 (6,865) and 7,967 (9,426).

**The freshness note.** `search_code` catches up first (architecture.md §4): the background writer
applies every save the watcher has seen, then the search embeds the queue, its own keyword results
first and then the newest edits, all within `catchup_budget_ms` (4 s). If something is still
missing, the results end with one line naming it, for example:

```
Note: 3 code chunks in 1 file (auth/sessions.py) are still being embedded: keyword matches for them
are current, ranking by meaning may be out of date. Search again in a few seconds, or use grep for
those files.
```

The parts it can hold: files saved moments ago that are still being indexed; chunks still being
embedded (with the files they are in); or that codemem could not confirm it has seen the latest
saves. `get_chunk` waits for the structure only, so its code, lines and links are current.

**The copy note.** A new worktree's index starts as a copy of another checkout's (architecture.md
§4.6). `search_code` and `get_chunk` wait for its first full check within `catchup_budget_ms`. If
the check has not ended by then, the answer is read from the copy and begins with `Note:
codemem's index for this checkout started as a copy of another checkout's index, ...`: what
follows can be the other checkout's code. A `get_chunk` that finds nothing in the copy ends with
the same note. `CodememService.search()` reports the case as `freshness.unchecked_copy`, and
`get_chunk()` as the key `unchecked_copy` of its answer.

**While something is loading.** While the embedding model is loading when the server starts, or
a search index is still loading, a search waits within the same budget, then answers from
keywords alone with a note; after a model load that failed it answers that way at once. A model
that was freed for being idle (§12.3) is waited for longer, up to 20 s: the first search after an
idle time is slower and has the same results. The CLI and the eval always wait for both.

**When codemem cannot embed.** A model that did not load, or an embedding endpoint that does not
answer, is not a load in progress: the note then says why, `Note: codemem cannot embed right now
(embedding request to 127.0.0.1:8791 failed: ...), so these results come from keyword matching
only. ...`. `CodememService.search()` reports the reason as `models_error`, beside
`models_loading`. A search that waits (`wait_for_models`, the CLI's) raises the error instead:
`embedder.EmbeddingUnavailable` for an endpoint.

**Whether the model is in memory.** `CodememService.status()` has `models_loaded`: true when the
model of every enabled vector type is in the memory of the process that answers, false when one is
not, null when embeddings come from an API. `codemem status --json` prints it, and `index_status`
ends with one JSON line that holds it beside `state`, `progress`, `chunks`, `vectors` and `stale`.
As text it is the line `embedding model: in memory`, or `embedding model: not in this process's
memory (it loads when a search or an update next needs it)`. A `codemem status` command is a
process of its own: its line tells nothing about the model of a running MCP server.

**stdout carries only MCP messages;** logs go to stderr.

### 12.2 The eval adapter (what `eval/src/cmeval/adapters/codemem.py` relies on)

A change to any of these must be made together with the eval:
- `CodememService(repo, index_dir=, config=)`, and its `.repo_root` (the adapter overwrites it),
  `.store`, `.last_error`, `.close()`.
- `.update(full=)`, which returns `IndexStats` with:
  - `.errors`: files that failed to chunk, never silent;
  - `.embedded`: per type; a no-op update gives 0;
  - `.to_dict()`.

  It blocks until the index and its saved search index are on disk, because the adapter measures
  the index folder's size right after. The saved search index is then the one the next start
  reads: under `auto`, the exact one or the compact one, by the size of the index (§8).
- The search index belongs to the service, not to a search: systems that share an index share
  it, and `vector_memory_mb` is read when the service is created. Two systems that should search
  with different indexes name them (`vector_backend = "faiss"`, `"compact"`), which gives each
  its own index key.
- `store.counts()["chunks"]`.
- `search(store, query, config, k=, signals=, debug=True)`:
  - an unknown signal raises `ValueError`; a configured signal with no stored vectors is skipped,
    and `resp.signals` lists the signals actually used (the adapter refuses a run where they differ
    from what it asked for);
  - each card has `path`, `start_line`, `end_line`, `qualname`, `score`, `ranks`, `kind`,
    `chunk_id`, plus `language`, `subkind`, `best_lines`.
- `format_results(SearchResponse(...))`, the card text exactly as the agent sees it; the eval
  counts its tokens.
- `config_from_dict(dict)`, `Config.enabled_vec_types()`, `Config.model_id()`,
  `Config.index_settings()`, `embedder.resolve_device()`, `codemem.__version__`.
  `resolve_device()` answers `cpu` in an environment without PyTorch, whatever it is asked.
- `CODEMEM_MODEL`-style fake models: `fake` and `fake:16` work, and `fake:not-a-number` fails
  indexing.
- `full=True` wipes in place and never deletes the folder, because the eval keeps its marker files
  there.
- An update and a rebuild give the same results (the B4 check).

### 12.3 Configuration

- **Load order, later wins:**
  1. built-in defaults;
  2. `~/.codemem/config.toml`;
  3. `<repo>/.codemem.toml`;
  4. environment variables (`CODEMEM_HOME`, `CODEMEM_DEVICE`, `CODEMEM_MODEL`,
     `CODEMEM_STEERING`, `CODEMEM_VECTOR_CACHE`, `CODEMEM_VECTOR_BACKEND`,
     `CODEMEM_MODEL_IDLE_MINUTES`).
- **Two kinds of settings:**
  - **Index-time:** they change what is stored. They are listed by `index_settings()`, and
    changing one redoes what it affects (§8).
  - **Search-time:** they change only how a query is answered (BM25 weights, RRF, candidates,
    filters, weights, the catch-up budget, steering). Changing one needs no re-index.
- **`[vectors.<type>]`** has `model` (a Hugging Face name or a local folder), `enabled`,
  `embedder` (a plugin, `"module:Class"`) and `version` (a label for the weights). An unknown key
  is refused, and an enabled type needs a text builder (`code` or `usage`). The model id is
  `model[@embedding_dim][#version][+embedder]`: index-time, and unchanged when neither option is
  set.
- **`vector_backend`:** `auto` (the default: the exact index while it fits `vector_memory_mb`,
  the compact one when it does not), `faiss` (exact: every vector in memory), `compact` (small
  codes of each vector in memory, exact scores from the stored vectors) or `"module:Class"` (a
  `store.VectorStore` subclass). Index-time when it names a backend, only so that eval systems
  with different backends don't share an index; `auto` is not in `index_settings()`.
  `CODEMEM_VECTOR_BACKEND` sets it from the environment, for an index that is built in one place
  and opened in another: `auto` picks by the memory of the place it runs in, so the two can
  differ, and every start that begins from the build's files then rebuilds the search index.
- **`[rrf] weights`:** search-time; signal -> weight, 1 for a signal not named. The signals are
  `bm25`, each vector type, and `names`, the keyword list of the names a caller passes apart from
  the query (§12.1); `names = 0` turns that list off.
- **`card_relations`:** search-time; a whole number, 0 or more; the default is 3. How many callers
  and callees each card names (§12.1); 0 names none. The ranking does not depend on it.
- **`more_results`:** search-time; a whole number, 0 or more; the default is 20. How many results
  after the k cards are named, one line each (§12.1); 0 names none. The cards do not depend on it.
- **`vector_memory_mb`:** search-time. The memory, in MB of 10^6 bytes, that the exact search
  indexes of one index may take before `auto` uses the compact one. 0, the default, is 2% of the
  machine's memory, and at least 128 MB. A whole number, 0 or more.
- **The `[compact]` section** is read when the backend is `compact` or `auto`. An unknown key, or
  a value outside its range, is refused when the config is read:

  | Key | Default | Range | Meaning |
  |---|---|---|---|
  | `bits` | 4 | 1 to 8 | bits per number of the fine code, which ranks the candidates. Every vector also has a 1-bit code, which a search scans; at `bits = 1` that is the only code, and the index is at its smallest |
  | `dim` | 0 | 0 to 4,096 | how many numbers of each vector the codes cover (the first N); 0 = as many as the index uses, which is `embedding_dim` or the model's length. A code never covers more than 4,096: at 0, an index of longer vectors codes their first 4,096 and logs a warning when it is made |
  | `rescore` | 200 | 1 or more | candidates scored exactly from the stored vectors: at least this many, and at least 4 for each result asked for |

  Those that differ from their defaults are in `index_settings()` as `compact`, for the same
  reason as `vector_backend`.
- **`vector_cache`:** `global` or `off`. **`vector_cache_max_gb`:** the cache file's size cap in
  GB (10⁹ bytes), a number of 0 or more; 0 means no cap; the default is 8.
  **`vector_cache_max_age_days`:** a number of days, 0 or more; a cached vector that nothing has
  used for that long is deleted; 0 means never; the default is 30. None of them is index-time: the
  cache changes where a vector comes from, never what an index stores.
- **`model_idle_minutes`:** a number, 0 or more; the default is 60. The local embedding model is
  freed after that many minutes in which nothing was embedded, and the next search or save loads
  it again; 0 keeps it in memory. `CODEMEM_MODEL_IDLE_MINUTES` sets it from the environment. It changes no index. A new value in `.codemem.toml`
  applies from the next full check. `codemem serve-embeddings` reads it when it starts, for the
  model it serves (§12.5).
- **The `[embedding]` section** has `provider` (`local` or `openai`), `model`, `base_url`, `space`,
  `api_key_env`, `dimensions`, `query_prefix`, `document_prefix`, `batch_size`, `max_concurrency`
  and `timeout_s`.
  - Index-time (in `index_settings()` as `embedding`, only for an API provider, so local indexes
    keep their settings): provider, model, dimensions, document prefix, and who serves the vectors.
    That is `space` when it is set, and then `base_url` is not among the settings; otherwise it is
    `base_url`, and there is no `space` entry.
  - `space` is a name of 1 to 64 characters with no whitespace and no `|`. It stands for the
    address in the embedder key (§5.4) and in `index_settings()`. Whoever sets it states that
    every address used under the name returns the same vector for the same text.
  - Search-time or operational: the key's variable name, the query prefix, `batch_size`,
    `max_concurrency`, `timeout_s`.
  - The key itself is read from the named environment variable at each request and is never stored.
  - A reply is brought to the configured form before it is stored: with `dimensions`, vectors
    longer than that are cut to their first numbers, and fewer numbers is an error; every vector is
    normalized to length 1.
- **The `[embedding.assist]` section** names an endpoint that embeds part of a build's document
  texts beside the local model (architecture.md §3.5). It needs `provider = "local"`.
  - `base_url`: the endpoint's OpenAI-style address. Empty means no assist, which also switches
    off one that a config file read earlier set.
  - `model`: the endpoint's name for the model. Required with `base_url`.
  - `api_key_env`: the environment variable that holds the key; empty for none.
  - `document_prefix`: put before each text. Left out, it is what the local model puts before a
    document (its `prefixes`). `""` is for a provider that adds the model's prompt on its side.
  - `request`: a table of more fields for the request body, the provider's own. `model` and
    `input` cannot be among them.
  - `batch_size` (32), `max_concurrency` (4), `timeout_s` (30): texts per request, requests in
    flight, seconds per request.
  - A reply's vectors are scaled to length 1 before they are compared or stored. A reply with a
    vector that cannot be scaled, or with another number of numbers than the local model's,
    ends the endpoint's part.
  - The endpoint is sent only texts the local model reads whole (`Embedder.cut`, §12.4).
  - `codemem status [PATH] --check-assist [--json]` compares the endpoint with each local model
    now, without a build, and prints one report per model. It loads a local model unless that
    model's vectors for the probe texts are remembered (decisions.md §6), and sends the probe
    texts only. Exit status 0: the endpoint can share a build's work; 1: it cannot; 2: no assist
    is set. With `--json` the output is a list of objects:
    - `host`, `model`: the endpoint; `local_model`: the model it was compared with;
    - `state`: `sharing`, `refused`, or `resting` when the endpoint could not be reached;
    - `reason`: one sentence, null when it can share;
    - `agreement`: the smallest cosine, null when nothing could be compared; `needed`: 0.99995;
    - `local_vectors`: `"embedded now"` or `"remembered"`;
    - `probes`: for each probe text `probe` (what it is), `characters`, `cosine`, `local_length`
      and `endpoint_length`, the length of the endpoint's vector as it came.
  - None of it is index-time: it is not in `index_settings()`, and the vectors carry the local
    embedder's key (§5.4).
  - An unknown key is refused.
- Every setting and its default: README, "Configuration".

### 12.4 Plugin classes

Named in the config as `"module:Class"` and loaded with `plugins.load_object`.

**An embedder** (`vectors.<type>.embedder`):
- subclasses `codemem.embedder.Embedder`, and is built as `Class(model: str, config: Config)`;
- gives `dim` (a property), `embed_documents(texts)` and `embed_queries(texts)`, each returning a
  float32 array of shape `(len(texts), dim)`; `ready` (a property, default true) may say a model is
  still loading;
- may define `unload(idle_seconds=0.0)`, which frees its model and returns true; the next call
  then loads the model again, and `ready` says false meanwhile. The default does nothing. codemem
  calls it only while no call of the embedder is running and none has ended within
  `model_idle_minutes`, so the class needs no clock or lock for it and can ignore the argument;
- may define `trim(idle_seconds=0.0)`, which gives back what its calls needed besides the model
  (on a GPU, the allocator's cache), keeps the model, and returns true. The default does nothing.
  codemem calls it under the same guard, once after each burst of calls, 5 s after the last one;
- codemem wraps it: it normalizes the vectors, and names them by the plugin key (§5.4). A
  `fake:<dim>` model still wins over a plugin, so tests stay fast.
- to be served by `codemem serve-embeddings` (§12.5) it also gives `embed_texts(texts)`, which
  embeds each text exactly as given, and `prefixes` (a property), the pair of strings it puts
  before a query and before a document. They must agree: `embed_texts([prefix + text])` equals
  `embed_queries([text])` and `embed_documents([text])`. The server checks this at start.
- with an assist endpoint (§12.3) its `prefixes` say what goes before the endpoint's texts, unless
  `document_prefix` is set, and `cut(texts)` says, with one true or false per document text,
  which texts it reads only in part: those are never sent to the endpoint. A class that reads
  every text whole returns false for each. A plugin that does not define `cut`, or gives no
  prefix by either way, gets no help from the endpoint, and `status` says so.

**A search index** (`vector_backend`):
- subclasses `codemem.store.VectorStore`, is built as `Class(dim: int)`, and keeps `dim`;
- gives `upsert(ids, vecs)`, `remove(ids)`, `ids()` (a set) and `__len__`; the vectors it gets are
  already truncated to `embedding_dim` and normalized;
- `search(query, k, allowed_ids=None)` returns at most `k` `(id, score)` pairs, best first, with
  the real similarity as the score (equal scores are ties); fewer than `k` only when no other
  vector qualifies; only ids in `allowed_ids` when it is given. The store does not call it for a
  query of zeros: `Store.vector_search` returns nothing for one;
- saving is optional: `to_bytes()` returns the bytes for `vec_<type><suffix>` (`suffix`, a class
  attribute, defaults to `.vec`) or None, and the class method `from_bytes(data)` reads them back;
- the class method `bytes_per_vector(dim)` is optional: about how many bytes one vector takes in
  memory, the 32 bytes the store keeps beside it included, for `codemem status`. The default
  says nothing;
- `bind(fetch)` is optional, for an index that does not keep the vectors themselves. The store
  calls it once, right after it builds or loads the index. `fetch(ids)` reads vectors from SQLite
  and returns `(found, vectors)`: an int64 array of the ids that still have a row, and a float32
  array of shape `(len(found), dim)` with their vectors, row for row, exactly as `upsert` got
  them. An id whose row is gone is left out. `fetch` reads on the thread that calls it, through
  a connection of that thread: call it from inside `search`. The default `bind` does nothing;
- the store calls one index from one thread at a time: from the thread that builds or loads it,
  and under the store's lock once it is in use. The indexes of two vector types can be called at
  the same time (one loads while the other is searched), so an index keeps its state in itself,
  not in its class or its module.

**Embedder factories.** `Indexer`, `search()` and `CodememService` take an `embedder_factory`
called as `factory(spec: VectorConfig, config: Config) -> Embedder`, once per vector type (and
once per distinct model for queries). `make_embedder` is the default, and also accepts a bare model
name. `CodememService` also calls `touch()`, `unload(idle_seconds)` and `trim(idle_seconds)` on what
its factory returns; `Embedder` gives each a default that does nothing.

### 12.5 The embedding server (`codemem serve-embeddings`)

`codemem serve-embeddings [PATH] [--host 127.0.0.1] [--port 8791]` serves one embedder over HTTP:
the config's local model (`[vectors.*] model` with `device`, `dtype`, `max_seq_length` and
`batch_size`; a `fake:<dim>` model; a plugin embedder that can be served, §12.4), whatever
`[embedding] provider` says. Every enabled vector type must name the same model. `PATH` is the
repository whose `.codemem.toml` is read, by default the one of the current directory.

**At start** it prints to stdout, as TOML under comment lines, the `[embedding]` section of a
client: `provider = "openai"`, `base_url`, `model`, `space`, `query_prefix`, `document_prefix`,
and `api_key_env = "CODEMEM_SERVE_KEY"` when a key is set. After an empty line come comment lines
only: when to use which section, and the `[embedding.assist]` section of a codemem that runs the
same model itself (§12.3), with `base_url`, `model` and, when a key is set, `api_key_env`, each
line behind `# `. So all of stdout parses as TOML and holds the `[embedding]` section alone.
Everything else goes to stderr. Exit code 2 means the port is taken or the model cannot be
served.

**Routes.** Bodies are JSON in OpenAI's shapes.

| Route | Request | Reply |
|---|---|---|
| `POST /v1/embeddings` | `model`: the served model's name. `input`: a string, or a list of 1 to 2,048 strings. `dimensions` (optional): a whole number from 1 to the model's length. `encoding_format` (optional): `float` or `base64` | `{"object": "list", "data": [{"object": "embedding", "index": i, "embedding": …}], "model": …, "usage": {"prompt_tokens": 0, "total_tokens": 0}}`, one entry per text, in order |
| `GET /v1/models` | none | `{"object": "list", "data": [{"id": <model>, "object": "model", "created": …, "owned_by": "codemem", "codemem": {"space", "dimensions", "query_prefix", "document_prefix"}}]}`: the served model, and under `codemem` what a client sets beside it |
| `GET /health` | none; no key needed | `{"status": "ok"}` once the server has loaded the model and takes requests |

- **Each text is embedded exactly as given.** The server puts nothing before it. A client makes a
  query or a document by sending the model's prefix and the text as one string, which is what
  `query_prefix` and `document_prefix` do.
- **`embedding`** is a list of numbers that carries each float32 exactly, or with `base64` the
  little-endian float32 bytes in base64. Vectors have length 1. With `dimensions`, a vector is
  cut to its first numbers and normalized again.
- **`usage`** is always zero: the server does not count tokens.
- **The key.** When `CODEMEM_SERVE_KEY` is set in the server's environment, every request but
  `GET /health` needs the header `Authorization: Bearer <key>`.
- **The model's memory.** After 5 s without a request the server gives back what its model calls
  needed besides the model. It also frees the model after `model_idle_minutes` without a request
  (60 by default); the next request loads it again and is answered when it is loaded. With 0 the
  model stays in memory for as long as the server runs.

**Errors** are `{"error": {"message", "type", "param": null, "code"}}`, with `type`
`invalid_request_error` below 500 and `server_error` from 500.

| Status | When |
|---|---|
| 400 | the body is not a JSON object; `input` is missing, empty or not text; `dimensions` or `encoding_format` has a value the server does not take |
| 401 | the key is missing or wrong (`code`: `invalid_api_key`) |
| 404 | an unknown route; or `model` is not the served model (`code`: `model_not_found`) |
| 405 | a route's other method; `Allow` names the right one |
| 411 | no `Content-Length` |
| 413 | a body over 16 MB, or more than 2,048 texts. The body is not read and the connection is closed |
| 500 | the model failed on a batch; the message carries the model's error. Every request with a text in that batch fails, and the server goes on |
| 503 | the server is stopping |

A codemem client retries 429, 500 and above, and dropped connections; it fails at once on the
others, with the server's message.

