# codemem, the next phase: overall plan

**Status:** a plan, written Nov 22, 2026. Nothing in this folder is built yet. How codemem works
today is in [architecture.md](../architecture.md).

**In one sentence.** codemem becomes the system under test for one question: *when does an index
help a coding agent that already has grep?* The work splits into three tracks. Track A builds the
end-to-end evaluation, track B rebuilds retrieval as three complementary representations, and
track C makes the index small.

| File | Read it if |
|---|---|
| `overview.md` (this file) | you are on the team: where we stand, what we want to show, how the tracks connect, the timeline, the paper |
| [track-a-evals.md](track-a-evals.md) | you build or use the evaluation |
| [track-b-retrieval.md](track-b-retrieval.md) | you work on what codemem stores and how it ranks |
| [track-c-memory.md](track-c-memory.md) | you work on memory, disk and speed |

Each track file can be read on its own. This page holds what all three share.

**How claims are marked.** Numbers from our own runs have no mark. *(pilot)* means a quick
measurement made while writing this plan. *(reported)* means a research pass found it on a primary
page, and nobody on the team has re-read that page yet. *(vendor)* means a company measured its own
product.

---

## 1. The plan on one page

1. **The question.** When does an index help a coding agent that already has grep? We are not
   trying to replace grep.
2. **Why it is open.** Anthropic says agentic search works better, on "mostly vibes". Cursor
   switched its embeddings off in July 2026 and published no numbers. Copilot went the other way.
   The studies that exist are small, use one model, stop at "did it find the right place", or put
   search results into the prompt instead of offering a tool. None uses vague requests (§3).
3. **What we measure.** The same agent on the same task, with and without codemem: did it complete
   the task, how long did it take, how many tokens did it use. The saving is the result (§4).
4. **Who it is for.** Students and engineers who already have Claude Code or Codex on a
   subscription. So Claude runs under our own subscriptions, with codemem attached as an MCP
   tool. Model calls with an API key happen in two places only: the embedding API, and the open
   models of the small-model study (§7).
5. **Three tracks.**
   - **A builds the pipeline first.** One command runs chosen tasks, setups and models, and records
     tokens and time from two sources that must agree. Once it runs, B and C change codemem and
     rerun it.
   - **B rebuilds retrieval as three layers:** keywords with stemming, dense vectors, and a graph.
     The embedding model becomes a choice of three.
   - **C makes the index small:** 15 to 45 times less memory for vectors, with exact rescoring
     from disk.
6. **What runs on what.** The baseline and the final codemem on every task. Today's codemem on
   medium tasks only. Small models (9B and 14B) on easy and medium tasks, with a few hard ones as
   a probe.
7. **Dates.** December 1: the solution and the results are done and presented. December 8: the
   paper is on arXiv, after a week of refining. What does not fit has no date, and search beyond
   code is one of those (§8).

**Seven things the research changed.** Each is explained where it is used. The middle column is
*(reported)*, except the last row.

| We assumed | The research says | Where |
|---|---|---|
| Claude and Codex have both said grep works better | only Anthropic has. OpenAI has published no comparison | §3.1 |
| Qwen3-Embedding-8B is the strongest open embedding model | it ranks fourth overall, and on finding code for an issue it scores no better than the 0.5B model we already use (20.3 against 20.8) *(reported)* | [track B](track-b-retrieval.md) §5.2 |
| Stemming will help keyword search | on code the one study found it hurts more queries than it helps, except short verb-like ones. It gets a gate | [track B](track-b-retrieval.md) §3.2 |
| A graph will make search more precise | studies disagree: callers help, unfiltered spreading hurts, and every study used bug fixes. Ours tests feature requests too | [track B](track-b-retrieval.md) §3.3 |
| Small models will complete easier tasks | given the right files, small models repaired 2 tasks of 100 in one study. Localization becomes their primary measure | [track A](track-a-evals.md) §11 |
| We need to build a task harvester | an open one exists. We add the layer nobody has | [track A](track-a-evals.md) §8.3 |
| 1-bit vectors might cost accuracy | on our own vectors, a 40-byte code plus rescoring kept 99.9% of the exact top 10 *(pilot)*. Published numbers are least kind on issue-to-code search, so the test goes deeper there | [track C](track-c-memory.md) §5 |

---

## 2. Recap: where codemem stands

### 2.1 What it is

codemem is a local code search tool for coding agents. It works next to grep, not instead of it.
grep finds exact strings. codemem is for questions that share no words with the code, such as
*"add OCR to the upload pipeline"* in a repository the agent has never seen.

How it works today, in five steps:

1. **Cut the repo into chunks.** A chunk is one searchable unit: a function, a method, a class or
   a block of top-level code. tree-sitter (a parser with a grammar per language) does the cutting,
   in nine languages.
2. **Remember three things about each chunk:** its words, the meaning of its code, and who calls
   it.
3. **Stay fresh.** A watcher sees every save. The structure (names, lines, call links) updates in
   milliseconds. The meaning (vectors) updates behind it. Every search first catches up for at most
   4 s, and says which files are still pending.
4. **Search three ways and merge.** A query is ranked by keywords, by the meaning of the code, and
   by the meaning of a short "who calls this" text. The three ranked lists are merged by rank.
5. **Answer with short cards:** location, name, a few lines. Agents call it over MCP (the protocol
   agents use to call tools); people use the command line.

### 2.2 What is built

