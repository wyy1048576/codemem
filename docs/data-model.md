# codemem data model (v2)

This is the contract for everything codemem stores: what each record holds, the rules for ids,
line numbers and hashes, and what can grow later without breaking indexes. The code that
implements it is `schema.py` (chunks), `languages/` + `chunker.py` (how chunks are cut),
`texts.py` (what gets embedded), `store.py` (SQLite + FAISS) and `vectorcache.py`.

If you change something here, one of three version numbers must change too (section 10).

---

## 0. The running example

Every section uses the same small repo:

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

The issue an agent searches for is *"Disabled users stay logged in"*. Note that `revoke_session`
shares no words with the issue. Its callers do. That is why codemem stores the call graph
next to the code.

---

## 1. The picture

```
repo file ──► File row
   │
   └─ tree-sitter ──► Chunks (function | method | class | block)
                         │
                         ├─ Calls (callee names seen in the chunk) ──► Edges (resolved: caller → callee)
                         ├─ FTS row (5 BM25 fields)
                         └─ Texts per vector type ──► Parts ──► Vector rows (float16) ──► FAISS (derived)
```

- **File.** One per source file.
- **Chunk.** One per thing a search can return.
- **Edge.** One per caller-callee pair.
- **Vector row.** One per embedded text part.
- **FAISS.** Rebuildable at any time from the vector rows.

---

## 2. File

| Field | Meaning | Example |
|---|---|---|
| `path` | repo-relative, forward slashes | `auth/sessions.py` |
| `language` | from the extension; `.h` is sniffed (C unless it uses C++ syntax) | `python` |
| `content_hash` | sha256 of the bytes, first 20 hex chars | `9f2c…` |
| `mtime`, `size` | quick pre-check: equal mtime + size means unchanged, so the file isn't read | |
| `status` | `ok`, or `skipped` (binary, generated or minified: recorded so it is not re-read) | `ok` |

**Which files are read.**
- Every extension of a supported language (`codemem languages`).
- Not read:
  - paths in `.gitignore`
  - `ALWAYS_SKIP_DIRS` (`.git`, `node_modules`, `.venv`, `build`, `dist`, …)
  - `DEFAULT_IGNORE` (`vendor/`, `*.min.js`, `*_pb2.py`, `*.pb.go`, …)
  - files over `max_file_size`
- **Read, then skipped** (status `skipped`, so the next scan does not read them again):
  - binary files (a NUL byte in the first 8 KB)
  - files marked `Code generated … DO NOT EDIT` or `@generated`
  - JS/TS files with a line over 5,000 characters (minified)

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
- for classes: `class`, `struct`, `interface`, `enum`, `trait`, `record`, …
- for functions: `constructor`, `destructor`, `macro`, `arrow` (`const f = () => {}`), `assigned` (`exports.f = function () {}`), `test_macro` (gtest `TEST(A, B)`)
- for blocks: `imports` or `statements`

**Not chunks:**
- **Anonymous functions** (lambdas, callbacks). Their lines belong to the enclosing chunk. This is the same rule as the eval's labeler.
- **Declarations without a body** (C prototypes, TS overload signatures, interface methods). They live in a block or in their class's skeleton.

### 3.2 Fields

| Field | Rule | Example |
|---|---|---|
| `chunk_id` | integer, local to one index, stable while the key is stable | `17` |
| `key` | `path::qualname`; duplicates in a file get `#2`, `#3` in source order | `auth/sessions.py::revoke_session` |
| | blocks: `path::<scope.><block>@<hash8 of the code>` | `auth/db.py::<block>@a41f09c2` |
| `path`, `language` | as for the file | |
| `kind`, `subkind` | 3.1 | `function`, `""` |
| `name` | the definition's own name; for blocks, a label (`imports` or the first line, ≤60 chars) | `revoke_session` |
| `qualname` | enclosing scopes and the name, joined by `.` (3.3) | `SessionManager.expire_old.is_old` |
| `class_name` | innermost enclosing class, receiver or impl type | `SessionManager` |
| `parent_key` | key of the enclosing chunk (class or function), else null | |
| `start_line`, `end_line` | 1-based, inclusive (3.4) | `19`, `20` |
| `signature` | the definition's text up to its body, on one line | `def revoke_session(session_id):` |
| `docstring` | Python: the docstring. Other languages: the comment block right above (markers stripped) | |
| `code` | the exact source lines `start_line..end_line` | |
| `skeleton` | classes only: header + one line per member (field text or method signature) | `class Table:\n    def insert(self, key, value):` |
| `content_hash` | sha256 of `code`, first 20 hex chars | |
| `is_test` | test file, or a test by its own name/attribute (3.6) | `false` |
| `calls`, `call_lines` | callee names in first-seen order, and the line of each first call | `["delete"]`, `[20]` |

### 3.3 Qualified names by language

