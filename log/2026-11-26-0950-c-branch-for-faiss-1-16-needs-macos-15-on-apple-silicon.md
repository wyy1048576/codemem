# Track C: a branch that moves the lock file to FAISS 1.16.0; it needs macOS 15 on an Apple-silicon Mac, and one run on Linux and on Windows

- **Track:** C. The two requests are for tracks A and B
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 09:50 UTC
- **Work package:** C2 (the search index's cost). Andre's decision of today, after the entry of 09:16
- **Branch, commits, pull request:** `andre/faiss-1-16` (`d001d9f`), one commit on `main` at `bdd58d5`. Andre opens the pull request

## Done

- **The change:** `uv.lock` moves `faiss-cpu` from 1.15.1 to 1.16.0. One file, 15 lines.
  `pyproject.toml` is not touched. It does not depend on #34, #35 or #36.
- **Why:** FAISS 1.15.1 has no vectorized code for ARM processors in several kernels, and 1.16.0
  adds it (entry of 09:16). On an M1, one search over 109,562 real vectors takes 8.1 ms with the
  exact index that `main` uses, against 11.4 ms. Results are the same.
- **The builds FAISS 1.16.0 has**, read from the new lock file:

| Platform | Builds |
|---|---|
| Mac, Apple silicon | macOS 15 or newer. **The 1.15.1 build was for macOS 14** |
| Mac, Intel | macOS 15, as with 1.15.1 |
| Linux | x86_64 and aarch64, glibc 2.27 or newer, and musl, as with 1.15.1 |
| Windows | x64 and ARM, Python 3.11 to 3.14, as with 1.15.1 |

## Checked

All on an M1 with macOS 26, in an environment made from the new lock file (`uv sync --frozen`:
Python 3.11.2, FAISS 1.16.0, numpy 2.4.6, torch 2.14.1):

- `main`'s suite: 457 tests pass.
- The combined track C code (`andre/track-c-all`): 622 pass; 619 pass and 3 are skipped with the
  suite forced onto the compact index, and the same forced onto the exact one.
- `scripts/check_faiss_calls.py` under Guard Malloc: all 2,608 combinations ran, exit status 0.
  Its `--dangling` case ends with status 11 under Guard Malloc, so the checker sees a misuse.
- The compact index against the oracle on the real vLLM index: the same counts as with 1.15.1.
- **Not checked: Linux and Windows at run time.** The repo has no CI, and there is no such
  machine here.

## Left

- The pull request (Andre). After it merges, everyone runs `uv sync`.

## Blocked on, or needed from others

- **Andrew and Wilson: is one of your machines an Apple-silicon Mac on macOS 14?** On it,
  `uv sync` would find no build of FAISS 1.16.0. Say so here before the pull request merges.
- **Andrew, on the PC, and anyone with a Windows machine:** one run, in a worktree of its own:

  ```bash
  git fetch origin && git worktree add ../codemem-faiss origin/andre/faiss-1-16 && cd ../codemem-faiss
  uv sync && uv run pytest -q
  ```

  Send back the last line of pytest, and the last 40 lines if a test fails.

## Next

- Andre: the pull request, once the two answers are in.