| Part | State today |
|---|---|
| Languages | Python, JavaScript, TypeScript, TSX, Go, Java, Rust, C, C++ |
| Storage | one SQLite file per checkout (chunks, keywords, call links, vectors), plus an in-memory copy of the vectors in FAISS, searched exactly |
| Keyword search | BM25 over five weighted fields (name, signature, path, doc text, body). Identifiers are split into words and also kept whole. Stemming exists as a light option and is off |
| Dense search | one vector per chunk for its code and one for its usage text. Default model: `jina-code-embeddings-0.5b`, 896 numbers per vector, run locally. Any OpenAI-compatible embedding API also works (tested against Nebius) |
| Relationships | call links resolved by name only. They are used to write the usage text and to show callers and callees in `get_chunk`. **Search never walks them** |
| Merging | reciprocal rank fusion: each list adds `1 / (60 + rank)` to a chunk's score |
| Freshness | the two-stage indexer, the 4 s catch-up, and a note naming anything still pending |
| Reuse | a machine-wide vector cache keyed by model and text hash, so a text embedded once is never embedded again |
| Front ends | an MCP server with four tools (`search_code`, `get_chunk`, `index_status`, `refresh_index`) and a CLI |
| Evaluation | `cmeval`: retrieval only. Fresh tasks from merged pull requests, gold files, classes and functions, paired tests |

### 2.3 What we measured

All of it is retrieval only: given the issue text, find the code the real fix changed. No agent was
in the loop. Tasks are fixes merged from July to October 2026, after the models' training cutoff.
The baseline, grep-fn-plus, is our tuned offline grep.

| Language (repos) | Tasks | Right file near the top (file MRR) | Right function near the top (function MRR) | Tokens read before the first right function |
|---|---|---|---|---|
| Python (pandas, transformers, home-assistant, airflow) | 100 | 0.63 vs 0.57 | 0.38 vs 0.46: grep ahead, not significant | 1,284 vs 1,871: not significant |
| C++ (Godot, duckdb, llama.cpp) | 68 | 0.52 vs 0.30 | 0.28 vs 0.15: significant | 1,813 vs 3,955: significant |
| TypeScript (vscode, playwright) | 50 | 0.45 vs 0.33 | 0.31 vs 0.26: a tie | 1,745 vs 4,329: significant |

Each cell is codemem vs grep-fn-plus. MRR is 1 divided by the rank of the first right result,
averaged over tasks. Only the function and token columns were tested for significance.

What the index costs today:

| Cost | Measured |
|---|---|
| Disk | 10 to 14 KB per chunk: 0.25 GB (playwright) to 2.35 GB (Godot) per repo |
| Memory | about 2.2 GB for the embedding model, plus 0.26 GB of vectors for a 102k-chunk repo (vLLM) |
| First build | 12 min to 2 h per repo on an M5 laptop GPU; about 5 h for vLLM on an M1 |
| One edit | searchable in 0.1 to 0.5 s |
| A few days of other people's commits | a median of 400 to 8,700 texts need new vectors, which is 0.3% to 3.8% of a repo's chunk count (9.9% on llama.cpp): 60 to 90 s on the M5 for the large Python repos |
| One search | 0.12 s for 10 words, 0.63 s for 250 words (vLLM, M1) |

The last-but-one row is new. It comes from the eval's own logs: each run stepped one index through
24 task commits per repo, a few days apart.

### 2.4 What we have not measured

- **No agent has been in the loop.** We don't know whether codemem changes completion, total
  tokens or wall time. This is the gap the whole phase exists to close.
- **Queries were whole issue texts.** They are long and full of identifiers, which favours grep.
  codemem is built for short, vague requests, and we have no task set of those.
- **Three languages have gold labels:** Python, C++ and TypeScript. codemem indexes nine.
- **No small models.** Every argument about closing the model gap is still a hypothesis.
- **No compression.** Every vector is stored at full size, twice or three times.

### 2.5 What the redesign changes, layer by layer

Today, relationships reach search only as a flattened text ("called by X, tested by Y") that is
embedded like any other text. The graph itself is stored, but never walked. The keyword and dense
layers exist in a basic form.

| Layer | Today | Next phase | Track |
|---|---|---|---|
| Dense vectors (meaning) | one small local model, full-size vectors | three model options (a light Mac model, local Qwen 8B, an API), shorter vectors | B, C |
| Keywords (exact words) | BM25, no stemming, no exact-name lookup | BM25 with stemming on the natural-language tokens, plus an exact lookup for names the query spells out | B |
| Graph (relationships) | call links by name, used only to build a text | typed, scored edges that search walks to pull in callers, tests and sibling implementations | B |
| Merging | three lists merged by rank | route the query, merge, expand along the graph, then rescore the top results | B |
| Vector storage | 2 bytes per number, in RAM and on disk | 1 bit per number in RAM, full vectors on disk for rescoring only | C |
| Branches | one index per checkout, a cache that only grows | one shared store, a small view per checkout, a size cap | B, C |
| Evaluation | retrieval only, three languages | end-to-end agent runs on public tasks in up to six languages, vague prompts, small models; a task generator later | A |

---

## 3. Why this phase: the question, and the evidence so far

**The question.** When does an index help a coding agent that already has grep? We are not trying
to replace grep or to prove it wrong. We want to measure, properly, what an index adds next to it.

### 3.1 What companies do, and what they have shown

| Who | What they do | What they have published |
|---|---|---|
| Anthropic (Claude Code) | grep, file listing and file reads; no index | statements only. Its lead said agentic search "outperformed everything. By a lot", on "some internal benchmarks also, but mostly vibes", and "at the cost of latency and tokens" (May 2025); and that it "generally works better" (Feb 2026) |
| OpenAI (Codex) | ripgrep; no index | **no statement that grep beats an index.** A request for semantic indexing was closed as "not currently on our roadmap". Its prompting guide says of semantic search tools that "we have seen success here as well" |
| Cursor | embeddings until July 2026; since then a local text index for fast grep | Nov 2025: semantic search raised answer accuracy by 12.5%. July 2026: staff forum replies that it "was rapidly no longer helping in a meaningful way". No numbers for the reversal |
| GitHub Copilot | one semantic index per repo, built on its servers | a new embedding model with +37.6% retrieval quality (Sep 2025) |
| Sourcegraph, JetBrains, Augment | hosted search tools for agents | their own measurements, each favourable to their product |

