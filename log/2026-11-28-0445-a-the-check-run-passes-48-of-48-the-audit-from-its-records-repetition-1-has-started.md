# Track A: the check run passes (48 runs, none discarded). The audit from its records. Repetition 1 has started

- **Track:** A, for the lead. The check run report of `runs.md` section 6, the audit of 14:50 UTC and points 2 to 13 of 15:13 UTC (both Nov 27)
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 04:45 UTC
- **Work package:** A12 (the runs), A4 (the integrity checks), A9 (tasks)
- **Branch, commits, pull request:** none. Runner at eval `722ded5` (no change in `eval/src` up to `739fbe3`), codemem `463171c`

## Done

**1. The check run passes on all five points. Haiku's repetition 1 started at 04:16 UTC.** The Sonnet half ended at 04:09 UTC. The 48 runs are the first runs of the plan.

| Pass point | Result |
|---|---|
| 1. A record and a grade for every run, none discarded | 48 of 48; 0 discarded, 0 flagged, all end `finished` |
| 2. The proxy's tokens equal the agent's | 48 of 48 |
| 3. codemem's results reach the agent | The first message begins with the block in 24 of 24 `codemem` runs: one header line, then exactly 20 lines that equal `identity.block.results`. 3 runs call `search_code` (all Haiku, one call each, turn 1); each gets 10 results with path, lines, name and code. Sonnet: 0 calls |
| 4. Every search is a search by meaning | The model is loaded on the GPU in every server log. `still loading` and `cannot embed right now`: 0 of 48 streams. Fallbacks 0. `watching for changes` is in the status text of 24 of 24 `codemem` runs |
| 5. Two `codemem` transcripts read | Read by an agent, not by a person; Andrew can read them from the archive. Haiku, pandas 68090, L2: the block holds no gold file (rank null); the agent searches once, then reproduces the fault and edits a gold file; solved. Sonnet, playwright 42260, L0: the gold file is rank 2 of the block; the agent opens it in turn 1 with no search, makes two edits, runs no test; solved in 4 turns |

One limit of the evidence for point 3: the first message is not in `stream.jsonl`, and bodies were off. The proof is `prompt.txt`, the runner's flag and what the agents do.

**2. The numbers. 3 tasks per repo: not a result.**

| Model | Level | Setup | Runs | Solved | Mean turns | Mean processed tokens | Mean agent s |
|---|---|---|---|---|---|---|---|
| Haiku | L0 | grep | 6 | 5 | 14.5 | 715,384 | 183.7 |
| Haiku | L0 | codemem | 6 | 5 | 15.2 | 772,341 | 200.7 |
| Haiku | L2 | grep | 6 | 6 | 18.8 | 899,789 | 343.8 |
| Haiku | L2 | codemem | 6 | 6 | 17.7 | 898,527 | 214.5 |
| Sonnet | L0 | grep | 6 | 5 | 5.2 | 200,095 | 49.6 |
| Sonnet | L0 | codemem | 6 | 5 | 4.2 | 171,839 | 32.8 |
| Sonnet | L2 | grep | 6 | 5 | 5.2 | 190,896 | 34.5 |
| Sonnet | L2 | codemem | 6 | 5 | 4.5 | 180,615 | 33.5 |

Paired, `codemem` minus `grep`, mean / median:

| Model | Level | Pairs | Turns | Tokens | Seconds | `codemem` used fewer tokens |
|---|---|---|---|---|---|---|
| Haiku | L0 | 6 | +0.7 / 0.0 | +56,957 / +934 | +17.0 / +2.9 | 3 of 6 |
| Haiku | L2 | 6 | -1.2 / -2.5 | -1,262 / -96,882 | -129.3 / -32.1 | 4 of 6 |
| Sonnet | L0 | 6 | -1.0 / -0.5 | -28,256 / -6,582 | -16.8 / -1.6 | 3 of 6 |
| Sonnet | L2 | 6 | -0.7 / 0.0 | -10,280 / +12,327 | -1.0 / +1.4 | 2 of 6 |

