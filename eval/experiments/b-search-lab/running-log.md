# Search lab: progress

Brief: `.cache/review/briefs/search-lab.md`. Scripts and raw results: `.cache/review/lab/` (`out/`).
Product code measured: `.cache/wt/lab-main` = `origin/main` at `8d86da8`. Index copies: `idx/pandas` (pandas `a0885a1`), `idx/vllm` (vLLM `e9acf48`).

## 06:45 Start: what the earlier agent left, and what holds

- Its `s1_baseline.py vllm-L0` was still running (pid 84312, an orphan): stopped at 06:44. Its outputs are moved to `out/earlier-agent/` and not used: every number below is from my own runs.
- **Question vectors match the task files** (checked, not assumed): the vLLM file's name hash equals sha256(embedder key + the 381 issue texts of `eval/tasks/e2e/vllm.jsonl`, in file order); the pandas file's equals sha256(the 352 issue texts of `e2e/pandas.jsonl`, in file order), the formula of `gate_real_index.py`, which made it. `e2e/pandas.jsonl` and `fresh-v1.jsonl` hold the same ids, order, texts and gold. The texts have not changed since Oct 24.
- **Gold matching:** a gold file by its path; a gold function by (path, qualified name), as the index stores `qualname` (`Class.method`, `outer.inner`). The snapshot is one commit, not each task's: labels it lacks are counted apart.
- **The product's own search is measured:** `codemem.search.search()` of `lab-main` on a `Store` opened as `CodememService` opens it (same arguments, `Config()` defaults = the indexes' recorded settings), with the stored question vectors handed in by text instead of a model. `k=50` gives the same first 10 as the product's `k=10` (same 50 candidates per list; ties ordered by location either way).
- Index settings recorded in both indexes equal `Config()` defaults (max_seq_length 1024, window 2,976 chars, no stemming). Both indexes were built with the same embedder key as the question vectors (`jina-code-embeddings-0.5b|doc|L1024|float16|mps`).
- The vague set has **17 pandas tasks** (not a few dozen), 16 with a gold function in the snapshot: every vague result below is a count out of 16 or 17.

## 06:57 The segfault of 06:52 (pid 9780) was not mine

- My only model-loading process was `embed_extra.py`, **pid 8510** (torch's log prefix in `out/embed_extra.log` is the pid; checked), started 06:51:10 by a shell, not by a Python process, and it **finished**: `qvec-extra.npz` holds 17 + 17 vague vectors and 352 + 381 title vectors, all finite, no zero rows, norms 1.000; two issue texts embedded again gave cosine 1.0000 with their stored vectors. It imported `codemem` (config, embedder) before torch, never imported FAISS (`codemem.embedder` does not import `codemem.store`), and ran with `OMP_NUM_THREADS` unset in the shell, so `codemem/__init__.py` set it to 1 and `KMP_DUPLICATE_LIB_OK=TRUE`.
- The crash report's process (launched 06:51:41.75, parent a Python process, pid 9770) had FAISS 1.16 of `.cache/wt/faiss-1-16/.venv` loaded (UUID of `libfaiss.dylib` = that venv's), torch and scikit-learn, and several OpenMP threads (it died in a join barrier): another job using the same venv.
- From now on no process of mine loads the model; the tokenizer alone (no weights) is loaded by `s2_errors.py` to count tokens.

## Stage 1, baseline (pandas and vague sets done; vLLM running, about 7 s a task: 2 keyword searches of a whole issue)

The lab re-does the product's fusion from the kept lists; it gives **the product's own top 50 for 352 of 352 pandas tasks and 17 of 17 at L1 and L2** (so the experiments' baseline is the product's search exactly).

| set | tasks | gold files in the snapshot | gold functions in the snapshot | tasks with no function label | tasks with a gold file / a gold function in the snapshot |
|---|---|---|---|---|---|
| pandas-L0 | 352 | 433 of 488 | 598 of 624 | 53 | 324 / 295 |
| vague (L0, L1, L2) | 17 | 24 of 27 | 30 of 33 | 1 | 16 / 16 |

A gold function **in the top k** (tasks with at least one; MRR of the first one):

| set | tasks | top 5 | top 10 | top 20 | top 50 | MRR |
|---|---|---|---|---|---|---|
| pandas-L0 | 295 | 160 (54%) | 180 (61%) | 197 (67%) | 217 (74%) | 0.401 |
| vague-L0 | 16 | 11 | 13 | 13 | 15 | 0.514 |
| vague-L1 | 16 | 9 | 9 | 10 | 13 | 0.355 |
| vague-L2 | 16 | 7 | 8 | 10 | 12 | 0.192 |

A gold **file** in the top k:

| set | tasks | top 5 | top 10 | top 20 | top 50 | MRR |
|---|---|---|---|---|---|---|
| pandas-L0 | 324 | 248 (77%) | 260 (80%) | 268 (83%) | 286 (88%) | 0.632 |
| vague-L0 | 16 | 15 | 15 | 15 | 15 | 0.896 |
| vague-L1 | 16 | 11 | 12 | 12 | 15 | 0.637 |
| vague-L2 | 16 | 11 | 13 | 14 | 16 | 0.435 |