One correction to how we have told this story. Our checkpoint slides put Claude Code and Codex
together as saying grep works better. Only Anthropic has said so. Codex uses grep, but OpenAI has
published no comparison. The paper's introduction should say exactly that.

**Why Cursor switched: two explanations, and the public facts fit both.**

| | Models became good at grep | A server-side index cost too much |
|---|---|---|
| For | it is the only reason staff give, with a mechanism (several search terms in parallel); the live effect in 2025 was already small (+0.3% of code kept); outside studies find the gain shrinks as models grow | Cursor called embedding "the expensive step" and reported up to 4 hours to a first query on new repos (Jan 2026); the index was "managed and queried on the server"; the 250,000-file limit belonged to it |
| Against | no data shown; in January 2026 Cursor still called semantic search "one of the biggest drivers of agent performance"; one study still finds a significant gain for a frontier model | nobody at Cursor names cost; the same costs existed when they measured +12.5% |

The measurement that would decide it is Cursor's own, which is unpublished, or ours: is there a
benefit left on vague requests in large repos, and does it survive when the index is local and
cheap?

### 3.2 What studies have measured

All figures in this table are *(reported)*.

| Model tier | Study | What was compared | Result |
|---|---|---|---|
| Frontier | Code Isn't Memory (a vendor; Opus 4.7; 91 tasks; 3 repetitions) | one harness with its index tools on and off; and against a separate grep agent | on vs off: 50.4% vs 41.9% completed, significant. Against the grep agent: 50.4% vs 45.3%, not significant; tokens 10.1k vs 14.0k; 4.5 vs 5.4 minutes |
| Cheap closed | CodeNib (Haiku 4.5; 200 SWE-bench Verified tasks) | search results placed up front, against grep and read | 79 vs 66 completed (p = 0.029, but the interval that respects repos includes zero); 50 to 87% fewer tokens on localization |
| Mid-size open | CodeGrep (a 30B agent; 500 tasks; one run) | the top 2 files of a retriever placed up front | a trained retriever: 27.0% vs 25.8% completed, 19% fewer tokens. A keyword retriever: worse than nothing |
| Mid-size open | Physical Cost of Context (a 35B agent) | 10 embedding hits up front, against grep on demand | 36% fewer model calls on localization; 29 vs 30 of 100 completed |
| Small open | Bellam (9 models from 0.6B to 32B; 500 tasks; 5 repetitions; pre-registered; localization only) | grep, plus embeddings, plus a graph, and a placebo tool | search tools add 6 to 10 points up to 14B and 2.6 points at 32B (not significant). Embeddings carry the gain, not the graph |
| Small open | ColGREP (1 to 1.7B models; file localization only) | grep against a local semantic index | a fine-tuned 1.7B model: 44% less time and 29% fewer tokens |
| Any | Embeddings vs. Grep (Ant Group, Nov 2026; 96 agent tasks) | grep, a keyword index, an embedding index | the choice of search tool moved localization by about 0.04; the choice of model by 0.03 to 0.30 |

**In plain words:**
- The benefit seems to shrink as the model gets stronger. For frontier models, what remains is
  mostly a saving in tokens and time.
- Almost nobody has measured task completion below 27B. The small-model studies stop at "did it
  find the right place".
- Every end-to-end gain for mid-size models came from placing results in the prompt. When search
  is a tool the agent may choose, it often goes unused.
- Precision matters: an imprecise retriever made an agent worse.
- Every study used issue texts. None used a short, vague request.

### 3.3 What nobody has done

| Gap | Is it real? |
|---|---|
| Completion, tokens and time together, from 9B open models to frontier models, on tasks newer than the models, in several languages | yes, as a combination. Each piece exists somewhere, for one model tier and on SWE-bench Verified |
| Vague, user-style requests, with the search tool as the variable | yes. Vague-prompt benchmarks exist (Saving SWE-Bench, FeatBench), but none varies the search tool |
| The cost of a **local** index, counted per task: build time, memory on a laptop, staleness while the agent edits | partly. Two studies measure build time and size on server hardware, apart from task cost |
| Whether the agent calls the tool, as something we vary and not just report | yes. It is reported as a statistic, never varied by model size and wording in real agent products |
| An open pipeline that harvests fresh tasks from GitHub | **no.** SWE-bench-Live's pipeline (RepoLaunch) is open, maintained, and takes any repo in all six of our languages. We should build on it, not rebuild it. What nobody has is the layer on top: vague prompts that are checked to stay solvable, and labels for how hard a task is to search for |

---

## 4. What we want to show

Four hypotheses. Each can come out either way, and each has a result that would count against it.

