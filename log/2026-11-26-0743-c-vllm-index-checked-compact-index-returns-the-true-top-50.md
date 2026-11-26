# Track C: on the real vLLM index the compact search index returns the true top 10 and top 50 in all 762 searches; a script fix for the PC check; two numbers for track B

- **Track:** C. Points 6 and 7 are for track B, point 8 for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 07:43 UTC
- **Work package:** C2, C3 (the check on a real index above 50,000 vectors)
- **Branch, commits, pull request:** `andre/compact-default` (`b6f1961`, #36), `andre/track-c-all` (`bd6ffbc`), `andre/track-c-results` (`28cf96f`, no pull request). `main` is unchanged at `bdd58d5`

## Done

**1. The real vLLM index is built:** 144,729 vectors (109,562 code, 35,167 usage) for 102,224
chunks, vLLM at `e9acf48`, the real model.

**2. The compact index against a brute-force oracle on it.** The questions are the 381 issue
texts of the eval's vLLM tasks, each asked of both vector types for 50 chunks: 762 searches per
row. The oracle scores the stored vectors in NumPy and uses neither codemem's search nor FAISS's.

| Setting | The true top 10 | The true top 50 |
|---|---|---|
| the exact index | 762 of 762 | 762 |
| the default: 4 bits, 200 candidates | 762 | 762 |
| 2 bits, 200 candidates | 762 | 762 |
| 8 bits, 200 candidates | 762 | 762 |
| 1 bit, 1,000 candidates | 762 | 762 |
| 1 bit, 500 candidates | 762 | 754 |
| 1 bit, 200 candidates | 762 | 664 |

The largest difference between a returned score and the oracle's: 0.0000001.

**3. How much room the default leaves** (the deepest place a chunk of a true top 50 had):

| | code vectors | usage vectors |
|---|---|---|
| the 1-bit scan keeps | 2,191 | 2,000 |
| the deepest place needed | 976 | 512 |
| the 4-bit ranking keeps | 220 | 204 |
| the deepest place needed with 4 bits | 102 | 74 |
| with 2 bits | 194 | 202 |
| with 8 bits | 95 | 53 |

So 4 bits is enough, 8 bits buys nothing (1.7 times the memory, 3.5 times the time to make the
codes), and 2 bits has no room left. A wider scan (4,000 to 16,000) changed no result.

**4. The weak point, measured again:** the 352 pandas questions asked of the vLLM index (a
question about something the repo does not hold). The true top 10 in 704 of 704 searches, the
true top 50 in 703. The lost result was at rank 44; its vector lay at place 2,178 of the scan,
which kept 2,000. With the scan keeping 4,000, all 704 are right. For that one question the
merged search returned the same 10 results, and the same 50, in the same order.

**5. What it saves and costs on vLLM:**

| | exact | compact, the default |
|---|---|---|
| memory the process holds for the search index | 278 MB | 106 MB |
| saved search index on disk | 261 MB | 86 MB |
| loading from the saved file / building from the rows | 0.3 s / 1.8 s | 0.3 s / 18.6 s |
| one search, 109,562 code vectors (median) | 16.3 ms | 15.5 ms |
| one search, 35,167 usage vectors (median) | 4.4 ms | 7.3 ms |

- On pandas (43,187 code vectors) the compact index is slower: 6.9 ms against 4.6 ms. It has a
  fixed cost of 4 to 7 ms a search. It is level at about 110,000 vectors and faster beyond.
  **This corrects the entry of 03:05**, which gave the audit's 6.5 ms against 9.9 ms for pandas:
  those two were not taken side by side.
- The default rule (`auto`) on the vLLM index: the exact index on a 16 GB machine (269 MB within
  a budget of 344 MB), the compact one on an 8 GB machine (91 MB).

**6. For track B, search time on a large repo.** On vLLM, with the query's vector given (no
model time):

| Query | A whole search | Of which keywords |
|---|---|---|
| three short questions, 4 to 9 words | 38 to 57 ms | 10 to 27 ms |
| a whole issue text (median 5,700 characters, 404 distinct tokens; 48 questions) | 2.4 s median, 11.5 s at most | 99% |

The vector part is about 14 ms for code and 4 ms for usage either way. An agent's queries are
short, so this is not what an agent waits for. The retrieval eval asks with whole issue texts,
and there the keyword search is nearly all of a search's time.

**7. For track B, a count for the reranker question.** The same 381 questions with the exact
index, merged search, on this one commit of vLLM. A gold file is matched by its path, a gold
function by its path and qualified name; 6 tasks have no gold file left in this index and 39 no
gold function.

| | Among the 10 results | Among 50 results |
|---|---|---|
| questions with a gold file found | 277 of 375 | 321 |
| questions with a gold function found | 206 of 342 | 254 |

So a perfect reranker over 50 candidates lifts "found in the top 10" by at most 12 points for
files and 14 for functions. These are not the eval's numbers: the eval indexes each task's own
commit. They say how much lies between rank 11 and rank 50.

**8. For track A, a fix in the check for the PC.** `scripts/check_search_indexes.py` ended in
`KeyError: 'repo'` when run without `--tasks`: #29 added a task file of another kind to
`eval/tasks`. That is how the entry of 2026-11-25 23:43 asks for it. It is fixed, with three
tests, on `andre/compact-default` and on `andre/track-c-all`. The two commands of that entry work
again after `git fetch` and a checkout of `origin/andre/track-c-all`. The package code is the
same as before.

**9. The results doc has all of this:** `docs/analysis/track-c-results.md` on
`andre/track-c-results`, §3.

## Checked

- The oracle agrees with the exact index in all 762 searches, to 0.0000002 in every score.
- Each memory and loading number is from a process of its own, twice. The search times are
  medians over the 381 questions, three passes, the indexes taking turns question by question in
  one process. Another job ran beside them: the ratios hold, the milliseconds are to be taken
  again.
- Not checked yet: the repo's check script on vLLM through the merged search (running; on pandas
  it gave the same 10 results in the same order for all 352 questions). Linux, x86, FAISS on more
  than one thread.

## Left

- The merged check on vLLM, and the times on a quiet machine.
- #34, #35, #36 (Andre merges). The fixes the audits asked for.

## Blocked on, or needed from others

- **Andrew:** the check on the PC (entry of 2026-11-25 23:43) is still wanted before #36. With
  vLLM checked here, what it adds is Linux, x86 and FAISS on every core.
- **Wilson:** nothing to do. Points 6 and 7 are yours to use or to ignore.

## Next

- Track C's session: the merged check's result, the quiet times, the pull request texts.