| Language | Scopes that add a qualifier | Example |
|---|---|---|
| Python | classes, enclosing functions | `SessionManager.expire_old.is_old` |
| JS / TS | classes, TS namespaces, enclosing functions | `SessionManager.expireOld.isOld`, `Auth.inner` |
| Go | method receiver type | `Manager.ExpireOld` |
| Java | classes (nested ones too) | `SessionManager.Inner.helper` |
| C | (none) | `revoke_session` |
| C++ | namespaces, classes, out-of-line `A<T>::b` (template arguments dropped) | `auth.SessionManager.ExpireOld` |
| Rust | `mod`, `impl` type (`impl Trait for T` gives `T.m`) | `Manager.expire_old` |

### 3.4 Line rules

These match the eval labeler for Python (identical scores at IoU 0.3/0.5/0.7 on dev50). They are
codemem's own rule for the other languages, documented so the labeler can cross-check
independently.

- **Lines are counted the way tree-sitter counts them: split on `\n` only.** The MVP used `str.splitlines()`, which also splits on form feeds and ` `. That shifted the code text of every later chunk in such files.
- **The range starts at the definition node**, including:
  - decorators (Python decorated definitions; TS member decorators)
  - annotations (Java `modifiers`)
  - attributes (Rust `#[test]`)
  - `export`
  - `template <…>`
  - the whole `const f = …` statement
