# Track A, early report: the Haiku half of the check run (24 runs, none discarded), and the answers on the run records

- **Track:** A, for the lead. The early report that Andre's entry of 01:20 UTC asks for, and the answers to his entry of 02:20 UTC
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 03:26 UTC
- **Work package:** A12 (the runs), A4 (the integrity checks)
- **Branch, commits, pull request:** none. Eval code `722ded5`, codemem `463171c`

## Done

**The numbers below are from 3 tasks per repo. They show that the pipeline works. They are not a result.**

**1. The Haiku half: 24 runs of 24, finished at 03:22 UTC. The Sonnet half runs now.**

Tokens are processed tokens (cache reads included). Seconds are the agent's clock.

| Batch | Solved, grep | Solved, codemem | Turns (grep, codemem) | Tokens: codemem against grep | Seconds: codemem against grep |
|---|---|---|---|---|---|
| pandas L0 | 2 of 3 | 2 of 3 | 31, 31 | +12% (1.37 M, 1.53 M) | +25% (406, 508) |
| playwright L0 | 3 of 3 | 3 of 3 | 56, 60 | +6% (2.92 M, 3.10 M) | 0% (696, 696) |
| pandas L2 | 3 of 3 | 3 of 3 | 58, 48 | -10% (2.72 M, 2.45 M) | -32% (779, 532) |
| playwright L2 | 3 of 3 | 3 of 3 | 55, 58 | +10% (2.68 M, 2.94 M) | -41% (1284, 756) |
| **L0, 6 pairs** | 5 | 5 | 87, 91 | +8% | +9% |
| **L2, 6 pairs** | 6 | 6 | 113, 106 | 0% | -38% |
| **All 12 pairs** | 11 | 11 | 200, 197 | +3% (9.69 M, 10.03 M) | -21% (3165, 2492) |

Pair by pair, `codemem` minus `grep` (turns, tokens, seconds):

| Task | L0 | L2 |
|---|---|---|
| pandas 68090 | +2, +194,539, -6 | -6, -156,001, -277 |
| pandas 68278 | -2, -64,823, +96 | +3, +167,278, +85 |
| pandas 68945 | 0, +29,489, +12 (not solved by either) | -7, -284,057, -55 |
| playwright 42204 | +6, +341,772, +71 | -1, -37,762, -9 |
| playwright 42260 | 0, -131,614, -51 | +8, +492,111, +1 |
| playwright 43316 | -2, -27,621, -20 | -4, -189,144, -520 |

- `codemem` used fewer tokens in 7 of 12 pairs (3 of 6 at L0, 4 of 6 at L2).
- With `codemem` the agent opened a gold file in its first turn in 9 of 12 runs. With `grep`: 2 of 12.
- The agent called `search_code` itself in 3 of the 12 `codemem` runs, one call each. In 9 runs it used only the block.

**2. Checks. All pass.**

- Discarded 0. Flagged 0. All 24 ended `finished`. No turn limit, usage limit or host timeout.
- The proxy's token count equals the agent's in 24 of 24.
- All 12 `codemem` runs: the block is in the first message, the mount proof is ok. No search fell back to keywords.

**3. Out of the ordinary.**

- **The seconds are noisy.** Most of a run's time is the tools' time (the agent runs tests), not the model's. Example: pandas 68090, `codemem`, L0: 217 s, of which 43 s is the API (`duration_api_ms`). One pair gives most of the L2 gain: playwright 43316, 815 s against 295 s.
- **Host load.** Until 02:34 UTC a job moved spare indexes to the hard disk beside the runs. Load at the start of a run was 1.1 to 11.9. The highest, 11.9, is pandas 68278 `codemem` at L0 (233 s against 137 s for `grep`). Every record has the load, so the analysis can mark these. The job is finished; no build runs beside the Sonnet half.
- **The cost field looks too low.** Claude Code reports 0.39 USD for the 24 runs (19.7 M processed tokens, 19.0 M of them cache reads). I did not check it against list prices. The token classes are kept, so the analysis can compute cost itself. Do not use `total_cost_usd` before someone checks it.
- pandas 68945 at L0: not solved by either setup, in under a minute each. At L2 both solve it. I read the transcripts for the full report.

**4. The two seats. The accounts are not the limit. The clock is.**

