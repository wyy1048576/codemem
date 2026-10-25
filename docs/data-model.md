# codemem data model and contracts

This is the contract for everything codemem stores and exposes:
- what each record holds;
- the rules for ids, line numbers and hashes;
- what can grow later without breaking indexes;
- the interfaces other code relies on: the MCP tools, the eval adapter and the config (§12).

The code that implements it:

| Part | Code |
|---|---|
| chunks | `schema.py` |
| how chunks are cut | `languages/` and `chunker.py` |
| what gets embedded | `texts.py` |
| storage | `store.py` (SQLite + FAISS) and `vectorcache.py` |

Changes coming with v3 (schema version 3) are marked **(v3)**. If you change something here, one
of the version numbers in §10 must change too.

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
                         └─ Texts per vector type ──► Parts ──► Vector rows (float16) ──► FAISS (derived)
```

| Record | One per | Notes |
|---|---|---|
| File | file the walk saw that has a supported extension | skipped files included, with a reason; partly parsed files are marked too (v3) |
| Chunk | thing a search can return | |
| Edge | caller–callee pair | |
| Vector row | embedded text part | |
| Queue row **(v3)** | chunk whose texts may be out of date | the to-do list from stage A to stage B (`dirty_texts`, §8) |
| FAISS | vector type | rebuildable at any time from the vector rows |

---

## 2. File

| Field | Meaning | Example |
|---|---|---|
| `path` | repo-relative, forward slashes | `auth/sessions.py` |
| `language` | from the extension; `.h` is sniffed (C unless it uses C++ syntax) | `python` |
| `content_hash` | sha256 of the bytes, first 20 hex chars | `9f2c…` |
| `mtime`, `size` | the quick pre-check: equal mtime and size means unchanged, so the file isn't read | |
| `status` | `ok` or `skipped` | `ok` |
| `reason` **(v3)** | for `skipped`: `too_large`, `generated`, `minified` or `binary`; for `ok`: `parse_errors` when tree-sitter could only partly parse the file (what it recovered is indexed) | `too_large` |

**Which files are read:**
- Every extension of a supported language (`codemem languages`).
- Never read:
  - paths in `.gitignore`;
  - `ALWAYS_SKIP_DIRS` (`.git`, `node_modules`, `.venv`, `build`, `dist`, …);
  - `DEFAULT_IGNORE` (`vendor/`, `*.min.js`, `*_pb2.py`, `*.pb.go`, …).
- **Stored as skipped with a reason**, so the next scan doesn't read them again:
  - files over `max_file_size` (10 MB in v3; in v2 these were not recorded at all);
  - binary files (a NUL byte in the first 8 KB);
  - files marked `Code generated … DO NOT EDIT` or `@generated`;
  - JS/TS files with a line over 5,000 characters.
- **Coverage (v3):** ignored files and files in unsupported languages have no row. They are counted
  in `meta.coverage` (by folder and by extension) at each reconcile.

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
| `lead_comment` **(v3)** | in languages whose docstring is inside the definition (the spec's `docstring_in_code`; Python today): the comment lines directly above the definition (no blank line between), markers stripped. Elsewhere those comments are the `docstring`. Before v3, Python dropped them | `Revoke one session; used on logout.` |
| `code` | the exact source lines `start_line..end_line` | |
| `skeleton` | classes only: header plus one line per member (field text or method signature) | `class Table:\n    def insert(self, key, value):` |
| `content_hash` | sha256 of `code`, first 20 hex chars | |
| `is_test` | test file, or a test by its own name or attribute (§3.6) | `false` |
| `calls`, `call_lines` | callee names in first-seen order, and the line of each first call | `["delete"]`, `[20]` |

A chunk counts as unchanged between two versions of a file when its `content_hash`, lines,
`docstring` and `lead_comment` are all equal.

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
other languages they are codemem's own rule, documented so the labeler can cross-check them
independently.

- **Lines are counted the way tree-sitter counts them: split on `\n` only.**
- **The range starts at the definition node,** including:
  - decorators (Python decorated definitions, TS member decorators);
  - annotations (Java `modifiers`);
  - attributes (Rust `#[test]`);
  - `export`, `template <…>`, and the whole `const f = …` statement.
