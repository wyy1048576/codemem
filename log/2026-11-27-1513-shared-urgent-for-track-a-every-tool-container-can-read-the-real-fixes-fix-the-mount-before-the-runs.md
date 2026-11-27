# URGENT for track A, before the runs: every `tool` container can read the real fixes and the hidden tests, and no `grep` container can. Then twelve smaller points from our reading of the measurement code

- **Track:** shared: from track C's session, for track A. It is the code reading announced in the entry of 14:50 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 15:13 UTC
- **Work package:** A4 (the integrity checks), §4.5 and §5 of track A's plan
- **Branch, commits, pull request:** none. Read: `eval/src/cmeval` on `main` at `6aad996`; nothing was changed

## Done

We read the measurement code and ran its real functions on made-up records (no container, no model). Most of it is solid, and the list of what is solid is at the end. One point has to be fixed before the first run.

## 1. Fix before the runs: the answer keys are mounted into every `tool` container

- **What the code does.** `codemem_mounts` (`e2e_run.py`, the function after `gated_mcp_config`) mounts the whole codemem checkout read-only at its own path: `f"{codemem['checkout']}:{codemem['checkout']}:ro"`. The checkout is the repo root of the codemem program (`e2e_index.codemem_checkout`).
- **What is in a checkout.** `eval/tasks/e2e/*.jsonl`. Each task's line holds `patch` (the real fix), `test_patch` (the hidden tests), `gold` and `query` (the issue text). The files are there at `463171c` too.
- **How an agent gets there.** The path is in `/tmp/mcp.json` and in the gate's config, and `ps` shows it. An agent that greps `/` for a phrase of the issue, as agents do when the repo has no match, lands on the task's line and can copy the fix. One `grep -rF` for a phrase of one issue printed the line with its fix.
- **Why it matters.** `grep` containers have no such mount. So this can raise completion in `tool` only, for a reason that is not codemem. How often an agent reads it is unknown; one such run in a repo's 42 `tool` runs is about 2 points of that repo's completion.
- **Whether your PC is affected** depends on what the mounted checkout holds. Your replay names the program as `.../codemem-run/.venv/bin/codemem`: if `codemem-run` is a checkout of this repo, `eval/tasks/` is in it. If `CMEVAL_HOME` or the work log is inside that folder, earlier runs' patches and the grader's test files are visible as well.

**The fix, either of:**
- mount only what codemem needs: its package (`<checkout>/src`) and its Python install, not the checkout's root; or build the install from a tree that holds nothing but codemem (`git archive 463171c src pyproject.toml ...`);
- or hide the rest after the bind mount: `--tmpfs <checkout>/eval`, and the same for any folder with task data, records or the work log.

**Then prove it, as a setup check of every codemem run:** inside the container, as the agent's user, `<checkout>/eval` does not exist (or is empty), and a `grep -rlF` for a phrase of the task's issue over everything outside `/testbed` finds nothing. A run that fails it does not start.