| # | Hypothesis | Measured by | Supported if | Counts against it |
|---|---|---|---|---|
| H1 | **Savings.** With codemem, a strong model finishes the same tasks with fewer tokens and less time | end-to-end runs: tokens and seconds per task; completion | at least 10% fewer tokens or seconds, with completion within 5 points | no saving, or completion drops |
| H2 | **Where.** The saving is larger in large repos and for vague requests | the same runs, split by repo size and prompt level | the effect grows along both | a flat effect |
| H3 | **The model gap.** codemem helps a 9B or 14B model more than a frontier model | the effect per model tier; "gap closed" ([track A](track-a-evals.md) §11) | a larger effect at 9B and 14B than at the frontier, on localization and, if the models can complete tasks at all, on completion | the same effect at every size, or a harness artefact (Bellam saw the size effect vanish in one harness) |
| H4 | **Asking.** Whether the agent asks for search matters as much as what search returns | codemem as a tool, against codemem's results placed up front | up front beats the tool | no difference |
| H5 | **Cost.** A local index can cost little enough to be worth it | tracks B and C: memory, disk, build time, freshness, added to the cost per task | H1's saving survives when the index's own cost is counted | the saving disappears once the build is counted |

**What we do if the answers are "no".** A careful negative result is worth reporting here, because
the industry has settled this question without publishing data. The study is designed so that
"an optional local index does not help a frontier agent, and here is by how little" is a finding
with intervals around it, not a failure.

---

## 5. One running example, used in all three track files

> Add OCR to the upload pipeline, so that text in uploaded images can be searched.

The repo is an upload service. It already has a stage that transcribes audio uploads. The word
"OCR" appears nowhere in it. An agent with grep has to guess names and read files until it
understands how stages work. An agent with a good index should find the transcribe stage, and the
three places a new stage must touch, in one search.

- [Track A](track-a-evals.md) turns this pull request into a task and measures both agents.
- [Track B](track-b-retrieval.md) shows how keywords, meaning and the graph each find a different
  part of the answer.
- [Track C](track-c-memory.md) follows the same search through memory and disk.

---

## 6. The three tracks, and how they connect

```
 ┌─────────────────────────── TRACK A: evaluation ───────────────────────────────┐
 │ retrieval eval · agent localization · end-to-end runs                         │
 │ task generator · vague prompts · task labels · small-model study              │
 └────▲──────────────────────────────────▲────────────────────────────────┬──────┘
      │ frozen configurations:           │ frozen configuration:          │ vague prompts,
      │ codemem-today, codemem-layered   │ codemem-compact                │ labels, verdicts
      │                                  │                                ▼
 ┌────┴──────── TRACK B: retrieval ──────┴───┐      ┌──────── TRACK C: memory ──────────┐
 │ keywords + dense vectors + graph          │      │ shorter vectors, 1-bit codes,     │
 │ the query path · embedding options        │◄────►│ exact rescoring, one copy on      │
 │ branch switches                           │      │ disk, the cache cap               │
 └───────────────────────────────────────────┘      └───────────────────────────────────┘
          shared between B and C: the vector store interface, and the vector cache
```

| Track | Owns | First deliverable | Its file |
|---|---|---|---|
| **A** | how we measure, and the task set | the pipeline skeleton: 10 public tasks, an agent with and without codemem, tokens counted two ways that agree | [track-a-evals.md](track-a-evals.md) |
| **B** | what codemem stores and how it ranks | a table of why today's searches miss, which orders the rest | [track-b-retrieval.md](track-b-retrieval.md) |
| **C** | memory, disk and speed | the compression table on our own vectors | [track-c-memory.md](track-c-memory.md) |

**What passes between the tracks:**

| What | From → to | When |
|---|---|---|
| `codemem-today`: the current default, frozen as the reference for every comparison | B → A | Nov 23 |
| The pipeline's first version, and the small plan B and C can run themselves ([track A](track-a-evals.md) §3.4) | A → B, C | Nov 25 |
| The vector store interface, with exact scores for the top results | C ↔ B | Nov 25, before B builds the query path |
| A codemem install without PyTorch, for the `api` embedding option | C → A | Nov 25: the task containers need it |
| `codemem-final`, frozen for the presentation | B, C → A | Nov 28, evening |
| `codemem-final`, the last freeze, for the test split | B, C → A | Dec 3, evening |
| Memory, disk and build-time numbers per repo | C → A | with each frozen configuration |
| Vague rewrites of the retrieval eval's dev tasks | A → B, C | a first subset by Nov 27, so gates can be judged on them before the freeze; the rest by Dec 3 |
| End-to-end verdicts on card formats and on reranking | A → B, C | after the first full batches |

**Three rules that keep the tracks from blocking each other:**
1. **The eval stays independent of codemem.** It reaches codemem through the MCP server, the
   command line and one adapter file. Nothing else.
2. **Contracts change only with notice.** Tool names, the card layout and the adapter's calls
   ([data-model.md](../data-model.md) §12) are what track A's runs depend on.
3. **Every index-time change shows up in `index_settings()`.** A new tokenizer, new edges or a new
   vector format must each change it, so two eval systems never share an index by mistake.

---

## 7. Shared ground rules

**Who we build for.** A student or an engineer who already has a coding agent on a subscription:
Claude Code, or Codex. So Claude runs under the subscriptions the three of us already have, each
of us on our own, with codemem attached as an MCP tool. No Claude API key is involved.

**Where API keys are used.** For model calls, in two places only:
- **the embedding API,** when embeddings are not computed locally;
- **the small-model study.** Open models are not part of any subscription, so they are called
  through an API: a hosted endpoint, or a server we host ourselves on our Macs
  ([track A](track-a-evals.md) §11).

One more key is already in use and costs nothing: the eval counts tokens with Anthropic's free
counting endpoint ([track A](track-a-evals.md) §5.4). No model is called with it, and codemem
itself never needs it.

**Models.**

