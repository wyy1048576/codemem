# codemem: Design Notes & Build Brief (Week 1)

Owner: Wilson (Person A, platform/backend). Team: Andre (retrieval), Andrew (data/eval).
Status: decisions agreed in discussion on Oct 20, 2026. This file is the brief for building the Week 1 backend skeleton.

**Changed on Oct 24, 2026:**
- **LLM summaries are dropped.** The `summary` slot is removed from the code, the config and the store. We won't use them.
- **The agent decides when to re-index.** The MCP server no longer re-indexes on save (config `watch = false` by default). `index_status()` lists changed files with how much of the repo depends on each, a new `reindex()` tool updates the index, and a Claude Code skill (`codemem-reindex`, installed by `init`) tells the agent how to weigh the two. Change detection (hashes, chunk diff, text hashes) is unchanged.

---

## 1. What we're building

A **local, agent-agnostic code search tool**. A developer points it at a repository. It indexes every function and exposes search to coding agents (Claude Code, Codex, Cursor) through an **MCP server** and to humans/eval scripts through a **CLI**. The goal is finding the code relevant to an issue more accurately, with fewer tokens and in less time than grep.

Research context: we compare grep vs. hybrid BM25 + embedding baseline vs. our additions (usage context, hierarchy, query routing, token-budgeted results) on SWE-bench / LocBench. The platform must make these components **easy to toggle and swap**.

## 2. Product shape (decided)

- **Local Python package**, installed with `uv tool install` / `pipx install` (from GitHub for now). No desktop app, no IDE extension, no remote server / hosted connector. Code never leaves the machine.
- One command, `codemem`, provides both the **CLI** and the **MCP server** (`codemem mcp`, stdio transport).
- **Core library** holds all logic; MCP and CLI are thin front-ends. Teammates import the library directly.
- **Process model (Week 1):** the MCP server owns the index and the file watcher while a session is running. On startup it does a **hash-based catch-up** (re-index only what changed while it was off). A long-running daemon is a possible later step; don't build it now, but keep the core free of assumptions that would block it.

## 3. Week 1 scope: thin end-to-end

`init` → chunk (tree-sitter, Python) → build texts (code, usage) → embed (jina-0.5b) → store (SQLite + FAISS) → hybrid search (BM25 + vectors, RRF) → MCP + CLI, plus watcher + catch-up.

**Not in Week 1:** hierarchy summaries, query routing, token-budget cards beyond a simple cap, daemon, web UI, non-Python languages.

## 4. Environment

- Dev machine: **Windows 11, no NVIDIA GPU, Intel Arc graphics**. Must work on Windows (paths, file watching, no POSIX-only calls).
- Python **3.11+** (3.10 acceptable if a dependency forces it), `uv` for dependencies, `pytest` for tests.
- Embedding device configurable: `auto | cpu | xpu | cuda`. Default `auto` → CPU here. `xpu` = PyTorch Intel GPU backend; treat it as experimental and fall back to CPU if unavailable.
- Big indexing runs / jina-1.5b may later run on a hackathon GPU. The code should work unchanged there (just `device=cuda`).

## 5. Package layout (suggested)

```
codemem/
  pyproject.toml          # entry point: codemem = codemem.cli:main
  README.md
  docs/design-notes.md    # copy of this file
  src/codemem/
    config.py      # settings, paths, per-vector-type model config
    schema.py      # Chunk dataclass + IDs
    chunker.py     # tree-sitter Python chunking + call extraction
    tokenize.py    # code-aware tokenization for BM25
    texts.py       # text builders: code, usage
    embedder.py    # Embedder interface; JinaEmbedder; FakeEmbedder for tests
    store.py       # SQLite (metadata, FTS5, call graph) + FAISS per vector type
    indexer.py     # full + incremental indexing (hash based)
    search.py      # BM25 search, vector search, RRF, result cards
    watcher.py     # watchdog → incremental re-index (debounced)
    prompts.py     # ALL agent-facing text: tool descriptions, server instructions, AGENTS/CLAUDE snippet
    agents.py      # writes agent config entries on `init`
    server.py      # MCP server
    cli.py         # CLI
  tests/
```

