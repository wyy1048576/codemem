# Track B: retrieval design

**Status:** a plan, written Nov 22, 2026. Nothing here is built yet. The shared context is in
[overview.md](overview.md). How retrieval works today is in [architecture.md](../architecture.md)
§3 and §6.

**Goal.** Find the right code more often and rank it higher, by giving codemem three
representations that cover each other's blind spots. Make the embedding model a choice. Settle
what happens when the user switches branches.

**Done means:**
1. keyword search with stemming, and an exact lookup for names the query spells out;
2. a typed graph of the code that search walks;
3. a query path that routes, merges, expands and tidies, where each step can be switched off and
   measured on its own;
4. three embedding options that a user picks with one setting;
5. a branch and worktree design with a size cap;
6. an ablation table that says which layer earns its place, and one frozen configuration
   (`codemem-layered`) handed to track A.

**What stays.** The two-stage indexer, the catch-up before every search, the freshness note,
SQLite as the source of truth, and the four MCP tools. Every new layer must fit the rule that
keeps updates fast: structure in stage A, within milliseconds; vectors in stage B, behind it.

---

## 1. In plain words

No single way of describing code finds everything.

- **Dense vectors** capture meaning. They match a question to code that shares no word with it.
  They are weak on exact names, and they know nothing about how pieces of code connect.
- **Keywords** capture exact words: names, error strings, rare terms. They miss synonyms and vague
  wording.
- **A graph** captures relationships: who calls what, what implements what, what tests what. It
  cannot start a search. It needs a first hit to walk from.

So codemem should keep all three, and let each do the part it is good at.

**The running example.** A small upload service, and a request an agent has never seen:

> Add OCR to the upload pipeline, so that text in uploaded images can be searched.

```
uploads/handler.py              handle_upload(file)            picks the stages for a file type
pipeline/registry.py            STAGES = {"audio": TranscribeAudio, "image": ThumbnailImage}
pipeline/stages/base.py         class Stage                    accepts(file), run(file)
pipeline/stages/transcribe.py   class TranscribeAudio(Stage)   speech in an audio file → text
pipeline/stages/thumbnail.py    class ThumbnailImage(Stage)    makes a preview of an image
search/indexer.py               index_text(doc_id, text)       makes extracted text searchable
tests/test_transcribe.py        4 tests of TranscribeAudio
```

The word "OCR" appears nowhere in this repo. What the agent needs is the existing stage that does
nearly the same job (`TranscribeAudio`), and the three places a new stage has to touch: the base
class, the registry, and the function that stores the text.

| Layer | What it finds for this request | What it cannot find |
|---|---|---|
| Keywords, with stemming | `handle_upload` and `uploads/handler.py` ("uploaded" meets "upload"); `ThumbnailImage` ("images" meets "image"); `pipeline/registry.py`; `index_text` ("searched" meets "search") | `TranscribeAudio`: it shares no word with the request |
| Dense vectors | `TranscribeAudio.run`: "get the text out of an audio file" is close in meaning to "get the text out of an image" | that a new stage must also be added to the registry |
| Graph, walking from `TranscribeAudio` | it extends `Stage`; `ThumbnailImage` is its sibling; `registry.py` refers to it; `handle_upload` runs it; `test_transcribe.py` tests it; it calls `index_text` | nothing, until another layer gives it `TranscribeAudio` to start from |

With grep alone, an agent gets there too, but by guessing. `grep OCR` finds nothing. `grep
pipeline` finds every CI file and data pipeline. It then reads files until the structure is clear.
That reading is what costs tokens and time, and it is what track A measures.

---

## 2. Where retrieval stands today

| Layer | What exists | What is missing |
|---|---|---|
| Keywords | SQLite FTS5 with BM25 over five weighted fields: name 10, signature 5, path 3, doc text 2, body 1. Identifiers are split into words and also kept whole. Stopwords are dropped from queries | stemming (a light version exists, switched off); an exact lookup for a name the query spells out |
| Dense | one vector per chunk for its code, in windows of about 3,000 characters; a second vector for a "usage text" that lists callers and tests by name. On vLLM: 109,562 code vectors and 35,167 usage vectors | a choice of model; shorter vectors (track C) |
| Graph | each chunk's call names, linked to definitions **by name only**, skipped when a name has more than 5 definitions. Used to write the usage text, and shown by `get_chunk` | search never walks it; no imports, no inheritance, no typed edges |
| Merging | reciprocal rank fusion: each list's top 50 adds `1 / (60 + rank)` | routing by query type; any use of the scores themselves |

**What our own measurements say about it:**

- **Relationships already pay off, even flattened.** On the first dev run, adding the usage vector
  was the largest single gain: function MRR went from 0.334 to 0.423.
- **codemem's edge is the query that names nothing.** When an issue names no right identifier,
  codemem beat tuned grep widely (function MRR 0.346 vs 0.188). When it names one, they are close
  (0.488 vs 0.424).
- **Name-only links are noisy.** On vLLM, 29% of call names resolve to one definition, 17% to 2–5
  (linked to all of them), 15% to more than 5 (not linked), and 39% to none (library calls).
  vLLM's three `append` methods each get 4,362 "callers", which are really `list.append`.
- **Merging by rank punishes a missing list.** A function nothing calls has no usage vector, so
  it can score in only two of three lists and ranks below chunks found in all three.

**Four ways the current design loses**, from the failure analysis in
[advanced-design.md](../advanced-design.md) §1:

| Pattern | Example | What would fix it |
|---|---|---|
| The query names the fix site, and it still isn't found | an issue says "probably in `Plotter._finalize_figure`"; BM25 splits the name into common words | an exact lookup that merging cannot bury (§3.2) |
| The query describes a symptom; the fix is in a caller | `Nominal._setup` ranks 2, the fix is in its caller at rank 48 | one step along the graph from the top hits (§3.3) |
| Tests that reproduce the problem outrank the code | three tests at ranks 1, 3 and 5 | tests become edges to the code they test, not rivals (§4, step 4) |
| A class and its methods crowd out the right method | `Blueprint` at rank 1, three siblings at 2–4, the right method at 24 | grouping a class with its matching methods (§4, step 4) |

---

## 3. The three representations

All three describe the same chunks and share one id per chunk. All three live in SQLite, so one
edit is still one transaction.

| | Dense vectors | Keywords | Graph |
|---|---|---|---|
| Answers | "what means the same as this?" | "where is this word or name?" | "what is connected to this?" |
| Built in | stage B (the model) | stage A (milliseconds) | stage A (milliseconds) |
| Stored as | one row per text window, plus 1-bit codes in memory (track C) | one FTS5 row per chunk | one row per edge |
| Cost of an edit | the changed chunks are embedded again | their rows are rewritten | their edges are relinked |
| Needs a model | yes | no | no |

Two of the three need no model. So a repo is searchable by keywords and graph about a minute after
indexing starts, and by meaning as embedding catches up. A search also still works, in a reduced
way, when the model or the API is unavailable.

### 3.1 Dense vectors

**Keep:** one vector per code window, with the short header (path, enclosing class, doc text)
that the code alone doesn't state.

**Change:**
- the model becomes a choice of three (§5);
- vectors are stored shorter, and scanned as 1-bit codes with exact rescoring. Track C owns this.
  What B relies on is that the top results come back with **exact** similarity scores.

**Open, decided by experiment B-E3:** whether the usage vector stays. It costs a quarter of all
vectors. The graph may do its job better: instead of embedding the sentence "called by
`handle_upload`", search can walk the edge from `handle_upload`.

### 3.2 Keywords

**Change 1: stemming on words, never on names.** Stemming cuts words to a common root, so
"uploaded", "uploads" and "upload" meet. Today "disabled" in a query does not match
`disable_user` in the code. Each token goes one of two ways:

| Token | Example | Treatment |
|---|---|---|
| a whole identifier | `handle_upload`, `TranscribeAudio` | kept exactly as written. `Session` and `Sessions` are different classes |
| a word: a part of an identifier, or a word of a comment, a docstring or the query | `upload`, `transcribe`, "uploaded" | stemmed with a standard English stemmer (Snowball), skipped for tokens under 4 letters |

The same function tokenizes the code and the query, as today, so both sides always agree.

**What the evidence says, both ways.**
- *Splitting identifiers and keeping them whole,* which codemem already does, is well supported.
  On a public code benchmark it lifted Go from 0.31 to 0.56 nDCG@10, and Java by 28% *(reported)*.
- *Stemming is not a sure win.* The one study of stemmers on code search found changes of −0.011
  to +0.007 in average precision on bug reports, with more queries hurt (92) than helped (53). On
  short two-word verb queries it helped twice as often as it hurt, 18 to 9 *(reported; 2012, one
  Java project)*.

A vague request looks like the second kind of query, and an issue text like the first. So stemming
is a hypothesis with a gate (B-E1), reported separately for the two kinds, and it is switched on
by default only if it passes.

**Change 2: an exact lookup for names.** If the query contains something that looks like a name
(text in backticks, a dotted path, `CamelCase`, `snake_case`, a file path, a quoted string), look
it up directly in the chunk table. A name that matches exactly one chunk is **pinned**: no later
step may rank it lower. A vague request contains no such name, so this step costs it nothing.

**Change 3 (an experiment): callers as a keyword field.** A sixth field holding the names of a
chunk's callers and tests. It gives keyword search the benefit of the usage text without a second
vector.

**Not changing:** SQLite FTS5 itself. It keeps the keyword index inside the same transaction as
everything else. A substring or regex index is out of scope: that is grep's job, and codemem
works next to grep.

### 3.3 Graph

**Nodes** are the things codemem already stores: chunks (functions, methods, classes, blocks) and
files.

**Edges** are typed, and each has a confidence between 0 and 1:

| Edge | From → to | Found by | Used for |
|---|---|---|---|
| `contains` | file → chunk, class → method | already stored | grouping a class with its methods |
| `calls` | function → function or class | call names, resolved by the rule below | callers and callees |
| `imports` | file → file | import statements, resolved per language | scoping the `calls` rule; "what depends on this file" |
| `inherits` | class → base class or interface | the class header | siblings: other classes with the same base |
| `refs` | chunk → a definition it names without calling it | identifiers that match an imported or same-file definition | registries, decorators, type annotations |
| `tests` | test → code under test | a `calls` or `refs` edge whose source is a test; file-name pairs (`test_x.py` and `x.py`) at low confidence | "tested by" |

In the running example, the registry line `"audio": TranscribeAudio` is a `refs` edge. Without
it, nothing connects the registry to the stage, because the registry never calls it by name.

**One more edge, as an experiment only:** `changes-with`, between files that changed in the same
commits. It is cheap to compute from git history and works in every language. But a November 2026
study found that co-change partners of the right function predict it barely better than chance
*(reported)*. It is tested in B-E3 and is off unless it earns its place.

**The rule for linking a call**, which replaces "link to every definition with that name":