| Tier | Model | Runs under | Harness |
|---|---|---|---|
| Frontier | Claude Sonnet 5.5 (`claude-sonnet-5-5`) | our Claude subscriptions | Claude Code |
| Cheap closed | Claude Haiku 5.5 (`claude-haiku-5-5`) | our Claude subscriptions | Claude Code |
| Small open | Qwen3.5-9B and Qwen3-14B, today's models in the 7B and 13B classes | an API: a hosted endpoint at cents per run where a provider serves the model, or a server on our Macs, which is free and slower | mini-SWE-agent |
| Larger open | Qwen3.8-27B | a hosted endpoint: it does not fit a 24 GB Mac. Added in the week before arXiv if the two smaller ones are done | mini-SWE-agent |

**Languages.** Python, C++, Go, Java, Rust and TypeScript, on medium to large repos. End to end,
Python and TypeScript come first, and the other four are chosen from the same public task sets as
usage allows. The retrieval eval stays at Python, C++ and TypeScript in this phase.

**Fresh tasks where we can get them.** A task is fresh for a model if its fix was merged after
that model's training cutoff. The retrieval eval's tasks are all fresh. The public end-to-end
sets are older: the newest Python task we saw on SWE-bench-Live's page was created in August 2025
*(checked Nov 22)*. Both setups run the same model on the same task, so a memorized fix cannot
favour one side. It can hide a saving, because a model that remembers a fix has less to search
for. So every end-to-end table says how many of its tasks are fresh, and the paper states the
limit.

**Three measures:** did the agent complete the task, how long did it take, and how many tokens did
it use. The headline is the saving in tokens and time at equal completion. Retrieval accuracy is
reported by the retrieval eval and used for tuning. It is not a headline.

**Token counts come from the API itself, measured the same way in every setup.** What we report
is a saving, the difference between two runs of one task, so both runs are always measured by the
same instrument ([track A](track-a-evals.md) §5).

**Dev and test.** Everything is built and tuned on the dev split, and the December 1 results are
dev results. The test split is run once, in the week before arXiv, with the frozen configuration
and after the analysis plan is written down. Writing the plan first is what "pre-registered"
means, and the strongest prior study did it.

**Names for configurations.** No version numbers.

| Name | What it is |
|---|---|
| `codemem-today` | the current default, frozen on Nov 23. The "simple version" in every comparison |
| `codemem-layered` | track B's retrieval on today's storage |
| `codemem-compact` | track C's storage under today's retrieval |
| `codemem-final` | both together: the configuration we present. Frozen before each batch we report, and the freeze date goes into the report |

**What runs on what.** The baseline (the agent without codemem) and `codemem-final` run on every
task. `codemem-today` runs on medium tasks only, which is enough to show the step from today's
version to the final one. Small models run on easy and medium tasks, plus about ten hard ones as a
probe. The full table is in [track A](track-a-evals.md) §3.3.

**What it costs us.**

| Resource | Cost | The real limit |
|---|---|---|
| Claude Code runs | nothing beyond our subscriptions | each seat's usage limit, which our own coding in these weeks draws on too. The pipeline pauses when a seat reaches its limit and resumes after the reset. Three seats run side by side |
| Embeddings through an API | $0.01 per million tokens: about $0.40 for a 40M-token repo *(reported)* | none that matters |
| Small open models | cents per run on a hosted endpoint *(reported prices)*; free on our Macs: the 9B on 16 GB, the 14B on 24 GB | hosted: whether a provider serves the 9B and the 14B. Nebius's documentation names the 27B, and we did not find the two smaller ones there *(checked Nov 22)*. On a Mac: laptop speed |
| Containers for hidden tests | free on the team's x86 machine | Macs emulate x86 slowly. A rented Linux machine is about $0.50 to $1.50 an hour if we need one |

**Tokens are still the measure, for a different reason.** On a subscription, a token is not a
fraction of a cent. It is a fraction of your usage limit. An agent that needs fewer tokens per task
gets more tasks out of the same plan and reaches its limit later. That is the saving a subscriber
feels, and it is why the paper's first numbers are tokens and time. A breakdown in dollars at API
prices can be computed later from the same records, because every run keeps its tokens in four
classes ([track A](track-a-evals.md) §5).

**How many runs fit in one usage window is unknown until we try.** It is the first number the
pipeline's first runs give us, and it sizes everything after it.

---

## 8. Timeline

Two dates. What does not fit before them has no date.

| Date | What is due | What "done" means |
|---|---|---|
| **Tue Dec 1, 2026** | **the solution and the results:** the course report and presentation | the evaluation pipeline runs end to end with trusted token and time counts; the solution we present is built and frozen; the run matrix has run on the dev tasks; the retrieval and memory tables exist |
| **Tue Dec 8, 2026** | **the paper, on arXiv** | the same results, refined: one last freeze, the test split run once, three repetitions, every integrity check passing, limits stated plainly |
| no date | what §8.3 lists, including search beyond code | designed in this plan; built after the paper, if at all |

### 8.1 Nine days to December 1

Three of us, working long days. The order matters more than the hours. Track A's pipeline is what
turns everything else into a result, so its first version exists on day 3.

| Days | Track A | Track B | Track C | Check at the end |
|---|---|---|---|---|
| **Nov 23–25** | A1: the pipeline skeleton on 10 public tasks. A2: the recording proxy and the cross-check | `codemem-today` frozen on day 1. B1: why today's searches miss. B2: stemming and exact lookup. B5: the `api` preset and its fixes | C1: the compression table, on real queries. The install without PyTorch that track A's containers need | one task runs end to end in both setups, and its tokens are counted two ways that agree |
| **Nov 26–28** | A3: flags, plans, resume. A7: the labels that can be computed. From A6: mini-SWE-agent and the localization tier. From A8: vague rewrites for a first subset. Batches: the baseline on every dev task, which does not depend on codemem, and today's codemem on the medium ones | B3: typed edges and the linking rule, for Python and TypeScript. B4: the query path, with relation lines on cards. B5: the `light` preset chosen | C2: the compact store, behind the interface agreed with B. C3: one copy on disk | **Nov 28, evening: the configuration we present is frozen** as `codemem-final` |
| **Nov 29–30** | the rest of the run matrix on the dev tasks: the final codemem on all of them, with the vague subset; small models on easy and medium, with the hard probe. A first report | the retrieval table, layer by layer, on the dev tasks | memory, disk and scan time from 100,000 to 1,000,000 vectors | every run in the tables passed its integrity checks |
| **Dec 1** | present, and hand in the report | | | |

