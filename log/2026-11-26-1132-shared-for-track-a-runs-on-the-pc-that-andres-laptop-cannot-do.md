# For track A, a request from Andre: four runs on the PC, because his laptop is too weak for them. He needs their numbers before he decides further

- **Track:** from Andre, as project lead, for track A's PC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 11:32 UTC
- **Work package:** C6 (the scale and cost report), and the checks of C2 on Linux
- **Branch, commits, pull request:** `andre/track-c-defaults` (`656e823`); it holds the script of run 3. If that branch is gone, it has been merged: use `origin/main`

## Done

**The request, in Andre's name.** His laptop is an M1 with 16 GB. It cannot hold a million
vectors beside its other work, and it is not Linux. Four things are still unmeasured, and two of
his decisions wait for them: what codemem can say about speed on a large repo, and whether the
compact index keeps its second code. These runs need the machine, not Andrew: start them in a
worktree of their own, let them run, and post what they print.

**This changes the order of the entry of 09:56 for these runs only.** The tasks stay first. Runs
1 to 3 use no GPU and no agent seat, so they can run beside the task work. Run 4 needs the GPU
for a few minutes per repo: fit it in where the GPU is free.

```bash
git fetch origin && git worktree add ../codemem-c origin/andre/track-c-defaults && cd ../codemem-c
uv sync
```

| Run | Command | Takes about | What it tells Andre |
|---|---|---|---|
| 1. The tests on Linux | `uv run pytest -q; CODEMEM_TEST_VECTOR_BACKEND=compact uv run pytest -q; uv run python scripts/check_faiss_calls.py` | 10 minutes | whether `main`'s code and FAISS 1.16.0 work on Linux and x86. Nobody has run them there |
| 2. How big each repo's index is | for each index folder the PC has: `sqlite3 "file:<index folder>/index.db?mode=ro" "select vec_type, count(*) from vectors group by 1; select count(*) from chunks;"` | a minute | which repos are large enough for the compact index to matter, on which machine |
| 3. Cost against size | `uv run python scripts/bench_search_scale.py --work <a folder with 12 GB free> --out scale-all-cores.json --sizes 100000,200000,500000,1000000,2000000` and then the same with `--out scale-one-core.json --threads 1 --sizes 100000,200000,500000,1000000` | 30 to 60 minutes each; no GPU; up to 6 GB of memory | memory and search time of the exact and the compact index from 100,000 to 2 million vectors: the size at which the compact index starts to save time. It also runs FAISS's own search over one code, which decides whether the second code stays |
| 4. The same results on real indexes | `uv run python scripts/check_search_indexes.py --index <index folder> --repo <owner/name>` for pandas, for playwright, and for the largest repo the PC has an index of | 15 to 40 minutes per repo, a few of them on the GPU | that the compact index returns what the exact one returns on Linux, and how fast each is there. It ends with PASS or with what differs |

**What to send back,** in one entry here:

1. Run 1: the last line of each pytest run; for `check_faiss_calls.py` its last line and its exit
   status. If a test fails, its last 40 lines.
2. Run 2: the counts, one line per repo.
3. Run 3: the two tables it prints, as they are, and the two JSON files (paste them into the
   entry, or commit them beside it).
4. Run 4: the table each run prints, with its last line.

**Three things to know.**

- Do not set `OMP_NUM_THREADS` yourself: run 3 sets it where it should, and the others must run
  as codemem runs on that machine.
- Run 3 writes only into `--work` and deletes its indexes when it ends. Run 4 copies `index.db`
  into a folder of its own and deletes the copy; it never changes an index.
- If `uv sync` fails, post the error and stop: that would be the first sign that FAISS 1.16.0
  does not install on the PC, and it matters more than the runs.

## Checked

- Run 3's script ran here on 20,000 and 60,000 vectors. Runs 1 and 4 ran here on macOS.
- Nothing of this has run on Linux.

## Left

- Nothing on track C's side until the numbers are back.

## Blocked on, or needed from others

- **Andrew:** the four runs. Runs 2 and 3 first: they are what Andre's decisions wait for.

## Next

- Track C's session reads the results here and puts them into the results doc.
