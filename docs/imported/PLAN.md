# CS329M Plan v4: Smart, fast, local code search for coding agents

**Status (2026-10-06):** design stage; nothing has been built. This replaces v3, which is archived in `archive/PLAN_v3_freshness.md`. Exa notes are in [EXA_NOTES.md](EXA_NOTES.md).

---

## 0. The project in five lines
1. **The gap.** Claude Code and Codex search code with grep. Claude Code tried semantic search and dropped it. Codex has an open feature request for it. Cursor kept it and reports +12.5% accuracy.
2. **Why semantic search loses.** Off-the-shelf embedders are bad at the agent's actual task: finding code from a bug description. They also raised worries about privacy, staleness and setup.
3. **What we build.** A **local**, always-fresh semantic code search tool that any agent can call (CLI + MCP). Your code never leaves the machine.
4. **What we research.** Using Exa's ideas, how **smart** (accurate) and how **cheap** (small and fast on a laptop) can a local code embedder get?
5. **How we'll know.** Three measures:
   - **accuracy:** does it find the right function for real GitHub issues?
   - **performance:** speed and memory
   - **efficiency:** tokens and turns when a real agent uses it, compared with grep

---

## 1. Use case and gap

### 1.1 How agents search code today (verified)

| Agent | How it searches | Semantic search? |
|---|---|---|
| Claude Code | `grep` / `find` through Bash ([docs](https://code.claude.com/docs/en/tools-reference)) | **Dropped.** Early versions used RAG with a local vector DB, but "agentic search generally works better", citing security, privacy, staleness and reliability ([Boris Cherny](https://x.com/bcherny/status/2017824286489383315)) |
| Codex CLI | Instructed to prefer `rg` ([instructions](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/prompts/base_instructions/default.md)) | **None built in.** A semantic-index feature request is open ([#5181](https://github.com/openai/codex/issues/5181)) |
| Cursor | grep plus its own semantic index | **Kept.** +12.5% accuracy on average (6.5–23.5% depending on model), best when combined with grep ([blog](https://cursor.com/blog/semsearch)) |

### 1.2 Why semantic search keeps losing: the real gap
- **Embedders are trained for the wrong task.** They learn to match docstrings to code, but agents search with bug reports or a few keywords.
  - Qwen3-Embedding-8B scores 71.7 nDCG@10 on classic code search, but only **20.3** when finding the code edited for an issue ([CORE-Bench](https://arxiv.org/abs/2606.11864)).
  - Short keyword queries drive embedders to near zero ([CoREB](https://arxiv.org/abs/2605.04615)). So keyword search has to stay in the mix.
- **Training on the right task matters more than model size.** A 137M embedder fine-tuned on issues (SweRankEmbed-Small) puts the right function in its top 10 for **74.5%** of SWE-bench Lite issues. The same-size CodeRankEmbed gets **58.8%**, and BM25 gets **36.9%** ([SweRank](https://arxiv.org/abs/2505.07849)).
- **The practical worries (privacy, staleness, setup) are design problems we solve:** run locally, use a file watcher, offer a one-command install.
- **It helps when done right:**
  - A code index raised resolve rate from 45.3% to 50.4% and cut cost per solved task from $2.92 to $2.30, compared with ripgrep ([Code Isn't Memory](https://arxiv.org/abs/2606.22417)).
  - Semantic search helped small agents: file-level F1 of 34.5 vs 18.8 with grep ([Small Agents with Semantic Search](https://arxiv.org/html/2610.05099)).

### 1.3 Tools that already exist (so we don't overclaim)
- [claude-context](https://github.com/zilliztech/claude-context) (MIT; Milvus): −39% tokens on 30 tasks.
- [Semble](https://github.com/MinishLab/semble) (MIT): CPU-only static embeddings plus BM25.
- [ColGREP / LateOn-Code](https://github.com/lightonai/next-plaid/blob/main/colgrep/README.md): multi-vector embeddings plus trigram search. The vendor reports 70% wins against grep and 15.7% fewer tokens.
- Also: ck, mgrep (cloud), Serena (LSP).

**The tool isn't new; the research is.** Most of these tools use general-purpose embedders and measure informally.

---

## 2. What we build

```
your repo ──edits──► 1 Watcher ──► 2 Chunker ──► 3 Enricher ──► 4 Embedder ──► 5 Store
                                                                                  ▲
agent ── "where are sessions revoked?" ──► 7 CLI / MCP ──► 6 Retriever ───────────┘
```

| # | Component | Job | Default |
|---|---|---|---|
| 1 | **Watcher** | Notice changed files | `watchdog`; skips `.gitignore` files; uses git's hashes at startup |
| 2 | **Chunker** | Split files into functions, in any language | tree-sitter. One chunk per function or method. A class chunk holds only its skeleton. Long functions are split into windows of about 2,000 characters |
| 3 | **Enricher** | Add text fields to each chunk | Baseline: path, class, signature, docstring. Research: *usage* fields (§3) |
| 4 | **Embedder** | Turn fields into vectors | SweRankEmbed-Small or CodeRankEmbed (both 137M); Qwen3-Embedding-0.6B for comparison |
| 5 | **Store** | Save chunks, vectors and the keyword index | LanceDB, which is local files with no server. Exact search is fast enough below about 1M functions |
| 6 | **Retriever** | Answer a query | Exa-style hybrid: BM25 top 30–50 plus vector top 50, merged with RRF (k=60). Returns one card per function |
| 7 | **Interfaces** | Let any agent call it | CLI (`cs search` / `cs read` / `cs status`) plus an MCP server |

### 2.1 What one chunk looks like
```json
{
  "id": "auth/session.py::revoke_session",
  "path": "auth/session.py", "lines": [41, 58], "lang": "python", "kind": "function",
  "signature": "def revoke_session(session_id: str) -> None",
  "docstring": "Invalidate one session token.",
  "code": "def revoke_session(session_id): ...",
  "hash": "a91f…",
  "usage": {
    "callers": ["users/service.py · disable_user: revoke_session(user.session_id)"],
    "tests":   ["test_disabled_user_loses_sessions"],
    "commits": ["Fix revoke for expired tokens (2026-08-12)"]
  },
  "vectors": {"code": [0.01, -0.04, "…"], "usage": [0.03, 0.02, "…"]}
}
```
- **The fields under `usage` are the research part (RQ1).** The baseline has everything else.
- **Line numbers are stored but never embedded.** `read` finds the function by name in the live file, so shifted lines don't matter.

### 2.2 Keeping it fresh (engineering, not research)
Example: the agent edits `revoke_session()`.
1. **The watcher** notices `session.py` changed.
2. **The chunker** re-splits that one file.
3. **Fingerprints are compared.** Unchanged functions keep their vectors; only changed ones are recomputed.
4. **Re-embed only `revoke_session`.** That's one model call, a few milliseconds on a GPU.
5. **Usage fields only:** if an edit changes a line that *calls* another function, the callee's `usage` vector is recomputed too. Its `code` vector isn't touched.
6. **Save.** If a search arrives before the update finishes, the changed file is searched live, so results are never stale.

**The Merkle tree:** fingerprints arranged folder → file → function let us find what changed quickly after a restart or a branch switch. Git already does this for committed files. It's for *finding changes*, not for search.

**Model upgrades:** every vector carries a version number. A new model re-embeds in the background, and the old vectors keep serving until it's done (Exa's exa-d idea).

---

## 3. The research question
> **Using Exa's ideas, how smart and how cheap can a local code-search embedder get at finding the code a coding agent needs?**

### RQ1, Smart: can a small embedder learn what code is *for* from the repo itself?
**Exa's idea:** the words people write *when linking to* a page describe it better than the page itself. Exa trains its model to predict the linked page from those words ("next-link prediction").

**The code version:** a function is "linked to" by three things:
- its callers' call sites
- the tests that exercise it
- the commits that changed it

**1a. Usage fields (no training).**
- **What we do:** add callers' call lines, tests and pre-issue commit messages as separate fields, each with its own keyword and vector score. Then test each field on its own.
- **Prior work:**
  - [CoRet](https://arxiv.org/abs/2505.24715) adds *callees*, the functions a function calls, using a trained model.
  - ColGREP lists caller *names*, but never tests whether they help.
  - In web search, anchor text has been found about twice as effective as page content ([Craswell et al. 2001](https://dl.acm.org/doi/10.1145/383952.383999)).
- **Not found:** callers' call sites, tests and commits as fields, each tested for function-level localization.

**1b. Per-repo training (Exa's next-link prediction).**
- **What we do:** fine-tune the 137M embedder with LoRA on our GPU, using pairs mined from the repo itself:
  - caller context → function
  - test → function
  - commit message → changed function

  Only history from **before** the issue's commit is used.
- **Two arms:**
  - CodeRankEmbed (MIT) plus per-repo training vs SweRankEmbed. This asks: can self-supervision on one repo match supervised issue training?
  - SweRankEmbed plus per-repo training. This asks: does it add more on top?
- **Prior work:**
  - Models trained across thousands of repos (SweRank, CoRet).
  - [Anchor-DR](https://arxiv.org/abs/2305.05834) trained "anchor text → page" for web text (+5.3%).
  - Per-project training for *file-level* bug localization ([Ye et al. 2014](https://dx.doi.org/10.1145/2635868.2635874)).
- **Not found:** training a modern embedder on one repo's own links and testing it on that repo's issues.
- **Freshness angle:** how long does a per-repo model stay good as the repo changes?

**Hypotheses** (thresholds to agree as a team):
- **H1:** usage fields raise function Acc@5 by ≥3 points over code-only, mostly on vague issues.
- **H2:** per-repo training adds ≥3 more points.

**What a result looks like** (made-up numbers): right function in the top 5: 52% with code only → 57% with usage → 61% with per-repo training.

### RQ2, Cheap: how small and fast can the index get before it misses?
**Exa's recipe:**
1. Keep the first 256 numbers of each vector (Matryoshka).
2. Store 1 bit per number.
3. Compare a full-precision query against the 1-bit vectors.
4. Re-check the top results with the full vectors.

Exa reports about 320× less memory.

**Our version, measured on finding the function for an issue:**
- **Shrinking:** truncate 1024 → 512 → 256 → 128 numbers; store int8 or 1 bit; with and without re-checking the top results.
- **A fast first pass:** a static embedder (potion-code, 16M parameters, no transformer) proposes candidates, and the transformer re-checks them.
- **Hardware:** CPU-only laptop vs GPU. Measure the time to index a repo (the real bottleneck), query latency and memory.
- **Scale:** repo sizes from 10k to 1M functions.

**Prior work:**
- Only truncation has been measured for this task, and only once ([SweRank](https://arxiv.org/abs/2505.07849), appendix D). Cutting to 256 numbers cost about 10 points off-the-shelf, but only about 5.5 after fine-tuning.
- **Not found:** 1-bit or int8 vectors with re-checking, a static first pass, or CPU indexing cost, for localization.

**Link to RQ1:** train RQ1's model with a Matryoshka loss so it shrinks with less loss.

**H3:** 256 numbers × 1 bit with re-checking keeps ≥98% of full accuracy at ≥30× less memory. A static first pass cuts CPU indexing time by ≥10× at ≤2 points of accuracy loss.

### Final check: real agents (H4)
Same agent, same budget, and only the tool changes: grep alone vs grep plus our tool (the baseline and the best configuration). We measure:
- tokens
- billed cost
- turns
- whether the agent opened the right files

**H4:** the same or better localization at a lower billed cost.

### Stretch: Exa's highlights
Return only the most relevant lines across all results, under one token budget. Exa reports −30% agent tokens. We can even plug our retriever into Exa's own WebCode-Highlights benchmark (§4).

### Considered, but not the headline

| Idea | Why not |
|---|---|
| Merkle tree | It finds changes; it doesn't improve search |
| LLM summaries | Already studied (Meta-RAG, role-aware summaries); an optional comparison |
| Learned sparse ([SPLADE-Code](https://arxiv.org/abs/2603.22008)) | Already exists, at 0.6B and up; we use it as a baseline |
| Multi-vector (LateOn-Code, ColGREP) | Already exists; we use it as a baseline |
| Query rewriting and routing | Partly studied, mixed results; the baseline gets a light heuristic router |
| Staleness study | Engineering handles it; see the archived v3 |

---

## 4. Evaluation

### Metrics
- **Latency:** query time (p50 and p95), time to index a repo, time from saving a file to it being searchable.
- **Accuracy**, at function and file level:
  - **Recall@k:** the share of the right functions that appear in the top k.
  - **Acc@k:** 1 if *all* of them appear.
  - **Precision@k:** the share of the top k that are right.
  - **MRR:** 1 divided by the rank of the first right result.

  *Example:* the right answers are {disable_user, revoke_session} and the top 5 is [login, disable_user, logout, check_session, audit]. Then Recall@5 = 0.5, Acc@5 = 0, Precision@5 = 0.2 and MRR = 0.5.
- **Efficiency (agent runs):** input, output and cached tokens; **billed cost** including prompt caching; turns; and how often the agent used the tool at all.

### Two query styles
1. The full issue text, which is what benchmarks use.
2. Short agent-style queries of 3–8 words, which is what agents actually type. Embedders break on these, so we test both.

### Benchmarks
Retrieval-only evaluation needs no test execution, so **covering many languages is cheap.**

| Benchmark | Languages | Use |
|---|---|---|
| SWE-bench Lite / Verified | Python | Sanity check: reproduce SweRank's 58.8 / 74.5 function Acc@10 |
| [LocBench](https://huggingface.co/datasets/czlll/Loc-Bench_V1) | Python | Main set: newer, with less contamination |
| SWE-bench Multilingual | 9 | Other languages |
| Multi-SWE-bench (flash) | 7 | Other languages; agent runs |
| SWE-PolyBench Verified | 4 | Other languages; ready-made retrieval metrics |
| [CORE-Bench](https://huggingface.co/datasets/zhangfw123/CORE-Bench) issue-to-edit | many | Large issue → code set (non-commercial license) |
| Agent Retrieval Bench | 6 | Token-budget metrics (stretch) |
| CoIR / CodeSearchNet | 6+ | Quick embedder sanity checks only |
| **Exa WebCode** (Highlights 250, RAG 307) | docs | Stretch. Plug our retriever into Exa's [harness](https://github.com/exa-labs/benchmarks) through its `Searcher` interface, download the cited pages, and compare groundedness with Exa at matched token budgets |

**Baselines:**
- grep agent and BM25
- CodeRankEmbed, SweRankEmbed-Small, Qwen3-Embedding-0.6B
- Semble, LateOn-Code / ColGREP, SPLADE-Code-0.6B, claude-context

**Methods borrowed from Exa:**
- score retrieval separately from agent success
- **memory filter:** drop tasks a model can solve from the issue alone
- change only the tool between runs
- bootstrap confidence intervals
- count searches that return nothing

**Leakage rules:**
- Mine pairs, tests and commits only from before the issue's commit.
- Check SweRank's training repos against our evaluation repos.

**Agent harness:**
- [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent), adding `cs search` as a command
- `claude --bare -p --output-format json`
- `codex exec --json`

Start with a 10-task pilot, then set a hard spending cap.

---

## 5. Integration (friend 1, brief)
- **CLI:** works in every agent that has a shell. Ship it with an Agent Skill and one line in AGENTS.md / CLAUDE.md.
- **MCP server:** Python SDK v2 (`MCPServer`), stdio.
  - **Claude Code:** `claude mcp add --scope project cs -- cs mcp`
  - **Codex:** `codex mcp add cs -- cs mcp`
  - **Cursor:** `.cursor/mcp.json`
- **Post-edit hooks (optional; the watcher already covers this):**
  - Claude Code: `PostToolUse`
  - Codex: `PostToolUse`
  - Cursor: `afterFileEdit`
- **Adoption is the real challenge.** Agents default to grep. What helps:
  - clear tool descriptions
  - server instructions under 2,048 characters
  - Claude Code's `alwaysLoad` setting
  - outputs under 10k tokens

  Measure how often agents actually use the tool.

---

## 6. Exa: what to read, and what we implement

| Read | What Exa does | What we implement | Where |
|---|---|---|---|
| [Latent Space podcast](https://www.latent.space/p/exa) and [2023 post](https://exa.ai/blog/building-search-for-the-post-chatgpt-world) | Next-link prediction: train on the text around links | Usage fields (1a) and per-repo training (1b) | RQ1 |
| [Web-scale vector DB](https://exa.ai/blog/building-web-scale-vector-db) | 256 numbers, 1 bit each, full-precision query, re-checking, clusters | The shrinking steps | RQ2 |
| [Composing a Search Engine](https://exa.ai/blog/composing-a-search-engine) | Dense top 50 plus keyword top 30, RRF k=60, router, reranking, dedup, tracing | The baseline retriever | §2 |
| [exa-d](https://exa.ai/blog/exa-d) | Compute only what's missing; version every column | Re-embed only changed functions; versioned vectors | §2.2 |
| [WebCode](https://exa.ai/blog/webcode) and [benchmarks repo](https://github.com/exa-labs/benchmarks) | Groundedness vs correctness, memory filter, `Searcher` interface | Evaluation methods; stretch run | §4 |
| [RL search outcomes](https://exa.ai/blog/rl-search-outcomes) | Swap only the search tool; count tokens to reach equal success | Agent study design | §4 |
| [Dynamic Highlights](https://exa.ai/blog/dynamic-highlights) | Pick the best tokens across all results under one budget | Stretch goal | §3 |
| Optional: [BM25 post](https://exa.ai/blog/bm25-optimization), [highlights server](https://exa.ai/blog/scaling-our-highlights-server) | Engineering details | Tips only | none |

More detail is in [EXA_NOTES.md](EXA_NOTES.md).

---

## 7. Team and timeline (10 weeks, Oct 6 – mid-Dec)

| Week | You (embeddings / retrieval) | Friend 1 (tool) | Friend 2 (evaluation) |
|---|---|---|---|
| 1 | Chunker (tree-sitter, 3+ languages), chunk records, baseline embeddings plus BM25 plus RRF | CLI and MCP skeleton | Loaders and metrics; reproduce SweRank's numbers |
| 2 | Baseline end-to-end on SWE-bench Lite and LocBench | Watcher and re-embedding of changed functions | Multi-language sets, short-query versions, BM25 and embedder baselines |
| 3 | RQ1a: mine usage fields, with leakage rules | Daemon and live search of changed files | External baselines (Semble, LateOn-Code, SPLADE-Code) |
| 4 | RQ1a field ablations, **the first result**; RQ2 setup | Hooks; registering with agents | Agent pilot (10 tasks); spending cap |
| 5–6 | RQ1b per-repo LoRA (plus Matryoshka loss); RQ2 shrinking curves, static first pass, CPU timing | One-command install | Memory filter; statistics |
| 7 | Best "smart + cheap" configuration; 1M-function scale test | Demo interface | claude-context baseline |
| 8 | Agent study (with friend 2) | | Agent study |
| 9 | Stretch: highlights, Exa WebCode run | Demo | Figures |
| 10 | Report, Exa-style blog post, poster | | |

**Decision points:**
- **Week 4:** do usage fields help? If not, RQ1b trains on plain code, which is still a valid study.
- **Week 6:** do we have time for the stretch goals?

---

## 8. Scope, risks and open decisions

**In scope:**
- a multi-language tool
- retrieval experiments on Python plus 2–3 other languages
- agent runs, Python first
- one GPU, everything local

**Out of scope:**
- training models from scratch
- cloud services
- the Merkle-tree and staleness research
- LLM summaries as a headline

**Risks:**
- **RQ1 gains turn out small.** That's still a result, and RQ2 is low-risk and stands on its own.
- **SweRankEmbed-Small is non-commercial (CC-BY-NC).** Ship the tool with an MIT or Apache model, such as our own fine-tune of CodeRankEmbed.
- **Contamination.** Use LocBench and newer sets, plus the memory filter.
- **Agents ignore the tool.** Use instructions, and measure adoption.
- **Laptop CPU speed is unknown.** Measure it in week 2.
- **Agent runs cost money.** Run the pilot first, then cap spending.

**Open decisions:**
- which languages beyond Python (TypeScript, Java, Go?)
- which embedding model to ship
- the tool's name
- the hypothesis thresholds

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **BM25** | Keyword search: ranks by shared words, weighting rare words more heavily |
| **Embedding / vector** | A list of numbers that captures meaning, so search can match by meaning rather than exact words |
| **Field** | One piece of text attached to a chunk (code, path, usage…), each searchable on its own |
| **RRF** | Merges ranked lists; anything ranked high in any list rises to the top |
| **Fine-tuning / LoRA** | Training an existing model a bit more on new examples. LoRA trains only a small add-on, so it's cheap |
| **Matryoshka** | Training a model so the first numbers of a vector work well on their own, which makes vectors safe to shorten |
| **Quantization (int8, 1-bit)** | Storing each number with fewer bits, so vectors take less memory |
| **Re-checking (rescoring)** | Re-ranking the top results with the full vectors |
| **Static embedder** | A lookup-table model with no transformer. Very fast on a CPU, but less accurate |
| **MCP** | The standard way coding agents connect to external tools |