**Track A is the tightest.** Its rows are more than one person's nine days. Three parts stand on
their own, so whoever is ahead can take one: the recording proxy, the second harness with the
small models, and the vague rewrites (§12).

### 8.2 December 2 to 8: refine, then arXiv

| Days | What happens |
|---|---|
| **Dec 2–3** | Fix what the first runs exposed, on the dev tasks only. One last freeze of `codemem-final`, by the evening of Dec 3. The analysis plan is written down and committed before any test run of codemem. The baseline starts on the test tasks on Dec 2, since it does not depend on codemem |
| **Dec 4–6** | **The test split, once:** the frozen configuration on every test task, three repetitions, with every check of [track A](track-a-evals.md) §7 switched on |
| alongside | What explains the headline, each on a subset: results up front, the placebo, the vague prompts. The small-model study at its planned size, and the 27B model if time allows. The third embedding option (local Qwen 8B), the two extra retrieval baselines, the memory and cost report |
| **Dec 7** | the last numbers go into the paper |
| **Dec 8** | arXiv, with the code, the task list and the run records |

Writing runs through the whole week. The paper says plainly what it rests on:

| The paper can claim | It leaves open |
|---|---|
| measured differences in tokens and time between Claude Code with and without codemem, with intervals, on a test split that was run once | differences in completion under about 12 to 15 points: the task set is too small to show them |
| the step from today's codemem to the final one, on medium tasks | that the tasks are newer than the models: the public task sets are older, and may be partly memorized (§7) |
| the effect on vague requests, on a checked subset | vague requests on every task |
| a small-model result at 9B and 14B: localization first, completion second | a small-model study as large as the main one |
| retrieval per layer, on our own fresh tasks in three languages | retrieval in six languages |
| the memory and disk cost of the index, on a laptop | branch switching and the reranker: designed, not built |

Stating these limits in the paper is part of not compromising on quality.

### 8.3 Left for later, with no date

Designed in the track files, and part of neither deadline. Each is picked up only if the paper is
taken further, for example to a conference (§9).

| What | Where it is designed | Why it waits |
|---|---|---|
| Our own fresh tasks at scale, from the generator, in six languages | [track A](track-a-evals.md) §8 | building and validating task images is the slowest job in the plan, and the image builder needs a model key of its own. This phase gets a trial at most |
| The retrieval eval in Go, Java and Rust | [track A](track-a-evals.md) §12.2 | each language needs its own labeler and hand-checked labels |
| The linking rule for Go, Java, Rust, C and C++ | [track B](track-b-retrieval.md) §3.3 | until then those languages keep name-only links at low confidence |
| Branch switching and the cache cap, built | [track B](track-b-retrieval.md) §6, [track C](track-c-memory.md) §4.7 | the design and its measured costs are in the plan; the paper's claims do not need the build |
| The reranker study | [track C](track-c-memory.md) §4.5 | it is judged end to end, and that takes usage the main matrix needs |
| Codex as a second agent; Opus on a subset | [track A](track-a-evals.md) §4.3 | the same pipeline, more usage |
| Search beyond code | §11.2 | a stretch goal |

### 8.4 What the early results can change

- **Agents rarely call codemem,** even when it is loaded up front: the "results up front" setup
  becomes the main one, and the wording that tells the agent about the tool becomes something we
  study.
