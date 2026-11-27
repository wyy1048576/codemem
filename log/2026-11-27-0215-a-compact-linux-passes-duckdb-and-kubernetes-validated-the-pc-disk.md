# Track A: `andre/compact-linux` passes on the PC and the diagnostic says what you expected; duckdb 58 and kubernetes 54 valid; the runner now warms codemem; the PC cannot build until its disk is freed

- **Track:** A. Answers Andre's entries of 21:00 (point 6), 21:10 and 21:20 UTC
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-27 02:15 UTC
- **Work package:** A1, A9; C2 on track C's side
- **Branch, commits, pull request:** `main`: #59 (`a216908`, the runner warms codemem). Data: `log/2026-11-27-0215-a-data/diagnose.txt` on this branch

## Done

**0. Our session was down from about 20:30 to 02:00 UTC** (the laptop that drives the PC died). The jobs on the PC ran on. Your entries of 16:10 to 21:50 UTC are read.

**1. `andre/compact-linux` (`bc76bd0`) on the PC** (Linux x86-64, AMD Ryzen 9 3950X, FAISS 1.16.0, numpy 2.4.6 with OpenBLAS 0.3.31, Python 3.11.18; `uv sync` clean; nothing else was running):

```
uv run pytest -q tests/test_compact_store.py
94 passed in 8.18s

uv run python scripts/diagnose_compact_store.py > diagnose.txt 2>&1      (exit status 0, 82 lines)
python -c "import faiss; print(faiss.get_compile_options())"
OPTIMIZE DD AVX2
```

The diagnostic, in all four thread settings (BLAS 1 or 16 threads, FAISS 1 or 16):
- **stage 1, prepare:** a row's bits depend on its call: no.
- **stage 2, rotation** at 32, 48 and 896 numbers: rows differ from a call of 4,096 for call sizes 1, 2, 3, ... (the list is in the file).
- **stage 3, FAISS encode** of the same float rows, one add against pieces: **equal** for 1 bit and for 4 bits.
- Every scenario: the ids are equal and the bytes are not; the first difference is in the correction numbers of a vector's code.

So the cause on x86 is the one you found (the rotation in BLAS), and the branch is enough here. The full file is beside this entry. With FAISS on one thread the bytes still differ, so `OMP_NUM_THREADS=1` would not have helped.

**2. Validation of 60 candidates** (PC, ended 21:57 and 22:08 UTC):

| Repo | Validated | Valid | Invalid |
|---|---|---|---|
| duckdb | 60 | 58 | 2 (one base commit does not compile with forced asserts; one other) |
| kubernetes | 58 | 54 | 4 |

The screen of these 112 valid tasks has started (two reads each). The table per repo and tier follows.

**3. The runner warms codemem before the agent starts** (#59). In a setup with codemem the runner starts `codemem mcp` before the agent's clock, waits until `index_status` says ready and a warm-up search has no note, and Claude Code then connects to that server through a relay. `run.json` records the seconds of the warm-up and every `search_code` result with a fallback note; a run whose first search was keywords only is discarded and done again. One real run with `09c4ef0` (Haiku, pandas 68090, L2 of `vague-b7-v3.jsonl`): warm-up 29 s, one search in turn 1 with no note, completed. Your wording "the model loaded before the agent starts" (21:50) is now what our runs do. codemem is not changed; two small proposals for it are in the pull request text (a start-up wait of its own, and one log line when the model is in memory).

## Checked

- Point 1: run on the PC at 02:05 UTC.
- Not checked: the whole suite on `andre/compact-linux`; `andre/search-recall` on Linux (say if you want it).

## Left

- **Runs 3 and 4 of the entry of 11:32 UTC are not done.** They were to start when the validations ended; our session was down then.
- ruff 60; the admission checks of vscode, home-assistant, trino; the hard-tier candidates.

## Blocked on, or needed from others

- **The PC's system drive is almost full: 30 GB free on C:.** At 21:18 UTC it had 159 GB free; at 22:10 UTC 23 GB. Our disk guard stopped the queue at once (both validations had just ended; nothing of ours was lost). Docker's virtual disk is 306 GB and did not grow in that hour (its use fell), so about 130 GB went to something outside our jobs. **No image is built and run 3 is not started until Andrew has looked:** run 3 needs 12 GB of scratch space. What does not write to the disk goes on: the screen, the prompts, the pipeline.
- **Andrew:** the disk; the three decisions on the entry of 13:52 UTC.

## Next

- Track A: the screen table of duckdb and kubernetes; then, when the disk allows, runs 3 and 4, ruff 60 and the other repos.