- **Leading doc comments are not in the range.** Their text goes to `docstring`. A 15-line kernel-doc comment above a 5-line function would otherwise halve the IoU.
- **A node that ends at column 0 ends on the previous line** (the labeler's rule). Examples are `#define X 1\n` and `///` comments.

### 3.5 Classes and blocks

- **A class chunk spans the whole class**, so it matches the eval's class gold exactly. It embeds and BM25-indexes its **skeleton**, not its full code. Methods are chunks of their own, so the class would otherwise duplicate them and crowd results.
- **A block is a maximal run of non-definition statements** at module or namespace level, with its exact lines.
  - Longer runs are cut at statement boundaries every `max_block_lines` (200).
  - Comments directly above a definition belong to that definition, not to the block.
  - A wrapper that holds definitions (`if TYPE_CHECKING:`, `try/except ImportError`, `#ifdef`, `extern "C"`) is opened. Its definitions become chunks and its other statements become blocks.
  - A wrapper without definitions is an ordinary statement.

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

- **Call** `(caller_id, callee_name, line)`: one row per distinct callee name in a chunk. The line is the first call site. `a.b.c()` counts as `c`. Python decorators count for the decorated function. Calls inside nested named definitions count for those definitions.
- **Edge** `(caller_id, callee_id)`: a call links to every function, method or class with that name **in the same language family** (`c`+`cpp`, `javascript`+`typescript`+`tsx`; other languages alone). Names defined more than `max_defs_per_name` (5) times are ignored (`get`, `run`). Self-calls are dropped.
- **The heuristic lives in one function** (`callgraph.resolve_edges`). It can be replaced by import- or scope-aware resolution later without touching anything else.
- **Blocks can be callers** (a `describe(...)` block in a JS test file), but never callees.

---

## 5. Texts and vectors

### 5.1 Vector types and their texts

Each vector type is embedded separately into its own vector set. Its signal can be switched on and off at search time (`--signals bm25,code,usage`).

**`code`:** a context header in the language's comment syntax, then (outside Python) the doc comment, then the code. For a class it is the skeleton instead of the code.

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
- **The header never contains line numbers**, so code moving down a file does not change its text and does not re-embed it.
- `code_header = false` turns the header off (an ablation).

**`usage`:** who calls the chunk. Built for functions, methods and classes that have callers; not for blocks.

```
revoke_session in auth/sessions.py
called by logout in api/routes.py
called by disable_user in auth/users.py
tested by test_disabled_user_loses_sessions in tests/test_users.py
```

- Up to `max_items` (20) lines, with half the room kept for tests.
- A caller that is a block is written `called at top level in <path>` (or `tested in <path>`).

**`summary`:** a slot for LLM summaries. It produces nothing yet.

### 5.2 Parts (windows)

- A `code` text longer than `window_chars` (default `3 × (max_seq_length − 32)` = 2976 for 1,024 tokens) is split into windows of whole lines.
- Each window has the same header plus `# part i/n`, and windows overlap by `window_overlap_lines` (3).
- The MVP truncated such texts silently instead: the end of a long function was never embedded.

### 5.3 Vector row

| Field | Meaning |
|---|---|
| `vector_id` | FAISS id |
| `chunk_id`, `vec_type`, `part`, `n_parts` | which text of which chunk; unique on `(chunk_id, vec_type, part)` |
| `start_off`, `end_off` | lines this part covers, **relative to the chunk's start line** |
| `text_hash` | sha256 of the embedded text, first 20 hex chars |
| `embedder` | the embedder key (5.4) |
| `dim`, `data` | the vector at the model's full dimension, float16 |

- **A chunk's score for one vector type is the maximum over its parts.** The card then reports that part's lines as `best_lines`.
- **This shape is deliberately multi-vector.** Line-level or token-level vectors (see `advanced-design.md`) are more rows of the same table, scored by a different aggregation.

### 5.4 Embedder key

`model | doc | L<max_seq_length> | <dtype> | <device>`, for example
`jinaai/jina-code-embeddings-0.5b|doc|L1024|float16|mps`.

- Equal keys mean interchangeable vectors.
- **Not part of the key:** `embedding_dim` (Matryoshka truncation). It is applied when the FAISS index is built, so changing it re-embeds nothing.
- A different key (another model, max length, dtype or device) re-embeds that vector type only.

### 5.5 Reuse

Before calling the model for a text, codemem looks for `(embedder key, text_hash)`:
1. in this index (a copy of the same text elsewhere in the repo)
2. in the shared **vector cache** `$CODEMEM_HOME/cache/vectors.db` (other indexes, earlier builds)

`IndexStats` reports `embedded` (vectors written), `model_embedded`, `reused` and `cache_hits`.
`vector_cache = "off"` (or `codemem index --no-cache`) forces cold timings for RQ3.

---

## 6. BM25 fields

Each chunk has one FTS5 row. Every field is pre-tokenized by `tokenize.py`:
- identifiers are split
- the whole identifier is kept too
- everything is lowercased

| Field | Content | Default weight |
|---|---|---|
| `name` | qualname + name | 10 |
| `path` | the file path | 3 |
| `signature` | signature | 5 |
| `doc` | docstring / doc comment | 2 |
| `body` | code (classes: the skeleton) | 1 |

A v1 weight triple `(name, signature, body)` is still accepted. It maps to `(name, 0, signature, body, body)`.

---

## 7. On disk

```
<index dir>/                         default ~/.codemem/indexes/<repo>-<hash8>/
  index.db                           SQLite (WAL): meta, files, chunks, fts, calls, edges, vectors
  vec_code.faiss, vec_code.json      derived exact search index + {epoch, dim, count, embedder}
  vec_usage.faiss, vec_usage.json
  write.lock                         one writer at a time (OS file lock)
$CODEMEM_HOME/cache/vectors.db       shared vector cache: (embedder, text_hash) -> float16 vector
```

`meta` keys:
- `schema_version` (2)
- `repo_path`, `indexed_commit`, `indexed_at`
- `codemem_version`, `index_settings`, `last_update` (the last `IndexStats`)
- per vector type: `vec.<type>.embedder`, `vec.<type>.full_dim`, `vec.<type>.dim_setting`, `vec.<type>.epoch`

The eval harness writes its own marker files into the index folder. codemem never deletes files
it does not own.

---

## 8. Consistency and recovery

- **SQLite is the source of truth.** A vector row is committed in the same transaction as its bookkeeping.
- **FAISS is derived.**
  - Every transaction that changes a vector type's rows bumps `vec.<type>.epoch`.
  - The in-memory FAISS index is changed only after the commit.
  - A saved `vec_<type>.faiss` is used only if its `.json` epoch equals `meta`. Otherwise it is rebuilt from the rows.
- **What goes wrong and what happens:**
  - A crash before saving, a corrupt file, or another process writing: the search index is rebuilt from the rows on next use. **No model call and no re-embedding.** The MVP re-embedded instead.
  - A process sees an epoch change made by another process: it reloads before searching.
- **Large deletions** give pages back to the OS (`auto_vacuum = INCREMENTAL`). The MVP's index file never shrank.

---

## 9. Identity across edits and commits

What stays the same when code changes, and what has to be recomputed:

| Change | Chunk key | Code text | Re-embedded |
|---|---|---|---|
| lines added above `revoke_session` | same | same (no line numbers in texts) | nothing |
| body of `revoke_session` edited | same | changed | its code vector |
| `disable_user` renamed | `disable_user` deleted, new key added | callee's usage text changed | new function's code + `revoke_session`'s usage |
| file moved | new keys | changed (header has the path) | the file's chunks (the cache does not help: new text) |
| a block edited | new key (content hash) | changed | that block |
| `embedding_dim` changed | same | same | nothing (FAISS rebuilt) |

---

## 10. Versioning rules

| Version | Where | Bump it when | Effect |
|---|---|---|---|
| `SCHEMA_VERSION` | `store.py` | tables or columns change | an older index is wiped and rebuilt (with a warning) |
| `TEXT_FORMAT_VERSION` | `config.py` | a text builder's output format changes | part of `index_settings()`; new texts get new hashes, so they re-embed |
| embedder key | `embedder.py` | automatic | the vector type with a new key is re-embedded |

`Config.index_settings()` lists every index-time setting. The eval adapter hashes it into its
`index_key`, so two systems share an index only when nothing that changes the index differs.

---

## 11. What is fixed and what is expected to grow

**Fixed** (changing these breaks eval comparability or stored indexes):
- the kinds and their names
- the line rules
- the key rules
- the vector row shape (one row per part, float16 at full dimension)
- the embedder-key semantics

**Expected to grow** without a schema change:
- **New vector types:** `summary`, `anchors` (call-site lines, commit messages, past issues) need a text builder and nothing else.
- **New part schemes:** line-level or token-level vectors.
- **New aggregations:** max, MaxSim, top-k mean.

**Expected to grow** with a schema bump:
- typed edges (`imports`, `inherits`, `tests`)
- stored call-site lines for anchor text (today only the first call line is kept)
