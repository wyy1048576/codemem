# Track B: retrieval design

**Status:** a plan, written Nov 22, 2026. Built since: see the work log. The shared context is in
[overview.md](overview.md). How retrieval works today is in [architecture.md](../architecture.md)
§3 and §6.

**Goal.** Find the right code more often and rank it higher, by giving codemem three
representations that cover each other's blind spots. Show on the retrieval eval that each one
earns its place, before the end-to-end runs use it. And make sure agents actually call codemem: a
better ranking changes nothing if the agent keeps using grep.

**Where this track sits.** The system is the project's secondary goal, after the study
([overview.md](overview.md), "What we are after"). One part of this track serves the primary goal
directly: if agents do not use codemem, the study has nothing to measure (§5).

**Done means:**
1. keyword search with stemming, and an exact lookup for names the query spells out;
2. a typed graph of the code that search walks;
3. a query path that routes, merges, expands and tidies, where each step can be switched off and
   measured on its own;
4. an MCP integration that agents actually use: tools they see from the first turn, text that
   tells them when to call, and a first answer worth calling for (§5);
5. track B's own eval: an ablation table on the retrieval eval that says which layer earns its
   place (§6);
6. one frozen configuration (`codemem-layered`) handed to track A, which runs it together with
   track C's storage;
7. every change announced to the other tracks on the day it lands (§8).

**What is not here.** The embedding model options, and how an index follows git branches, belong
to track C ([track-c-memory.md](track-c-memory.md) §6 and §7). Track B takes the embedding model
as given.

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
- the model becomes a choice of three, which track C owns
  ([track-c-memory.md](track-c-memory.md) §6);
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

## 5. Making agents use it: the MCP integration

**Why this is track B's job.** A better ranking changes nothing if the agent never asks. An agent
that has grep, and a search tool it does not know, often keeps using grep. In published studies,
tools the agent could choose were left unused in most runs: 0 to 6% of runs for one
language-server tool, 0 to 40% in another study, and one vendor counted 1 call in 143 sessions
*(reported: [track A](track-a-evals.md) §4.1 and §16)*. If that happens to codemem, the study
measures nothing and the system helps nobody. So the integration is part of retrieval quality,
and it belongs to this track.

**What "robust enough to be used" means.**

| The agent must | So codemem must | Where that lives today |
|---|---|---|
| see the tools from its first turn | be registered so that its tools are loaded up front, not hidden behind a tool-search step | `codemem init` (`agents.py`). It writes `.mcp.json` for Claude Code and prints a snippet for Codex. It does not ask for up-front loading yet |
| understand in one read when to call them | describe each tool by the tasks it is for, with examples, and say what grep is still better at | all agent-facing text is in `prompts.py`, in three strengths: `none`, `light` (the default) and `strong` |
| get something useful the first time | answer the first search fast, with results it can act on: file and line, signature, a preview, relation lines | the cards (§4), and the catch-up before a search |
| never be stopped by the tool | start quickly, never hang, and say plainly when the index is still building or the model is loading, with keyword results meanwhile | the indexing and loading notices. The case of an embedding API that is down is track C's ([track-c-memory.md](track-c-memory.md) §6.5) |
| keep trusting it after its own edits | return fresh results for code it has just changed | the two-stage indexer, which stays |

**How it is measured.** For every run of the `tool` setup, track A's pipeline records whether
codemem was called, how often, at which turn first, and what it returned
([track A](track-a-evals.md) §6). Track B runs track A's small iteration plan (track A §3.4) for
each variant of the text or the registration, and reads four numbers:

1. **the share of runs that call codemem at least once,** on tasks whose prompt names no file;
2. **the turn of the first call:** does the agent reach for it first, or only after grep failed;
3. **calls per run,** and whether the agent still calls it late in a run;
4. **tokens and time of the runs that call it,** against the baseline.

**The aim is use where it helps, not a high call count.** A text that orders the agent to call
codemem on every task also forces a call where grep is the better tool, and that costs tokens.
The fourth number is there to catch that. The proposed bar, to settle after the first
measurement: with the text that ships, codemem is called in at least two thirds of the runs on
tasks that name no file, and those runs cost no more than the baseline.

