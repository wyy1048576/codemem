# The search lab: what codemem's search misses, and what recovers it

Offline experiments on two real indexes, made on 2026-11-26 in track C's session for track B.
This folder is a record and a starting point for more experiments. It is not part of the
product and not meant to be merged.

**Read first:** `report.md` (the findings, with one worked example), then `running-log.md` (every
table of every experiment, in the order they ran). The pages the worked example shows are in
`results/example-page.txt`. What the branch `andre/search-recall` took from it is in the work log
(2026-11-26, 21:00 UTC and the entry after it).

## What it measures, and how

- **Tasks:** the 733 issue tasks of `eval/tasks/e2e/vllm.jsonl` and `pandas.jsonl`, the issue as the
  query; the 16 vague pandas tasks at L1 and L2; and the issue's first line as a short query.
- **A hit:** the chunk of a function the real fix changed, by chunk id, in the 10 results, or
  named on the page.
- **Held out:** every setting was chosen on half 0 of the tasks (sha256 of the task id) and is
  reported on half 1 (175 vLLM tasks and 162 pandas tasks with a gold function). The vague tasks
  were never used to choose.
- **No model call:** the query vectors were made once (`s1_run.py`, `embed_extra.py`) and are
  replayed by `prod.Precomputed`, so an experiment takes seconds to minutes.

## What you need to run it

- Two indexes built by codemem at these commits: vLLM `e9acf48`, pandas `a0885a1`, with the exact
  (FAISS) index, and the query vectors made from them. They are not in the repository (238 MB of
  per-task files). **The paths are those of the Mac they ran on:** `lab_common.py` holds them
  (`REPOS`, `OUT`, `EXTRA_VECS`), and each script adds the lab folder to `sys.path`. Change those
  first.
- `PYTHONPATH=<a checkout of codemem>/src`. For the `validate_*` scripts and `allgold.py` that
  checkout is the branch `andre/search-recall`.
- On macOS, FAISS runs on one thread (codemem sets that at import).

## The scripts