- **Leading comments are never in the range,** in any language (Python too, in v3). Their text
  goes to `docstring`, or to `lead_comment` where the docstring is inside the code (Python). One
  rule for every language: a new language only declares its comment syntax. A 15-line kernel-doc comment
  above a 5-line function would otherwise halve the IoU.
- **A node that ends at column 0 ends on the previous line** (the labeler's rule). Examples:
  `#define X 1\n`, `///` comments.

### 3.5 Classes and blocks

- **A class chunk spans the whole class,** matching the eval's class gold exactly. It embeds and
  BM25-indexes its **outline** (skeleton), not its full code: the methods are chunks of their
  own, and would otherwise be duplicated and crowd results.
- **A block is a maximal run of non-definition statements** at module or namespace level, with
  its exact lines:
  - Runs are cut at statement boundaries every `max_block_lines` (200). **(v3)** A single statement
    longer than that is cut by lines, so no block exceeds 200 lines.
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

---

## 4. Calls and edges

- **Call** `(caller_id, callee_name, line)`: one row per distinct callee name in a chunk.
  - The line is the first call site, and `a.b.c()` counts as `c`.
  - Python decorators count for the decorated function.
  - Calls inside nested named definitions count for those definitions.
  - **(v3)** Indexed by `callee_name`, so "every call to name X" is a lookup.
- **Edge** `(caller_id, callee_id)`: a call links to every function, method or class with that
  name **in the same language family** (`c`+`cpp`, `javascript`+`typescript`+`tsx`; the other
  languages alone).
  - Names defined more than `max_defs_per_name` (5) times are ignored (`get`, `run`).
  - Self-calls are dropped.
- **The heuristic lives in one function,** `callgraph.resolve_edges`. It can be replaced by
  import- or scope-aware resolution without touching anything else.
- **Blocks can be callers** (a `describe(...)` block in a JS test file), but never callees.
- **What an edit can change (v3 incremental updates):**
  - the edges *from* the changed files' chunks;
  - the edges *to* any name whose set of definitions changed (added, deleted, or crossing the
    5-definitions limit).

  Nothing else.

---

## 5. Texts and vectors

### 5.1 Vector types and their texts

Each vector type is embedded separately into its own vector set, and its signal can be switched
on and off at search time (`--signals bm25,code,usage`).

**`code`:** a context header in the language's comment syntax, then the doc text, then the code.
The doc text is the comment block above the definition: its `docstring`, or **(v3)** its
`lead_comment` where the docstring is inside the code (Python). A class
uses its outline instead of its code.

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
- It depends only on the chunk's own name and path and on its callers. **So an edit in file A can
  change only the usage texts of what A's chunks call, plus A's own** (decisions D20).

**`summary`:** an empty slot for LLM summaries. It produces nothing.

### 5.2 Parts (windows)

- A `code` text longer than `window_chars` (default 3 × (`max_seq_length` − 32) = 2,976
  characters) is split into windows of whole lines, overlapping by `window_overlap_lines` (3).
- Each window repeats the header plus `# part i/n`.
- **(v3)** Windows after the first also carry the chunk's one-line signature:
  `# part 2/3 of def extract_precompiled_and_patch_package(...)`.
- **(v3)** The number of windows is chosen first, then the lines are split evenly, so no window is
  a tiny leftover.

### 5.3 Vector row

| Field | Meaning |
|---|---|
| `vector_id` | the FAISS id |
| `chunk_id`, `vec_type`, `part`, `n_parts` | which text of which chunk; unique on `(chunk_id, vec_type, part)` |
| `start_off`, `end_off` | lines this part covers, **relative to the chunk's start line** |
| `text_hash` | sha256 of the embedded text, first 20 hex chars |
| `embedder` | the embedder key (§5.4) |
| `dim`, `data` | the vector at the model's full size, float16 |

- **A chunk's score for one vector type is the maximum over its parts.** The card reports that
  part's lines as `best_lines`.
- **The shape is deliberately multi-vector.** Line- or token-level vectors (`advanced-design.md`)
  would be more rows of the same table, scored by a different aggregation.

### 5.4 Embedder key

The identity of an embedding space. Equal keys mean interchangeable vectors.

| Provider | Key | Example |
|---|---|---|
| local | `model \| doc \| L<max_seq_length> \| <dtype> \| <device>` | `jinaai/jina-code-embeddings-0.5b\|doc\|L1024\|float16\|mps` |
| API **(v3)** | `api:<host> \| <model> \| dims=<d> \| doc=<hash of the document prefix>` | `api:api.studio.nebius.com\|Qwen/Qwen3-Embedding-8B\|dims=1024\|doc=0` |

- **Not part of the key:**
  - `embedding_dim` (Matryoshka truncation), which is applied when FAISS is built, so changing it
    re-embeds nothing;
  - the query prefix, which only affects queries;
  - the API key.
- A different key re-embeds that vector type only.

### 5.5 Reuse

Before calling the model for a text, codemem looks for `(embedder key, text_hash)`:
1. in this index (the same text elsewhere in the repo);
2. in the shared **vector cache**, `$CODEMEM_HOME/cache/vectors.db`, which holds every text ever
   embedded on this machine and only grows.

`IndexStats` reports `embedded` (vectors written for changed texts), `model_embedded`, `reused`
and `cache_hits`; and, for the structure, `chunks_added`, `chunks_updated`, `chunks_moved` (only
their line numbers shifted, **v3**), `chunks_deleted`, `relinked` and `queued`. `vector_cache =
"off"` (or `codemem index --no-cache`) forces cold timings.

---

## 6. BM25 fields

Each chunk has one FTS5 row. Every field is pre-tokenized by `tokenize.py`: identifiers are
split, the whole identifier is kept too, and everything is lowercased. SQLite matches the weights
to the columns **by position**, so the column order in the table, in `upsert_chunk` and in
`BM25_FIELDS` must stay the same.

| # | Field | Content | Weight |
|---|---|---|---|
| 1 | `name` | qualname + name | 10 |
| 2 | `path` | the file path | 3 |
| 3 | `signature` | signature | 5 |
| 4 | `doc` | docstring / doc comment, plus `lead_comment` (v3) | 2 |
| 5 | `body` | code (classes: the outline) | 1 |

- A v1 weight triple `(name, signature, body)` is still accepted. It maps to
  `(name, 0, signature, body, body)`.
- **(v3) Query side only:** stopwords are dropped and at most the 32 rarest words are kept, using
  document counts from an `fts5vocab` table. The stored rows are unchanged.

---

## 7. On disk

```
<index dir>/                         default ~/.codemem/indexes/<repo>-<hash8 of the repo path>/
  index.db                           SQLite (WAL): meta, files, chunks, fts (+ fts_vocab, v3), calls, edges, vectors,
                                     dirty_texts (v3: the queue)
  vec_code.faiss, vec_code.json      derived exact search index + {epoch, dim, count, embedder}
  vec_usage.faiss, vec_usage.json
  write.lock                         one writer at a time (OS file lock)
$CODEMEM_HOME/cache/vectors.db       shared vector cache: (embedder, text_hash) -> float16 vector
```

`meta` keys:
- `schema_version` (3 in v3);
- `repo_path`, `indexed_commit`, `indexed_at`;
- `codemem_version`, `index_settings`, `last_update` (the last `IndexStats`);
- `coverage` **(v3)**: ignored and non-code counts;
- `last_scan_at` **(v3)**: when the last full check started (files saved within 2 s of it are re-hashed next time);
- `dirty_seq` **(v3)**: the queue's sequence number, one per stage-A commit;
- per vector type: `vec.<type>.embedder`, `vec.<type>.full_dim`, `vec.<type>.dim_setting`,
  `vec.<type>.epoch`.

The eval harness writes its own marker files into the index folder. codemem never deletes files
it doesn't own.

---

## 8. Consistency and recovery

- **SQLite is the source of truth.** A vector row is committed in the same transaction as its
  bookkeeping.
- **FAISS is derived. It is kept correct by three rules:**
  1. every transaction that changes a vector type's rows bumps `vec.<type>.epoch`;
  2. the in-memory index is patched only after the commit, and its epoch is set last;
  3. **(v3)** an index that is behind catches up by vector id: vector rows never change in place
     (a new vector is a new row, and ids are never reused), so the ids missing on either side are
     the whole difference. This applies to a saved `vec_<type>.faiss` (used if its dim and embedder
     match, whatever epoch it was saved at) and to another process's writes. In v2 any mismatch
     rebuilt the index from all rows.
- **Saving FAISS:**
  - the data file is written first and its note second, each by atomic rename;
  - **(v3)** the MCP server saves lazily (after 30 s idle, on shutdown, on refresh), while the CLI
    and the blocking `update()` save at once;
  - **(v3)** the index is copied while holding the lock and written after releasing it, so
    searches don't wait.
- **(v3) The queue (`dirty_texts`: chunk id, sequence number).** Stage A writes a row for every
  chunk whose texts may have changed, in the same transaction as the change. Stage B rebuilds those
  texts, embeds the changed ones, and deletes a row only if its number is unchanged (a chunk edited
  again meanwhile stays queued). A crash between the stages leaves the rows, so the next start
  finishes the work. "Is anything pending?" is a count of this table.
- **(v3) Settings check:** at each update, `meta.index_settings` is compared with the current
  `Config.index_settings()`. A difference redoes only what that setting affects (decisions D23):
  vectors (re-embed that type), texts (rebuild every text, re-embed the changed ones), links
  (relink every call), or a rebuild (chunker version, file selection, BM25 tokenization, block
  size; vectors of unchanged texts come back from the cache). A chunker or text change would
  otherwise never reach files that don't change.
- **What goes wrong, and what happens:**
  - A crash before saving: the saved file is behind and catches up by id at the next load. A corrupt
    or missing file is rebuilt from the rows. No model call, no re-embedding, either way.
  - A process sees an epoch change made by another process: it catches up by id before searching.
- **Large deletions** give pages back to the OS (`auto_vacuum = INCREMENTAL`).

---

## 9. Identity across edits and commits

What stays the same when code changes, and what is recomputed:

| Change | Chunk key | Texts | Re-embedded |
|---|---|---|---|
| lines added above `revoke_session` | same | same (no line numbers in texts) | nothing |
| body of `revoke_session` edited | same | its code text | its code vector |
| the comment above a Python function edited (v3) | same | its code text (the doc text) | its code vector |
| `revoke_session` renamed everywhere (4 files) | old key deleted, new key added | changed files' code texts; the new name's usage; callees' usage (`Table.delete`) | 9 of 33 texts in the sample repo (measured) |
| file moved | new keys | changed (the header has the path) | the file's chunks, plus what they call (usage) |
| a block edited | new key (content hash) | changed | that block |
| `embedding_dim` changed | same | same | nothing (FAISS rebuilt) |

---

## 10. Versioning rules

| Version | Where | Bump it when | Effect |
|---|---|---|---|
| `SCHEMA_VERSION` (3 in v3) | `store.py` | tables or columns change | an older index is wiped and rebuilt, with a warning (cheap with the vector cache) |
| `CHUNKER_VERSION` (2 in v3) | `config.py` | chunking changes (kinds, ranges, keys, calls) | part of `index_settings()`: the index is rebuilt, with vectors of unchanged texts from the cache |
| `TEXT_FORMAT_VERSION` (3 in v3) | `config.py` | a text builder's output changes | part of `index_settings()`: every text is rebuilt and the changed ones re-embedded, and the eval keeps the indexes apart |
| embedder key | `embedder.py` | automatic | the vector type with a new key is re-embedded |

`Config.index_settings()` lists every index-time setting. The eval adapter hashes it into its
`index_key`, so two systems share an index only when nothing that changes the index differs.

---

## 11. What is fixed, and what is expected to grow

**Fixed** (changing these breaks eval comparability or stored indexes):
- the kinds and their names;
- the line rules;
- the key rules;
- the vector row shape (one row per part, float16 at full size);
- the embedder-key semantics.

**Expected to grow without a schema change:**
- **New vector types:** `summary`, `anchors` (call-site lines, commit messages, past issues). Each
  needs a text builder and nothing else.
- **New part schemes:** line- or token-level vectors.
- **New aggregations:** max, MaxSim, top-k mean.

**Expected to grow with a schema bump:**
- typed edges (`imports`, `inherits`, `tests`);
- stored call-site lines for anchor text (today only the first call line is kept).

---

## 12. Contracts

### 12.1 MCP tools (what agents rely on)

The tool names stay stable, so other front-ends and versions can be compared.

| Tool | Arguments | Returns |
|---|---|---|
| `search_code` | `query: str`, `k: int = 10` (capped at 50), `path_prefix: str \| None`, **(v3)** `kinds: list[str] \| None`, **(v3)** `tests: "include" \| "exclude" \| "only"` | numbered cards: `N. path:start-end  name  [id X]`, the signature, the first doc line, up to 6 preview lines (a long function adds `best a-b`); **(v3)** a closing `Note: ...` line when the search could not include every save or embedding yet |
| `get_chunk` | `ref`: a chunk id, `path:line` or `path::qualname` | full code (a long class: outline + members), plus callers and callees as `name (path:lines)` |
| `index_status` | none | state, progress, counts, models, indexed commit, staleness; **(v3)** freshness (pending files), coverage, embedder (local or remote) |
| `refresh_index` **(v3)** | none | runs a full check now (waits up to 60 s for embeddings): `Checked every file in 0.5 s: 2 files changed, ...` |

**Freshness contract (v3).** `search_code` has the background writer apply every save the
watcher has seen (stage A), then embeds the queue (newest edits first), all within
`catchup_budget_ms` (4 s), then searches. If the budget runs out, the results say what is
pending: files not applied yet, chunks whose vectors are still being computed, or "unconfirmed"
when the watcher couldn't confirm in time that it had seen every earlier save; `search_code` ends
with a `Note:` line saying which. `get_chunk` waits for stage A only: its code, lines and links are
current. While the embedding model is still loading (at startup), an MCP search waits for it within
the same budget, then answers from keywords alone with a note; the CLI and the eval always wait.

**stdout carries only MCP messages;** logs go to stderr.

### 12.2 The eval adapter (what `eval/src/cmeval/adapters/codemem.py` relies on)

A redesign must keep all of this, or change the adapter together with Andrew:
- `CodememService(repo, index_dir=, config=)`, and its `.repo_root` (the adapter overwrites it),
  `.store`, `.last_error`, `.close()`.
- `.update(full=)`, which returns `IndexStats` with:
  - `.errors`: files that failed to chunk, never silent;
  - `.embedded`: per type; a no-op update must give 0;
  - `.to_dict()`.

  It blocks until the index and its FAISS files are on disk, because the adapter measures the
  index folder's size right after.
- `store.counts()["chunks"]`.
- `search(store, query, config, k=, signals=, debug=True)`:
  - it raises if a requested signal has no vectors;
  - `resp.signals` lists the signals used;
  - each card has `path`, `start_line`, `end_line`, `qualname`, `score`, `ranks`, `kind`,
    `chunk_id`, plus `language`, `subkind`, `best_lines`.
- `format_results(SearchResponse(...))`, the card text exactly as the agent sees it; the eval
  counts its tokens.
- `config_from_dict(dict)`, `Config.enabled_vec_types()`, `Config.model_id()`,
  `Config.index_settings()`, `embedder.resolve_device()`.
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
     `CODEMEM_STEERING`, `CODEMEM_VECTOR_CACHE`).
- **Two kinds of settings:**
  - **Index-time:** they change what is stored, so changing one rebuilds the index. They are listed
    by `index_settings()`.
  - **Search-time:** they change only how a query is answered (BM25 weights, RRF, candidates,
    filters, weights). Changing one needs no re-index.
- **(v3) The `[embedding]` section** has `provider` (`local` or `openai`), `model`, `base_url`,
  `api_key_env`, `dimensions`, `query_prefix`, `document_prefix`, `batch_size` and
  `max_concurrency`.
  - Index-time (in `index_settings()` as `embedding`, only for an API provider, so local indexes
    keep their settings): provider, model, base URL, dimensions, document prefix.
  - Search-time or operational: the key's variable name, the query prefix, `batch_size`,
    `max_concurrency`, `timeout_s`.
  - The key itself is read from the named environment variable at each request and is never stored.
