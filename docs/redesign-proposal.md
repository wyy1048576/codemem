# codemem v3: redesign proposal (for approval)

Status: **draft for Andre's approval** (2026-10-24). Once approved, this file is folded into
`architecture.md`, `data-model.md` and `decisions.md` and then deleted (see §6).

Running example throughout: the sample repo (`tests/fixtures/sample_repo`), where an agent renames
`revoke_session` to `end_session` and fixes its callers. Numbers marked *measured* come from this
week's runs on the M1 (vLLM index: 6,235 files, 102k chunks, 145k vectors).

---

## 0. In one page

**Goal.** Semantic search over a codebase that answers vague, feature-level questions, used next to
grep, not instead of it. Typical questions:
- "I want to add login auth but have no idea where to start."
- "I want to add OCR to my pipeline. It doesn't support image upload yet."

Keyword search fails on these (no shared words with the code), and grep takes many tries. The
system should find the relevant functions in one or two calls, quickly and cheaply in tokens.

**This MVP is done when the system is:**

| Property | Check | Today (measured) | Target |
|---|---|---|---|
| Fresh | an edit is searchable (keywords and vectors) after a one-function edit, vLLM-size repo | 8 s per save + queueing | < 1 s |
| Cheap when idle | update with nothing changed, vLLM | 6.8 s | < 0.5 s |
| Consistent | incremental index equals a full rebuild after random edit sequences | not tested | identical, in tests |
| Crash-safe | killed at any point, restart repairs it | yes for SQLite and FAISS; untested end to end | tested |
| Complete | every file is indexed or listed with a reason | size-skipped and non-code files invisible | nothing silent |
| Fast search | short query (10 words), vLLM | 0.27 s | < 0.3 s |
| | long query (250 words), vLLM | 1.64 s (BM25 1.1 s) | < 0.7 s |
| Portable | install + `codemem init` + agent use, with or without a GPU, local or API embeddings | local model only, global install | both |
| No regression | the existing dev runs: v3 at least as good as v2, and ahead of the grep baselines | v2 ahead of dev-tuned grep (not significant) | the same or better |

**Not in this MVP:** tuning (RRF k, BM25 weights, candidates), new retrieval algorithms
(multi-vector, reranker), model training, and eval changes (one is highlighted for later in §3).
They come after, guided by `advanced-design.md`.

**What changes, by component:**

| Component | Change |
|---|---|
| Watcher | passes changed paths on; short quiet period with a maximum wait; polling fallback; reacts to git branch switches |
| Indexer | incremental: only changed files plus the exact usage ripple; the full update becomes the same code path; FAISS saved lazily |
| Search | catches up on pending changes before answering; neutral weights; BM25 query clean-up for long queries |
| Chunker | Python leading comments kept; window headers name their function; even-sized windows; huge blocks split |
| Coverage | 10 MB file cap; every skipped file recorded with a reason; status shows what isn't indexed |
| Embeddings | provider choice: local model (default) or any OpenAI-compatible API (Nebius, OpenAI, a self-hosted server) |
| MCP | search filters, a `refresh_index` tool, freshness and coverage in `index_status`, an install that doesn't need a global command |
| Eval | **no change in this MVP.** One change is highlighted for later (§3): today's queries can't show the vague-question use case |

---

## 1. Answers to your notes

### 1.1 Windows and chunk length

- **A window is not a chunk.** It is one of several vectors of the same chunk (same chunk id,
  "part i of n", its own line range). Results are per chunk; a chunk's code score is its best
  window; the card shows that window's lines.
- **What a chunk knows about others:** its parent (a method points to its class, a nested function to
  its function, through `parent_key`); a class lists its members (outline and `get_chunk`). Sibling
  functions know each other only through the file and the call graph.
- **What a window knows:** the path, the enclosing class, and "part i/n". **It does not know its own
  function's name**: windows 2..n of `extract_precompiled_and_patch_package` never mention it.
  Fixed in §2.5.
