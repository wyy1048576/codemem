# Track B: loop vs grep on 21 tasks, results per round (n = 10 / 25 / 50), the duckdb-25101 case study, and grep's memory of the repos; PR #45

- **Track:** B
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-26 13:21 UTC
- **Work package:** B1 (why searches miss) and the query path; end-to-end comparison without tests
- **Branch, commits, pull request:** `wilson/loop-vs-grep-e2e` (`2c2a7b6`, `aa17019`), from `main`;
  **PR #45** https://github.com/wyy1048576/codemem/pull/45 (open, no reviewers requested). Folder
  `eval/experiments/b1-loop/`; the summary is `loop_vs_grep.md` there

## Done

**Track B's focus is now codemem's search loop against a grep agent, end to end** (Wilson's decision, 2026-11-26).
Result tables show only the one-shot search and the loop; the other retrieval arms (whole-issue, revise, diagnose,
one-hop) are dropped from here on.

**The algorithms, as they are in the PR.**
- *One-shot* (`aug_retriever.py`, `mode="oneshot"`): one Sonnet 5.5 call writes intent, symptom and up to 12
  verbatim anchors; codemem fuses (RRF, k = 60) dense intent + symptom on code and usage vectors (jina-code-0.5b),
  BM25 on the anchors, and BM25 / dense on the whole issue; top 50.
- *The loop* (`mode="loop"`; end to end `e2e_loop.py`): round 1 is exactly the one-shot search (checked in the
  code, `aug_retriever.py:203-204`, `e2e_loop.py:93-94`). Each round Sonnet sees up to N unseen results, says
  found or not, picks results, and writes the next query (intent, symptom, anchors, up to 3 `look_in` paths).
  Rounds 2+ fuse dense intent + symptom (pool 100), all anchors as one BM25 query, and lists limited to each
  `look_in` path. Seen results are never shown again. End to end, "found" triggers a fix call with the full code
  of the picks (up to 8 chunks) that returns exact edits; cap 10 rounds or $3. New: `LOOP_N` (default 50) and
  `LOOP_TAG` (output prefix) env settings.
- *Grep agent* (`e2e_run.py`): `claude -p`, Sonnet 5.5, medium effort, Read / Edit / Write / Grep / Glob, no shell,
  $5 budget, fresh copy of the repo at the base commit with git history removed.
- *One-hop* (`hop_retriever.py`): callers and callees of each top-50 result, ranked by cosine to the issue, 15 / 10
  / 5 per result by rank band. **Dropped**: of one-shot's 27 misses it adds 7 (all that are one call away), 6 of
  them in files the top 50 already has, at about 125 added functions (3,300 lines) per task; none of the 20 that
  are not one call away. The loop recovers more.

**Retrieval only (50 tasks, from `loopfull_results.md`).** Function MRR, one-shot vs loop (full code): DuckDB
0.298 → 0.711 (p 0.002), pandas 0.395 → 0.764 (p 0.003). Tasks with every gold function in the top 10: 8 → 16
(DuckDB), 9 → 14 (pandas).

**End to end, 21 tasks (7 DuckDB, 14 pandas, 36 gold functions), one run each, Sonnet 5.5.** n = results shown
per round. Recall = gold functions seen (≥ half their lines shown to the model) or edited (diff touches a line in
them), over 36. Edit columns count tasks with scored gold functions (20; pandas-68081 has none).

| Arm | $ per task | Recall | Tasks whose diff edits ≥1 gold function | … every gold function | … every gold file (of 21) | Tasks with no change | Median rounds |
|---|---:|---:|---:|---:|---:|---:|---:|
| loop, n=10 | $0.20 | 30/36 (83%) | 11/20 | 9/20 | 13 | 7 | 2 |
| loop, n=25 | $0.24 | 31/36 (86%) | 9/20 | 8/20 | 10 | 9 | 1 |
| loop, n=50 | $0.27 | 33/36 (92%) | 10/20 | 9/20 | 12 | 7 | 1 |
| grep agent | $0.08 | 24/36 (67%) | 15/20 | 12/20 | 15 | 0 | — |

- **n barely matters**: $0.27 → $0.20 and a little recall; edit columns move by 1-2 tasks (one run, noise).
- **The loop's gap is in deciding and fixing, not finding.** n = 50's 7 no-change tasks all ran the full 10
  rounds and cost $4.24 of the arm's $5.59 (76%). In all 7 every gold function had been shown. In 5 the fix
  call said "could not fix" (duckdb 23825, 23876; pandas 68575, 68947, 69478); in 2 Sonnet never said found
  (duckdb 23952, pandas 69447). Seen results are never shown again, so later rounds search what is left. Grep
  edited a gold function in 4 of these 7.

**duckdb-25101 case study** (`out/e2e-25101/`, `why25101.py`). Gold: `TopNHeap::Sink` and helpers in
`physical_top_n.cpp` (LIMIT 0 under a LEFT_DELIM_JOIN).
- grep $0.10 / 7 turns, codemem agent $0.26 / 15, codemem + grep agent $0.26 / 17 (1 codemem search, 6 greps):
  all edited the gold file. Loop with fix (n = 50) $0.77, fixed in round 10 at the cap. Retrieval-only loop-full
  $0.58, 5 rounds, never said found.
- Grep's first search `limit == 0` returned 5 lines including `physical_top_n.cpp:580`.
- The loop's round-1 top 50: 26 delim-join results, 0 from `physical_top_n.cpp`; Sonnet then chased delim-join
  state reuse for every round. Round 1's anchors did include `TOP_N` among 12 words: gold file at 26 and gold
  function at 588 in that BM25 list, lost in the fusion.
- Single queries, top 1,000: `TOP_N Top: 0` puts the gold file at 2 (BM25) / 3 (dense);
  `TopNHeap Sink limit 0 empty heap` at 1 / 1 (gold function 5 / 2); `limit == 0` at 339 / 192. codemem is weak on
  exact code patterns and strong on concepts; the problem is the hypothesis and the query shape.

**Does grep win from memory?** (`grep_memory.py` over the 23 finished grep runs, `grep_memory.json`.) In 9 runs the
first call searches inside the exact gold file although neither its path nor its file name is in the issue (e.g.
pandas-66270, 69113); 3 more name a gold file the issue names; 3 use code names not in the issue and land on it
(weaker test). So Sonnet remembers the repos' layout; nothing shows it saw the fixes (mid-2026). Those 12
first-call runs cost $0.063 on average, the other 11 $0.088, the loop $0.27: memory explains a little of grep's
cost, most is that a grep call returns a few lines and a loop round 50 results.

## Checked

- `e2e_topn_score.py` and `e2e_score.py --common` were run on the finished outputs and give the tables above;
  `e2e_topn.py` logged no failed run (42 runs). The loop-n runs used `e2e_loop.py` as committed, except the two
  pandas-70107 runs (n = 10, 25), which ran after another session's local edit (same 500-character previews,
  but the one-shot query call, $0.0125, is added to their cost).