- The agent opened a gold file in its first turn in 17 of 24 `codemem` runs and in 3 of 24 `grep` runs.
- **For section 8 of the plan.** Haiku: 5.5 minutes of wall time a run (agent 3.9). Sonnet: 2.0 minutes a run (agent 0.6); Sonnet ran 2 or 3 test commands in 12 runs, Haiku about 60. About 1.4 minutes of every run is preparation and grading. Limits: 0 runs at the turn, time or usage limit. Seat 1's weekly use: 11% before, 12% after Haiku's 24 runs, 13% after Sonnet's 24. No 5-hour header exists. No answer with status 429, no retry, in 567 requests.

**3. The audit of 14:50 UTC, from the 48 records.**

- **A1.** In `run.json`: processed tokens, the four classes, peak context. Not built: tokens read by tool, tokens before the first edit (the turn of the first edit is recorded; the tokens can be worked out from `proxy.jsonl`), cost.
- **A2.** `proxy.jsonl` keeps the whole `usage` object on 511 of 511 requests. Every cache write is `ephemeral_1h` (757,865 tokens; 5-minute 0). Side calls to another model: 0. `run.json` keeps only the four classes; the split by model stays in `proxy.jsonl`.
- **A3.** Cache reads are 94 to 97% of processed tokens. Your point holds: the classes must be reported beside the sum.

| Model | Setup | Input | Cache write | Cache read | Output | Processed |
|---|---|---|---|---|---|---|
| Haiku | grep | 400 | 256,035 | 9,348,084 | 86,522 | 9,691,041 |
| Haiku | codemem | 394 | 280,345 | 9,647,050 | 97,419 | 10,025,208 |
| Sonnet | grep | 124 | 103,648 | 2,227,093 | 15,080 | 2,345,945 |
| Sonnet | codemem | 104 | 117,837 | 1,980,954 | 15,831 | 2,114,726 |

- **A4. Cache luck is the place in the batch.** In each model and setup, 11 of 12 first requests read the standing prompt from the cache and 1 wrote it: always the first run of that model and setup (pandas 68090 at L0). The one-hour cache lasted over the whole batch, also over the pause. The standing prompt of `codemem` is 1,571 tokens larger.
- **A5. No price table exists in the eval code.** Claude Code's own figure sums to 0.39 USD (Haiku, 24 runs) and 1.62 USD (Sonnet). A fit of its per-run cost to the token classes is exact, and gives its rates per million tokens: Haiku 0.20 cache write, 0.01 cache read, 0.50 output; Sonnet 4.00, 0.10, 10.00. Haiku's look ten times too low. So `total_cost_usd` is not usable, as you said. **Needed: your price table, per model and class.** The score column is a small change to the eval; it reads finished records, so it can come after the runs start.
- **A6.** One value each over 48 runs: Claude Code 2.1.332, the same binary path, eval `722ded5`, codemem `463171c`, model ids `claude-haiku-5-5` and `claude-sonnet-5-5` (request and answer agree). The binary's hash is not recorded, only path and version.
- **A7. Outside the clock, seconds, mean:**

| Model | Setup | Preparation | of it: owner change of the tree | Wait for codemem | Mount proof | Grading | Block search (ahead of the run) |
|---|---|---|---|---|---|---|---|
| Haiku | grep | 49.6 | 48.7 | - | - | 26.5 | - |
| Haiku | codemem | 76.5 | 63.4 | 10.3 | 2.1 | 26.2 | 8.2 |
| Sonnet | grep | 45.9 | 45.2 | - | - | 25.6 | - |
| Sonnet | codemem | 56.4 | 45.0 | 9.5 | 1.3 | 25.6 | 8.2 |

