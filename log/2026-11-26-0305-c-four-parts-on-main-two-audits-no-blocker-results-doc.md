# Track C: four parts are on `main`, two audits found no blocker, and a results doc is on a branch

- **Track:** C. Point 5 is for track B
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 03:05 UTC
- **Work package:** C2, C4, C5, C8, C9; experiment C-E8
- **Branch, commits, pull request:** on `main`: #30, #31, #32, #33 (`b69ab80`). Open: #34 `andre/vector-cache-cap` (`5445e5d`, refreshed on `main`), #35 `andre/compact-store`, #36 `andre/compact-default`. New: `andre/track-c-results` (`99463ae`), no pull request

## Done

**1. Four parts are on `main`:** the embedding server (#30), model memory (#31), branches and
worktrees (#32), the embedding assist (#33). Each squash on `main` is, byte for byte, the branch
that was tested. #34 is refreshed on `main` and its suite passes (488). #35 and #36 follow in
that order, each refreshed after the one before lands.

**2. An audit of `main` at `b69ab80`** by a separate agent told to break it, on a real clone of
flask with real git operations:

| Area | Result |
|---|---|
| branch switches (`codemem index`, `codemem watch`, the MCP server) | after each of 21 switches the index equals a fresh build, vector by vector; a return to a commit seen before gives the model 0 texts |
| worktrees | a new worktree's index is a copy and ends equal to a fresh build, also with two starts at once; the clean-up deleted exactly the right folders in 18 starts with 12 traps |
| a search right after a large switch | embeds its own keyword results first; none took longer than 4.0 s |
| the embedding server, the assist, the idle unload | work; a build through the server equals the in-process build byte for byte |

**3. An audit of #34 (the cache): nothing blocks it.** The cap cannot lose or change a vector an
index needs: 31 builds under very small caps all equal a fresh build. A cache file that cannot be
used never stopped a build; on `main` a cache file that is not a database stops `codemem index`.

**4. An audit of #35 and #36 (the search index): nothing blocks them.** With its own brute-force
oracle on the real pandas index (49,770 vectors): the compact index returned exact scores and the
same top 10 in 1,640 of 1,640 searches, and the same top 50 in 1,639. The one miss is a question
about another repo, at rank 45: its vector lay at place 2,021 of the 1-bit scan, which keeps
2,000. Memory held: 46.5 MB against 110 MB for the exact index.

**5. Findings, for track B where they touch what an agent sees:**

| Finding | Where |
|---|---|
| in a new worktree far from its source, `search_code` and `get_chunk` answer from the other checkout's code for about a second, with only the "still being built" note | #32, on `main` |
| `codemem search` on the command line after `git switch` answers from the old branch and says nothing. The MCP server follows the switch | on `main` before track C |
| with the embedding server down, commands end in a long traceback, and the MCP error is only "Error executing tool search_code" | #30, on `main` |
| a worktree inside the main checkout (`.claude/worktrees/`) doubles the main index: 83 files became 166 | a known gap, measured |
| the exact index's saved file has no checksum: a flipped bit loads unchanged | on `main` before track C |
| after a power cut a saved index can be newer than the database and is trusted | #35 narrows it, does not close it |
| a cache locked by another process stalls an MCP search for 64 s | on `main` before track C |

None gives a wrong result in normal use. Track C fixes its own on a follow-up branch after #36.

**6. C-E8, how big a real branch switch is** (open pull requests against the default branch's
tip, code texts only):

| Repo | Pull requests | A pull request's own change, median | A first switch: median / 90th percentile |
|---|---|---|---|
| pandas | 50 | 10 texts | 83 / 1,449 |
| playwright | 12 | 45 texts | 146 / 905 |
| vLLM | 50 | 15 texts | 1,809 / 37,712 |

**7. A results doc:** `docs/analysis/track-c-results.md` on `andre/track-c-results`: what was
built, the numbers, what is our own work and what is reused, what the audits found, what is not
checked.

**8. A survey of ready-made agent loops for small open models** is done, for the open-model
evaluation. It confirms mini-SWE-agent as the loop to start with. Its findings for track A:
Llama has no competitive model at 30B or below, and LiteLLM (a dependency of mini-SWE-agent) was
compromised on PyPI a second time on Oct 21 (version 1.107.0), so pin it.

## Checked

- The audits' own runs: the whole suite of the combined code three ways (619; 616 and 3 skipped;
  616 and 3 skipped), #35 alone (588), `main` (456, and one test that needs `codemem` on PATH),
  #34 (487, and one timing test that passed 5 of 5 alone).
- Not checked: Linux, x86, CUDA; a real index above 50,000 vectors; a real model in the audits.

## Left

- #34, #35, #36 (Andre merges). The follow-up branch with the fixes of point 5.
- The real vLLM index (91,355 of about 145,000 vectors): its build runs again, alone.

## Blocked on, or needed from others

- **Andrew:** the check on the PC (entry of 2026-11-25 23:43) is still wanted before #36.

## Next

- Track C's session: the vLLM check, then the fixes.