- **Length:** functions and classes have no cap (the syntax decides). Blocks are capped at 200 lines,
  but only between statements, so one huge statement stays one block (*measured*: a 1,668-line dict
  in `vllm/envs.py`, 32 windows). Windows are about 3,000 characters (the model reads 1,024 tokens),
  with 3 lines of overlap. *Measured on vLLM:* 95.4% of chunks fit one window.

### 1.2 Links and usages: do we need them, and in which direction?

- **Stored once:** each call link is one row (caller → callee) in `edges`. Both directions are
  queries on the same table, so "tracking both" costs nothing extra.
- **Used twice:**
  - usage text (who calls me, which tests cover me) is embedded for search;
  - `get_chunk` shows callers and callees, so the agent can navigate.
- **We keep them.** Usage vectors were the biggest measured gain (dev50 function MRR 0.334 → 0.423
  in the MVP). They fit the goal: they describe a helper by where it is used ("called by
  upload_view in api/upload.py"), which is how a vague feature question reaches it.
- **The ripple stays one hop, along outgoing calls.** A usage text lists callers, so a change in file
  A changes only: A's own texts; the usage texts of what A's chunks call, before and after the edit;
  and the chunks whose callers changed because a name was added or removed (including the
  5-definitions limit). §2.2 computes exactly this set. *Measured:* a full rename across 4 files
  re-embedded 9 of 33 texts, and only one (`Table.delete`) sat outside the changed files.
- **Not now:** putting callee descriptions into the caller's text ("calls ocr_image: extracts text
  from an image"). It may help vague queries, but changes would then ripple to callers too. Parked
  as an experiment (`advanced-design.md`, anchors).
- **Later (phase 3, optional):** more precise links. Prefer the same class (`self.x()`), then the same
  file, then the imported module, before falling back to repo-wide name matching.

### 1.3 Not missing files

Today there are three silent holes: files over the size cap are not recorded anywhere; files in
languages we don't parse are never listed; ignored files are not counted. The fix is in §2.6: a
10 MB cap, a status and a reason for every skipped file, and a coverage report in `index_status`.

### 1.4 Comments (how they work today)

| Comment | Today | Change |
|---|---|---|
| Inside a function, class or block | part of its code: embedded and keyword-searchable | none |
| Directly above a definition, JS/TS/Go/Java/C/C++/Rust | becomes the chunk's doc text (embedded, BM25 doc field) | none |
| Directly above a definition, **Python** | **dropped**: removed from the block above, never added to the function | becomes doc text, as for other languages; line ranges unchanged (eval labeler compatibility) |
| On its own between definitions (blank lines around, no code) | **dropped** | parked: license headers would become noise; needs a rule (§6 of decisions) |
| Inside a class, between methods | in the class's code but not in its outline, so not searchable | parked |

### 1.5 How updates are triggered

The debounce number stops mattering much once searches catch up on pending changes themselves
(§2.1). Proposed triggers, in order of importance:
1. **Catch-up before every search.** Pending changes are applied first, within a time budget.
2. **Background updates.** After 0.5 s without new saves, and at most every 2 s while saves keep
   coming, so a long editing burst can't postpone indexing forever.
3. **Safety nets:**
   - a full reconcile at startup;
   - a full reconcile every 5 minutes (a scan: 0.3 s on vLLM when nothing changed);
   - a `refresh_index` MCP tool, for after `git checkout` or `git pull`, or when in doubt;
   - polling every 10 s when OS file events don't work (network drives, WSL, Linux watch limits).

A Claude skill would only work in Claude Code; an MCP tool works in every agent, so the manual
trigger is a tool.

### 1.6 API embeddings

Yes, as a provider choice (§2.7). One OpenAI-compatible client covers Nebius, OpenAI, Together,
Fireworks, a self-hosted vLLM or TEI server, and Ollama. Your Nebius key works through it; the key
is read from an environment variable, never stored.

---

## 2. Design

### 2.1 The freshness model (the core idea)

```
 file saved ──▶ watcher ──▶ dirty set {paths}          (in memory; a crash loses nothing:
                               │                         the startup reconcile finds the same files)
             ┌─────────────────┴───────────────────┐
             ▼                                     ▼
   background: 0.5 s after the last      search_code(): apply the dirty set first
   save (at most every 2 s while           (budget 2 s), then search
   saves keep coming)                              │
             └──────────────▶ incremental update ◀─┘
                       (changed files + exact usage ripple)

 safety nets: startup reconcile · reconcile every 5 min · refresh_index tool · polling fallback
```

**The guarantee for the agent:** a search reflects every file saved before the search started.
The one exception is embeddings for very large edits (for example a whole-repo reformat) that don't
fit in the 2 s budget. Then keywords and links are already current, and the results say which
files are still being embedded.

**Why a budget:** the structural part of an update (chunks, BM25 rows, links) takes milliseconds.
Embedding takes about 0.2 s per changed text with the local model. A one-function edit needs 1 to 3
texts, so it always fits.

### 2.2 The incremental update

`update(paths=None)`. With paths (from the watcher), only those files are checked. Without paths, a
reconcile scan finds the changed files (size and date, then content hash), exactly as today.
**Both go through the same steps,** so there is one code path to get right:

```
1. Find changed files: for each path, check size and date, then the content hash.
   Classify as changed, deleted, touched (same content, new date) or skipped.
2. Remember the old state of these files: their chunk ids, the names they define,
   and their outgoing links.
3. Re-chunk the changed files (outside the write transaction).
4. In one SQLite transaction:
   a. apply each file's chunk changes by key (as today), with BM25 rows and call names;
   b. names_changed = names whose set of definitions changed (chunks added or deleted);
   c. relink: the chunks of the changed files, plus every chunk anywhere that calls a name in
      names_changed. Delete their links and resolve their calls again (same ≤5-definitions rule);
   d. record which callees gained or lost a caller.
5. Dirty texts:
   code   = new or changed chunks in the changed files
   usage  = chunks in the changed files
          + their old and new callees
          + callees from 4d
   Build only these texts, compare hashes with stored vectors, delete vectors whose text is gone.
6. Embed what's missing (this index → shared cache → model or API), code texts first.
7. Patch FAISS in memory after the commit (as today). Write the FAISS files lazily: after 30 s
   idle, on shutdown, and on refresh_index; never on every save, never blocking searches.
```

The rename example: step 4b finds `revoke_session` and `end_session`. Step 4c relinks the changed
files plus the callers of those two names. Step 5 builds the texts of the changed files' chunks
plus `Table.delete`'s usage: the same 9 texts the full update found, but without rebuilding the
other 24 to compare their hashes.

**What it needs from storage:** an index on `calls(callee_name)` (to find "all calls to name X"),
and caller lookups limited to the dirty chunks (`caller_refs(ids)` instead of all edges).

**Cost per save:** proportional to the change, not the repo. That's a stat per path, re-chunking a
file (milliseconds), relinking a few hundred calls, building a few dozen texts, and embedding the
changed ones.

**Verify mode:** today's global recomputation (every link, every text) stays, as
`codemem index --verify`. It is used by the tests and can be run when in doubt. It reports any
difference between the incremental result and a from-scratch result.

**Ignore rules or config change** (`.gitignore`, `.codemem.toml`): a full reconcile, which also drops
newly ignored files and adds newly included ones.

### 2.3 Consistency and concurrency

| Situation | What happens |
|---|---|
| Search during an update | SQLite readers see the state before or after a transaction, never half; FAISS is patched under its lock after the commit (as today) |
| The structure is committed but embeddings are still running | keyword and link results are current; the changed chunks' vectors are briefly stale; the catch-up budget usually covers this |
| Crash at any point | SQLite rolls back the open transaction; FAISS is rebuilt from SQLite if its version is behind; the startup reconcile re-finds pending files |
| Two processes on one index (two agent sessions) | `write.lock` serializes writers; a search waits for the other writer only up to its budget, then searches what is committed |
| A file changes while it is being indexed | its watcher event lands in the dirty set again; the next pass picks it up |
| FAISS save | the index is copied under the lock (fast) and written outside it, so searches don't wait 2 s |

### 2.4 Watcher

- Events carry paths. Each path is checked against the ignore rules and supported extensions
  before it enters the dirty set, so editor temp files and `node_modules` never trigger work.
- Directory moves and deletes: expand to the indexed files under that path.
- Bursts (`git checkout` writing 500 files) simply make a large dirty set; above 2,000 files, the
  watcher switches to a full reconcile.
- Watching `.git/HEAD` and refs triggers a reconcile on branch switches. The reconcile also
  records the indexed commit.
- If the OS watcher fails to start or hits Linux's watch limit: warn, and fall back to polling
  (a scan every 10 s).

### 2.5 Chunking and texts

1. **Python leading comments** become doc text (§1.4). Line ranges are unchanged.
2. **Window headers name their function.** Every window after the first gets the chunk's signature:
   ```
   # setup.py
   # in precompiled_wheel_utils
   # part 2/3 of def extract_precompiled_and_patch_package(...)
   ```
3. **Even-sized windows.** Choose the number of windows first, then split evenly. That gives 126
   lines → 3 windows of about 42 lines, instead of 64 + 63 + 5 (*measured* today). Every window
   stays within the model's limit.
4. **Huge blocks are split by lines** even inside one statement, at most 200 lines each, so a
   result points at a readable range. Functions and classes stay whole: one result is one function.
5. `TEXT_FORMAT_VERSION` goes up, so the eval keeps old and new indexes apart.

### 2.6 File coverage

- `max_file_size` = 10 MB (recorded in decisions.md).
- Every file the walk sees ends in exactly one place:

| Outcome | Stored as |
|---|---|
| indexed | `files` row, status `ok` (parse errors counted) |
| skipped: too large, generated, minified, binary | `files` row with status `skipped` and the **reason** (new column) |
| ignored (gitignore, default patterns, always-skipped folders) | counted in `meta.coverage` |
| not code (no supported language: `.md`, `.yaml`, `.sql`, ...) | counted by extension in `meta.coverage` |

- `index_status` and `codemem status` show the coverage. For example: "6,235 indexed · 3 skipped
  (2 generated, 1 too large: vllm/x.py 12 MB) · 410 not code (.md 220, .yaml 120, ...)".
- Parked: a plain-text chunker for non-code files (docs, configs), so "where is the config for X"
  works too.

### 2.7 Embedding providers

```toml
# .codemem.toml (per repo) or ~/.codemem/config.toml (per machine)
[embedding]
provider = "openai"                          # "local" (default) or "openai" = any OpenAI-compatible API
model = "Qwen/Qwen3-Embedding-8B"            # whichever models your account offers
base_url = "https://api.studio.nebius.com/v1"  # from the provider's docs
api_key_env = "NEBIUS_API_KEY"               # the key is read from this variable, never from a file
dimensions = 1024                            # optional: shorter vectors if the model supports it
query_prefix = "Instruct: Given a code search request, retrieve the relevant code\nQuery: "
```

- **Same model for indexing and queries,** always. The cache key includes the provider, model,
  dimensions and document prefix, so vectors from different setups never mix.
- **Indexing through an API:** batches of 64 texts, up to 4 requests in parallel, retries with
  backoff on rate limits and server errors. Vectors already stored are kept if a run fails, and the
  next update continues. This can make the first index of a large repo much faster than the
  laptop's GPU.
- **Queries through an API:** one HTTP call per search, cached for repeated queries. It adds a
  network round trip, to be measured.
- **Dimensions matter for memory.** Qwen3-Embedding-8B returns 4,096 numbers per vector, 4.6× our
  896. Asking for 1,024 (it is trained for shorter vectors) keeps FAISS small.
- **Privacy.** Remote embedding sends code to the provider. It is opt-in, and `index_status` shows
  "embeddings: remote (api.studio.nebius.com)".
- **Default stays local** `jina-code-embeddings-0.5b`: private, offline, free, and the model behind
  every result so far. The comparison (jina 0.5B and 1.5B; Qwen3-Embedding 0.6B, 4B, 8B;
  voyage-code-3) is the first tuning experiment, on the new eval sets.
- **Packaging:** the local model (PyTorch, about 2 GB installed) becomes an optional extra,
  `codemem[local]`, so an API-only install is small.

### 2.8 Search changes in this MVP (only robustness, latency and not gaming the eval)

- **Neutral weights** by default: tests, classes and blocks are no longer halved. The knobs stay
  for experiments.
- **BM25 query clean-up,** for latency on long queries:
  - stopwords are dropped from the query only (the index is unchanged);
  - if more than 32 distinct words remain, only the 32 rarest are kept (document counts from an
    `fts5vocab` table).

  Expected: 1.1 s → about 0.1 s on 250-word queries (to be measured).
- **Unchanged until tuning:** RRF k = 60, 50 candidates per list, field weights 10/3/5/2/1. All are
  documented in decisions.md as provisional or hand-picked.

### 2.9 MCP tools and portability

| Tool | Change |
|---|---|
| `search_code(query, k=10, path_prefix=None, kinds=None, tests="include")` | new optional `kinds` and `tests` ("include", "exclude", "only"); catch-up before searching; a freshness line when something is still being indexed |
| `get_chunk(ref)` | unchanged |
| `index_status()` | adds coverage, freshness (pending files, last update) and the embedder (local or remote) |
| `refresh_index()` | **new**: full reconcile now; waits up to 60 s; returns what changed |

Server instructions are reworded around the goal: "describe what you want to build or change in
plain words; use grep for exact strings; call refresh_index after git checkout or pull".

Portability:
- **Launch command.** `codemem init` writes a command that works however codemem was installed: the
  `codemem` command if it's on PATH (uv tool, pipx), otherwise `<this python> -m codemem mcp`
  (adds a `__main__.py`).
- **No stall on first use.** `codemem init` downloads the model with a progress bar.
- **Unchanged:** stdout carries only protocol messages, and Windows paths and locks work.
- **Tool names stay stable,** so Wilson's portable version and ours can be compared later.

### 2.10 Data model changes (schema v3)

- `files`: new `reason` column for skipped files.
- `meta.coverage`: ignored and non-code counts, by folder and extension.
- `calls`: new index on `callee_name`.
- Embedder key: `local:<model>|L<len>|<dtype>|<device>` or `api:<host>|<model>|dims=<d>|doc=<prefix hash>`.
- `schema_version` = 3. Old indexes are rebuilt once, cheaply thanks to the vector cache.

---

## 3. How we prove it

**Tests** (fake embedding model, fast):
- **Differential:** random edit scripts on the fixture repos (rename, move a function to another
  file, delete a file, add a 6th same-named function, edit comments, change `.gitignore`). After
  each step, the incremental index must equal a full rebuild: chunks, links, text hashes, vectors.
- **Freshness:** save a file, then search immediately; the result must reflect the save.
- **Crash:** stop between the structure commit and the embeddings; restart; the index must be
  complete and consistent.
- **Concurrency:** search during an update; two processes on one index.
- **Coverage:** skipped and non-code files are reported.
- **API embedder:** against a fake HTTP server, so no network is needed in tests.

**Benchmarks** (vLLM index on the M1, before and after):
- latency per save: a one-function edit, a reformatted file, a 200-file branch switch;
- a no-op update;
- time from save to searchable;
- search latency for short and long queries;
- memory.

**Retrieval: no eval change in this MVP.**
- Re-run the existing dev tasks (the 13 small-repo tasks locally) as a regression check: v3 against
  v2 and the grep baselines, with the same metrics as today.
- The eval's update-vs-rebuild check (B4) now exercises the incremental path. So it doubles as a
  consistency check on real repos and real commits.
- **Effects on the eval** (nothing to change in its code, but Andrew should know):
  - the text-format version goes up, so v3 gets new index keys and won't share indexes with v2;
  - default weights become neutral; our eval configs pin their weights explicitly, so their
    results don't move, but a config that leaves weights out will;
  - `search()` gains optional arguments and `update()` an optional `paths`; the adapter's calls
    stay as they are.

**Highlighted for later: why the eval should eventually change.** The eval's queries are whole
issue texts, and its answers are bug-fix locations. Our goal is short, vague, feature-level
questions ("I want to add OCR to uploads"), which this eval never asks. So it can't show the tool's
main strength, and tuning on it pulls the system towards matching issue texts. When we get to
tuning, I'd propose to Andrew a short-query version of the same tasks: one sentence per task in a
user's voice, written from the issue text only, with the same gold. The tasks that are feature
requests would be the closest match to our goal.

---

## 4. Work plan

Each phase ends with green tests, recorded measurements and a local commit (no push).

| Phase | Content |
|---|---|
| 0 | Your approval of this proposal. Docs consolidation (§6), so the approved design lives in the final docs. |
| 1. Robust core | incremental update and verify mode; watcher paths, quiet period and maximum wait, polling fallback, git HEAD; catch-up before search; lazy FAISS saves; coverage; chunker fixes. Differential, crash and freshness tests; vLLM before/after. |
| 2. Portability and providers | OpenAI-compatible embedder, Nebius smoke test (needs your key in the environment); `codemem[local]` extra; MCP tool changes and launch command; neutral weights; BM25 query clean-up. |
| 3. Regression check | the existing dev tasks locally (v3 vs v2 vs grep) and the B4 check; the full dev50 on a faster machine or with API embeddings. Optional: more precise links (§1.2). |
| 4. Docs final pass | measurements into the docs; then tuning, the eval change highlighted in §3, and the advanced design. |

---

## 5. Risks

- **The 2 s budget is a guess.** Measure staleness on vLLM, then set it.
- **Watch limits on Linux for very large repos.** The polling fallback covers them, but it is slower
  to notice changes.
- **API embeddings:** rate limits, cost per first index (tens of millions of tokens for a vLLM-size
  repo; check the provider's price), and privacy. All are opt-in and visible in status.

---

## 6. Docs after approval

| Keep (in `codemem/`) | Gets |
|---|---|
| `README.md` | what codemem is, the goal in three lines, install, quickstart (CLI, MCP), configuration, how to evaluate, team |
| `docs/architecture.md` | the high-level visual view and components, the freshness model, where the code lives; the still-valid parts of Wilson's `design-notes.md` and of PLAN's use case |
| `docs/data-model.md` | tables, records, ids, versions; **contracts**: MCP tools, the eval adapter, config |
| `docs/decisions.md` (renamed from `decisions-v2.md`) | every constant or choice with its reason and status (measured, provisional, hand-picked): Wilson's BM25 weights, jina-0.5b, k = 60, 50 candidates, the 0.5 s / 2 s / 2 s timings, 10 MB, windows; plus a **parked questions** section (standalone comments, class-level comments, callee descriptions, plain-text files) |
| `docs/exa.md` | ideas lifted from Exa or to research: `EXA_NOTES.md` and `exa-ideas.md` merged |
| `docs/advanced-design.md` | the research roadmap: kept, plus PLAN's and PROPOSAL's research questions |

Removed after merging: `docs/baseline-v2-diff.md`, `docs/design-notes.md`, `docs/exa-ideas.md`,
this proposal, and `CS329M/{PLAN, PROPOSAL_DRAFT, EXA_NOTES}.md`. `docs/benchmarks/*.json` stays as
data. `eval/README.md` is Andrew's and stays as is.