## 6. Chunking

- Parser: **tree-sitter** + `tree-sitter-python`.
- **One chunk per function or method** (including nested functions and `async def`), from the `def` line (include decorators) to end of body.
- **One "file header" chunk per file** for module-level code outside functions (imports, constants, top-level statements). Skip it if empty.
- Classes: not a chunk of their own in Week 1. Store `class_name` / qualified name on methods (`SessionManager.expire_old`) so hierarchy can be added later.
- Chunk fields: `chunk_id` (int), `key` (stable string: `path::qualname`, add `#2` etc. on duplicate names), `path` (repo-relative, forward slashes), `qualname`, `name`, `kind` (`function|method|file_header`), `start_line`, `end_line`, `signature`, `docstring`, `code`, `content_hash`.
- Also extract **calls made** by each function (callee names: plain identifiers and the last part of attribute calls, e.g. `db.sessions.delete` → `delete`).

## 7. What gets indexed

- `.py` files only. Respect `.gitignore` (use `pathspec`); always skip `.git`, `venv`, `.venv`, `env`, `build`, `dist`, `node_modules`, `__pycache__`, `site-packages`.
- **Keep test files.** They are needed for usage context ("tested by").
- Skip files over a size limit (configurable, e.g. 1 MB) and files that fail to parse (log, don't crash).

## 8. Text types → one vector set each

Each function gets **several different texts**, each embedded separately into its **own vector set**. Never concatenate them into one vector. This keeps signals undiluted and lets us do ablations by choosing which sets to search at query time.

| Text type | Built from | Week 1 |
|---|---|---|
| `code` | the function's source (signature + docstring + body) | yes |
| `usage` | callers ("called by X in path"), tests ("tested by test_Y"), optionally commit subjects | yes |

- Implement text builders as a **registry** (`name → function(chunk, context) → str | None`) so new types are added without touching the store or search.
- **Call graph resolution (baseline heuristic):** link a call to every chunk with that function name; **ignore names defined more than N times** (configurable, e.g. 5) to avoid noise like `get`/`run`. Callers in files under `tests/` or named `test_*` count as "tested by". Keep the heuristic isolated so it can be improved.
- **Commit messages:** optional, **off by default** (`git log` per file is noisy at function level). Only ever read history up to the indexed commit (no leakage for SWE-bench).
- Cap usage text length (e.g. top 20 callers/tests).

## 9. Storage: SQLite + FAISS (decided over LanceDB / Chroma / sqlite-vec)

Reasons: full control over BM25 tokenization and per-field weights, a natural relational fit for the call graph and hierarchy, exact repeatable search for evals, and easy addition of new vector sets for custom embeddings.

**SQLite (`index.db`):**
- `chunks`: all chunk fields above.
- `calls`: `caller_id, callee_name`; `edges`: resolved `caller_id, callee_id`.
- `files`: `path, content_hash, mtime` (for catch-up).
- `fts` (FTS5): columns `name_tokens`, `signature_tokens`, `body_tokens`, filled with **pre-tokenized text** (see §10), tokenizer `unicode61` with no extra splitting, queried with weighted `bm25(fts, 10.0, 5.0, 1.0)` (weights configurable).
- `embeddings`: `chunk_id, vec_type, text_hash, model`. Used to decide what needs re-embedding.
- `meta`: schema version, repo path, indexed commit, per-vec-type model name + dim.

**FAISS:** one index file per vector type (`vec_code.faiss`, `vec_usage.faiss`, …).
- Use `IndexIDMap2(IndexFlatIP)` with **`chunk_id` as the FAISS ID**, so there is no fragile row alignment and updates are `remove_ids` + `add_with_ids`.
- L2-normalize vectors → inner product = cosine.
- **Flat (exact) search only** for now. Repeatable eval numbers matter more than speed at SWE-bench repo sizes.
- If the configured model for a vec type changes (name or dim), rebuild that vec type only.
- Hide all of this behind a small `VectorStore` interface so it can be swapped later.

## 10. BM25 tokenization (our code, not the DB's)

Pre-tokenize in Python before inserting into FTS5, and apply the **same function to queries**:
- Split snake_case and camelCase/PascalCase; **also keep the full identifier** (`revoke_session` → `revoke session revoke_session`; `getUserById` → `get user by id getuserbyid`).
- Lowercase; split on punctuation/dots (`db.sessions.delete` → `db sessions delete`).
- Optional (config, default off): light stemming, stop-word removal.
- Escape/quote tokens when building FTS5 MATCH queries (FTS5 syntax chars in user queries must not break search); OR the query tokens together.

## 11. Embedding model

- **Default: `jinaai/jina-code-embeddings-0.5b`** via `sentence-transformers`. 896-dim (supports truncation, Matryoshka). Keep **`jina-code-embeddings-1.5b`** configurable for evals.
- **Use the model's task prompts:** queries with `prompt_name="nl2code_query"`, code/text documents with `prompt_name="nl2code_document"`. The prefixes are roughly "Find the most relevant code snippet given the following query:\n" / "Candidate code snippet:\n". **Verify via `model.prompts` after loading** (confirmed for the 1.5b card; assumed for 0.5b). Handle this inside the embedder so callers never see prefixes.
- Model is configured **per vector type** (e.g. code → jina, usage → jina; later maybe usage → Qwen3-Embedding-0.6B). A query is embedded once **per distinct model** in use.
- Optional `embedding_dim` truncation setting (default full).
- Batch encoding; cache model on first download (Hugging Face cache). License: jina code models are reportedly non-commercial, fine for the course. Note in the README.
- Provide a **`FakeEmbedder`** (deterministic, hash-based, tiny dim) for tests and fast dev without downloading the model.

## 12. Indexing & freshness

- **Full index:** walk files → chunk → build texts → embed what's missing → write store.
- **Incremental (used by catch-up, `reindex` and the optional watcher):**
  1. Detect changed/added/deleted files by `content_hash` (mtime as a quick pre-check).
  2. Re-chunk changed files; match chunks by `key`; update changed rows, insert new, delete removed (also remove their vectors and edges).
  3. Recompute call edges (cheap) and rebuild **all** text builders' texts; compare `text_hash` against `embeddings`; **re-embed only texts whose hash changed**. This correctly refreshes callers' and callees' usage text when a function changes.
- **Watcher (optional since Oct 24, `watch = true`):** `watchdog`, debounce (~300–500 ms), batch events, then run incremental. Target: update within ~1 s of a save for small edits. By default the agent calls `reindex()` instead.
- **Concurrency:** one writer at a time (simple lock file in the index dir); SQLite WAL mode so searches can run during updates.
- Record timings (chunk/embed/write) and counts (chunks re-embedded); needed later for RQ3.

## 13. Index location

- Default: **global cache, not inside the repo**: `~/.codemem/indexes/<repo-name>-<short-hash-of-abs-path>/` (override base with env `CODEMEM_HOME`).
- `--index-dir` override on every command (the eval harness needs per-commit indexes, e.g. `<repo>@<commit>`).
- Store repo path + git HEAD commit in `meta`.

## 14. Retrieval (baseline)

1. Tokenize query (same as §10) → BM25 top-N from FTS5.
2. Embed query → top-N from each enabled vector set.
3. **RRF merge:** `score = Σ 1 / (k + rank)`, `k = 60`, over all enabled lists. Optional per-list weights (default 1.0), the hook for later query routing.
4. Look up top-k `chunk_id`s in SQLite and return **result cards**: `path:start-end`, `qualname`, `signature`, first docstring line, short code preview (cap lines/chars), and optionally per-signal ranks (debug flag, useful for analysis).
- Search options: `k`, which signals to use (`bm25`, `code`, `usage`, …), path prefix filter (filter IDs via SQLite).
- Keep `search()` a pure library function returning structured data. MCP and CLI only format it. Andre's retrieval work plugs in here.

## 15. CLI

```
codemem init [PATH] [--agents claude,cursor,codex] [--no-index]
codemem index [PATH] [--full] [--index-dir DIR]
codemem search "query" [-k 10] [--signals bm25,code,usage] [--json] [--debug]
codemem status [PATH]      # counts, models, last indexed commit, staleness
codemem watch [PATH]       # foreground watcher (handy for testing)
codemem mcp [PATH]         # MCP server over stdio (what agents launch)
```
- `--json` output on search/status for Andrew's eval scripts.

## 16. MCP server

- **MCP Python SDK v2 note:** `FastMCP` was renamed. Use `from mcp.server.mcpserver import MCPServer` (`MCPServer(name=..., instructions=...)`, `@server.tool(...)`, `server.run("stdio")`), **or** pin `mcp<2` and use `FastMCP`. Pick one deliberately and pin the version range.
- Transport: **stdio**. Never print to stdout except protocol messages (logs → stderr / log file).
- Repo resolution: CLI arg, else the working directory the agent launched it in (walk up to the git root).
- On startup: open the index (build it if missing), run catch-up, start the watcher if `watch = true`, then serve. Don't block the handshake for minutes on a first full index. Start indexing in the background and let tools report "indexing in progress, X% done".
- Tools (keep the list small and clear):
  - `search_code(query: str, k: int = 10, path_prefix: str | None = None)` → result cards
  - `get_chunk(chunk_id or path:line)` → full code + callers/callees
  - `index_status()` → ready/indexing, counts, staleness (changed files, ranked by how many other files call into them)
  - `reindex()` → update the index now (added Oct 24)
- Tool descriptions and server `instructions` come from `prompts.py` (see §17).

## 17. Agent discovery & steering

**Registration (`codemem init` writes these, with confirmation / dry-run):**
- Claude Code: project `.mcp.json` (or print the `claude mcp add codemem -- codemem mcp` command)
- Cursor: `.cursor/mcp.json`
- Codex: `~/.codex/config.toml` (print the snippet rather than editing a global file silently)

**Steering (all text lives in `prompts.py`, so it can be edited/varied for the agent study):**
- Tool descriptions, e.g. *"Use search_code FIRST to locate code relevant to an issue, bug or feature, especially when you don't know exact identifiers. Returns ranked functions with file:line. Prefer this over grep for exploratory search; use grep for exact strings."*
- MCP server `instructions`: a short usage guide.
- Optional `AGENTS.md` / `CLAUDE.md` snippet (`init --write-agent-notes`): *"This repo is indexed by codemem. Prefer `search_code` before grep when locating code."*
- How strongly we steer is a **variable in the agent study**. Keep it configurable (e.g. `steering: none|light|strong`).

## 18. Configuration (one place)

`config.toml` (global `~/.codemem/config.toml`, optional per-repo override) with env overrides. Keys: `device`, `vectors.<type>.model`, `vectors.<type>.enabled`, `embedding_dim`, `batch_size`, `bm25.weights`, `rrf.k`, `rrf.weights`, `usage.max_defs_per_name`, `usage.include_commits`, `max_file_size`, `ignore` extras, `steering`.

## 19. Testing / done criteria for Week 1

- Unit tests (use `FakeEmbedder`, no model download): tokenizer splits, chunker on a fixture file (functions, methods, nested, decorators, async, file header), usage text from a small fixture repo, store add/update/delete keeps SQLite and FAISS in sync, RRF math, incremental update re-embeds only changed texts (including a caller's usage text when a callee is renamed).
- Integration: index a small fixture repo end to end; `codemem search` finds the expected function for an NL query that shares no words with its code (the `revoke_session` / "disabled users stay logged in" example, with a caller `disable_user` and test `test_disabled_user_loses_sessions`).
- Smoke test with real jina-0.5b on CPU on a medium repo (e.g. `requests` or `flask`); record indexing time and query latency.
- MCP: register in Claude Code locally, confirm the tools appear and `search_code` returns results.
- Works on Windows.

## 20. Open items (decide later)

- Whether a daemon is needed (depends on whether freshness experiments need updates while no agent runs).
- Optional web viewer (browse chunks, run queries, show call graph), also useful for presentations.
- Better call resolution (imports/scopes), hierarchy, query routing, token-budgeted cards.
- Hackathon compute (check with Anni). "SharedNets" study for discovery patterns.
