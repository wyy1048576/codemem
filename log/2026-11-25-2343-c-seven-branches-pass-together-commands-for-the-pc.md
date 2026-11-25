# Track C: seven branches pass together; one branch and two commands to check them on the PC

- **Track:** C. The commands are for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-25 23:43 UTC
- **Work package:** C2, C4, parts of C1, C5, C8 and C9
- **Branch, commits, pull request:** all pushed, no pull request yet. Andre opens them

| Branch | Tip | Merges | What it is |
|---|---|---|---|
| `andre/embedding-endpoints` | `8bed3ed` | first | `codemem serve-embeddings`, the `[embedding] space` setting |
| `andre/model-idle-unload` | `62ab80c` | on the first | less model memory, the idle unload, the right precision on a CPU |
| `andre/worktree-start` | `6eda3a6` | on the second | a new worktree starts from a copy; branch-switch tests |
| `andre/embedding-assist` | `58e6956` | on the third | an optional second source for a build's embeddings |
| `andre/vector-cache-cap` | `1920202` | any time | the vector cache in a smaller layout, with a size cap |
| `andre/compact-store` | `ea93781` | any time | the compact search index, as a setting |
| `andre/compact-default` | `9b275fc` | on `compact-store`, last | the search index picked by the machine's memory |
| `andre/track-c-all` | `9713c8b` | never: for testing | all seven merged |

## Done

**1. All seven branches work together.** `andre/track-c-all` merges them on `main` at `041124e`.
Its suite: 619 tests pass with the default setting, and 616 pass with 3 skipped when the whole
suite is forced onto the compact index, and the same on the exact one.

**2. The default search index follows the machine's memory** (`andre/compact-default`). The
setting is `vector_backend = "auto"`:
- the exact index, as today, while the exact indexes of all vector types fit a budget together;
- the compact index when they do not.

The budget is 2% of the memory the machine reports, and at least 128 MB. `vector_memory_mb`
sets another. An exact index takes 1,856 bytes per vector of 896 numbers.

| Memory the machine reports | Budget | Exact up to |
|---|---|---|
| 16 GiB | 344 MB | 185,127 vectors |
| 24 GiB | 515 MB | 277,691 vectors |
| 48 GiB | 1,031 MB | 555,383 vectors |

The earlier entry of 22:18 gave rounder figures (320 MB, 170,000); these are the exact ones.
An index that was built before the change keeps its settings and its index key, and nothing is
embedded again.

**3. Wilson's #26 and `andre/embedding-endpoints` met in `cli.py`.** #26 made the command line
import nothing heavy, so that `codemem hook` starts fast. The branch had brought numpy back to
the top (318 ms to start, against 115 ms). It is fixed, at 117 ms, and a test keeps it so.

**4. One fact about every time measured so far.** On macOS codemem sets `OMP_NUM_THREADS` to 1
when it is unset, because the faiss and torch wheels each bring their own OpenMP. So every FAISS
time in track C's entries was taken with FAISS on one thread. On Linux codemem does not touch
the variable, and FAISS uses every core. No time was taken that way. **Do not set
`OMP_NUM_THREADS=2` on a Mac:** with it, `tests/test_platform.py` hangs until its 300 s limit.

## Checked

- The three runs of point 1 are mine, on `andre/track-c-all` at `9713c8b`, on an M1.
- The real pandas index (49,770 vectors, 352 issue texts): the default rule and the compact
  index at 4 bits gave the same top 10, top 50 and merged results as the exact index in every
  search (the agent's run with the repo's own script; equal to my run of 18:23).
- **Not checked: Linux, x86, FAISS on more than one thread through codemem, a real index above
  50,000 vectors.** That is what the commands below are for.

## Left

- The pull requests (Andre). The check on the PC (below). The vLLM check here is stopped at
  77,900 of about 145,000 vectors and can go on later.

## Blocked on, or needed from others

- **Andrew (track A), when the PC has a free quarter of an hour.** In a clone or worktree of
  its own, so that the running batches are not touched:

  ```bash
  git fetch origin && git worktree add ../codemem-c origin/andre/track-c-all && cd ../codemem-c
  uv sync && uv run pytest -q; CODEMEM_TEST_VECTOR_BACKEND=compact uv run pytest -q; CODEMEM_TEST_VECTOR_BACKEND=faiss uv run pytest -q; uv run python scripts/check_faiss_calls.py
  ```

  Then once per repo, on an index the PC already has:

  ```bash
  uv run python scripts/check_search_indexes.py --index <a task's index folder> --repo pandas-dev/pandas
  uv run python scripts/check_search_indexes.py --index <a task's index folder> --repo microsoft/playwright
  ```

  - The second script never changes the index: it copies `index.db` to a folder of its own
    (232 MB for pandas) and deletes the copy. It embeds the repo's issue texts with the index's
    own model, so it needs the GPU for a few minutes. It ends with PASS or FAIL.
  - Do not set `OMP_NUM_THREADS`.
  - What to send back if something fails: the last 40 lines of pytest; for
    `check_faiss_calls.py` its first line, its last line and the exit status; for the second
    script the table it prints and its JSON file.
  - A larger repo is worth more than a second small one: if an index of vscode or
    home-assistant exists, run the second script on it too.
- **Wilson (track B):** nothing new. `andre/compact-default` changes one text of yours: the note
  for a search that answers from keywords now names the search index as well as the model
  (`prompts.models_loading_notice`). Say if you want other words.

## Next

- Andre's session: the pull request texts for the two new branches; the vLLM check when the
  machine is free.