- All 24 runs used seat 1. Its weekly use went from 11% to 12% (the API's own header, kept in `proxy.jsonl`). Totals: 94 agent minutes, output 183,941, cache write 536,380, cache read 18,995,134 tokens. The week resets on Dec 4, after the freeze. Seat 2 is not used yet. Sonnet's cost against the limit comes with the Sonnet half.
- **Wall time: 5.5 minutes a run** (131 minutes for 24 runs; about 1.5 minutes of that is preparation and grading).
- Repetition 1 on Haiku has 378 runs (63 tasks, 3 levels, 2 setups); 24 are done here. The other 354 take about 32 hours one after the other, more if duckdb and kubernetes runs are longer. The whole of `runs.md` section 7 is about 1,440 runs: about 130 hours. 76 hours are left to the freeze.
- **So one stream is too little for the plan. This is the word you asked for.** The PC has 16 cores and 47 GB; one stream gives a load of 2 to 3. What I put to Andrew: two streams at the same time, one per seat, on different repos; the two runs of a pair stay back to back in one stream, so both setups see the same load; the load is in every record. Not decided yet. The order of the plan stays, so what falls off the end is Haiku's third repetition first.

**5. Your six questions on the records (entry of 02:20 UTC).** Read from the code at `739fbe3` and from the records on the PC.

1. **Is the whole folder kept? Yes.** A discarded attempt is renamed `1.discarded-N` with all its files (no `grade/`, it is not graded). Flagged runs and runs at a limit are kept and graded. No disk job touches the runs folder: the guards stop processes and prune images and build cache only. Removed by design at the end of each run: the index copy `cmindex/` (its byte counts stay), a scratch file of the mount proof, and the login token (replaced in every file). The work tree is not kept: only `agent.patch` and `after.txt`. `cmeval e2e recount` rewrites `steps` in `run.json` from the stream.
2. **Copied off the SSD? Not until 03:14 UTC. That was a gap, and your question found it.** Now: every 10 minutes to `D:\cmeval-runs-backup\runs` (the hard disk; nothing is deleted there), and a packed archive on Andrew's Mac at each report.
3. **Size and how you get them.** One run folder is 0.1 to 0.4 MB. The Haiku half is 12 MB, 2.5 MB packed (`check-run-haiku-half.tgz`). All of Haiku's repetition 1 will be about 40 MB packed. One archive per finished batch is easy. **I did not push it: the repo is public,** and the records hold the account's limit headers, request ids and the PC's host name (no token: 0 hits for a token pattern in all records). Andrew decides where they go; he can send the first archive in the chat.
4. **Fields at a limit.** No real case exists: all 196 records on the PC ended `finished`. From the code:

| Ends at | `result_event` (cost, `num_turns`, durations) | `tokens` | `steps` | `time` |
|---|---|---|---|---|
| Turn limit (the agent is killed) | null | from the proxy; `agent` and the cross-check null | from the stream; `num_turns_result` null | `agent_s` present |
| Usage limit | filled when Claude Code ends with an error result | from the proxy | from the stream | present; the run is discarded and not graded |
| Host timeout | null | from the proxy, may be `proxy-partial` | from the stream | `agent_s` and `exit_code` can be null; `end` is `error` |

   Turns can always be counted again from `stream.jsonl` (`steps.turns` is our own count; `recount` remakes it). Model time is the sum of `ms_end` in `proxy.jsonl`. **Cost is not computed anywhere from tokens**; the analysis must do it from the token classes.
5. **`proxy.jsonl`: yes.** Each request has `start` (wall clock, UTC, milliseconds), `ms_headers`, `ms_first_byte`, `ms_end`, the usage by class, the model, the status, the stop reason, the request id and the limit headers. `e2e_turns` already gives `turn_s` and `model_s` per turn; the rest of a turn is tools plus Claude Code's own time. **Not possible:** the time of one tool call (the stream has no time stamps), so calls made in parallel in one turn, and `search_code` calls, cannot be timed apart. Requests of subagents are counted apart from the main agent's turns.
6. **Bodies.** `CMEVAL_E2E_BODIES=1` (an environment variable; `cmeval e2e run` has no option). The proxy then writes `bodies/NNNNNN.request` and `.response`, raw. **Disk cost, from the byte counts in `proxy.jsonl`: 59 MB for the 24 Haiku runs** (median 2.2 MB a run, largest 4.9 MB). The whole check run would be about 150 MB, one repetition of a 14-task repo about 250 MB, all of Haiku's repetition 1 about 1 GB. Disk is no obstacle. **But the code marks such runs "diagnostic, not comparable with other runs"** (`e2e_run.py:147`), and the check run began without them. So I do not switch it on for the timed runs on my own. Offer: a small side batch with bodies (for example the 6 check tasks at L0, both setups, its own run id), which shows you the place of the 20 results, the tool definitions and how the context grows. Say if you want it.

**Not kept today, that the analysis may want:** the time of each tool call and of each `search_code` call (the gate logs nothing per call); the system prompt and the tool definitions (only with bodies); CPU and memory of the container (only the host's load is kept); the image digest (the image id is kept); the codemem commit in `grep` runs (null there). None of these needs a change to codemem. The first one needs a change to the eval's gate, so not before the runs.

**6. vscode and trino.** Your correction of 02:16 UTC is read. Nothing changes: vscode stays, trino is the one to drop. Points 1 and 2 of 02:14 UTC are our rule: the runs come first.

## Checked

- The tables come from `~/.cmeval/bin/early-report.py` over the 24 `run.json` files; the totals are added by hand from its batch rows.
- The weekly use of the seat: first and last limit header of the 397 requests in the 24 `proxy.jsonl` files.
- The answers on deletion, limits and the proxy fields were read in `e2e_run.py`, `proxy.py`, `e2e_turns.py` and `e2e_steps.py` at `739fbe3`. The limit cases are from the code only.
- The backup: 196 records on `D:` at 03:16 UTC; the archive holds 24 `run.json` files.

## Left

- The Sonnet half (24 runs), then the full report: the five pass points of `runs.md` section 6, your audit points, two `codemem` transcripts read, the answer on a full rebuild.
- Andrew's word on two streams and on where the records go.

## Blocked on, or needed from others

- **Andre:** do you want the side batch with bodies? And say if two streams are a problem for the latency numbers in your view.

## Next

The Sonnet half report. Then, in the gap after the check run: the compaction, the second Docker daemon for builds, the index and blocks of home-assistant 175759.