- **A 9B model completes nothing:** the small-model study is measured by localization.
- **Almost no missed search is one graph step from a hit** (track B's first table): the graph work
  shrinks to relation lines on cards.
- **Whatever the sign of the result,** the paper is written from what was measured.

### 8.5 If time runs short

Cut scope, never the checks.

| Can give | Cannot give |
|---|---|
| languages end to end: Python and TypeScript first, the other four as usage allows | two token counts that agree, on every run |
| the smaller setups: the placebo, the stronger wording, the repo map | three repetitions |
| the number of tasks in the small-model study, and the 27B model | a frozen configuration before any batch we report |
| the generator trial, and the third embedding option | a dev split to build on and a test split run once |

---

## 9. The paper

**One paper, on arXiv on December 8, 2026,** written to the standard of a conference paper, with
its limits stated (§8.2).

**Where it could go afterwards.** This is not part of the plan's deadlines. It is listed so the
paper is written with a venue's rules in mind. All *(reported)*.

| Venue | Deadline | Fit |
|---|---|---|
| **NeurIPS 2027, Evaluations & Datasets** (the former Datasets & Benchmarks track) | not announced. In 2026 the abstract was due May 4 and the paper May 6. Nine pages | the best fit: it is the home of benchmark studies, and it accepts tools and generators. It would need the work of §8.3 |
| ICLR 2027 workshops | papers suggested for Feb 1, 2027; the workshop list appears Nov 29 | the December paper as it stands |
| FSE 2027 tool demonstrations | Jan 26, 2027; 4 pages | codemem as a tool |
| TMLR | rolling | no deadline to meet |

**What the NeurIPS track requires** *(reported)*: the data hosted and reachable without asking the authors;
a Croissant metadata file with its responsible-AI fields; and code at submission for benchmark
suites, generators and tools. Review is double-blind by default.

**The claim, in one sentence.**

> The first pre-registered, end-to-end study of when an optional, locally built code index helps
> an agent that already has grep: from open 9B models to a frontier model, in several languages,
> with precise and vague versions of a prompt, counting the index's own cost and whether the
> agent actually calls it.

**Contributions.**
1. **The study:** search setup × model size × repo size × prompt vagueness, with completion, time
   and tokens.
2. **The task layer:** paired precise and vague prompts that are checked to be still solvable,
   with labels for how hard each task is to *search* for, and the tool that adds this layer to
   any task that has a container and hidden tests.
3. **The system:** a local, always-fresh index with three representations and a measured memory
   budget, as the thing under test and as a working tool.

**How we differ from the closest work.**

| Study | It has | It lacks |
|---|---|---|
| Code Isn't Memory | end to end; tokens and time | one model; 91 tasks; issue texts; index cost not counted; a closed system |
| Bellam | model sizes from 0.6B to 32B; a placebo; pre-registration | localization only; Python; no completion |
| CodeNib, CodeGrep | completion for mid-size models; index build cost | results up front only; SWE-bench Verified; one model each |
| ColGREP | a local tool; time and tokens | models under 2B; file localization only |
| Sourcegraph CodeScaleBench | 370 tasks, 9 languages | the two setups had different access to the code; a vendor's product |

**Which experiment feeds which part of the paper.**

| Paper element | Comes from |
|---|---|
| Figure 1: the effect of codemem on tokens, time and completion, by model size | A12 and A11 |
| Figure 2: the same effect by repo size and by prompt vagueness | A12 |
| Figure 3: tool against up-front results against placebo | A12 |
| Table 1: the task set, by language, size, kind and vagueness | A7 to A9 |
| Table 2: retrieval in three languages, issue texts and vague requests, per layer | A10, B7 |
| Figure 4: memory, disk and build time against repo size; cost per task with the index counted | C6 |
| Appendix: adoption by wording; how failed runs ended; link quality | A12, A11, B-E6 |

**What reviewers of this track check** *(reported, from its guidelines and two checklists)*:
- the claim the benchmark supports is stated, with its limits;
- another team can rerun it from the paper: "no code = reject" for tools;
- contamination is addressed (on SWE-bench Verified, models named the right file from the issue
  alone up to 76% of the time);
- variance is reported: several repetitions, paired intervals, corrected tests;
- the tests that grade a task are sound;
- novelty is argued against named prior work. Negative results count "when rigorously supported".

---

## 10. Risks

| Risk | Why it matters | What we do |
|---|---|---|
| Agents don't call codemem | no call, no effect | tools loaded up front; adoption measured in the first batch; the up-front setup separates information from asking |
| Small models complete nothing | H3 could not be tested on completion | localization as their primary measure; the first small-model batch measures the floor |
| Environments are slow to build | it would be the longest job in track A | this phase's results use public tasks that already have containers; our own tasks get a trial at most (§8.3) |
| The result is null for frontier models | the headline changes | designed for: a null with tight intervals is a result, and H3 and H5 stand on their own |
| We tune to our own eval | the gains would not transfer | every gate is judged on vague prompts too; the test split is run once |
| Nine days is short | a rushed pipeline gives numbers nobody can trust | the checks are not optional (§8.5); scope gives way first; the paper states its limits |
| Usage limits | three subscription seats are all the Claude time we have, and we code on the same seats | the run matrix spends large tasks only on the baseline and the final configuration; the baseline is reused; the pipeline pauses and resumes; the first batch measures how many runs a seat allows, and the number of tasks follows from it |
| The public tasks are older than the models | a model may remember a fix | both setups run the same model, so it cannot favour one side; it can hide a saving. Every table says how many of its tasks are fresh, and the paper states the limit |
| The field moves | a new model or a new vendor statement can change the story | the pipeline lets us rerun on newer tasks and models in days |

---

## 11. Follow-ups

### 11.1 Larger open models

The 27B class is the natural next point on the curve: Qwen3.8-27B is served by Nebius at $0.45 in
and $3.00 out per million tokens, and published budgets for 24 to 35B models on fresh tasks are 2
to 3.7 million tokens and $0.09 to $0.62 per task *(reported)*. It needs no new harness, only an
endpoint. It does not run on a 24 GB Mac, so it is not part of the claim about laptops. It is run
in the week before arXiv if the 9B and 14B runs are done (§8.2), and stays a follow-up otherwise.

### 11.2 Beyond code: search a folder, or a whole machine

**A stretch goal.** It is outside both deadlines of §8, and nothing in this phase waits for it.

**The idea.** Nothing in codemem's engine is specific to code except the chunker. The same index
could cover a folder of documents, so an agent can search your files by meaning. macOS's own file
search is mostly by words and file names.

**Why it could matter more than code search.** The argument for grep rests on code having names a
model can guess. Documents don't. On a fixed set of 100,000 documents, a frontier model answered
70.1% of questions with embedding search and 55.9% with keyword search *(reported: BrowseComp-Plus)*.
That is a far larger gap than any study finds for code.

**What it needs that this phase does not build.**

| Need | Candidate | Hard part |
|---|---|---|
| Reading PDFs, Office files and slides | a converter such as MarkItDown or Docling | scans and layout; errors from text recognition hurt search |
| Chunking prose | paragraphs under their headings | a paragraph often loses its subject when cut out |
| Images and scanned pages | an embedding model that reads images. EmbeddingGemma 2, a candidate for our light option, puts text and images into one space; the strongest page-image models are larger and keep many vectors per page *(reported)* | size and speed on a laptop |
| Trust | a folder the user chooses, never the whole disk by default | an index of personal files is a target, and every snippet it returns can carry instructions meant for the agent |

**What this phase already prepares.** The compact vector store (track C) is what makes a much
larger index affordable. Indexing a repo's README and docs folder, which track B lists as its
first optional extension, is the same prose chunker. The task generator's method (a prompt, a
hidden check, two setups) carries over to document questions.

