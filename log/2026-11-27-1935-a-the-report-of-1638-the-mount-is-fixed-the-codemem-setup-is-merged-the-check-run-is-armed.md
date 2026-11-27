# Track A, for Andre: the report of 16:38 UTC. The mount is fixed, the `codemem` setup is merged, and the check run is armed for 01:00 UTC

- **Track:** A, for the lead. The report that the entry of 16:38 UTC asks for; it also answers 15:13, 17:16 and 17:53 UTC
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-27 19:35 UTC
- **Work package:** A12 (the runs), A6 (the setups), A4 (the integrity checks), A9 (tasks)
- **Branch, commits, pull request:** `main` at `8a17f0e`. Merged today after 18:20 UTC: #76 (prompts of playwright 43342), #77 `c368cb7` (your block code and the mount fix), #78 (the sampler: one task per issue), #79 (the vscode recipe)

## Done

**The four points.**

| # | Point | State |
|---|---|---|
| 1 | The mount of the codemem checkout | **Fixed and proven in a container** (part 1) |
| 2 | The block and the `codemem` setup | **Merged** (#77). Your code, reviewed and tried with a real run (part 2) |
| 3 | Fair tasks, prompts, indexes | **Ready for five repos: 54 run tasks, 162 blocks** (part 3) |
| 4 | Can the check run start at 01:00 UTC | **Yes. It is armed** (part 4) |

**1. The mount (15:13 UTC, point 1).**

- **The fix.** A container of `tool` or `codemem` now gets `<checkout>/.venv`, `<checkout>/src` and the Python install, each read-only at its own path. Not the checkout. The layout is checked before any run (`e2e_index.codemem_mount_paths`), and there is no fallback to the whole checkout.
- **The proof, in every run that mounts codemem.** In the same container, as the agent's user, before codemem and Claude Code start and outside the clock: the checkout holds only `.venv` and `src`, and `grep -rIlF` over every mounted path finds none of the longest added lines of the task's real fix and hidden tests (up to 3 of each, 40 characters or more; lines that the prompt holds are left out). The phrases reach grep on standard input from a file that only root can read, and the file is deleted before the agent starts. A run that fails does not start. The result is `integrity.codemem_mount_proof` in `run.json`.
- **We used the fix lines, not the issue text,** as the phrases: `prompt.txt` holds the issue by design.
- **In a real container** (run `try-codemem-1`, pandas 68278, L2, Haiku, codemem `463171c`): `ok: true`, `checkout_eval: absent`, `checkout_entries: [.venv, src]`, grep exit 1, no hit, 7 mounted paths searched, 11.7 s.
- **The other mounts, audited.** `grep` and `upfront`: only the Claude Code binary and `/out`. `/out` is the run's own folder (the prompt, the scripts, the index copy), never other runs or `~/.cmeval`. `/cmindex` is the index of the base commit; the blocks sit beside it and are not mounted. `/hf` on our PC holds only the jina model. `/testbed` is a fresh `git init` of the base source with no history.
- **Two things left open, neither shows an answer:** the agent can write to `/out` (it could change its own records), and other ports of the host's gateway address were not checked.
- **The look back** is in our entry of 18:27 UTC: 171 runs, none touched the checkout or a task file.

**2. The `codemem` setup (17:53 UTC).**

- **An independent review of your branch** found no leak (the block text holds only `path:line  name`; the gold ranks go to the record), and `grep` and `tool` unchanged. It found two gaps, both fixed in #77:
  - a block made with another codemem commit or on another index was accepted, and a rebuild of an index left its blocks. Now such a block is refused, and a rebuild deletes them;
  - `--force` wrote the new block before the check, so it could replace a good block with a bad one. Now it writes a temporary file first.
- **Your three checks on the first real run:**
  1. `opens_with_text`: true on every main request of the `codemem` run (9 of 11 proxy lines; the other two are a count request and one side request). `block_in_first_message: true`, no flag. In 8 earlier container runs on the PC (Claude Code 2.1.332) the prompt is the third text block of the first user message, as on your Mac.
  2. A real search on a real index: the timings hold `embed_query:jinaai/jina-code-embeddings-0.5b`, at L0 (the whole issue as the query) and at L2. Not compared with `search_code` in a container for the same query; it comes with the check run.
  3. The seconds of a block on the PC: 6.7 to 10.6.
- **The first pair.** Both setups finished and passed the tests; the proxy's token count equals the agent's in both. `codemem`: 9 turns, 423,174 tokens, 283.5 s; the block had a gold file at rank 2 and the gold function at rank 3; the agent also called `search_code` once. `grep`: 9 turns, 381,366 tokens, 254.0 s. One pair with builds running beside it: not a result.
- **Also in #77:** your point 5 (the setup that goes first moves from task to task), `time.host_load_start` and `host_load_end` (the host's load averages around each container), and `identity.seat` (the name of the login token's file).
- **Left open, on purpose:** a run whose first message lacks the block is flagged, not discarded. And "used" and "1st call" are constant in `codemem` runs; the agent's own calls are in `steps.mcp_tools` until the score has a column.

**3. The tasks** (fair by the screen, L1 and L2, index and three blocks made with `463171c`). Sample: `eval/tasks/run-sample-v1.jsonl`, seed `runs-v1`.

| Repo | Fair: easy / medium / hard tier | Run |
|---|---|---|
| pandas | 14 / 3 / 0 | 6 + 3 + 0 = 9 |
| ruff | 10 / 3 / 0 | 6 + 3 + 0 = 9 |
| duckdb | 30 / 11 / 4 | 6 + 4 + 4 = 14 |
| playwright | 20 / 8 / 1 | 6 + 7 + 1 = 14 |
| kubernetes | 18 / 2 / 0 | 6 + 2 + 0 = 8 |

- **One task per issue** (Andrew's decision, #78). playwright 43342 and 43482 are two fixes of one issue with one hidden test. The sampler keeps the lowest pull request number of an issue in a repo; 43482 is not run, and one more medium task takes the place.
- **pandas runs the 9 it has** (`runs.md` §3). Its hard tier has 0 fair of 15 valid.
- **162 of 162 blocks are ready** (54 tasks, three levels; each has 20 results and was made with the embedding model).

**4. The check run.**

- **Armed** on the PC for 2026-11-28 01:00 UTC: pandas 68278, 68945, 68090 and playwright 42204, 43316, 42260, at L0 and L2, in `grep` and `codemem`, Haiku first and then Sonnet. 48 runs. Eval `e69513a` or later, codemem `463171c`.
- **At 00:30 UTC we read the lock hash here.** If it is not `463171c`, the indexes and the blocks of the six tasks are made again before the start (minutes). The other 48 tasks follow before their batches.
- **The PC is quiet during the check run:** the builds stop at 00:40 UTC.
- **Seats.** Two login tokens are on the PC now, a third and a fourth are asked for. A batch that stops at a usage limit starts again with the next token; finished runs are skipped and the discarded one is done again. **The runs go one at a time until the check run shows what one account can carry.** At 5 to 7 minutes a run, the 48 runs take 4 to 6 hours, so the report of the check run comes at about 06:00 UTC, not at 03:00.
- **After it, without waiting for Andrew** (his decision), if the five points of `runs.md` §6 hold: Haiku's repetition 1 on pandas, ruff, duckdb, playwright, then kubernetes.

**5. The other repos (17:00 UTC).**

- **home-assistant: admitted** (6 of 10 valid, builds of about 200 s). 60 candidates and the hard-tier file are in validation now.
- **vscode: 5 of the first 7 builds failed in `npm ci`.** Two causes, both fixed in the recipe (#79): GCC 12 of Debian bookworm cannot compile `native-keymap` against the headers of Electron 43 (about 40% of the candidates), and the parallel header downloads of node-gyp race on an empty cache. One trial build of an Electron 43 task passes. The admission runs again. An image is about 12 GB and a build about 13 minutes.
- **trino:** its admission started at 19:28 UTC.
- **Builds beside the batches** (Andrew's decision): after the check run they go on, 2 at a time, and every run records the host's load. Our estimate from the entry of 18:27 UTC stands: home-assistant and vscode late on Nov 28 UTC, trino on Nov 29.
- **A disk stop at 19:04 UTC:** the vscode and home-assistant images grew the PC's disk file to its guard limit, and the guard stopped every job. Compacted, restarted at 19:11 UTC. Nothing was lost.

## Checked

- #77: 954 tests; the two real runs above, read from `run.json`, `proxy.jsonl`, `mount-proof.txt` and `prompt.txt`.
- The blocks: a script read all 162 files (20 results, `embedded: true`).
- Both login tokens: one small request each.
- Not checked: a Sonnet run with a block; `index_status` in a container with `463171c` (point 4 of §6); a batch that changes its seat at a real usage limit.

## Left

- The check run and its report: the five points of §6, the audit of 14:50 UTC, and your points 2 to 13 of 15:13 UTC from its records.
- The replay with the compact index (14:45 UTC); the thread work's parts 2 and 3.

## Blocked on, or needed from others

- **Andre:** the lock hash at 00:30 UTC in this log. And, if you agree, a login token of your account for the rotation (Andrew sends the instructions).
- **Wilson:** the same token request.

## Next

Track A: the check run at 01:00 UTC, then its report.
