# Proposal draft: Potential Design, Timeline, and suggested edits

*How to use this file (don't paste this part):*
- Open it in VS Code's Markdown preview (Cmd+Shift+V), select a section, copy it and paste it into Google Docs. Headings, bold text and tables usually survive.
- Google Docs also has *Paste from Markdown* (right-click) if you'd rather copy the raw text.
- Part A is the short design section for the proposal. Part B is the timeline. Part C has suggested edits for the other sections.
- The **Appendix** holds the detailed design notes. They're for the team, not the proposal.
- Citations use [n] numbers that continue your existing reference list (new references start at [9]; full list near the end).

---

# Part A: Potential Design (paste-ready)

## Potential Design
We will build an **agent-agnostic code search tool**: a local index exposed through MCP and a command-line interface. Claude Code, Codex, Cursor or any other coding agent can call it instead of grepping through files. It should help in three ways:
- **Accuracy.** Retrieve the right code more often (higher recall, precision and MRR), especially when the issue's wording doesn't appear in the code.
- **Tokens.** The agent reads a few relevant functions instead of pages of grep output and whole files.
- **Time.** Fast queries, index updates within about a second of a file changing, and fewer search–read rounds per task.

### Pipeline
![Figure 1: Pipeline overview](figures/pipeline.png)

*Figure 1. Pipeline overview. The top lane builds the index and keeps it up to date. The bottom lane answers an agent's query.*

1. **Chunking.** Each file is parsed with tree-sitter and chunked at the function level, one chunk per function or method. This works across programming languages.
2. **Augmentation.** Each chunk is augmented with metadata:
   - its path, signature and docstring
   - its **usage context**: callers' call sites, the tests that exercise it, and messages of past commits that touched it
   - optionally, an LLM-generated summary

   File and module summaries form a hierarchy above the functions.
3. **Indexing.** A local hybrid index:
   - BM25 for exact identifiers
   - embeddings from an open code model for semantic matching
   - a call graph linking functions
4. **Retrieval.**
   - Each query is routed by type: identifier-like queries weight keywords, while natural-language queries weight semantics and usage.
   - Candidates from each signal are merged with reciprocal rank fusion (RRF).
   - The agent receives compact result cards within a fixed token budget.
5. **Incremental updates.** A file watcher and content hashes detect which functions changed. Only those chunks are re-embedded, and only their dependents (callers' usage context, file summaries) are refreshed.

### What's unique
Consider the issue *"Disabled users stay logged in."* The function that needs fixing, `revoke_session()`, never mentions "disabled" or "logged in", so grep misses it unless the agent guesses the right words. Its usage context gives it away: it is called by `disable_user()` and tested by `test_disabled_user_loses_sessions`.

Web search learned this long ago: the anchor text of links pointing to a page often describes the page better than the page itself, and Exa built its search engine on this idea [26]. We treat a function's callers, tests and commits as its "links".

| | Typical code-search tools | Our design |
|---|---|---|
| Chunk content | Raw code | Code + usage context + summaries |
| Retrieval | One similarity score, or plain keyword + vector search | Query routing and multi-signal fusion, Exa-style [24] |
| Output | Whole chunks or files | Compact cards within a token budget [28] |
| Freshness | Periodic re-sync (e.g. every 5 minutes [23]) | Incremental, about a second after a change |

For each stage we will explore state-of-the-art retrieval methods, adapting the design of [Exa's search engine](https://exa.ai/blog/composing-a-search-engine) to code [24].

### Research questions
Our **baseline** is what existing tools do: function-level chunks with basic metadata (in our own chunk schema) and hybrid BM25 + embedding retrieval. We then add one component at a time and measure what each one contributes:
- usage context
- LLM summaries
- summary hierarchy
- query routing
- token-budgeted results

The research questions:
- **RQ1 – Accuracy.** Do usage-context augmentation and Exa-style multi-signal retrieval improve Recall@k and MRR over the hybrid baseline and over grep? Which components contribute most?
- **RQ2 – Tokens.** How many tokens does an agent consume before reaching the relevant code, with our tool versus grep? How much recall do we get within a fixed context budget?
- **RQ3 – Time.** What are the query, indexing and update latencies? Does end-to-end task time decrease?

**Evaluation data.**
- **SWE-bench (Lite / Verified)** is the main benchmark. Each task gives three things:
  - a GitHub issue, which becomes the query
  - the repository at the issue's base commit
  - the gold patch; the functions it modifies are the relevance labels
- **LocBench** [27]: 560 newer issues with function-level labels. It checks that our results aren't inflated by models having memorized SWE-bench.
- **Grep baseline.**
  - *Offline:* ripgrep over keywords and identifiers extracted from the issue, with files ranked by number of matches.
  - *In agent runs:* the agent's own grep.
- **[Exa's open-source benchmarks](https://github.com/exa-labs/benchmarks)** [31] (stretch). These test *web* search, so they can't measure code localization. But the Highlights track of Exa's WebCode benchmark [30] asks a question close to ours: does the returned snippet contain the answer, and how many tokens did it take? Its harness lets a custom retriever plug in. Running our retriever on it would compare our token-budgeted results directly with Exa's published numbers.

### Scope
- **Baseline (build first, by Oct 19).** What existing tools do; the reference point for every RQ.
  - Function-level chunking with basic metadata
  - Hybrid BM25 + embedding retrieval, merged with RRF
  - Evaluation script: SWE-bench labels, Recall@k, MRR, grep baseline
- **Core (by Nov 23).** Enough to answer RQ1–RQ3.
  - RQ1: usage context, LLM summaries, summary hierarchy, rule-based query routing
  - RQ2: token-budgeted results, plus a small agent study with vs. without the tool
  - RQ3: incremental updates and latency measurements
  - An MCP server and a CLI, so any agent can use the tool
- **Stretch (if time allows).** Novel optimizations.
  - An Exa-style embedding model trained on the repository's own usage pairs [26]
  - Learned query routing and highlights; vector compression
  - Hierarchy traversal (greedy vs. beam search); Exa's WebCode benchmark; more languages

---

# Part B: Timeline (paste-ready)

## Timeline
The course expectation is about 5–10 hours per person per week. Suggested roles (placeholders):
- **A:** chunking, augmentation and updates
- **B:** retrieval and the MCP tool
- **C:** evaluation

| Week | Focus and deliverable | Primary owner |
|---|---|---|
| Oct 6–12 | Finalize research questions, the task subset (repositories and commits), the chunk schema, and the evaluation protocol for accuracy, tokens and time. Read core related work. Build a SWE-bench loader that extracts the gold functions; sanity-check BM25 | All. A schema, B retrieval design, C evaluation |
| Oct 13–19 | **Baseline:** tree-sitter chunking, basic metadata, hybrid BM25 + embedding retrieval with RRF. First Recall@k, MRR and latency on about 50 tasks; grep-agent reference runs on a few tasks | A chunking, B retrieval, C metrics |
| Oct 20–26 | **Augmentation:** usage context and LLM summaries (cached by content hash); call graph. Ablation on 50–100 tasks. MCP skeleton | A augmentation and graph, B MCP, C ablation |
| Oct 27 | **Checkpoint report:** design, baseline and first augmentation results, revised scope | All |
| Oct 27–Nov 9 | **Full pipeline:** summary hierarchy, query routing, token-budgeted results, incremental updates | A hierarchy and updates, B routing and packing, C token and latency metrics |
| Nov 10–23 | **Full evaluation:** accuracy (offline, each component added in turn); tokens (fixed budget offline, plus a small agent run with vs without the tool); time (query, indexing, update and task latency) | C lead; all on failure analysis |
| Nov 24–Dec 1 | Analyze results, write the final report, prepare the presentation, and release the code and MCP tool | All |

Stretch goals (see Scope) start only once the core is on track at the Oct 27 checkpoint, and must not delay the core evaluation in Nov 10–23.

---

# Part C: Suggested edits to the other sections

## C0. Title and goal paragraph (to align with the new framing)
**Possible titles**, if the team wants the title to match the design:
- *"An Exa-Style Hybrid Code Index for Coding Agents: Accuracy, Tokens and Latency"*
- or keep the current title and add a subtitle: *"…: An Agent-Agnostic, Multi-Signal Retrieval Tool"*

**Replacement for the third paragraph of the Introduction** ("Our goal is to investigate…"):

Our goal is to build an agent-agnostic code search tool that coding agents such as Claude Code and Codex can call instead of grepping through files, and to measure whether it helps on three fronts: finding the right code more accurately, using fewer tokens, and saving time. The tool adapts the design of Exa's web search engine to code: it combines several retrieval signals (keywords, meaning, how the code is used, code structure and a hierarchy of summaries), routes each query to the signals that suit it, and returns compact, token-budgeted answers. Its index updates incrementally as code changes. We expose it through MCP and evaluate it on repository-level tasks against grep-based agents and a standard hybrid-search baseline.

## C1. Introduction and Motivation: add after the second paragraph (paste-ready)
Industry practice is split on whether code indexes are worth it.
- **Claude Code** started with retrieval over a local vector database, but its team found that letting the agent search with grep and find "generally works better". They cited security, privacy, staleness and reliability [9]. On macOS and Linux, Claude Code now searches through shell `grep` and `find` [10].
- **Codex** is instructed to prefer ripgrep (`rg`) [11], and a request to add semantic indexing is still open [12].
- **Cursor** takes the opposite view. It reports that adding semantic search to grep improves agent accuracy by 12.5% on average [13], and it keeps its index fresh with Merkle-tree syncing and cached embeddings [14].

One reason the debate persists is that off-the-shelf embedding models are trained for a different task than the one agents face:
- A strong model that scores 71.7 nDCG@10 on classic code search drops to 20.3 when asked to find the code an issue requires [16].
- A small model trained specifically on issues finds the right function in its top 10 for 74.5% of SWE-bench Lite issues. The same-size model without issue training gets 58.8%, and BM25 gets 36.9% [15].

The potential payoff is real:
- In one small study, giving an agent an index cut its tokens by 39% with unchanged localization accuracy [23].
- In another, an index raised the issue resolve rate from 45.3% to 50.4%, and lowered the cost per solved task from $2.92 to $2.30, compared with ripgrep [22].

So the questions that matter are *what* gets indexed, *how* it is retrieved, and *how fast and cheaply* it answers, rather than whether an index exists at all. That is what this project studies.

## C2. Related Work: add a paragraph and table rows (paste-ready)
**Issue localization and retrieval for agents.**
- SweRank trains retrievers and rerankers specifically for issue-to-function localization [15].
- CoRet adds call-graph context to a dense retriever [19].
- LocAgent navigates a code graph with an LLM agent [20].
- Meta-RAG localizes bugs using LLM summaries of the codebase [18].
- Anthropic's Contextual Retrieval prepends LLM-written context to each chunk, cutting retrieval failures by 35–67% on mixed corpora [17]. This motivates our summary augmentation.

**Index maintenance.**
- RepoDoc updates generated documentation incrementally and saves 77% of tokens, but doesn't evaluate retrieval [21].
- Agent studies comparing an index with grep don't measure update cost [22].

**Retrieval design borrowed from Exa's web search engine:**
- composing routing, multi-signal retrieval and rank fusion [24]
- token-budgeted highlights [28]
- incremental recomputation of derived data [25]
- the idea that text describing a link characterizes its target [26]

| Prior work | Primary contribution | Our extension |
|---|---|---|
| SweRank [15] | Retriever and reranker trained for issue → function localization | Same task, but we vary *what signals are indexed and how they are combined* |
| Contextual Retrieval [17] | LLM context prepended to text chunks | Code-specific signals (usage, summaries), with build and update cost |
| Meta-RAG [18], RepoDoc [21] | Summaries for localization; incremental doc updates | Summaries as one retrieval signal, with update cost |
| Exa search engine [24–26, 28] | Routing, multi-signal fusion, highlights, incremental pipeline | Adapted to a local code index for coding agents |

## C3. Small fixes and scope notes (for whoever owns each section)
- **Typo:** "MMR" should be **MRR** (Mean Reciprocal Rank), in two places in Potential Experiments.
- **Wrong link:** the RepoBench link points to the SWE-bench inference API. RepoBench is https://arxiv.org/abs/2306.03091.
- **Undefined task:** the timeline mentions "semantic-Q&A", but no section describes it. Either define it (e.g. a small set of "where is X handled?" questions) or drop it.
- **Contamination:** OpenAI stopped reporting SWE-bench Verified in Feb 2026 because of contamination. Consider two checks:
  - adding LocBench [27] (560 newer tasks with function-level labels) as a check set
  - a "memory filter" that drops tasks a model can solve from the issue text alone (an evaluation idea from Exa's WebCode benchmark)
- **Standard metric:** add function-level **Acc@k** (all gold functions in the top k) next to Recall@k. It's the standard in localization papers (LocAgent, SweRank), so our numbers become comparable.
- **Downstream evaluation:** pass rate requires running each task's tests in Docker. It's cheaper to measure whether the agent opened or edited the gold files, plus tokens, tool calls and wall time; keep pass rate optional.
- **Time measurements:** the Experiments section already lists query latency and index construction time. Add **update latency** (time from saving a file to it being searchable) and **end-to-end task time**, to match the third goal.
- **Scope in the old design text:** "reads/writes", "depends_on", "candidate invariants" and "architectural roles" each need data-flow analysis or extra LLM passes. Marking them as stretch goals keeps the core doable at 5–10 hours per week.

## References to add (continuing from [8]; renumber if needed)
- [9] B. Cherny (Claude Code), on replacing RAG with agentic search. https://x.com/bcherny/status/2017824286489383315
- [10] Claude Code tools reference. https://code.claude.com/docs/en/tools-reference
- [11] OpenAI Codex base instructions ("prefer using rg"). https://github.com/openai/codex/blob/main/codex-rs/protocol/src/prompts/base_instructions/default.md
- [12] OpenAI Codex issue #5181: semantic code index request. https://github.com/openai/codex/issues/5181
- [13] Cursor, "Improving agent with semantic search," 2025. https://cursor.com/blog/semsearch
- [14] Cursor, "Securely indexing large codebases," 2026. https://cursor.com/blog/secure-codebase-indexing
- [15] SweRank: Software Issue Localization with Code Ranking, 2025. https://arxiv.org/abs/2505.07849
- [16] CORE-Bench (code retrieval benchmark), 2026. https://arxiv.org/abs/2606.11864
- [17] Anthropic, "Introducing Contextual Retrieval," 2024. https://www.anthropic.com/engineering/contextual-retrieval
- [18] Meta-RAG on Large Codebases Using Code Summarization, 2025. https://arxiv.org/abs/2508.02611
- [19] CoRet: Improved Retriever for Code Editing, ACL 2025. https://arxiv.org/abs/2505.24715
- [20] LocAgent: Graph-Guided LLM Agents for Code Localization, ACL 2025. https://arxiv.org/abs/2503.09089
- [21] RepoDoc (incremental repository documentation), 2026. https://arxiv.org/abs/2604.26523
- [22] Code Isn't Memory, 2026. https://arxiv.org/abs/2606.22417
- [23] Zilliz, claude-context (MCP code search) and its evaluation. https://github.com/zilliztech/claude-context
- [24] Exa, "Composing a Search Engine," 2026. https://exa.ai/blog/composing-a-search-engine
- [25] Exa, "exa-d: Data Framework to Process the Web," 2026. https://exa.ai/blog/exa-d
- [26] W. Bryk (Exa) on next-link prediction, Latent Space podcast, 2025. https://www.latent.space/p/exa
- [27] Loc-Bench dataset (from LocAgent). https://huggingface.co/datasets/czlll/Loc-Bench_V1
- [28] Exa, "Dynamic Highlights," 2026. https://exa.ai/blog/dynamic-highlights
- [29] CoREB (code retrieval with short keyword queries), 2026. https://arxiv.org/abs/2605.04615
- [30] Exa, "WebCode: Search Evals for Coding Agents," 2026. https://exa.ai/blog/webcode
- [31] Exa open-source benchmarks (MIT). https://github.com/exa-labs/benchmarks

*Before submitting:* double-check the exact titles and years of the 2026 arXiv papers ([16], [21], [22], [29]). We verified their numbers from abstracts and summaries, not full reads.

---

# Appendix: detailed design notes (for the team, not for the proposal)

## Components in detail

**1. Parsing and chunking.**
- tree-sitter splits every file into functions, methods and classes.
- Each function becomes one chunk, with:
  - a stable id (e.g. `auth/session.py::revoke_session`)
  - its file path and line range
  - its source code
- A class chunk holds only the class signature, its docstring and its method names. Very long functions are split into windows of about 2,000 characters.

**2. Augmentation.** Fields are stored separately so each can be switched on or off and evaluated on its own. Every field records its provenance, and whether it's a tool-extracted fact or an LLM summary.
- **Basic metadata (no LLM):** path, enclosing class, signature, docstring, imports.
- **Usage context (no LLM):** callers' call lines, the tests that exercise the function, and messages of past commits that touched it. Only history from before the task's base commit is used.
- **LLM summary (optional):** one or two sentences on purpose and behavior, generated only from the repository at the task's base commit.

**3. Call graph.**
- Deterministic edges from static analysis:
  - *contains* (folder → file → function)
  - *imports*
  - *calls*
  - *inherits*
  - *tested_by*
- Edges are resolved by name, so they're approximate but cheap.
- The graph feeds the usage context and lets retrieval expand one hop from a strong hit.

**4. Summary hierarchy.**
- Following CodeWiki [6], an LLM writes summaries bottom-up:
  - file summaries from their functions
  - module summaries from file summaries
  - finally a repository overview
- Each summary links to the children it was built from.
- The hierarchy serves both as a retrieval signal and as a "browse" mode.

| Layer | Example content | Role in retrieval |
|---|---|---|
| Repository | Packages, overall architecture | Routes broad questions to the right subsystem |
| Module / file | Responsibilities, imports, configuration | Local design context and boundaries |
| Function / class | Signature, summary, usage, calls | Candidate code to change |
| Evidence | Source spans, tests | Grounds claims; what the agent finally reads |

**5. Indexes.**
- Every text field is indexed in a local store (LanceDB), in two ways:
  - BM25, with identifiers split into words (`revokeSession` → "revoke session")
  - one embedding per field, from an open code model (e.g. CodeRankEmbed, or SweRankEmbed-Small [15])
- At repository scale, exact vector search takes milliseconds, so there's no approximate index to maintain.

**6. Retrieval pipeline.**
1. **Route** the query (identifier-like or descriptive).
2. **Gather candidates** from each signal: keywords, semantics, usage and hierarchy.
3. **Fuse** the rankings with RRF.
4. **Optionally expand** along call edges.
5. **Pack** the answer under a token budget: compact cards (path, function, lines, signature, one-line summary), plus the most relevant lines and the ancestor summaries.

The agent then reads the live code for the cards it chooses.

**7. Agent interface.**
- An MCP server plus a command-line tool, with three operations:
  - `search`
  - `browse` (walk the hierarchy)
  - `read` (live code by id)
- The command-line tool also works in agents that have no MCP support.

**8. Incremental updates.** Every stored item is keyed by a hash of its inputs plus the version of the step that produced it, following exa-d [25]. On a file change or a new commit:
1. Re-parse only the changed files.
2. Re-embed the changed functions.
3. Update their edges.
4. Refresh dependents: callers' usage context, the file summary, then module summaries.
5. Stop moving up the hierarchy once a regenerated summary is unchanged.

Searches that arrive mid-update also check the changed files directly.

## Versions compared (ablation ladder)

| Version | Retrieval | Goal it targets |
|---|---|---|
| Grep agent | The agent's own grep/find (no tool) | Reference point for accuracy, tokens and time |
| Baseline | Function chunks + basic metadata; BM25 + embeddings merged with RRF | The simple-hybrid floor |
| + usage | Baseline + usage context | Accuracy on vaguely worded issues |
| + summaries | Baseline + LLM summaries | Accuracy, at an LLM cost |
| + hierarchy | Baseline + summary hierarchy and browse | Accuracy on broad questions |
| + routing | Query routing between signals | Accuracy on identifier vs descriptive queries |
| Full | All of the above + token-budgeted results | All three goals |

## Novelty notes (to our knowledge)
- **Existing tools stop at simple hybrid search.** They typically combine keyword and vector search [23], and report token savings from small, setup-specific studies [13, 23].
- **Prior research tends to evaluate one layer at a time:**
  - CodeWiki: documentation, not retrieval [6]
  - Meta-RAG: summaries inside an LLM pipeline [18]
  - CoRet: call-graph neighbors with a trained retriever [19]
- **Usage context untested.** We didn't find callers' call sites, tests and commit messages evaluated as a retrieval signal for function-level localization.
- **No combined study of Exa-style retrieval for code.** We found none that adapts Exa-style routing, fusion and token-budgeted answers to code search for agents. Nor one that measures accuracy, tokens and time together against grep in the same harness [13, 22, 23].
- **Embedding models fail on short keyword queries** [29]. That's the motivation for query routing.

## Initial hypotheses
- **H1 (accuracy):** the full pipeline beats grep and the simple-hybrid baseline on function-level Recall@5 and MRR, with the largest gains on vaguely worded issues. Usage context gives the most gain for its cost.
- **H2 (tokens):** agents reach the gold function using fewer tokens with the tool than with grep, and token-budgeted results cut tokens further without lowering recall.
- **H3 (time):** on a laptop, a query takes under about half a second and an update under about a second. End-to-end task time falls compared with grep.

## What we reuse vs. build
- **Reused:**
  - tree-sitter (plus Aider's tag queries)
  - LanceDB or bm25s
  - an off-the-shelf embedding model (sentence-transformers)
  - PyDriller (git history)
  - networkx
  - watchdog
  - the MCP Python SDK
- **Our own code:**
  - the usage-context extraction
  - query routing
  - token-budgeted packing
  - incremental updates
- **Minimum for first results:** chunking, basic metadata, the index and flat hybrid retrieval, plus the evaluation script. No watcher or MCP is needed until the agent experiment.