**Both agents.** Claude Code is measured first, because track A runs it. The registration is also
checked on Codex by hand: the tools appear, and a search returns. Codex joins the measurement when
track A adds it.

**What is frozen with a configuration.** The tool names, their descriptions, the server
instructions and the card layout are part of `codemem-final`. Track A's `tool` setup means
"codemem as it ships", so a change to any of them changes what that setup measures.

---

## 6. Experiments and gates

**This is track B's own eval, and it comes before the end-to-end runs.** A new piece of retrieval
goes into a configuration that track A runs only after it has passed its gate here. A pass on the
retrieval eval takes minutes. An end-to-end batch takes hours of usage. So this is where track B
finds out whether a change is worth an end-to-end run.

All of these run on the retrieval eval, which needs no agent and no API money. The embedding model
is the one track C sets for the eval, and track B does not vary it. Each is run with two
kinds of query: the issue text, and track A's vague rewrite of the same task. Thresholds are
proposals to agree before running.

| # | Experiment | Question | Gate |
|---|---|---|---|
| B-E0 | **Headroom.** For every dev task where the right function is not in the top 10: was it in the top 200? One edge away from a top-10 result? Named in the query? | Which lever can fix the most misses, before building any? | orders B-E1 to B-E4 |
| B-E1 | Stemming: none, the light version, Snowball on words | Does stemming help code queries, and does it hurt name-heavy ones? | at least +2 points of function success@10 on vague queries; no significant loss on queries that name an identifier |
| B-E2 | Exact lookup and pinning | Does it fix the "names the fix site" misses? | every dev query that names a unique right chunk has it in the top 3 |
| B-E3 | Relationships, four ways: the usage vector (today), callers as a keyword field, one-step graph expansion, and combinations. Then one edge kind at a time, name-only links against the new linking rule, and a random-neighbour placebo. Reported by kind of task (bug fix, pattern-following feature) and by how many steps the right function is from the nearest hit | Does walking the graph replace the usage vector? Which edges matter, and for which tasks? | expansion must beat the placebo; without the usage vector it must be within noise of today's default, or better, before the usage vector is dropped |
| B-E4 | Merging variants (§4, step 3) | Is rank fusion leaving accuracy on the table? | a variant is adopted only at +2 points on both query kinds |
| B-E6 | Link quality: 200 hand-checked calls per language, and one Python repo compared with a language server | How precise are the new links? | at least 90% of high-confidence links correct |
| B-E7 | Cards: relation lines on and off; 5, 8, 10 cards | Do richer cards save an agent turns? | judged end to end by track A |
| B-E9 | **Adoption** (§5): variants of the tool descriptions, the server instructions and the registration, on track A's iteration plan | Do agents call codemem when the prompt names no file, and do those runs cost less? | with the text that ships, called in at least two thirds of such runs, and those runs cost no more than the baseline. A proposal, to settle after the first measurement |

The numbers skip B-E5 and B-E8. Those two experiments are track C's now, as C-E7 and C-E8.

**B-E0 comes first, and is cheap.** It only rereads results the eval already produces. If almost
no miss is one edge away from a hit, the graph work shrinks to relation lines. If most are, it
moves to the front.

---

## 7. Work packages

"Core" marks what the paper needs. Nothing is sized in working days: the deadlines are below.

| # | Work | Deliverable | Done when | Needs |
|---|---|---|---|---|
| B1 | **Headroom analysis** (B-E0), and a per-step switch for every stage of the query path | the miss table; settings that turn each step on and off | the team has ordered the rest of this list from it | the eval's dev runs |
| B2 **(core)** | **Keywords:** Snowball stemming on words, the exact lookup with pinning, callers as a field | a new tokenizer version; B-E1 and B-E2 results | gates of B-E1 and B-E2 judged; update and rebuild give the same results | — |
| B3 **(core)** | **Graph:** the typed edge table; the linking rule for Python, TypeScript, Go, Rust, C and C++, in that order. Java is a bonus; `imports`, `inherits`, `refs`, `tests` | edges in the index; B-E6's precision numbers | a one-function edit still updates in under 0.5 s on vLLM; `codemem index --verify` passes | B1 |
| B4 **(core)** | **Query path:** routing, merging variants, one-step expansion, tidying, relation lines | the path of §4, every step switchable; B-E3 and B-E4 results | the frozen `codemem-layered` configuration is handed to track A | B2, B3, C2 |
| B7 | **Ablations and freeze:** run the whole ladder on the test split once | the paper's retrieval table | numbers for three languages, both query kinds; six once track A has labelers for the other three | A's task sets |
| B8 **(core)** | **The MCP integration** (§5): tools loaded up front for every supported agent, the agent-facing text, the notices, a start that never hangs | the text and registration that ship; B-E9's numbers | the bar of B-E9 is met on the pilot repos, and `codemem init` is checked by hand on Claude Code and Codex | A's iteration plan (track A §3.4) |

