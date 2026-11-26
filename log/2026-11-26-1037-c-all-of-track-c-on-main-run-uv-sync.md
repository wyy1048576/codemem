# Track C: all of it is on `main`, with FAISS 1.16.0 in the lock file. Run `uv sync`; an Apple-silicon Mac needs macOS 15

- **Track:** C. Point 2 is for everyone
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 10:37 UTC
- **Work package:** C2, C3 (closing)
- **Branch, commits, pull request:** on `main`: #36 (`07a77ee`), #38 (`cffcfa7`). New branch: `archive/codemem-before-track-c` (`1a7e4d1`). Left: `andre/track-c-results` (the results doc, no pull request yet)

## Done

**1. #36 and #38 are on `main`.** Andre merged them. Each is, byte for byte, the tested content:
`main` after #36 has the tree of the combined branch that was tested, and #38 adds the lock-file
change of the tested branch and nothing else. So `main` now holds all seven parts of track C
(#30 to #36) and pins FAISS 1.16.0.

**2. What everyone has to do: `uv sync`.**

| | |
|---|---|
| after pulling `main` | `uv sync`, which installs FAISS 1.16.0 |
| **an Apple-silicon Mac** | **needs macOS 15 or newer.** FAISS 1.16.0 has no build for macOS 14 on ARM, and `uv sync` then fails. If that is your machine, say so here at once: the way back is to revert #38, one file |
| Linux, Windows, Intel Macs | builds exist as before. Nobody has run `main` on Linux or Windows with 1.16.0 yet: `uv sync && uv run pytest -q`, and post the last line here |

**3. What changed on `main` with #36:**

- `vector_backend = "auto"` is the default. It uses the exact index while the exact indexes of
  all vector types fit 2% of the machine's memory, and the compact one beyond. On the eval's PC
  every repo stays on the exact index, so results do not change.
- `faiss-cpu>=1.15.1` is the requirement in `pyproject.toml`.
- `scripts/check_search_indexes.py` and `scripts/check_faiss_calls.py` are in the repo.
- A search that answers from keywords while something loads now names the search index as well
  as the model in its note (`prompts.models_loading_notice`).

**4. An archive of codemem before track C:** the branch `archive/codemem-before-track-c`, at
`1a7e4d1`, the last commit before #30. Its package code is that of `041124e`, which track A's
runs so far used. It is there to benchmark against; nothing merges from it.

## Checked

- The trees: `git rev-parse 07a77ee^{tree}` equals the tested combined tree, and `cffcfa7`'s tree
  equals that tree with the tested lock-file change merged in.
- The combined code under FAISS 1.16.0, on an M1 with macOS 26, in an environment made from the
  new lock file: 622 tests pass; 619 pass and 3 are skipped forced onto the compact index, and
  the same forced onto the exact one; every FAISS call under the memory checker.
- Not checked: Linux, x86, Windows.

## Left

- The results doc (`andre/track-c-results`): its state lines are being updated, then Andre
  merges it.
- The fixes the audits asked for, on a follow-up branch.

## Blocked on, or needed from others

- **Andrew and Wilson:** point 2. First of all, whether `uv sync` works on your machines.
- **Andrew:** the run on the PC is now a run of `main` itself.

## Next

- Track C's session: the results doc.
