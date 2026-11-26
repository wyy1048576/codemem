# Track A, for Andre: run 1 ends (the FAISS call check passes), and run 2, the size of each index on the PC

- **Track:** A, for track C. Answers the entry of 11:32 UTC, runs 1 and 2
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-26 19:40 UTC
- **Work package:** C6 and C2 on track C's side
- **Branch, commits, pull request:** none. codemem `main` at `09c4ef0`, in a worktree of its own on the PC

## Done

**Run 1, third part: `uv run python scripts/check_faiss_calls.py` passes.**

```
FAISS 1.16.0 on 16 thread(s), x86_64 Linux-6.18.58.1-microsoft-standard-WSL2-x86_64-with-glibc2.39, Python 3.11.18
FAISS 1.16.0: all 2608 combinations ran, code lengths 1 to 4097, bits 1 to 8
exit status 0
```

The two pytest runs are in our entry of 19:25 UTC: 5 failed in `tests/test_compact_store.py`, the same five with the compact index forced.

**Run 2: the indexes the PC has.** 20 task indexes (10 pandas, 10 playwright; built with codemem `041124e`) and one small index of the codemem repo. No other repo has an index yet. The PC has no `sqlite3` program, so the counts are read with Python's `sqlite3` module, read only, with your two queries.

| Index | Chunks | Vectors, `code` | Vectors, `usage` | `index.db` |
|---|---|---|---|---|
| pandas, smallest (66225) | 36,693 | 38,046 | 6,000 | 202 MB |
| pandas, largest (70742) | 40,412 | 41,932 | 6,419 | 224 MB |
| playwright, smallest (42164) | 17,368 | 20,175 | 7,456 | 124 MB |
| playwright, largest (43000) | 17,803 | 20,731 | 7,692 | 127 MB |
| the codemem repo itself | 2,087 | 2,123 | 948 | 11 MB |

Every line: `~/.cmeval/logs/andre-run2.txt` on the PC. The largest index the PC has is pandas, with about 48,000 vectors in all. So nothing on this machine is near the size where the compact index would matter; run 3 gives that size.

## Checked

- The commands ran on the PC at `09c4ef0` after a clean `uv sync`. Two task validations were building images beside them.

## Left

- Run 3 (cost against size) and run 4 (the same results on real indexes, for pandas and playwright): they are timings, so they wait until the two validations end (about one more hour). Then both run with nothing beside them.

## Blocked on, or needed from others

- Nothing.

## Next

- Track A: runs 3 and 4, posted with their tables and JSON files.
