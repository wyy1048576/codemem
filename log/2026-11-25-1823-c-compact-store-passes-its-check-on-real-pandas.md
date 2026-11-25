# The compact store passes its check on a real pandas index: the same results in 352 of 352 searches

- **Track:** C
- **Who:** Andre, with Claude Code
- **When:** 2026-11-25 18:23 UTC
- **Work package:** C2 (its "done when"), part of C1
- **Branch, commits, pull request:** `andre/track-c-all` (`03fc6f3`), which merges all five track C
  branches for testing. Local, not pushed

## Done

**The check of plan track C §9 (C2) on real data.** A pandas index built with the real model
(`jina-code-embeddings-0.5b`, pandas at `a0885a1`, 41,632 chunks, 43,187 code vectors and 6,583
usage vectors). The questions are the issue texts of the eval's 352 pandas tasks (`fresh-v1`:
66 dev, 286 test), embedded as a search embeds them. Each setting opened the same rows. The
exact index is the reference.

| Setting | Top 10 per vector type equal | Top 50, mean overlap (code / usage) | The whole search: the same 10 results in the same order |
|---|---|---|---|
| **the default** (4 bits, 200 candidates) | 352 of 352 | 1.0000 / 1.0000 | 352 of 352 |
| 4 bits, 500 | 352 of 352 | 1.0000 / 1.0000 | 352 of 352 |
| 2 bits, 500 | 352 of 352 | 1.0000 / 1.0000 | 352 of 352 |
| 1 bit, 1,000 or 2,000 | 352 of 352 | 1.0000 / 1.0000 | 352 of 352 |
| 1 bit, 500 | 352 of 352 | 0.9999 / 1.0000 | 352 of 352 |
| 1 bit, 200 | 352 of 352 | 0.9988 / 0.9994 | 346 of 352 |

"The whole search" is codemem's merged search, keywords and both vector types, 10 results. The
dev and the test questions give the same picture: no difference in either split, except the six
of the last row, which are all test questions.

**So the pass rule is met with room to spare.** The plan asks for the same top 10 in at least
99% of dev queries. The default gave the same top 10, the same top 50 and the same merged
results in every search, here and on the 768 searches of the earlier entry.

**One cost seen in this run.** On an index of this size the default's vector step was slower
than the exact one: 19.8 ms against 6.2 ms per vector type (median). A build was using the
machine, so the values are rough. The earlier measurement put the two level at 60,000 to 160,000
vectors, and 2 ms apart at 31,000 on a calmer machine.

## Checked

- My own run: `.personal/benchmarks/gate_real_index.py`, with the code of `andre/track-c-all`.
  The index was built by `codemem index` in 2 h 54 min on an M1 with other jobs running.
- Not checked: the eval's own metrics (the results are identical, so they cannot differ);
  another model; an index above 50,000 real vectors. A real vLLM index (about 145,000 vectors)
  is being built for that, and its 381 issue texts will be run the same way.

## Left

- The vLLM check. The pull requests.

## Blocked on, or needed from others

- **Andre:** push the branches and open the pull requests. Decide whether `codemem-final` sets
  `vector_backend = "compact"`.
- **Andrew:** nothing. A configuration with `vector_backend = "compact"` returns the same
  results as today's, so completion and tokens cannot change through it. What changes is the
  memory of each codemem process and the size of the saved search index.

## Next

- Andre's session: the vLLM check when its build is done.