- The 25101 ranks are from an earlier run of `why25101.py` on the 25101 index (the codemem + grep agent's edit was
  undone with its saved diff for the run and put back after); not rerun for this entry.
- Before the pandas runs, the runner waited until another session's pilot using `~/e2e-copies/pandas` had finished.
- **Not checked:** nothing was built or tested; one run per arm and task; the grep-memory test is a string match
  on paths and names, not a proof.

## Left

- Repeat runs (3-5 per arm and task) and grading of the saved diffs with hidden tests.
- The scripts still use absolute Windows paths and a local codemem at `7c24558`.
- Local only, not in the PR: another session's newer `e2e_loop.py` on Wilson's laptop (`LOOP_FULL=1` raw-code
  judge, one-shot cost counted). The PR has the version these runs used.

## Blocked on, or needed from others

- **Andrew (A):** whether the grader can grade a saved diff in the task's image (apply diff, add hidden tests,
  run), so `out/e2e-all/<task>/*.diff` get real verdicts. Wilson's laptop has no Docker or NVIDIA GPU.
- **Andre (C):** a look at PR #45, if he has time.

## Next

Wilson, in this order:
0. The fix step: on "could not fix", let the fix call ask for more code or let the next round see earlier
   results again; look at why the judge never said found on 23952 and 69447.
1. Narrow probes per round (several one-guess searches, each anchor its own BM25 search) and an exact-text search.
2. The renaming control for contamination: rename and move files in the test copy, rerun grep on the 23 tasks
   (about $2) and the loop (about $6).