| Script | What it does |
|---|---|
| `allgold.py` | Fixes that change two or more functions: how many of them a search shows. For each such task, the gold functions among the 10 cards, and among the cards plus the names the branch adds (related callers and callees; results 11 to 30 by name). The branch's own search on the index copies. |
| `bm25_variants.py` | Keyword lists for shortened or reduced queries, through the product's own calls (bm25_match + Store.bm25_search), 200 deep, for experiments 7 (keywords from a shortened issue) and 12 (keywords on the issue's identifiers). Per task of the repo's L0 set: title the issue's first line w32/w64/w128 its first 32, 64, 128 words idents the code-like names in it (core.identifiers: dotted names, snake_case, CamelCase) idents_q those and its quoted strings Kept in out/bm25v-<repo>.json as {task id: {variant: [chunk ids]}}. |
| `budget.py` | The character budget of search_code's answer: what the MCP tool returns today (the cards and the search footer) and with parts 1 and 2 at their defaults (related names on the cards, the next 20 results by name), with the branch's own search() and render, on one query set (or a shard of it). Today's text is the same response rendered without the related names and the more block: parts 1 and 2 change no result (tests/test_search.py), so it is what main returns. |
| `cochange.py` | Files changed together, from the local git history (bare clones, read only), for experiment 13. |
| `core.py` | The lab's own search over the kept lists: the product's fusion re-done in Python, so that every experiment is a change to one ranking function and the baseline is the product's search exactly. |
| `e12_held.py` | Experiment 12 on the held-out half (titles) and all vague tasks: the short query as is, against the short query plus the L0 issue's names as a fourth, keyword-only list (no setting is chosen, so both halves are reported). Also the L0 query plus its own names as a fourth list. |
| `e14_files.py` | Experiment 14: a keyword ranking over whole files, and experiment 15's outline capped per file. |
| `e15_outline.py` | Experiment 15: results grouped by file, each file with an outline of its functions (names, no code). For the baseline's top 10: how many distinct files; whether a gold function's name would be on the page without being one of the 10 results; and what the page costs (names, characters). Beside it, the same reach for experiment 8 (3 relations per card) and for the names of results 11 to 30, on the same tasks. |
| `e16_tests_apart.py` | Part 4, measured as experiment 11 was: test chunks take no place among the 10 cards (the cards are the ranking with tests left out of every list, as `tests="exclude"`), and the best 5 test chunks (the same three lists with only tests, fused) are named after the cards. Per set: a gold function in the 10 cards, against today's 10; and the tasks where a named test is one call away from a gold function (it calls one), with every edge and with callees over 100 callers left out. |
| `e8_choice.py` | Experiment 8, how a card's neighbours are chosen: by similarity to the query (as in s3_lab), at random, or by the fewest callers (the most specific first). Also: a fixed hub cap of 100 callers in place of the repo's 99th percentile. Reach = a gold function in the top 10 or named on a card. |
| `embed_extra.py` | Embed, once, the short queries the lab needs and the indexes' model made no vector of yet: the vague pandas prompts (L1, L2) and every task's issue title (pandas, vLLM). Query prefix as the product embeds a query (Embedder.embed_queries). Saved to qvec-extra.npz; the model is then freed. |
| `example_page.py` | The worked example's page: what search_code returns for pandas-dev__pandas-68195 at L2, today and with the branch's parts (related names, the next results by name, a guessed name), on the real pandas index; and with tests named apart. |
| `graph_stats.py` | The stored call graph of each index: degrees, hubs, test chunks, and the three edge versions the graph experiments use: (a) all edges; (b) without hub callees (more than K callers, K at the 99th and the 90th percentile of callers per callee); (c) only edges whose callee's name is defined once in the repo (callable kinds, per language family, as the indexer resolves calls). |
| `lab_common.py` | Shared data for the offline retrieval lab: tasks, gold labels, query vectors, and one index's chunks, vectors and call edges in numpy. Everything is read from copies under .cache/review/lab/idx. No model is needed: every chunk's vector is stored, so any candidate is scored exactly. |
| `metrics.py` | Ranks of the first gold file and the first gold function in a result list, and the tables made of them. |
| `prod.py` | The product's own code on an index copy: its Store, its search(), with question vectors made earlier. |
| `s1_baseline.py` | Stage 1: the product's own search() on an index copy, 50 results per task, with the rank each result had in each list. One query set per run; the raw results are kept in out/s1-<set>.json. |
| `s1_report.py` | Stage 1 tables from the kept runs (s1_run.py), and the check that the lab's fusion of the kept lists gives the product's own top 50 for every task (core.Fuser). |
| `s1_run.py` | Stage 1 run, one query set (or one shard of it): per task, * the product's own search(): codemem.search.search(store, query, Config(), k=50, debug=True), the stored question vector handed in by text (prod.Precomputed). Its first 10 are what the MCP tool returns for k=10 (same 50 candidates per list, ties ordered by location either way); * each of the search's three lists out to 1,000, through the product's own calls: bm25_match() + Store.bm25_search(match, 1000) and Store.vector_search(type, vector, 1000) (exact FAISS here). Kept in out/s1-<set>[.<shard>].json, nothing else is written. |
| `s2_errors.py` | Stage 2: where the gold functions are when the product's top 10 has none of them, and what they are. |
| `s3_e7kw.py` | Experiment 7's keyword part for a set whose s3 run had no keyword variants yet: the keyword list from a shortened issue (title, first 32/64/128 words, the names in it), in place of the whole issue's (e7kw) or beside it (e7kw2), merged into out/s3-<set>.json. Needs no vectors. |
| `s3_extra.py` | Stage 3, the experiments that are not one ranking choice: 3 (random neighbours and the placebo, at the settings experiment 1 chose), 8 (reach), the measurements of 9 and 13, the teammate's version, and 12 (a query in two parts: dense on the short text, keywords on the L0 issue's names). |
| `s3_lab.py` | Stage 3: every experiment as a ranking function over the kept lists (s1_run.py) and the stored vectors (lab_common.Index: every chunk scored exactly against the query vector, best part). |
| `s3_report.py` | Stage 3 report: for each experiment family, the variant chosen on the tuning half (half 0 of vllm-L0 and pandas-L0, by the hash of the task id), reported on the held-out half (half 1) and on the vague sets, against the baseline on the same tasks, with a paired bootstrap interval. |
| `s3_show.py` | Held-out results of named variants (no choice made here): half 1 of the L0 and title sets, all 17 vague tasks, against the baseline on the same tasks, with the paired bootstrap interval. |
| `validate_branch.py` | The branch's own search (andre/search-recall) on the index copies, to check that what the lab measured is what the product now does: reach with the cards' relations (card_relations = 3, the default), the top 10 with names passed apart from a short query, and the time both take. |
| `validate_part4.py` | Part 4 with the branch's own search(): `tests_apart` on, held-out halves and the vague sets. A gold function in the 10 cards, against today's; and the tasks where a named test calls a gold function (an edge in the index from the test to it; callees over 100 callers left out, as the cards do). |

## The small result files (`results/`)

- `s1-report.json`: the baseline per task set. `s2-summary.txt`: where the missed functions are.
- `s3-report*.json`, `s3-extra.txt`: every ranking experiment, the variant chosen on half 0 and its
  held-out counts with bootstrap intervals.
- `e14-measure.json`, `e15-outline.json`, `e16-tests-apart.json`: whole-file keywords, file
  outlines, tests kept apart.
- `validate-*.json`: the branch's own `search()` against the lab's numbers.
- `allgold-*.json`: fixes that change two or more functions, per task (how many of them are among
  the 10 results, with related names, with the next 20, with both, and with the control).
- `graph-stats.json`: the stored call graph of each index (degrees, hubs, test chunks).