| The call looks like | It is linked to | Confidence |
|---|---|---|
| `self.x()`, `this.x()`, `Class.x()` | that class's method, or a base class's | high |
| `x()`, and `x` is defined in the same file | that definition | high |
| `x()` or `m.x()`, and `x` or `m` is imported | the imported definition | high |
| `x()`, with one definition in the repo | that definition | medium |
| `obj.x()`, receiver unknown | methods named `x` on classes the file defines or imports | low, split among them |
| anything else | nothing | |

This is the "import-aware call links" question from advanced-design, now with a rule. It removes
the `list.append` collisions, because `list` is not a class the file defines or imports.

**What to expect from it.** One open-source project that links calls this way (tree-sitter, names
and imports) reports that its confident links are 93 to 100% correct, but that it finds very
different shares of the true links per language: TypeScript 96%, Java 69%, Go 67%, C 66%, Python
45%, C++ about 23%, Rust 8% *(reported; the project's own numbers)*. So the graph will be thin in
Rust and C++, and B-E6 measures our own numbers before the graph is trusted in those languages.

**Why tree-sitter, not a language server.** A language server gives exact links: Pyright's
references were 100% correct in one 2026 study, against 76% for grep *(reported)*. But it needs
each project's toolchain installed, differs per language, and starts cold: in the same study a
first query returned 1 of 14 references until the files had been opened. codemem has to work on
any checkout with no setup, in nine languages, and update in milliseconds. Two alternatives are
ruled out: GitHub's stack-graphs was archived in September 2025, and SCIP indexes record
definitions and references but no call edges *(reported)*. The edge table is the seam: a language
server can fill the same table later, on demand, for the unresolved links of the top results.

**Storage and updates.** One row per edge: source, target, kind, confidence. Edges are built in
stage A. The rule for what an edit can change stays the one that keeps updates small: the edges
*from* the changed files, and the edges *to* any name whose set of definitions changed.

**What published studies say about graphs for finding code.** They disagree, so both sides are
listed. All figures are *(reported)*.

| Finding | Study | Points which way |
|---|---|---|
| One step along call and containment edges from the top 5 dense hits lifted Recall@20 from 0.42 to 0.60. Each neighbour also had to be in the dense top 500 and pass a model's check. Call edges gave the most, imports and inheritance almost nothing | SpIDER, 2026 | for expansion, with a filter |
| Expanding around grep hits: file Acc@5 55.7, against 48.2 without | LARGER, 2026 | for |
| An agent with graph traversal tools: function Acc@10 71.5, against 66.1 without traversal | LocAgent, 2025 | for |
| Adding a PageRank list to BM25 lowered MRR from 0.357 to about 0.35. Callers of the right function carry signal; callees, siblings and co-change partners are near chance | GraphScent, Nov 2026 | against a PageRank list; for callers only |
| With a graph linked by name, like ours: graph tools changed function Acc@10 by −0.012 to +0.078 over grep across nine models, and by −0.022 to +0.036 on top of embedding search | Bellam, 2026 | weak |
| A tuned retriever with no graph beat the graph agent, 82.1 to 77.4 | SweRank, 2025 | against needing a graph at all |
| Repo-map tools lifted recall@10 from 0.72 to as much as 0.83, and task completion did not move | Sepidband et al., Nov 2026 | better retrieval may not reach the end result |

Three things hold across them. Callers matter more than callees. Spreading without a filter (two
steps, PageRank) adds noise. A gain in retrieval may not survive to the end of a task, which is
why track A, not this table, has the last word.

**One gap in all of them:** every study uses bug fixes. In a bug fix the sibling of the broken
function is irrelevant. In a request like the OCR one, the sibling *is* the answer. So inheritance
and sibling edges may matter for us where they did not for them. That is a hypothesis, and B-E3
tests it on pattern-following tasks separately.

**How search uses the graph** (steps 4 and 6 of §4), designed from that evidence:
- **Expansion, with a filter.** From each of the top results, look one step along call edges
  (callers weigh more than callees) and at the members of the same class. A neighbour is admitted
  only if some layer already ranked it in its top 300, so the graph can lift a chunk but not
  invent one. At most 10 are added, each shown under the result that brought it in. A chunk with
  thousands of callers passes on almost nothing.
- **Relation lines.** A card shows its chunk's closest relations in one or two lines, so the agent
  need not ask again. This uses every edge kind, including siblings, and costs no ranking risk.

No PageRank list and no unfiltered second step, unless B-E3 shows a gain from them on our tasks.

---

## 4. The query path

```
 "Add OCR to the upload pipeline, so that text in uploaded images can be searched."
        │
        ▼
 1. READ THE QUERY (no model)
        does it spell out a name, a path, a quoted string?  → exact lookup, pinned
        how name-like or how wordy is it?                   → weights for step 3
        │
        ▼
 2. CANDIDATES: 100 to 200 from each layer
        keywords (BM25, stemmed)         dense (1-bit scan, then exact rescoring)
        │
        ▼
 3. MERGE the lists into one
        │
        ▼
 4. WALK THE GRAPH one step from the top results: lift the neighbours that
        another layer also found
        │
        ▼
 5. TIDY: at most 2 results per file · a class with its matching methods ·
          tests listed under the code they test
        │
        ▼
 6. CARDS with relation lines, under a token budget, and the freshness note
```

**In the example.** Step 1 finds no name to look up, and marks the query as wordy, so the dense
list weighs more. Step 2: keywords return `handle_upload`, `ThumbnailImage`, the registry and
`index_text`; dense returns `TranscribeAudio.run`. Step 3 merges them. Step 4 walks from
`TranscribeAudio`: `handle_upload` runs it and it calls `index_text`, and keywords found both
already, so both move up. Whether to also walk inheritance and reference edges, which would lift
`Stage` and the registry, is what B-E3 tests on tasks like this one. Step 5 folds
`TranscribeAudio.run` into its class. Step 6 returns:

```
1. pipeline/stages/transcribe.py:12-58  TranscribeAudio  [id 412]
   class TranscribeAudio(Stage):
   |  extends Stage (pipeline/stages/base.py:8) · sibling: ThumbnailImage
   |  referred to in pipeline/registry.py:21 · run by handle_upload (uploads/handler.py:40)
   |  calls index_text (search/indexer.py:15) · tested by tests/test_transcribe.py (4 tests)
```

One card names the pattern to copy, the base class, the registry line, the caller, the function
that stores the text, and the tests. That is the answer to "where do I start?" in about 100
tokens.

**The choices inside each step, and how each is tested:**

| Step | Default to start from | Variants to test |
|---|---|---|
| 1. Read the query | pin exact unique name matches | weights set by query type; no routing |
| 2. Candidates | 100 per layer | 50, 200 |
| 3. Merge | rank fusion with weights, as today | **score every candidate in every layer:** a chunk that keywords found but the dense list missed gets its dense score computed directly, from its vector on disk, so no chunk is punished for a missing list; then a weighted sum of normalised scores; last, a small learned model over six to eight signals |
| 4. Graph walk | one step along calls and class members; a neighbour must be in some layer's top 300; at most 10 added | off; no filter; one edge kind at a time (inheritance, references, changes-with); **a random neighbour, as a placebo**; two steps; PageRank |
| 5. Tidy | 2 per file, grouping on | off |
| 6. Cards | relation lines on, 8 cards | relation lines off; 5 or 10 cards; say "no strong match, try grep for X" when every layer scores low |

**Why precision over recall.** An agent pays for every token of every card. A wrong card near the
top costs twice: the tokens to read it, and the turn spent following it. So the default returns
fewer cards, and the metrics that matter are precision in the top 5 and tokens to the first right
result, not recall at 50.

**What the evidence says about merging** *(reported)*. In general text search, a weighted sum of
normalised scores beat rank fusion on all nine datasets of the standard comparison (Bruch et al.,
2023), and its one weight could be set from a small sample of queries. On code the picture is less
kind to merging at all: a 2026 study found that fusing BM25 and dense lists by rank never beat the
better of the two alone on its tasks. Dense models also collapse on short keyword queries (nDCG@10
of 0.00 to 0.02 in one benchmark, against 0.45 to 0.58 on long ones). That is the case for step 1:
a short, name-like query should lean on keywords, and a wordy one on meaning.

**A learned merge is the last resort, on purpose.** It can overfit to the eval's issue texts. If we
get to it, it trains on the dev split with vague and issue-style queries mixed, and is checked on
repos it never saw.

---

## 5. Embedding model options

**In plain words.** The embedding model turns code and questions into vectors. A larger model
usually understands more, and costs more memory and more time per text. Today codemem has one
default, chosen for laptops. The plan is three options behind one setting.

### 5.1 The three options

Figures marked *(reported)* come from model cards, leaderboards and provider pages read on Nov 22.

| | `light` (the default) | `qwen8b-local` | `api` |
|---|---|---|---|
| For | any Mac with 16 GB | a Mac with 32 GB, or 24 GB with little else running; code must not leave the machine | anyone with a key; no model on the machine |
| Model | to be chosen by B-E5 among: **EmbeddingGemma 2** (0.27B, Oct 2026), **Qwen3-Embedding-0.6B**, and today's `jina-code-embeddings-0.5b` as the baseline | Qwen3-Embedding-8B, weights stored in 8 bits (an 8 GB file) | Qwen3-Embedding-8B on Nebius, full-precision weights |
| Vector | 768 to 1,024 numbers, stored shorter (track C) | 4,096, stored as 1,024 | 4,096, stored as 1,024 |
| Runs as | inside codemem, or a local server (llama.cpp or MLX) | a local server: `llama-server --embedding --pooling last`, or MLX | HTTPS |
| First build of a large repo (about 40M tokens) | about 2 hours on a 16 GB M4 for EmbeddingGemma 2 *(reported)*; 4.4 hours on an M1 with today's model | not practical: 9 to 10 hours on an M3 Max, 40 to 70 hours on an M1 *(reported, scaled)*. Build through the API, or accept days | $0.40. About 100 minutes at the rate limit Nebius shows as an example; less with a raised limit or its low-priority tier *(reported)* |
| One query | 15 to 70 ms | under a second for a short query *(estimate)* | 0.3 s on a good day; provider medians of several seconds have been observed *(reported; to measure)* |
| Model memory | 0.3 to 2.2 GB | 8 to 9 GB | none |
| Code leaves the machine | no | no | yes |

**The three options exist for different people, not for different quality levels.** That is the
main thing the research changed.

### 5.2 Is a bigger embedding model better for us? Both sides

All *(reported)*.

| For | Against |
|---|---|
| On classic code search (find code from a description), Qwen3-Embedding-8B scores 80.7 and its 0.6B sibling 75.4. It is the best model on that board that did not train on the board's own data | On finding the code to change for an issue, which is our task, Qwen3-8B scores 20.3 on CORE-Bench and today's jina 0.5B scores 20.8. The 0.6B sibling scores 17.0 |
| Its vectors can be cut to any length, and keep about 99% of their quality at 512 numbers and 96% at 256 in third-party tests on general text | It is no longer the strongest open model overall: it ranks fourth on the multilingual board, behind models of 12B and 27B |
| EmbeddingGemma 2, at 0.27B, scores 77.9 on the same code board: most of the 8B's score at one thirtieth of the size | No issue-to-code numbers exist yet for EmbeddingGemma 2. It is six weeks old |
| | Training on the task beats size: fine-tuning Qwen3-8B on issues lifts it from 20.3 to 32.8, and a 7B model trained for issue localization scores 22.4 |

**Reading.** Size alone buys little on the task we care about, and the model we already use is
competitive on it. The 8B options are worth building because they are a clean way to test this on
our own tasks, and because an API removes the model from the laptop. But the default is whatever
B-E5 shows on our tasks and on vague requests, not the largest model. Training a model on issue
and code pairs is the stronger lever. It is idea 4 in
[advanced-design.md](../advanced-design.md) and is outside this phase.

### 5.3 Rules that keep vectors from different setups apart

1. **One index per vector space.** The model, the precision of its weights and the runtime are
   all part of the embedder key. Vectors with different keys never mix.
2. **Which setups make the same vectors?** For a model fine-tuned from Qwen3-8B, weights at 8 bits
   give almost the same vectors as full precision (cosine 0.9995 on average). Weights at 4 bits do
   not: 0.973 on average, 0.937 at worst, and the top result changes for about 2% of queries
   *(reported)*. So "build through the API, then update and search locally at 8 bits" is plausible
   and nobody has tested it. Experiment B-E5b tests it. A 4-bit local model always gets its own
   index.
3. **Cut and re-normalise ourselves.** Nebius accepts a `dimensions` setting but does not document
   whether this model honours it. codemem forwards the setting today and does not check the length
   that comes back. It should check, cut and re-normalise.
4. **Each model gets its own query instruction.** Qwen wants `Instruct: <one sentence>\nQuery:`
   before a query and nothing before a document. EmbeddingGemma 2 wants `task: code retrieval |
   query: `. Today the local path gives jina's prefixes to any model that lacks jina's prompt
   names (`embedder.py`), which would quietly cost other models accuracy.
5. **Precision on the Mac GPU is per model.** Today `auto` means half precision there.
   EmbeddingGemma 2's card says half precision silently degrades its vectors *(reported)*.

### 5.4 Local Qwen 8B: what goes wrong

Small mistakes here change the vectors without any error *(reported)*:

| Mistake | Effect |
|---|---|
| llama.cpp without `--pooling last`, or without the closing end-of-text token | about 20% lower scores |
| closing with the chat end-of-turn token instead of the end-of-text token | vectors that barely resemble the right ones (cosine 0.5 to 0.8) |
| Ollama's `qwen3-embedding:8b` tag | it is the 4-bit file, and Ollama adds no query instruction |
| a host that returns vectors that are not normalised (Fireworks does) | wrong scores unless we normalise |

So the `qwen8b-local` option ships with a check: embed 20 fixed texts at start-up and compare
them with stored reference vectors. If they don't match, refuse to index and say why.

### 5.5 The API: batching, limits, failure, privacy

```toml
[embedding]
preset = "api"                 # light | qwen8b-local | api; the lines below are what "api" fills in
provider = "openai"
base_url = "https://api.tokenfactory.nebius.com/v1"
model = "Qwen/Qwen3-Embedding-8B"
api_key_env = "NEBIUS_API_KEY"
dimensions = 1024
query_prefix = "Instruct: Given a question about a codebase, retrieve the code that answers it\nQuery:"
```

The older host in today's README, `api.studio.nebius.com`, still answers; Nebius's current
documentation gives the host above.

| Topic | Today | Change |
|---|---|---|
| Batching | 64 texts per request, 4 requests at once, 6 tries | batch by tokens, not by count, with texts sorted by length; back off on the provider's rate-limit reply; use the low-priority tier for first builds |
| Resuming | stage B's queue already survives a stop | show progress and remaining cost in `codemem status` |
| Cost | not shown | print the estimate before a first build ("about 38M tokens, $0.38") |
| The API is down | each search waits about 31 s, then fails | answer at once from keywords and the graph, with a note, and show the error in `index_status` |
| Query time | one request per search | keep the cache of recent query vectors; measure the real delay (B-E5 reports it) |
| Privacy | `codemem status` says code is sent to the provider | add the provider's terms in one line. Nebius's documents disagree: its quick guide says content is not used for training; its terms say inputs are stored and used to train small helper models unless you opt out *(reported)* |
| A second provider | any OpenAI-compatible endpoint works | list DeepInfra as the tested fallback: same model, same price |

### 5.6 Faster first builds, whatever the model

The first build is the worst moment of every option. Two changes help all three:
- **Progressive indexing.** Keywords and the graph are ready about a minute after indexing starts.
  Vectors follow in priority order: files the agent touches or searches first, the rest after.
  Search notes already say what is still pending.
- **Build once, reuse.** The vector cache is keyed by model and text, so a cache built by one
  teammate or by CI serves the others. Cursor found teammates' copies of a repo 92% alike.

### 5.7 Experiments for this section

| # | Experiment | Pass |
|---|---|---|
| B-E5 | jina 0.5B, EmbeddingGemma 2, Qwen3-0.6B and Qwen3-8B (API), at full length and at 256, 512 and 1,024 numbers, on the dev tasks in both query kinds. Reported with build time, query time and memory | chooses the `light` default: the best accuracy among models that build a 100k-chunk repo in under 3 hours on a 16 GB Mac |
| B-E5b | The same 1,000 chunks and 100 queries embedded by the API and by the local 8-bit model | the two top-10 lists share at least 95% of their entries; then the two setups may share an index |
| B-E5c | Query delay through the API, 200 searches at different times of day, for two providers | reported. A query must be embedded by the same model as the code, so a slow API cannot be patched with a small local model. If the median is over 1 s, the remedies are a faster provider, or, on a Mac that can hold it and if B-E5b passes, the local 8-bit model for queries |

---

## 6. Branch switches and worktrees

**The worry.** If the user keeps switching branches, will codemem be embedding all the time? Does
it need one index per branch? How big does the cache get?

### 6.1 What happens today

1. The watcher sees the branch head change and waits for git to finish writing files.
2. A full check finds the files whose content changed: 0.3 to 0.5 s on vLLM.
3. Stage A re-chunks only those files, in milliseconds each.
4. Stage B looks up every changed text in the machine-wide vector cache, by model and text hash.
   Only a text never seen before on this machine goes to the model.
5. Searches meanwhile answer at once, with a note naming the files still pending.

So there is **one index per checkout, not per branch**, and switching back to a branch seen
before costs no model time at all.

### 6.2 What a switch costs

The eval's logs give real numbers. Each run stepped one index through 24 task commits per repo,
a few days apart. That is close to "switch to a branch a few days of commits away".

| Repo (chunks) | Texts needing new vectors: median | 9 in 10 updates stay under | Whole update, M5 GPU, today's model (median) |
|---|---|---|---|
| Godot (195k) | 626 | 3,994 | 32 s |
| home-assistant (176k) | 2,758 | 8,536 | 87 s |
| airflow (104k) | 1,635 | 4,278 | 59 s |
| transformers (89k) | 2,044 | 4,018 | 64 s |
| vscode (229k) | 8,730 | 25,987 | 323 s |
| llama.cpp (32k) | 3,182 | 7,583 | 124 s |

The time covers re-chunking and embedding. On an M1 the model is about 4 times slower. Through an
embedding API the same work takes seconds. Each new vector adds about 4.5 KB to the cache today,
and 0.5 to 2 KB in track C's format. A switch that brings 3,000 new texts therefore adds about
14 MB today, and 2 to 6 MB after track C.

**In plain words:** the first visit to a branch costs one to five minutes of background embedding
on a laptop, during which keyword and graph search are already current. Every later visit is free.
The storage is small.

### 6.3 What to change

| Change | Why | Size |
|---|---|---|
| **Drop obsolete work when the head moves again.** Queued chunks that no longer exist after the next switch are removed from the queue | switching back and forth quickly must not leave a pile of embedding for branches the user already left | small |
| **Embed in priority order after a switch:** files the agent searched or edited first, the rest after | the queue can be minutes long; the part the agent needs is usually seconds | small |
| **Keep vector bytes in one shared store.** Today each index holds its own copy of every vector, and the cache holds another. Proposed: the index row keeps only the text hash, and the bytes live once per machine | removes a copy (track C §4.4), and makes a new worktree cost no vector storage | medium; a schema change |
| **A size cap with least-recently-used eviction** on that store (track C §4.7) | the cache only grows today | small |
| **A new worktree starts from a copy of the main checkout's structure**, then updates the difference | measured on vLLM: 23 s to a first current search this way, against 99 s from scratch. With vectors out of the index file the copy shrinks from 0.8 GB to under 0.5 GB | built and tested on a shelved branch |

Eviction is safe by construction. The store is a cache: the code is the source of truth. If a
vector that a live chunk needs was evicted, the chunk goes back on the queue and is embedded
again, and the search note says so meanwhile.

### 6.4 What other tools do

All *(reported)*, from each tool's own documentation.

| Tool | On a branch switch | Limit it states |
|---|---|---|
| Cursor, until mid-2026 | a tree of file hashes found what changed; embeddings were cached by chunk content; a new checkout started from the most similar existing index, which cut the slowest first queries from 4 hours to 21 seconds | 250,000 files |
| Cursor, since July 2026 | no embeddings; a local text index tied to a commit, with edits layered on top, rebuilt after a big pull or switch | about half the source size |
| Continue | branch tags over a cache keyed by file content; an entry is deleted when no tag uses it | none documented |
| Zoekt (Sourcegraph) | one index for all branches, with a mark per file saying which branches hold it | 64 branches per repo |
| GitHub code search | keyed by file content; the default branch only | — |
| claude-context | one index per folder path; cleared by hand | — |

Our design is the same family as Cursor's old one and Continue's: vectors keyed by content, and
one small view per checkout. No tool in this list documents a size cap or an eviction rule. Ours
would.

### 6.5 What stays open

- **Agents in several worktrees through one MCP server.** A tool call does not say which folder it
  came from. The shelved design added a `root` argument to every tool, which agents must
  remember to pass. Whether an agent host starts one server per worktree is undocumented. This
  needs a test with a real agent before any design is chosen.
- **How large real branch differences are.** The table above is drift along one branch. A
  long-lived feature branch can differ more. Experiment B-E8 measures it on real pull-request
  branches.

---

## 7. Experiments and gates

All of these run on the retrieval eval, which needs no agent and no API money. Each is run with two
kinds of query: the issue text, and track A's vague rewrite of the same task. Thresholds are
proposals to agree before running.

| # | Experiment | Question | Gate |
|---|---|---|---|
| B-E0 | **Headroom.** For every dev task where the right function is not in the top 10: was it in the top 200? One edge away from a top-10 result? Named in the query? | Which lever can fix the most misses, before building any? | orders B-E1 to B-E4 |
| B-E1 | Stemming: none, the light version, Snowball on words | Does stemming help code queries, and does it hurt name-heavy ones? | at least +2 points of function success@10 on vague queries; no significant loss on queries that name an identifier |
| B-E2 | Exact lookup and pinning | Does it fix the "names the fix site" misses? | every dev query that names a unique right chunk has it in the top 3 |
| B-E3 | Relationships, four ways: the usage vector (today), callers as a keyword field, one-step graph expansion, and combinations. Then one edge kind at a time, name-only links against the new linking rule, and a random-neighbour placebo. Reported by kind of task (bug fix, pattern-following feature) and by how many steps the right function is from the nearest hit | Does walking the graph replace the usage vector? Which edges matter, and for which tasks? | expansion must beat the placebo; without the usage vector it must be within noise of today's default, or better, before the usage vector is dropped |
| B-E4 | Merging variants (§4, step 3) | Is rank fusion leaving accuracy on the table? | a variant is adopted only at +2 points on both query kinds |
| B-E5 | Embedding models at several vector lengths (§5) | How much does a bigger model buy, on our tasks and on vague queries? | reported as a curve of accuracy against cost; picks the default per option |
| B-E6 | Link quality: 200 hand-checked calls per language, and one Python repo compared with a language server | How precise are the new links? | at least 90% of high-confidence links correct |
| B-E7 | Cards: relation lines on and off; 5, 8, 10 cards | Do richer cards save an agent turns? | judged end to end by track A |
| B-E8 | Branch differences: changed chunks between a repo's main branch and 50 open pull-request branches, for three repos | How big is a real switch? | reported; sets the default cap |

**B-E0 comes first, and is cheap.** It only rereads results the eval already produces. If almost
no miss is one edge away from a hit, the graph work shrinks to relation lines. If most are, it
moves to the front.

---

## 8. Work packages

Sizes are rough working days for one person. "Core" marks what the paper needs. The rest improves
the product and can slip.

| # | Work | Deliverable | Done when | Needs | Days |
|---|---|---|---|---|---|
| B1 | **Headroom analysis** (B-E0), and a per-step switch for every stage of the query path | the miss table; settings that turn each step on and off | the team has ordered the rest of this list from it | the eval's dev runs | 2 |
| B2 **(core)** | **Keywords:** Snowball stemming on words, the exact lookup with pinning, callers as a field | a new tokenizer version; B-E1 and B-E2 results | gates of B-E1 and B-E2 judged; update and rebuild give the same results | — | 4 |
| B3 **(core)** | **Graph:** the typed edge table; the linking rule for Python and TypeScript first, then Go, Java, Rust, C and C++; `imports`, `inherits`, `refs`, `tests` | edges in the index; B-E6's precision numbers | a one-function edit still updates in under 0.5 s on vLLM; `codemem index --verify` passes | B1 | 9 |
| B4 **(core)** | **Query path:** routing, merging variants, one-step expansion, tidying, relation lines | the path of §4, every step switchable; B-E3 and B-E4 results | the frozen `codemem-layered` configuration is handed to track A | B2, B3, C2 | 6 |
| B5 **(core)** | **Embedding options** (§5): three presets, the local Qwen runtime, API batching and its failure handling | one setting that selects an option; B-E5's curve | each option builds and searches the sample repo from a clean machine by following the README | — | 5 |
| B6 | **Branches:** drop obsolete queue work, priority order, the shared vector store, the worktree start | §6.3 built; B-E8's numbers | switching between two cached branches embeds nothing and finishes stage A in seconds | C4 | 5 |
| B7 | **Ablations and freeze:** run the whole ladder on the test split once | the paper's retrieval table | numbers for three languages, both query kinds; six once track A has labelers for the other three | A's task sets | 3 |

**When** (the dates are in [overview.md](overview.md) §8):

| By | Packages | What it gives |
|---|---|---|
| **Dec 1** | B1, B2, B3 for Python and TypeScript, B4, and from B5 the `api` and `light` presets | the layered retrieval we present: stemming and exact lookup if they pass their gates, typed edges, the query path with relation lines on cards, two embedding options |
| **Dec 8** | the rest of B5 (the local Qwen 8B preset, and the test of API against local vectors); the merging experiments; B7 in three languages, on the test split, once | the third embedding option, and the paper's retrieval table, layer by layer |
| **Later, no date** | B3 for Go, Java, Rust, C and C++; B6 | the linking rule in every language; branch switching, built |

B1 comes first because it orders everything else. B2 and B5 do not touch each other and go side by
side. B4 needs B2, B3 and track C's vector store interface, which the two tracks agree on by
Nov 25.

---

## 9. What track B needs from, and gives to, the others

| With | B needs | B gives |
|---|---|---|
| **Track A** | vague rewrites of the dev tasks, a first subset by Nov 27; end-to-end runs that compare card formats (B-E7); later, gold labels for Go, Java and Rust | two frozen configurations: `codemem-today` (the current default, frozen now as the baseline) and `codemem-layered`. Stable tool names and card format, with any change announced before A's runs |
| **Track C** | a vector store that returns exact scores for its top results; the cost of each embedding option | which vector types exist; the embedding options and their vector lengths; the branch design the cache must serve |

**Tell track A as soon as something can run.** Track A starts on today's codemem, on two
pilot repos ([track A](track-a-evals.md) §2.2). Each time a new piece of retrieval works on one
repo, write it in the work log ([CONTRIBUTING.md](../../CONTRIBUTING.md) §4): the configuration
name, the commit, and which index-time settings changed. Track A then indexes its pilot repos
again and runs them. Do not wait for the freeze: an early run on a rough version finds problems
the retrieval eval cannot.

**Contracts that must not move without telling track A:** the MCP tool names and arguments, the
card layout, `search()` and `format_results()`, and `Config.index_settings()`
([data-model.md](../data-model.md) §12). New tokenization, new edges and a new vector format are
all index-time settings: each must appear in `index_settings()`, so two eval systems never share
an index by mistake.

---

## 10. Risks and open questions

| Risk or question | Why it matters | What we do |
|---|---|---|
| The graph adds noise instead of signal | hubs and wrong links can flood the top 10 | confidence on every edge, shares divided among neighbours, B-E6 before B4, and a switch to turn expansion off |
| Stemming hurts name-heavy queries | codemem must not get worse where grep is already good | names are never stemmed; B-E1 reports the two query kinds separately |
| Tuning to the eval | issue texts are not what agents type | every gate is judged on vague rewrites too; the test split is run once, at the end |
| The linking rule differs by language | nine languages, one rule | Python and TypeScript first; a language without the rule keeps name-only links at low confidence |
| Richer cards cost tokens | relation lines add about 50 tokens per card | B-E7: keep them only if they save an agent turns end to end |
| A bigger embedding model changes little on code | the Nov 4 memo found small gains from size alone on public code benchmarks | B-E5 measures it on our tasks before the default is chosen |
| Should README and docs files be indexed? | a vague request often matches a "how to add a stage" page better than any function | not in this phase's core; it is the first step of the beyond-code follow-up ([overview.md](overview.md) §11) |

---

## Sources

Items marked *(reported)* in this file were read by research passes on Nov 22, 2026. Re-read a
page before citing it in the paper.

**Graphs for finding code**
- SpIDER, https://arxiv.org/abs/2512.16956 · LARGER, https://arxiv.org/abs/2605.16352 ·
  LocAgent, https://arxiv.org/abs/2503.09089 · GraphScent, https://arxiv.org/abs/2611.17527
- Bellam, https://arxiv.org/abs/2610.33958 · SweRank, https://arxiv.org/abs/2505.07849 ·
  Sepidband et al., https://arxiv.org/abs/2611.07286
- KGCompass, https://arxiv.org/abs/2503.21710 · RepoAtlas, https://arxiv.org/abs/2609.16936 ·
  Codebase-Memory, https://arxiv.org/abs/2603.27277

**Linking calls**
- A tree-sitter linker's own accuracy report, https://github.com/squid-protocol/gitgalaxy
- Does a language server save tokens for coding agents?, https://arxiv.org/abs/2608.13568
- stack-graphs (archived), https://github.com/github/stack-graphs · SCIP,
  https://github.com/sourcegraph/scip

**Keywords and merging**
- Identifier tokenization for code search, https://arxiv.org/abs/2605.18561
- Hill et al., stemmers on code, SCAM 2012 (slides),
  https://ieee-scam.org/2012/resources/Emilly_Slides.pdf
- Bruch et al., An Analysis of Fusion Functions for Hybrid Retrieval,
  https://arxiv.org/abs/2210.11934
- Hybrid retrieval on code tasks (FSE 2026), https://arxiv.org/abs/2605.14503 · CoREB,
  https://arxiv.org/abs/2605.04615 · CORE-Bench, https://arxiv.org/abs/2606.11864
- Sourcegraph on BM25F, https://sourcegraph.com/blog/keeping-it-boring-and-relevant-with-bm25f ·
  SQLite FTS5, https://sqlite.org/fts5.html

**Embedding models**
- The MTEB leaderboard, https://huggingface.co/spaces/mteb/leaderboard
- Qwen3-Embedding, https://huggingface.co/Qwen/Qwen3-Embedding-8B and
  https://arxiv.org/abs/2506.05176
- EmbeddingGemma 2, https://huggingface.co/google/embeddinggemma-2 · its timings on a 16 GB M4,
  https://github.com/junmo-kim/ANERun
- jina-code-embeddings, https://arxiv.org/abs/2508.21290
- 4-bit and 8-bit weights compared with full precision,
  https://huggingface.co/juliensimon/Octen-Embedding-8B-mlx-4bit
- llama.cpp pooling issue, https://github.com/ggml-org/llama.cpp/issues/14234 · Ollama's 8B tag,
  https://github.com/ollama/ollama/issues/16076
- Nebius Token Factory: models, https://tokenfactory.nebius.com/api/public/models_info · rate
  limits, https://docs.tokenfactory.nebius.com/ai-models-inference/rate-limits.md · terms,
  https://docs.tokenfactory.nebius.com/legal/terms-of-service
- DeepInfra, https://deepinfra.com/Qwen/Qwen3-Embedding-8B

**Branches in other tools**
- Cursor, https://cursor.com/blog/secure-codebase-indexing and
  https://cursor.com/blog/fast-regex-search
- Continue, https://github.com/continuedev/continue/blob/main/core/indexing/README.md
- Zoekt, https://github.com/sourcegraph/zoekt/blob/main/doc/design.md
- GitHub code search,
  https://github.blog/engineering/architecture-optimization/the-technology-behind-githubs-new-code-search

**Ours**
- The eval's run logs in `eval/results/` (the update sizes of §6.2), and
  [advanced-design.md](../advanced-design.md) §1 (the failure analysis).