- **A8.** Every record has the load at start and end. 8 of 48 runs started with a 1-minute load above 5 (highest 11.9). Until 02:34 UTC a disk job ran beside the runs; two Sonnet runs had a load of about 7 with no such job, cause unknown.
- **A9.** One seat for all 48, so both runs of a pair are on the same seat. Status 429: 0. Retries: 0.
- **A10.** The API's share of the agent's time: Haiku 18% (`grep`) and 23% (`codemem`); Sonnet 40% and 46%. `duration_api_ms` and the proxy's sum agree within 1%. Before the first edit, mean seconds: Haiku 21.1 and 21.5; Sonnet 13.1 and 11.6.
- **A11.** Discarded: 0 in each setup. One set-aside folder exists (`haiku-pandas-L0`, pandas 68945, `grep`): the run that the pause of 01:06 UTC cut off. It has no record and the score skips it.
- **A12. Not as you state it.** No run ended at a limit here. But the code grades a run that ends at the turn or time limit like any other, so it counts as solved when its patch passes; it is not forced to "not completed". The record keeps how the run ended, so the score can apply your rule later without a new run. Say which you want.
- **A13.** No run lacks tokens, time, turns or a grade. The score drops a missing value from a mean and makes a pair only where both setups have the value.
- **A14. Not as you state it: `codemem` has 7 more tools than `grep`, not 4.** 27 against 20: codemem's 4, and 3 tools for MCP resources that Claude Code adds for any MCP server. The first request is 4,926 bytes larger beside the block, the same in all 24 pairs. Bodies were off, so the split of those bytes cannot be shown; the side batch with bodies would show it.

**4. Points 2 to 13 of 15:13 UTC, in short.** 0 flagged; no run at the time limit, so what Claude Code writes at TERM is still unknown; the setup that goes first changes from task to task (`grep` went first in 16 of 24 pairs with 3 tasks a batch); `codemem` has about 0.1 s more inside the clock; no 429; exit code 0 in all 48, memory is not recorded; no API error at the end of any run; 0 of 480 block results name a removed config file. **One fault in the score:** its codemem columns count the block as a call at turn 0, so "used" is 1.00 in every `codemem` row. The agent's own calls are 3 of 24. I correct the column before any table goes out.

**5. Other things you should know.**

- **pandas 68945** is not solved in 6 of its 8 runs. The grader and the environment are sound (1,121 of 1,121 pass-to-pass in all 8). The fixes are incomplete. One hidden test (all values coerced, with a format that is not ISO) checks a case that the issue does not state. The task passed the screen; Andrew decides if it stays.
- `steps.edits.files_edited` is empty when the agent edits through a Python script (Sonnet does this). The patch is still right.
- **Your question on a full rebuild: about 2.8 hours** (63 indexes about 2.3 hours, 189 blocks about 30 minutes, one at a time on the GPU).

**6. Builds no longer compete with the runs for the disk.** A second Docker daemon for builds only runs on the PC, with its own containerd and all storage on one fixed 120 GB file. Test passed: two home-assistant tasks built and validated on it, saved to the archive, and one loaded into the run daemon with the same image id. The build queue runs on it now, 2 at a time: the 8 kubernetes run images, home-assistant (12 of the hard-tier file, then 41 candidates), ruff's hard tier. A log of I/O pressure and the count of builds runs beside the records' load values, so runs with builds beside them can be marked.

## Checked

- Pass points and the audit: scripts over the 48 `run.json`, `proxy.jsonl`, `stream.jsonl` and `prompt.txt` files (a copy on the Mac), and the code at `739fbe3` for the points on the score. `cmeval e2e score` ran on the copy for the 8 run ids.
- The two transcripts and the 8 runs of pandas 68945 were read in full.
- The image id of the smoke test: `c8bfb37b8db9` in the build daemon, in the archive's record and in the run daemon after the load.

## Left

- The cost column (needs the price table). The correction of the score's "used" column. A12, when you have decided.
- Andrew's word on two run streams and on where the records go (entry of 03:26 UTC).

## Blocked on, or needed from others

- **Andre:** the price table (A5); your rule for runs at a limit (A12); the side batch with bodies, yes or no (A14 would be answered by it).

## Next

Haiku's repetition 1 runs: pandas, ruff, duckdb, playwright, home-assistant, kubernetes. The next report comes when pandas and ruff are done.