Vague set, top 10 / 15 / 20 / 30 (of 16): gold function L0 13/13/13/15, L1 9/9/10/11, L2 8/9/10/12; gold file L0 15/15/15/15, L1 12/12/12/12, L2 13/13/14/14.
What it shows: on the vague tasks, removing the names (L1) costs 4 of 16 tasks their gold function in the top 10, and the short request (L2) 5; a gold file stays in the top 10 for 12 to 13. The median product search took 439 ms with a whole pandas issue, 43 ms with an L2 request.

## Call graph facts (coordinator's numbers checked; `out/graph-stats.json`)

| | vLLM | pandas |
|---|---|---|
| chunks / test chunks (`is_test`) | 102,224 / 38,862 | 41,632 / 28,755 |
| edges; distinct callers; distinct callees | 305,482; 60,639; 35,167 | 163,090; 30,872; 6,583 |
| callers per callee: median, p90, p99, max | 2, 10, 95, 4,362 | 2, 25, 381, 9,117 |
| callees per caller: median, p90, p99 | 3, 11, 25 | 4, 11, 20 |
| biggest hubs | `ConstantList.append`, `FreeKVCacheBlockQueue.append`, `FlatLogprobs.append` (4,362 each: really `list.append`), `zeros`, `max` | `DataFrame` (two classes, 9,117 each), `Series` 6,460, `assert_frame_equal` 5,669 |
| edges kept (b) without callees over p99 / p90 callers | 157,712 / 81,496 | 75,311 / 20,870 |
| edges kept (c) callee name defined once (callable kinds, per language family) | 111,216 | 57,905 |
| edges from test callers | 151,484 | 128,568 |

Every graph experiment is run on (a) all edges, (b99), (b90) and (c).

## 07:08 Stage 1 complete (vLLM done; the earlier count reproduced exactly)

vLLM-L0: 381 tasks; gold files in the snapshot 596 of 604, gold functions 787 of 854; 23 tasks with no function label; 375 tasks with a gold file and 342 with a gold function in the snapshot. The lab's fusion = the product's top 50 for **381 of 381**. Median product search 2.3 s (the keyword search of a whole issue).

