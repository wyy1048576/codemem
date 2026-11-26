# For track A: the commit of codemem to run is `8d86da8` on `main`. There will be no tag

- **Track:** shared: from track C, for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 14:24 UTC
- **Work package:** none: track C handed to the runs
- **Branch, commits, pull request:** `main` at `8d86da8` (8d86da8a6b97cff78e342eb4f3fa60e0c5c89917), with #51 (defaults), #52 (the runner's pin of the search index) and #53 (the audits' fixes)

## Done

**All of track C is on `main`.** The last pull request, #53, is merged. The commit to build the
indexes with and to run is:

```bash
git fetch origin && git checkout 8d86da8a6b97cff78e342eb4f3fa60e0c5c89917
uv sync
```

**There will be no tag `codemem-final`** (Andre): the commit hash is the name. Where our note
of today for track A's agents ("how to run track C's codemem in the runs") says `git checkout
codemem-final`, use the line above. Every `index.json` and every `run.json` must name this
commit. If track B's work adds something before Friday noon Pacific, we post the new hash here,
and the indexes are built once more with it.

## Checked

- `main` at `8d86da8` has exactly the files that were tested before the merge. On an M1 with
  FAISS 1.16.0: 730 tests pass; 727 pass and 3 are skipped with the suite forced onto the compact
  index, and the same on the exact one. The eval's suite: 812 pass, 20 skipped.
- Not checked: Linux, x86, a real container. Your first build and run with this commit are that
  check: `scripts/check_run_start.py` shows a run's start in one command (point 6 of the note).

## Left

- Nothing in track C blocks the runs.

## Blocked on, or needed from others

- **Andrew:** a word here that the entries of today have been read, and whether `uv sync` worked.

## Next

- Track C's session: the audit of pull request #45 with Andre, then the open-model harness.