**First step, when a track finishes early.** A one-week spike: text, Markdown and PDF through a
converter, a paragraph chunker, the same pipeline. Compare an agent with grep, an agent with
Spotlight's command line (`mdfind`), and an agent with codemem, on a public question set over
documents. Decide from that whether it is an extension of this paper or a second one.

---

## 12. Decisions needed from the team

| # | Decision | Suggested default |
|---|---|---|
| 1 | Who takes which track | by current ownership: A to Andrew (the eval), B to Andre (the backend and retrieval), C to Wilson (the vector-store plugin and installation) |
| 2 | Which public task set the results come from | SWE-bench-Live: its Python set, and its multi-language set for the other five languages, which has over 100 tasks in each with x86 images *(checked Nov 22)*. SWE-bench Pro's second version if its ready-made Claude Code setup saves a day |
| 3 | Where containers run | the team's x86 machine; a rented Linux machine if it is not free in time |
| 4 | Which Claude model carries the main comparison | Sonnet 5.5 for the matrix; Haiku 5.5 for building the pipeline and for the loop B and C run |
| 5 | Is agent localization in scope | yes: it needs no containers, and it is the measure small models need |
| 6 | The small models | Qwen3.5-9B and Qwen3-14B, on our Macs |
| 7 | The frozen reference | `codemem-today` = the current `main`, tagged on Nov 23 |
| 8 | Where the small models run | a hosted endpoint under an API key, if a provider serves the 9B and the 14B; self-hosted on our Macs otherwise |
| 9 | Who helps track A before December 1 | whoever is ahead takes one of: the recording proxy, the second harness with the small models, the vague rewrites |
| 10 | Whether the task generator gets a trial in this phase | only if we accept a model key and a search key for its image builder; otherwise it waits (§8.3) |

---

## Sources

Items marked *(reported)* in this file were read by research passes on Nov 22, 2026. Re-read a
page before citing it in the paper. Each track file lists its own sources.

**What companies do and have said**
- Claude Code's lead on agentic search: Latent Space, https://www.latent.space/p/claude-code
  (May 2025), and https://x.com/bcherny/status/2017824286489383315 (Feb 2026)
- Codex: the closed request for semantic indexing, https://github.com/openai/codex/issues/609 ·
  the open one, https://github.com/openai/codex/issues/5181 · the prompting guide,
  https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide.md
- Cursor: semantic search, https://cursor.com/blog/semsearch (Nov 2025) · indexing,
  https://cursor.com/blog/secure-codebase-indexing (Jan 2026) · fast regex search,
  https://cursor.com/blog/fast-regex-search (Mar 2026) · the forum threads on dropping
  embeddings, https://forum.cursor.com/t/165899 and https://forum.cursor.com/t/167527 (Jul to Aug
  2026) · the search documentation, https://cursor.com/docs/agent/tools/search
- GitHub Copilot's embedding model,
  https://github.blog/news-insights/product-news/copilot-new-embedding-model-vs-code/
- Sourcegraph, https://sourcegraph.com/blog/why-coding-agents-fail-large-codebases · JetBrains,
  https://blog.jetbrains.com/ai/2026/07/introducing-jetbrains-context-repository-intelligence-for-coding-agents/

**Studies**
- Code Isn't Memory, https://arxiv.org/abs/2606.22417 · Bellam, https://arxiv.org/abs/2610.33958 ·
  ColGREP, https://arxiv.org/abs/2610.05099
- CodeNib, https://arxiv.org/abs/2607.25431 · CodeGrep, https://arxiv.org/abs/2608.05886 ·
  Physical Cost of Context, https://arxiv.org/abs/2610.34763
- Embeddings vs. Grep, https://arxiv.org/abs/2611.20455 · ContextBench,
  https://arxiv.org/abs/2602.05892
- Saving SWE-Bench, https://arxiv.org/abs/2510.08996 · FeatBench,
  https://arxiv.org/abs/2509.22237
- SWE-bench-Live and RepoLaunch, https://arxiv.org/abs/2603.05026 · its task sets,
  https://github.com/microsoft/SWE-bench-Live · SWE-rebench V2, https://arxiv.org/abs/2602.23866
- BrowseComp-Plus, https://arxiv.org/abs/2508.06600

**Venues and what reviewers expect**
- NeurIPS 2026, Evaluations & Datasets: the call,
  https://neurips.cc/Conferences/2026/CallForEvaluationsDatasets · reviewer guidelines,
  https://neurips.cc/Conferences/2026/EvaluationsDatasetsReviewerGuidelines
- ICLR 2027 workshops, https://iclr.cc/Conferences/2027/CallForWorkshops · FSE 2027,
  https://conf.researchr.org/home/fse-2027 · TMLR, https://jmlr.org/tmlr/editorial-policies.html
- BetterBench, https://arxiv.org/abs/2411.12990 · the agentic benchmark checklist,
  https://arxiv.org/abs/2507.02825 · The SWE-Bench Illusion, https://arxiv.org/abs/2506.12286

**Ours**
- The retrieval results: `eval/results/2026-10-26-py100`, `-cpp68` and `-ts50`.
- How codemem works today: [architecture.md](../architecture.md), [data-model.md](../data-model.md),
  [decisions.md](../decisions.md). Earlier research directions:
  [advanced-design.md](../advanced-design.md), [exa.md](../exa.md).