**When** (the dates are in [overview.md](overview.md) §8):

| By | Packages | What it gives |
|---|---|---|
| **Nov 27, 16:30 Pacific:** the freeze | B1, B2, B8, B4, and B3 for Python, TypeScript, Go, Rust, C and C++, in that order | the layered retrieval we present, in every language of the main runs: stemming and exact lookup, the integration that ships with its adoption numbers, the query path with relation lines on cards, typed edges. Each piece is in only if it has passed its gate on the retrieval eval by then |
| **Nov 30** | B7 on the test split, once; the merging experiments; anything that missed the freeze and has passed its gate since | the retrieval table, layer by layer, for the presentation. Nothing in this track is planned for later than this, except Java in B3, which is a bonus |

The aim is to leave nothing open after December 1. What is still open then is finished in the week
of the paper.

B1 comes first because it orders everything else. B2 and B3 do not touch each other and go side by
side. B4 needs both, and track C's vector store interface, which the two tracks agree on by
Nov 23. B8 needs track A's pipeline, which is running on two repos now, so the adoption check is
made on those before the freeze. The numbers skip B5 and B6: the embedding options and the branch work are track C's now,
as C8 and C9.

---

## 8. What track B needs from, and gives to, the others

| With | B needs | B gives |
|---|---|---|
| **Track A** | vague rewrites of the dev tasks, a first subset by Nov 24 if it is to count for the freeze; the iteration plan, with the adoption numbers in its report (§5); end-to-end runs that compare card formats (B-E7); later, gold labels for Go, Java and Rust | two frozen configurations: `codemem-today` (the current default, frozen now as the baseline) and `codemem-layered`; the tool text and registration that ship; an announcement of every change on the day it lands (below) |
| **Track C** | a vector store that returns exact scores for its top results; which embedding model and vector length the eval uses | which vector types exist (code only, or code and usage). Track C's storage, its cache and its branch design all depend on that |

**Announce every change, to everyone.** Track B will change the algorithm and what the index
stores. That is expected. What must not happen is that the others learn of a change from a broken
run. So every change that reaches `main` is announced in the work log
([CONTRIBUTING.md](../../CONTRIBUTING.md) §3 and §4) on the day it lands. The entry says:
- what changed, in one sentence;
- whether indexes must be rebuilt. A change to any index-time setting makes every existing index
  of that configuration out of date;
- whether a tool name, a description, the server instructions or the card layout changed;
- its result on the retrieval eval, and on the adoption check if it touches the integration;
- the configuration name and the commit to run.

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

## 9. Risks and open questions

| Risk or question | Why it matters | What we do |
|---|---|---|
| The graph adds noise instead of signal | hubs and wrong links can flood the top 10 | confidence on every edge, shares divided among neighbours, B-E6 before B4, and a switch to turn expansion off |
| Stemming hurts name-heavy queries | codemem must not get worse where grep is already good | names are never stemmed; B-E1 reports the two query kinds separately |
| Tuning to the eval | issue texts are not what agents type | every gate is judged on vague rewrites too; the test split is run once, at the end |
| The linking rule differs by language | nine languages, one rule | the languages of the main runs come before the freeze: Python, TypeScript, Go, Rust, C and C++. A language without the rule keeps name-only links at low confidence |
| Richer cards cost tokens | relation lines add about 50 tokens per card | B-E7: keep them only if they save an agent turns end to end |
| Agents do not call codemem | then no ranking improvement reaches the result | §5: tools loaded up front, text that says when to call, a fast first answer; B-E9 measured through track A's pipeline before the freeze |
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

**Ours**
- [advanced-design.md](../advanced-design.md) §1 (the failure analysis).
