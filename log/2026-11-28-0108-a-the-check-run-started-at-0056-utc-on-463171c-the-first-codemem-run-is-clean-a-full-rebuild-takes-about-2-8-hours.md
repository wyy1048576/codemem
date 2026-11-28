# Track A: the check run started at 00:56 UTC on `463171c`. The first `codemem` run is clean. A full rebuild of indexes and blocks takes about 2.8 hours

- **Track:** A. Answers the final lock entry of 00:55 UTC and point 5 of the entry of 00:40 UTC
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 01:08 UTC
- **Work package:** A12 (the runs)
- **Branch, commits, pull request:** eval `main` at `722ded5`, codemem `463171c`. No new commit

## Done

**1. The check run runs.**

- Started 00:56:25 UTC, 90 seconds after the final lock entry. Both checkouts were clean: eval `722ded5`, codemem `463171c`.
- 48 runs, one at a time: Haiku L0 pandas, L0 playwright, L2 pandas, L2 playwright, then Sonnet the same. No image build runs beside it.
- **Its runs carry the run ids of the plan** (`haiku-pandas-L0` and so on), as `runs.md` §6 says they are the first runs of the plan. Repetition 1 uses the same ids, so it skips them.

**2. The first two runs (pandas 68090, L0, Haiku).**

| Setup | End | Completed | Turns | Tokens | Seconds |
|---|---|---|---|---|---|
| `grep` | finished | yes | 11 | 519,304 | 223 |
| `codemem` | finished | yes | 13 | 713,843 | 217 |

- The `codemem` run: no flag, not discarded. The mount proof is ok (the checkout holds only `.venv` and `src`; none of the 6 phrases of the fix and the hidden tests is found). The block of L0 is in its record. The proxy's token count is the source of the tokens.
- One pair says nothing about the setups. The numbers are here only to show that the chain works.

**3. Point 5: how long a full rebuild takes on the PC.** About **2.8 hours**, one index at a time on the RTX 3060 Ti, from our logs with `463171c`:

| Repo | Mean seconds per index | Run tasks |
|---|---|---|
| pandas | 63 | 9 |
| playwright | 52 | 14 |
| ruff | 84 | 9 |
| duckdb | 140 | 14 |
| kubernetes | 194 | 8 |
| home-assistant | 347 | 8 |

- The 62 indexes: about 2.3 hours. The 186 blocks: 9.7 s each, about 30 minutes.
- The means hold the first build of each repo, which is cold and much slower (up to 1,770 s for home-assistant).

**4. home-assistant since our entry of 22:21 UTC.**

- A second screen wave on the 15 candidates that the recipe fix rescued: 4 more fair. **11 fair of 48 valid** (#83).
- Prompts for the 4 (#84). The run sample now holds **8 home-assistant run tasks: 6 easy, 2 medium, 0 hard**, all with index and blocks on `463171c`. By the seeded order 184675 and 183382 came into the six easy run tasks, and 182220 and 182592 became spares.
- For your memory probe of 22:43 UTC: it has no sessions for 183382, 184675 and 184035.

## Checked

- The record of the first `codemem` run was read field by field: `flags` empty, `codemem_mount_proof.ok` true, `checkout_eval` absent, `grep_exit` 1, `identity.seat` set, `identity.block` set.
- Not yet checked: the five pass points over all runs. They come with the report.

## Left

- The report of the check run: about 05:00 UTC. A first look after the Haiku half, about 02:45 UTC, with minutes and tokens per run and the load on a seat.
- No token comes from Andre or Wilson (your entry of 00:00 UTC): understood. The runs use Andrew's two accounts only. No token of yours was ever stored on the PC.
- The compact-index batch is withdrawn for us (00:55 UTC): understood. We answer track B's questions on the pipeline here.
- The disk of the PC allows no image build beside the runs tonight: the images of the run tasks need the room. So more home-assistant candidates, vscode and trino build in the gaps between batches. vscode and trino will not be in Haiku's first repetition tonight.

## Blocked on, or needed from others

Nothing.

## Next

The first look after the Haiku half. Then the report.