**And look back:** in the runs made so far (the pilot, the vague-prompt runs, the replay's 62), did any command of the agent touch a path under the checkout or under `CMEVAL_HOME`? The commands are in each run's steps. Please post the count.

## 2 to 13. Smaller, in order of weight

| # | What can lean | Which way | The smallest fix, or the record that settles it |
|---|---|---|---|
| 2 | **A flagged run leaves every number, completion included** (`e2e_score`: `kept` drops runs with `flags`). A run with more requests has more chances of a broken stream, so long runs are flagged more often | differences are pulled towards zero: with a 0.2 to 0.5% chance of a break per request, a token gap kept 56 to 73% of its size in our simulation with your `paired_difference` | keep flagged runs in completion; for tokens use the proxy's sums when a stream broke. Record: flags by setup and reason, and the number of requests of flagged against kept runs |
| 3 | **A run stopped at the time limit stays or leaves by whether Claude Code writes a result event at TERM.** With a result event and a request in flight, the cross-check flags it and it leaves the tables. The turn limit (`kill -9`) leaves no result event, so those runs always stay | the setup with more time-limit runs loses its worst runs | skip the cross-check for runs that end at a limit and use the proxy's sums. Record: does Claude Code write a result event at TERM; time-limit runs and how many are flagged, by setup |
| 4 | **The score prints per-setup means over different sets of tasks side by side.** A setup that lost the runs of one large task looks cheaper there while the paired difference is zero. The paired number is a mean difference, so the largest tasks dominate it, and "over N tasks" is not the count behind each measure | either | per-setup means over the paired tasks only; the mean ratio as §13 says; the number of tasks behind each measure |
| 5 | **`grep` runs first in every pair of a one-repetition batch,** and in 2 of 3 pairs with three repetitions (`plan_runs` rotates by repetition only). The second run finds the image's files in the host's page cache | the later setup, by perhaps 1% of wall time (estimated, not measured) | one line: `shift = (rep - 1 + i) % len(setups)` with `i` the task's index. It also keeps `upfront` from always going last |
| 6 | **codemem's shutdown may be inside the `tool` clock:** the bridge returns only when the gate closes the socket, after codemem has exited | `grep`, by seconds a run | record: `agent_s − duration_ms/1000` by setup in the check run |
| 7 | **Processed tokens add every model at par, and `run.json` keeps only the proxy's totals,** not its split by model | the setup that hands work to a smaller model looks dearer in tokens than in price | save the proxy's per-model sums in `run.json`; report the main model's tokens beside the total |
| 8 | **Discarded attempts vanish from the score once redone** (they move to `<rep>.discarded-<n>`, which `load_records` skips) | hides how often only `tool` was redone | count the set-aside folders by setup and reason in the score |
| 9 | **Any 429 discards the run and stops the batch,** also one that Claude Code waited out | the setup that sends fewer requests | treat a 429 as a usage limit only if the run then failed or the reset header names the usage window. Record: 429s per run by setup |
| 10 | **codemem shares the container's 16 GB with the agent's builds and tests,** and nothing records memory | `grep` on heavy builds (duckdb), if a build is killed for memory in `tool` only | record the container's peak memory and OOM kills by setup |
| 11 | **The behaviour columns count grep-like actions only:** codemem's calls are not in "content searches", and a subagent's codemem calls are not in `codemem_calls` | `tool`, if the columns are read as all searching | a column for searches with codemem's included |
| 12 | **The index may hold files that the container deletes before the agent starts** (`CLAUDE.md`, `AGENTS.md`, `.claude/`) | `tool`, only if a search returns their text | record: any `search_code` result that names a path of its run's `removed.txt`; or build the index after the same removal |
| 13 | **A run that ended in an API error counts as not completed** and stays done | neither setup, but it adds failures that are not the agent's | discard a run when the proxy shows the API failing at its end |

## For the `upfront` setup you are building

- **`grep`'s container exactly:** no checkout mount (so point 1 does not arise), no gate, no index copy, no codemem process; `codemem=False`, no MCP servers, the check that no `mcp__` tool is loaded, and a check for the block.
- **The block through `make_prompt` into `prompt.txt`:** the proxy then counts it in every request with no new token code. Record the block's own hash and its file.
- **The search's seconds** per task and level, outside the clock and reported beside wall time. Refuse a block whose timings have no `embed_query:` key.
- **Gold marks:** a gold path in the block is not in a tool result, so `first_gold_surfaced_turn` misses it. Count the block as surfaced at turn 0, with its gold ranks.
- **Runs added later under the same run id** pair with `grep` runs made hours earlier, possibly by another Claude Code version: let the score refuse a pair whose two runs have different `harness_version`. `run_state` never compares model or level, so a reused run id with another `--model` or `--prompt-level` silently skips runs that exist.

## What is solid, so that nobody spends time proving it

- Which requests count (status 200 with a usage block; `count_tokens` apart; a retried request once), and that the tables always use the proxy's count.
- Processed tokens cannot move with cache luck; the four classes and the 1-hour and 5-minute cache writes are in `run.json` and in the proxy log, so cost at fixed list prices can be computed later.
- `total_cost_usd` is used in no table and no decision.
- The clock's limits: the gate's wait, the index copy, the container's start and the collection are outside it and recorded apart; Claude Code's own start is inside it for every setup.
- Both limits stop every setup the same way; a run is discarded before it is graded; the grader is the same for every setup.
- The container, the prompt frame and Claude Code's environment are the same for every setup, apart from codemem (and points 1, 10 and 12).
- The gate's warm-up search cannot change what the agent sees.
- Turn counting: a turn is one model answer of the main agent, and parallel calls are one turn.

## Checked

- Point 1: the mount line and the task files' fields were read by Andre's session as well (`codemem_mounts`; the keys of a line of `eval/tasks/e2e/pandas-large.jsonl`: `patch`, `test_patch`, `gold`, `query`).
- Points 2, 4 and 5: the score's `kept`, `paired_difference` and `plan_runs` were read by Andre's session as well. The simulations and the other points are the audit's, made with your functions on made-up records.
- Not checked: anything on the PC. Which checkout it mounts, where `CMEVAL_HOME` is, the flag and discard counts, 429s, memory: only your records can say.

## Left

Nothing on our side until you answer.

## Blocked on, or needed from others

**Track A:** point 1 before the first run, with its proof and the look back, posted here. Points 2 to 13 with the check run or after it, as they fit; 5 is one line and is best in before the first batch.

## Next

Andre's session: read your answer. Our advice to Andre is that the runs should not start with point 1 open; the decision is his.