| set | tasks | function top 5 / 10 / 20 / 50 | function MRR | file top 5 / 10 / 20 / 50 | file MRR |
|---|---|---|---|---|---|
| vllm-L0 | 342 / 375 | 175 / 206 / 232 / 254 (51 / 60 / 68 / 74%) | 0.344 | 250 / 277 / 302 / 321 (67 / 74 / 81 / 86%) | 0.558 |
| pandas-L0 | 295 / 324 | 160 / 180 / 197 / 217 (54 / 61 / 67 / 74%) | 0.401 | 248 / 260 / 268 / 286 (77 / 80 / 83 / 88%) | 0.632 |
| vague-L0 | 16 / 16 | 11 / 13 / 13 / 15 | 0.514 | 15 / 15 / 15 / 15 | 0.896 |
| vague-L1 | 16 / 16 | 9 / 9 / 10 / 13 | 0.355 | 11 / 12 / 12 / 15 | 0.637 |
| vague-L2 | 16 / 16 | 7 / 8 / 10 / 12 | 0.192 | 11 / 13 / 14 / 16 | 0.435 |
| pandas-title (extra: the issue's first line as a short query) | 295 / 324 | 111 / 136 / 162 / 197 (38 / 46 / 55 / 67%) | 0.280 | 198 / 221 / 242 / 268 | 0.520 |

What it shows: the earlier vLLM numbers (file 67/74/81/86%, function 51/60/68/74%) come out exactly. pandas is a little better than vLLM at L0. A short query costs a lot: the issue's title alone puts a gold function in the top 10 for 46% of pandas tasks against 61% with the whole issue; on the 16 vague tasks, 8 at L2 against 13 at L0.

## 07:10 Stage 2, the error distribution (`s2_errors.py`, `out/s2-errors.json`, `out/s2-summary.txt`)

For each task with a gold function in the snapshot and none in the top 10, the closest gold function (best fused place, else best place in any list):

| where the closest gold function is | vLLM-L0 | pandas-L0 | vague-L2 |
|---|---|---|---|
| in the top 10 (hits) | 206 of 342 | 180 of 295 | 8 of 16 |
| fused 11 to 20 | 26 | 17 | 2 |
| fused 21 to 50 | 22 | 20 | 2 |
| a candidate (some list's top 50), fused past 50 | 22 | 26 | 2 |
| only in some list's 51 to 200 | 31 | 19 | 2 |
| only in some list's 201 to 1,000 | 21 | 25 | 0 |
| in no list's top 1,000 | 14 | 8 | 0 |
| (tasks whose gold functions are all missing from the snapshot, not counted above) | 16 | 4 | 0 |

The same misses by reach from the top 10 (all edges; the ladder takes the first that holds):

| | vLLM-L0 | pandas-L0 | vague-L2 |
|---|---|---|---|
| top 10 | 206 (60%) | 180 (61%) | 8 |
| else one call away from a top-10 result | 35 (10%) | 40 (14%) | 2 |
| else in the file of a top-10 result | 18 (5%) | 31 (11%) | 4 |
| else in the folder of one | 30 (9%) | 19 (6%) | 1 |
| none of these | 53 (15%) | 25 (8%) | 1 |
| one call away with edges (c) only (unique names) | 26 | 29 | 0 |

What the gold function is, misses against hits (closest gold function of each task):

| | vLLM misses / hits | pandas misses / hits | vague-L2 misses / hits |
|---|---|---|---|
| named in the query (its name as a word) | 45 of 136 / 139 of 206 | 21 of 115 / 121 of 180 | 0 / 0 |
| a window cut by the model (tokens > 1,024) | 0 / 0 | 0 / 6 | 0 / 0 |
| several code windows (text > 2,976 chars) | 67 / 84 (49% / 41%) | 48 / 90 (42% / 50%) | 1 / 3 |
| more than 3 windows | 21 / 23 | 9 / 42 | 0 / 1 |
| median lines; chars | 69; 2,859 / 56; 2,292 | 62; 2,397 / 76; 2,894 | 34; 1,400 / 44; 1,877 |
| no usage vector (nobody calls it) | 75 (55%) / 71 (35%) | 49 (43%) / 42 (23%) | 1 / 1 |
| kind: method / function (no class outline or block is a closest gold function) | 97 / 39 vs 137 / 69 | 80 / 35 vs 103 / 77 | 6 / 2 vs 6 / 2 |
| a gold file is already in the top 10 | 51 of 136 | 64 of 115 | 5 of 8 |

Also: **250 of 381 vLLM issue texts and 121 of 352 pandas ones are longer than the model's 1,024 tokens** (counted with the query prompt): the query vector of a whole issue sees only its first part. The rebuilt code text of every gold chunk examined equals the stored one (its hash), so the window and token counts are the indexer's own.

What it answers:
- **Mostly ranking, not chunking or embedding.** Of the misses, about half are already candidates (some list's top 50): 70 of 136 on vLLM, 63 of 115 on pandas, 6 of 8 at L2. Another third sit in a list's 51 to 1,000. Only 14 (vLLM) and 8 (pandas) are in no list's top 1,000.
- **Long functions are not the cause.** The model cut no window of a missed gold function. Misses have several windows about as often as hits (49% against 41% on vLLM; 42% against 50% on pandas). The 14 vLLM functions no list finds are long (median 114 lines, 9 of 14 windowed), but they are 14 tasks.
- **Whether the query names the function separates hits from misses most** (vLLM: 67% of hits, 33% of misses; pandas: 67% and 18%). Even named, a function can be lost in the fusion: 11 vLLM misses and 6 pandas misses have their gold function at keyword rank 1 to 10 and still fall out of the fused top 10.
- **Functions nobody calls are at a disadvantage**: 55% of vLLM misses have no usage vector against 35% of hits (pandas 43% against 23%). With three lists fused, a chunk that can be in only two of them starts behind.
- **Reach**: one more call from a top-10 result would reach the gold function in 35 (vLLM) and 40 (pandas) more tasks, the same file in 18 and 31 more. For about half the misses a gold file is already in the top 10 (51 of 136; 64 of 115): the file is found, the function is not.

## 07:18 Stage 3: the graph experiments (1, 2, 3, 8, 9) on the four edge versions

Protocol: every setting chosen on half 0 of vLLM-L0 + pandas-L0 (sha256 of the task id), reported on half 1 (vLLM 175 tasks with a gold function, pandas 162), and on all 16 vague tasks (their L1/L2 texts were never used to choose). Counts are tasks with a gold function in the top 10, base -> experiment, with the 95% bootstrap interval of the difference and tasks won/lost. "title" sets are an extra short-query check (the issue's first line as the query), same halves. Raw: `out/s3-*.json`, `out/s3-report*.json`, `out/s3-extra.json`.

**1. The graph as a fourth list** (callers/callees of the top n, scored by their own code-vector similarity, best m, fused by RRF; 81 settings per edge version):

| edges | chosen on half 0 | vLLM-L0 (99 of 175) | pandas-L0 (94 of 162) | vague-L2 (8 of 16) | vllm-title (58) | pandas-title (70) | files at top 10 |
|---|---|---|---|---|---|---|---|
| (a) all | callers, n5, m5, w1 | 98 (-1, -7..+5) | 99 (+5, -1..+11) | 9 | 58 | 73 | vLLM -2, vllm-title -6 |
| (b99) | callers, n5, m5, w1 | 99 (+0) | 98 (+4, -1..+10) | 9 | 58 | 74 | -2, -5 |
| (b90) | callers, n5, m5, w1 | 100 (+1, -5..+7) | 99 (+5, -1..+11) | 9 | 62 | 76 (+6, +2..+11) | -2, -5 |
| (c) unique names | callers, n3, m5, w2 | 94 (-5, -10..+0) | 96 (+2) | 8 | 61 | 74 | -6, -11 |

It adds 1 to 2 candidates a search. No version gains on both repos; (c), the edges least likely to be wrong, does worst. **Graph quality is not what limits it.**

**2. The graph as a lift only** (a candidate gains beta/(k+1) per edge to a top-n result; no new candidates at depth 50; at depth 200 the lists' top 200 compete): best per version on half 0, held out: depth 50: (a) -3 / +1, (b99) -1 / +0, (b90) +1 / +3, (c) -2 / +2 (vLLM / pandas). Depth 200: (a) +1 / +3, (b99) +1 / +4, (b90) -2 / +8 (CI +0..+16), (c) -6 / +4. Signs disagree between repos; nothing to keep.

**3. Andre's question: similar neighbours, random neighbours, and a placebo** (setting chosen on half 0 among the experiment-1 settings with both directions: b90, n3, m5, w1; random and placebo averaged over 5 draws):

| held out | base | most similar neighbours | random neighbours | placebo (random chunks of the repo) |
|---|---|---|---|---|
| vLLM-L0 (175) | 99 | 98 | 100.6 | 97.8 |
| pandas-L0 (162) | 94 | 97 | 94.2 | 94.0 |
| vague-L2 (16) | 8 | 9 | 8.2 | 8.0 |
| vllm-title (175) | 58 | 59 | 59.2 | 57.8 |
| pandas-title (162) | 70 | 76 | 74.2 | 69.6 |

Random neighbours do as well as the most similar ones on vLLM and slightly worse on pandas; both beat the placebo by 0 to 6 tasks. **The teammate's version** (every caller and callee of all 50 results, after rank 50) adds a median of 434 functions a search on vLLM (873 on pandas); 136 of its 188,522 additions on vLLM are gold functions (1 in 1,386; pandas 1 in 3,660). It cannot change the top 10 or 20.

**8. Reach without changing the ranking**: each card also names its 3 neighbours most similar to the query (both directions). Tasks with a gold function in the top 10 **or named on a card**, held out:

| held out | top 10 | (a) all edges | (b99) | (b90) | (c) | (b99), 5 per card | callers only | callees only | 3 best of the card's own file |
|---|---|---|---|---|---|---|---|---|---|
| vLLM-L0 (175) | 99 | 117 (+18, +11..+26) | 117 (+18) | 114 | 111 | 119 | 111 | 105 | 111 |
| pandas-L0 (162) | 94 | 110 (+16, +9..+24) | 109 (+15) | 107 | 107 | 111 | 110 | 97 | 109 |
| vague-L1 (16) | 9 | 12 | 12 | 11 | 11 | 13 | 11 | 10 | 11 |
| vague-L2 (16) | 8 | 10 | 9 | 9 | 8 | 9 | 9 | 9 | 12 |
| vllm-title (175) | 58 | 88 | 89 | 84 | 80 | 90 | 82 | 69 | 81 |
| pandas-title (162) | 70 | 90 | 89 | 87 | 86 | 91 | 86 | 77 | 79 |

Names added per search: about 18 to 21 with (a), 16 to 18 with (b99). Callers carry most of it on pandas. Choosing the 3 at random instead of by similarity loses 0 to 7 tasks (all 342 vLLM tasks: 236 against 235; vllm-title 181 against 174); a fixed cap of 100 callers equals (b99).
**The control that matters: listing results 11 to 30 by name reaches as much.** Held out, a gold function in the top 30: vLLM 116, pandas 108, vague-L2 12, vllm-title 98, pandas-title 87, against 117, 109, 9, 89, 89 for the relation lines (difference relation lines minus top 30: +1 (-8..+10), +1 (-7..+9), -3, -9 (-20..+2), +2). The two reach different tasks: together 127 (vLLM), 117 (pandas), 12, 109, 96.

**9. Tests as a bridge, the measure first.** Of the misses, the gold function is a direct callee of a test chunk in the top 10 for 8 of 136 (vLLM-L0) and 2 of 115 (pandas-L0); of a test chunk in some list's top 50 for 22 and 11; within two calls 31 and 15. On the title queries 46 of 224 and 24 of 159. Not common at L0. The list (callees of the best-ranked test chunks), chosen per version, held out: L0 -2 to +1 on both repos; vllm-title +8 (+2..+15) with (a), +5 with (b99); pandas-title +1 to +2.

What the graph does, in one line: **as a ranking signal it adds a few tasks on one repo and loses a few on the other, no better than random neighbours; as names on the cards it puts a gold function in sight for 15 to 18 more of about 170 held-out tasks, as many as simply listing the next 20 results, and the two together add 23 to 28.**

## 07:45 Stage 3: the other experiments (held out as above; vLLM-L0 base 99 of 175, pandas-L0 94 of 162, vague-L2 8 of 16)

| experiment (setting chosen on half 0) | vLLM-L0 | pandas-L0 | vague-L2 | vllm-title | pandas-title | files at top 10 | adds a search |
|---|---|---|---|---|---|---|---|
| 4. file siblings as a list (n3, m5, w0.5) | +4 (+1..+8) | +2 | +1 | +1 | -1 | vLLM -1, pandas -2, titles -4, -5 | 0.5 |
| 5. a file-level list (best chunk of the 3 files with the best chunk, w0.5) | -1 | +0 | +0 | +0 | +2 | vLLM +3, pandas -2 | 0 |
| 6. exact names of the query among definitions (L0 only; up to 20, w1) | +5 (-0..+11) | +0 (-6..+6) | +0 | +1 | +3 | +3, +1 | 9 / 6 |
| 7. fusion: depth 200, k 30, usage weight 0.5 | +5 (-1..+11) | +2 (-5..+9) | +1 | +9 (+2..+17) | +4 (+1..+8) | +6, **-5** | 390 |
| 7. depth 200 alone (k 60, weights 1) | -4 | +1 | +2 | +1 | -3 | +3, +0 | 390 |
| 7. a chunk nobody calls gets its code rank again in place of the usage list | +7 (+0..+14) | +1 | -2 | +1 | **-9** (-17..-2) | +3, **-8** | 390 |
| 7. keywords of the title or first 32-128 words in place of the whole issue (best: the issue's names) | +3 | **-7** (-15..+0) | | | | +2, **-8** | |
| 7. a second keyword list on the issue's names and quoted strings | +7 (+0..+15) | +6 (-2..+14) | (L0: +1) | | | +8, **-7** | 25 |
| 9. callees of the best-ranked test chunks as a list (a, T5, m5) | -1 | -1 | +1 | +8 (+2..+15) | +2 | +1, +2 | 2.6 |
| 10. at most 3 results per file in the top 10 | -5 | **-7** (-12..-2) | -1 | -2 | -4 | +2, +1 | 0 |
| 11. test chunks weighted 0.5 | **+5 (+1..+10)**, 5 won / 0 lost | **+5 (+0..+10)**, 6 / 1 | +1 | **+15 (+8..+23)** | **+12 (+5..+20)** | +3, +1; titles +8, +12 | 0 |
| 11. test chunks left out | +4 (+0..+9) | +6 (-2..+14) | **+3** (8 -> 11) | +9 | +10 | +5, +3; titles +9, +20 | 0 |
| 13. files changed together (n10, 10 files, best 10 chunks, w0.5) | -1 | +3 | +0 | **-5** (-10..-1) | +1 | +2, +1 | 6 |

Measures that go with them:
- **13, plain measure** (only commits older than each task's issue; 13,768 of them on average for vLLM, 15,719 for pandas; at least 290): of the tasks whose gold file is not among the top-10 files, a gold file is among the 5 files most often changed together with some top-10 file for 34 of 98 (vLLM-L0) and 28 of 64 (pandas-L0); among the 5 of the summed counts for 15 and 8. As names to show it might help; as a list it does not.
- **11 is the one ranking change that gains on every set with almost no loss, but read it with care:** the gold labels are never test code (pandas: 1 of 488 gold files is a test file, vLLM 13 of 604; gold functions 1 and 0), so any demotion of tests looks good here. The product's docs already say so (`config.py`: "Halving tests ... scores better on the eval only because its answers are never tests"). These labels cannot settle it.
- **12, a query in two parts** (no setting chosen; held-out halves for the title sets):

| set | short query as is | + the L0 issue's names as a fourth, keyword-only list | the whole L0 issue | L0 + its names as a fourth list |
|---|---|---|---|---|
| vllm-title, half 1 (175) | 58 | **88** (+30, +20..+40) | 99 | 110 (+11, +4..+19) |
| pandas-title, half 1 (162) | 70 | **81** (+11, +4..+19) | 94 | 95 (+1); files **-7** (-13..-2) |
| vague-L1 (16) | 9 | 11 | 13 | 13 |
| vague-L2 (16) | 8 | 11 (+3, +0..+6) | 13 | 13 |

The names list's weight, chosen on half 0 among 0.25, 0.5, 0.75 and 1: 1 (+53 functions and +20 files at top 10 over the four half-0 sets). Names passed apart recover 30 of the 41 tasks a short query loses on vLLM, 11 of 24 on pandas, 3 of 5 on the vague set. **The search tool should take names as a separate argument.** With the whole issue as the query too, they still help vLLM and cost pandas 7 gold files.

## 07:55 Experiment 15: results grouped by file, each file with the outline of its functions (`e15_outline.py`, `out/e15-outline.json`)

A gold function on the page (in the top 10, or named in the outline of a top-10 file), and what the page costs:

| set | top 10 | outline page | gain (95% CI) | distinct files | names on the page (mean / median) | characters | for comparison: 3 relations per card | names of results 11 to 30 |
|---|---|---|---|---|---|---|---|---|
| vLLM-L0, half 1 (175) | 99 | 125 | +26 (+17..+36) | 6.2 | 239 / 209 | 9,846 | 117 | 116 |
| pandas-L0, half 1 (162) | 94 | 129 | +35 (+25..+46) | 5.6 | 424 / 386 | 13,691 | 109 | 108 |
| vague-L0 (16) | 13 | 15 | +2 | 4.6 | 371 | 11,842 | 14 | 15 |
| vague-L1 (16) | 9 | 12 | +3 | 5.8 | 519 | 16,149 | 12 | 11 |
| vague-L2 (16) | 8 | 13 | +5 (+2..+9) | 5.4 | 488 | 16,312 | 9 | 12 |
| vllm-title, half 1 (175) | 58 | 104 | +46 | 6.1 | 227 | 9,825 | 89 | 98 |
| pandas-title, half 1 (162) | 70 | 101 | +31 | 5.1 | 406 | 14,534 | 89 | 87 |

What it shows: the file outline reaches the most tasks of any layout, but at 200 to 500 function names a search (10,000 to 16,000 characters, several times the 10 cards themselves): pandas files hold hundreds of methods. The same file structure named sparingly reaches much of it: the 3 functions of each card's own file closest to the query (experiment 8, "siblings") reach 12 of 16 at L2 with about 16 names. A capped outline (each top-10 file with its m functions closest to the query) is computed in `e14_files.py` (e15cap) and reported below.

## 07:55 Experiment 14, a keyword ranking over whole files (pandas done, vLLM running; `e14_files.py`)

Scratch FTS5 tables (`out/files-fts-<repo>.db`), one row per file of the snapshot, codemem's own keyword text and tokenizer; "text" = path + the file from the checkout at the index's commit, one column; "fields" = codemem's five fields gathered per file, codemem's field weights. The query's words are the product's.

(a) The plain measure, a gold file in the top 5 / top 10 files (tasks with a gold file):

| set | whole-file keywords, text | whole-file keywords, fields | files by their best chunk in codemem's chunk keyword list | files of the product's fused results |
|---|---|---|---|---|
| pandas-L0, all 324 | 146 / 189 | 153 / 177 | 151 / 184 | 260 / 265 |
| pandas-title, all 324 | 166 / 213 | 159 / 191 | 153 / 187 | 219 / 246 |
| vague-L1 (16) | 10 / 12 | 9 / 12 | 10 / 10 | 11 / 12 |
| vague-L2 (16) | 12 / 14 | 9 / 12 | 7 / 9 | 12 / 13 |

What it shows: with a whole issue, whole-file keywords find files no better than chunk keywords do (146 against 151 at top 5); with a short query they do better (title: 166 against 153; L2: 12 against 7 of 16), as the study found. But the product's fused ranking already puts a gold file in its first 5 files for 260 (L0), 219 (title) and 12 of 16 (L2) tasks, more than any keyword ranking alone. Whether the whole-file list adds to the fusion is (b), below once vLLM is done.

## 07:44 Stage 4, part 1 committed: `ba1ea14` on `andre/search-recall` (worktree `.cache/wt/search-recall`, from `origin/main` `8d86da8`; not pushed)

Each result of `search_code` gets `related: <qualified name> (<path>:<start line>), ...`: up to `card_relations` (default 3; 0 = off) callers and callees closest to the query by their stored code vectors (no model call), results themselves and callees with more than 100 callers left out (their callers not followed). Ranking unchanged (tested). Checked against the lab with the branch's own `search()` on the index copies, held-out halves: vLLM-L0 99 -> 117 of 175 (lab: 117), pandas-L0 94 -> 108 of 162 (lab, cap 100: 108), pandas-title 70 -> 88, vllm-title 58 -> 89, vague-L2 8 -> 9; 16 to 18 names a search; the extra work 4 ms median on pandas, 9 ms on vLLM (p90 9 and 19 ms). Tests: `tests/test_search.py` (5 new), `tests/test_frontends.py` (MCP and CLI output); 119 passed in the three touched files.
An earlier commit `510c7b9` (parts 1 and 3 together, another line format) was replaced by this one before anyone used it.

## 07:58 Part 0 committed: `f821dc7` (after part 1 `ba1ea14`, which had already landed)

The four MCP tools are registered with `structured_output=False`. Checked in the installed `mcp` 2.3: a tool returning `str` otherwise announces an output schema `{"result": string}` and sends `structuredContent: {"result": "<text>"}` beside the text (shown with a two-tool probe: before, `structured_content={'result': '1. a.py:1-2 ...\n   def f():'}`; after, `None`, the text alone, no output schema). New test `test_mcp_tools_answer_in_plain_text`: all four tools through the real MCP server object, one text content each, no structured content, the search answer starts `1. auth/sessions.py:19-20  revoke_session`, with real line ends. 94 passed in `test_frontends.py` + `test_search.py`.
Next: part 2 (in progress, set aside in a stash while part 0 went in), then part 3, then part 4.

## 08:05 Part 2 committed: `868fea6`

After the k cards: `More results, by name (ask get_chunk for any of them):` and results k+1 to k+M, `path:start line  name`, one per line (`more_results`, default 20; 0 = off). Same merge, same order; the cards are unchanged (tested: keys and scores equal with the block on and off, and the block equals results 4 to 23 of a k = 23 search). k + M up to 50 is always available (each list gives `candidates` = 50). 122 passed in the touched files. The character budget on the 381 vLLM issues is being measured (three processes on a machine that hit a load average of 62); the vague set so far: today 5,125 characters on average (95th percentile 6,865), with parts 1 and 2 at their defaults 7,967 (9,426).

## 08:12 Part 3 committed: `dc074ae`; the character budget in the docs: `b38f74b`

Part 3: `names` on `search_code`, `search()`, `CodememService.search` and `codemem search --names a,b`: a fourth list built as experiment 12 built it (the names joined by spaces through `bm25_match()`, `Store.bm25_search()` over the five keyword columns with the field weights 10/3/5/2/1, top 50, RRF weight 1; `[rrf] weights = { names = 0 }` turns it off). One sentence in every steering level's description: "Put any function, class, method or file names you know or guess in `names`, apart from the query: they are matched as exact words, and guessed names are welcome." Tests: without names (none, empty, blanks, weight 0) the results and scores equal the three lists' own merge; a named function moves up (into the first three on the test repo); CLI and MCP take it. Checked with the branch's own search on the index copies: vllm-title 58 -> 88 of 175, pandas-title 70 -> 81 of 162, vague-L2 8 -> 11 of 16 (the lab's numbers exactly). 125 passed in the touched files.

**Character budget** (branch's own `search()` + `format_results()` + the MCP footer, real vLLM index, 381 issues, k = 10):

| | today (main) | parts 1 and 2 at their defaults |
|---|---|---|
| vLLM, 381 issues: mean / 95th percentile | 5,801 / 7,660 characters | 9,332 / 11,713 (+3,532 on average) |
| vague pandas requests, 17: mean / 95th percentile | 5,125 / 6,865 | 7,967 / 9,426 |

Today's text is the same response rendered without the related names and the more block, which is what main returns, since the ranking is unchanged.

## 08:22 Part 4 committed: `32b79b8` (option `tests_apart`, default off; nothing changes unless it is set)

With `tests_apart = true` and no `tests` argument: the cards are those of `tests="exclude"`, and the best `tests_apart_count` (5) test chunks (the same lists with only tests, merged) follow the cards under `Tests that match:`. A `tests` argument wins (tested through MCP too). Measured as experiment 11, lab (`e16_tests_apart.py`) and the branch's own search agree exactly:

| held out / vague | gold function in the 10 cards: today -> tests apart | tests among today's 10 (mean) | a named test calls a gold function (callees over 100 callers left out) | of those, gold function not in the cards |
|---|---|---|---|---|
| vLLM-L0 (175) | 99 -> 103 (+4, +0..+9; 5 won, 1 lost) | 1.9 | 47 | 4 |
| pandas-L0 (162) | 94 -> 100 (+6, -2..+14; 12 won, 6 lost) | 2.9 | 31 | 1 |
| vague-L0 (16) | 13 -> 13 | 2.2 | 4 | 0 |
| vague-L1 (16) | 9 -> 10 | 2.6 | 4 | 1 |
| vague-L2 (16) | 8 -> 11 (+3, +0..+6) | 3.2 | 3 | 0 |
| vllm-title (175) | 58 -> 67 (+9, +2..+17) | 3.3 | 38 | 11 |
| pandas-title (162) | 70 -> 80 (+10, +1..+19) | 4.6 | 29 | 1 |

What it shows: the named tests mostly lead to a gold function the cards already show; they add a path to it for 4 (vLLM) and 1 (pandas) held-out tasks at L0, 11 on vLLM titles. The extra search over test chunks costs 40 to 140 ms median for a short query and 343 ms for a whole pandas issue (the first search takes about 420 ms there). The gold labels are never tests, so the card numbers favour the option by construction.

Branch now: `ba1ea14` part 1, `f821dc7` part 0, `868fea6` part 2, `dc074ae` part 3, `b38f74b` docs (character budget), `32b79b8` part 4. The full suite runs next.

## 08:25 Experiment 14 finished (vLLM too) and the capped outline

(a) vLLM, a gold file in the top 5 / 10 files: whole-file keywords (text) 179 / 220 of 375 at L0 against 228 / 259 for chunk keywords by best chunk (and 262 / 295 for the product's fused files); with the title as the query 200 / 234 against 206 / 244. **On vLLM whole files do not beat chunks even for short queries; on pandas they do for short ones** (title 166 against 153; L2 12 against 7 of 16). A whole-file keyword query of a whole vLLM issue takes 3.6 s (median).
(b) The whole-file list fused as one more list (best 2 chunks of the 5 best files; chosen on half 0 among 24, "text" rows best on the vague and title sets), held out: vLLM-L0 96 (-3), pandas-L0 96 (+2), vague-L1 9 -> 11, vague-L2 8 -> 11, vllm-title 58 -> 67 (+9, +1..+17), pandas-title 70 -> 75 (+5). With codemem's five fields instead of the plain file text: vLLM-L0 93 (-6, -12..-1). It needs a new keyword table (an index change).
Experiment 15 capped (each top-10 file shown with its m functions closest to the query, results left out), held out: m = 5 (about 20 names): vLLM-L0 109, pandas-L0 109, vague-L1 11, vague-L2 12, vllm-title 82, pandas-title 80; m = 10 (about 45 names): 116, 118, 12, 13, 93, 87. The full outline (200 to 500 names) reaches 125, 129, 12, 13, 104, 101.

## 08:25 The experiments ranked by gain on the vague prompts (L1, L2; 16 tasks each), with cost

Settings chosen on half 0 of the two L0 sets; the vague tasks were never used to choose. A difference of 1 or 2 out of 16 is one or two tasks. The title columns (the issue's first line as a short query, held-out halves) give the same comparison on 175 and 162 tasks.

**What reaches the page** (a gold function among the 10 cards or named on the page; today L1 9, L2 8, vllm-title 58, pandas-title 70, vLLM-L0 99, pandas-L0 94):

| change | L1 | L2 | vllm-title | pandas-title | vLLM-L0 / pandas-L0 | cost a search |
|---|---|---|---|---|---|---|
| parts 1 + 2: related names + next 20 results by name (on the branch) | 13 (+4) | 12 (+4) | 109 (+51) | 96 (+26) | 127 (+28) / 117 (+23) | about 37 names; +2,842 characters on the vague set, +3,532 on vLLM (+61%) |
| whole outline of the top-10 files (exp 15) | 12 (+3) | 13 (+5) | 104 (+46) | 101 (+31) | 125 (+26) / 129 (+35) | 200 to 500 names, 10,000 to 16,000 characters |
| next 20 results by name (part 2 alone) | 11 (+2) | 12 (+4) | 98 (+40) | 87 (+17) | 116 (+17) / 108 (+14) | 20 names |
| 3 closest functions of each card's own file (exp 8, siblings) | 11 (+2) | 12 (+4) | 81 (+23) | 79 (+9) | 111 (+12) / 109 (+15) | about 16 names |
| each top-10 file's 5 closest functions (exp 15 capped) | 11 (+2) | 12 (+4) | 82 (+24) | 80 (+10) | 109 (+10) / 109 (+15) | about 20 names |
| related names, 3 per card (part 1 alone) | 12 (+3) | 9 (+1) | 89 (+31) | 88 (+18) | 117 (+18) / 108 (+14) | about 17 names, 4 to 9 ms |

**What changes the 10 cards** (today the same as above):

| change | L1 | L2 | vllm-title | pandas-title | vLLM-L0 / pandas-L0 | cost and caveat |
|---|---|---|---|---|---|---|
| names passed apart (part 3; here the L0 issue's identifiers) | 11 (+2) | 11 (+3) | 88 (+30) | 81 (+11) | with the whole issue too: 110 (+11) / 95 (+1, files -7) | the agent must know or guess names; one more keyword search (58 to 376 ms with all of an issue's identifiers) |
| test chunks out of the cards (part 4 option; exp 11 "left out") | 10 (+1) | 11 (+3) | 67 (+9) | 80 (+10) | 103 (+4) / 100 (+6) | gold labels are never tests: favoured by construction; naming the tests costs a second search |
| whole-file keyword list (exp 14) | 11 (+2) | 11 (+3) | 67 (+9) | 75 (+5) | 96 (-3) / 96 (+2) | a new keyword table (index change); 3.6 s for a whole vLLM issue |
| graph as a lift (exp 2) | 9 (0) | 10 (+2) | 63 (+5) | 72 (+2) | 93 (-6) / 98 (+4) | lists 200 deep |
| graph as a fourth list (exp 1) | 10 (+1) | 9 (+1) | 62 (+4) | 76 (+6) | 100 (+1) / 99 (+5) | random neighbours do as well (exp 3) |
| tests weighted 0.5 (exp 11) | 9 (0) | 9 (+1) | 73 (+15) | 82 (+12) | 104 (+5) / 99 (+5) | gold never tests |
| fusion: depth 200, k 30, usage 0.5 (exp 7) | 9 (0) | 9 (+1) | 67 (+9) | 74 (+4) | 104 (+5) / 96 (+2) | pandas files -5 |
| callees of the best tests as a list (exp 9) | 9 (0) | 9 (+1) | 66 (+8) | 72 (+2) | 98 (-1) / 93 (-1) | |
| file siblings as a list (exp 4) | 9 (0) | 9 (+1) | 59 (+1) | 69 (-1) | 103 (+4) / 96 (+2) | files -1 to -5 |
| file-level list by best chunk (exp 5) | 9 (0) | 8 (0) | 58 (0) | 72 (+2) | 98 (-1) / 94 (0) | |
| exact names of the query (exp 6) | 9 (0) | 8 (0) | 59 (+1) | 73 (+3) | 104 (+5) / 94 (0) | L0 only: vague requests name nothing |
| files changed together (exp 13) | 9 (0) | 8 (0) | 53 (-5) | 71 (+1) | 98 (-1) / 97 (+3) | |
| at most 3 per file (exp 10) | 9 (0) | 7 (-1) | 56 (-2) | 66 (-4) | 94 (-5) / 87 (-7) | |
| a chunk nobody calls gets its code rank twice (exp 7) | 8 (-1) | 6 (-2) | 59 (+1) | 61 (-9) | 106 (+7) / 95 (+1) | |

## 08:35 Full suite on `32b79b8` (the branch's last commit), and the report

`.cache/review/run_suites.sh search-recall`, no other pytest running: the default backend **746 passed, 4 deselected** (169 s); the compact and faiss backends are running (results appended below when done).
The report: `.personal/audits/2026-11-26-search-misses-and-what-recovers-them.md` (the finding first, the pandas-68195 example throughout). The example's actual pages, today and with each part: `out/example-page.txt`.

## 08:42 Full suite done on `32b79b8`: all three runs pass

| run | result |
|---|---|
| default backend | 746 passed, 4 deselected (169 s) |
| `CODEMEM_TEST_VECTOR_BACKEND=compact` | 743 passed, 3 skipped (default-only tests), 4 deselected (169 s) |
| `CODEMEM_TEST_VECTOR_BACKEND=faiss` | 743 passed, 3 skipped, 4 deselected (171 s) |

Logs: `.cache/review/search-recall-{plain,compact,faiss}.log`. The branch is complete: `ba1ea14` part 1, `f821dc7` part 0, `868fea6` part 2, `dc074ae` part 3, `b38f74b` docs, `32b79b8` part 4. Not pushed.
