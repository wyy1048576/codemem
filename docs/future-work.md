# Future work: update cost on very large repos

Written 2026-10-24. Usage vectors and the call graph stay: in the first dev run
(`eval/results/2026-10-23-dev50-final/`) usage is codemem's best signal. It lifts file
recall@10 from 0.703 (code only) to 0.848, and it is the only codemem system above
`grep-fn-plus` (0.760). The LLM summary slot was removed and is not planned.

## What an update costs today

An update re-embeds only texts whose hash changed. The changed code, plus the usage text of
the functions it calls, is all that goes through the model. To *find* those texts, some steps
still look at the whole repo. Median of the 38 updates in the dev run, django-size repos:

| Step | Median | Covers |
|---|---|---|
| embed changed texts | 63.1 s | only what changed |
| chunk changed files | 0.47 s | only changed files |
| write chunks + recompute all call edges | 0.70 s | edges: whole repo |
| rebuild and hash every function's texts | 0.09 s | whole repo |
| rewrite the whole vector file + id sidecar | 0.08 s | whole repo |
| scan (size + mtime of every file) | 0.02 s | whole repo |

Embedding dominates big updates. For a one-file agent edit on fast hardware, the whole-repo
steps are most of the cost, and on repos 10 to 100 times django they grow to tens of
seconds. The items below remove them.

## 1. Incremental call edges (A ∪ B)

A = functions in changed files (edited, added, deleted, renamed). Every edge that can
change touches a node in A ∪ B:

- calls out of a function in A: delete its edges, resolve its calls again;
- calls to a name added to or removed from the repo in A: re-resolve the callers of that name
  (needs an index on `calls(callee_name)`);
- other definitions of a name whose count crossed `max_defs_per_name`: all of that name's
  edges switch on or off.

B = the functions whose caller list changed: the callees of A's functions, before and after
the edit, and the other definitions in the threshold case. Only their usage text is rebuilt.
Their code vectors stay. Callers outside A ∪ B get a rewritten edge row but no re-embed,
since a function's usage text lists who calls it, not what it calls.

Keep the global rebuild for full indexes, and test that the incremental graph equals the
global one after random edits, renames and deletes. Also sort usage callers by path and
name, not line, so a caller that only moved down doesn't re-embed its callees.

## 2. Texts only for A ∪ B

`_embed` loads, rebuilds and hashes every function's texts on each update. With A ∪ B known,
build texts only for those functions.

## 3. Vectors in SQLite

Each update rewrites the whole FAISS file and its id sidecar, even when 3 vectors changed.
Store vectors as rows in SQLite, written in the same transaction as the chunks, and build
the FAISS index in memory at startup. That removes the sidecar and `reconcile()`. The
`VectorStore` plugin becomes an in-memory index built from SQLite, with no save/load of its
own (agreed 2026-10-24). An MCP server would also see writes from another process, which today
it doesn't: it searches the vectors it loaded at startup.

## 4. Targeted scan

The walk checks every file. When the agent calls `reindex`, the server could check only the
paths it knows changed, with a full scan at startup, after a `.gitignore` change or a folder
move or delete, and now and then as a safety net. Without the watcher, codemem has no path
list of its own, so this needs either the watcher's events or a cheap repo-wide signal such
as `git status`.

## 5. First index

The first index embeds everything (about 9 minutes for django on Andrew's Mac, hours on a CPU).
Options:
- a content-addressed embedding cache keyed by (model id, text hash), shared across branches,
  worktrees and machines (the eval builds one index per commit, so it gains the most);
- BM25 first, with vectors filling in behind it;
- `ignore` patterns for vendored and generated code;
- a lower `max_seq_length`;
- a GPU.

## 6. Agent-driven reindex: open points

- The skill exists only for Claude Code. Cursor and Codex need their own form, such as
  `.cursor/rules` or `AGENTS.md`. The tool descriptions and server instructions already
  mention `reindex`, so they still work without it.
- The importance numbers come from name-matched call edges. Measure whether agents reindex at
  sensible times, e.g. as a condition in the agent study, with `watch = true` as the control.
