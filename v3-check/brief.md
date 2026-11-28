# Brief: does PR #85 ("v3") really do better than what is on `main` ("v2")? An independent check, Haiku and Sonnet

codemem (the repo at `<codemem>`) is a code-search MCP server for coding
agents. Its `main` is locked for an evaluation at commit `463171c`. Another track's agent has opened
PR #85 (commit `4902671`): it rewrites the tool descriptions, limits `search_code` to 10 results, adds
four optional inputs the agent fills in (`intent`, `symptom`, `anchors`, `locations`), and removes the
hooks. That agent now claims PR #85 outperforms `main`, from two small tests of its own (real fix
runs, Haiku, L2, no shell, its own harness):

| Its test | Arm | Cost | Turns | Seconds | Gold functions edited |
|---|---|---|---|---|---|
| 5 tasks, one run each | grep | $0.058 | 79 | 240 | 7 of 11 |
| | plain codemem `463171c` (tool only) | $0.078 | 93 | 367 | 5 of 11 |
| | PR #85 (tool only) | $0.059 | 72 | 292 | 6 of 11 |
| 5 tasks, two runs each, 8 pairs | `463171c` (tool only) | $0.121 | 141 | 631 | 7 of 17 |
| | PR #85 (tool only) | $0.097 | 117 | 536 | 7 of 17 |

Its own log entry says the gap is as large as the run-to-run noise
(`.worklog/log/2026-11-28-0115-b-pr-85-against-mains-codemem-haiku-quick-test.md`; also
`…-0040-b-item-1-results-…md` and `…-0040-b-pr-85-…md`). **The project lead wants this claim checked
independently, with a clear view of tokens, time, turns and cost, for Haiku and Sonnet.** Your job is
to run that check on this Mac and report what the numbers support. Either answer is fine. Do not
argue for or against the PR.

## Two things the claim leaves out, which the check must cover

1. **What runs in the evaluation is not the tool alone.** "v2" is codemem `463171c` as the MCP tool
   **plus** the 20 best results of one codemem search on the request at the top of the first message
   (`eval/src/cmeval/e2e_block.py`: the header line, then `path:start_line  qualified name`, 20
   lines). The other agent tested neither arm with those 20 lines. So there are two comparisons:
   tool against tool, and the real one, v3 against v2 with the 20 lines in both.
2. **Noise.** One or two runs per cell cannot separate a 20% gap from chance. Every difference you
   report must stand next to the difference between two runs of the same arm.

## The arms (five), all in our session harness

| Arm | The agent has |
|---|---|
| `grep` | its own tools only |
| `v2-tool` | codemem `463171c` as the MCP tool |
| `v3-tool` | PR #85 as the MCP tool |
| `v2` | `v2-tool` plus the 20 lines at the top of the first message |
| `v3` | `v3-tool` plus the same 20 lines |

- The 20 lines are made once per task with `codemem search -k 20` at `463171c`, as the evaluation
  makes them, and are the same text in `v2` and `v3`. Block F of the harness already has arms with
  these lines (`upfront`, and the lines plus the tool): reuse its code and, where the text is the
  same, its saved lines (`.cache/review/compare/upfront/`).
- codemem's source for v2: the worktree `.cache/wt/compare-main` (`463171c`). For v3: make a new
  detached worktree `.cache/wt/compare-pr85` at `4902671`
  (`git -C <codemem> worktree add --detach .cache/wt/compare-pr85 4902671`).
  Do not use or touch `.cache/wt/pr85` (a review runs there), `.cache/wt/compare-dedup`,
  `.cache/wt/eval-vector-backend` or `.cache/wt/start-search-hook`.

## The harness, the tasks, the models

- **The harness** is `.cache/review/compare/bin/`: `compare.py` (the arms, the gates, the recording
  proxy, the scoring), `pipeline.py`, `blockf.py` and `blockg.py` (two earlier blocks; `blockg.py`
  shows arms that differ only in the server's source and environment, taking turns), and their
  report scripts. A session is Claude Code headless (`claude -p`) in a task's own copy of the repo at
  its base commit, with its own index; the agent may read and search but not edit, and answers with
  the files and functions it would change. Read `compare.py` before anything else. Do not weaken or
  change its gates.
- **Tasks, set 1:** our 17 pandas tasks at L2 (`.cache/review/compare/tasks/`), each with its own
  commit and index, as in blocks F and G.
- **Tasks, set 2:** the 6 vLLM tasks at L2 in `.cache/review/adopt/vllm-l2.jsonl` (they hold gold
  files and functions), on the vLLM checkout `.cache/repos/vllm` (`e9acf48`) with the real index
  `.cache/bench/real-vllm` (144,729 vectors). `.cache/review/adopt/bin/probe.py` shows how a session
  gets its own clone of that index (`cp -c`) and how vLLM's own agent file is kept out of the prompt.
  Never write to the real index or the checkout: work on clones.
- **Models:** `claude-haiku-5-5` and `claude-sonnet-5-5`.

## The order, so that a first answer comes early

1. **Stage 1, Haiku on pandas (153 sessions):** per task, `grep` once and the four codemem arms
   twice, the arms taking turns and the order changing from task to task.
2. **Stage 2, vLLM (84 sessions):** Haiku as in stage 1 (54), Sonnet once per arm (30).
3. **Stage 3, Sonnet on pandas (85 sessions):** each arm once.
4. Only if time is left: a second Sonnet run per cell on pandas.

After each stage, write its tables into the report file (below), so that the lead can read an interim
answer. **Stop making sessions at 07:00 UTC on Nov 28** wherever you are.

## Before the first session

- **Wait for the machine.** Another measurement (`blockg.py`) is being stopped. Start no session and
  load no model while a `blockg.py` process or another `claude -p` session of this project runs
  (look with `ps`, and mind that a search for a process name can match itself).
- **v3 on our indexes:** PR #85 touches `store.py`. Show that its server opens an existing index
  without rebuilding it (same vector count, status ready). If it rebuilds or migrates, stop and
  report: that alone is a finding.
- **A plain search is the same in both:** three real queries through `search_code` with only
  `query`, at `463171c` and at `4902671`, on the same index clone: the same results. Say if not.
- **One dry start per arm** (the harness has a dry mode that makes no model call): the first request
  holds the right tool descriptions (v2's or v3's), no hook, and in `v2` and `v3` the 20 lines.

## What to measure and report

For each arm, model and task set:

- **Quality:** the right file named first; the right function named (the harness's rules).
- **Turns, seconds, tokens** (all processed, and by class: new input, cache write, cache read,
  output) **and cost** (`total_cost_usd`): medians and sums.
- **Use:** `search_code` calls per session; for v3, how often each new input is filled, and how long
  the call's arguments are against v2's.
- **What a turn costs more in v3:** the characters and tokens of codemem's tool definitions in the
  first request, v2 against v3, from the saved request bodies.
- **Pairs on the same task:** `v3-tool` against `v2-tool`, `v3` against `v2`, and each against
  `grep`: lower / equal / higher for turns, tokens, cost and seconds.
- **Noise:** for Haiku, the two runs of the same arm and task against each other, in the same form.
  Then say for each difference between arms whether it is larger than that.

## Rules

- Write `.py` files only through the shell (a heredoc or a short Python replace), never with the
  Write or Edit tool. New scripts go in `.cache/review/compare/bin/`.
- One heavy process at a time: one session at a time, as the harness runs them. Look at
  `memory_pressure` and `uptime` before each stage. The disk has about 13 GB free: remove each
  session's index clone when it ends, and stop if less than 6 GB is free.
- Everything stays inside the project folder (`source .cache/env.sh`; never `~/.codemem`). No
  network. Sessions use the owner's subscription login through the harness as it is. At most 340
  sessions. Stop at once at any sign of a usage limit and do not restart. Never put the owner's
  name, email or the project's name into a prompt.
- No commit, no push, no work-log entry.

## The report

- File `.personal/benchmarks/2026-11-28-v3-against-v2.md`, lean: the answer in the first six lines
  (does v3 beat v2 as a tool? does it beat v2 with the 20 lines, which is what runs? on which
  measures, by how much, and is that more than the noise?), then one table per stage and comparison,
  one worked example of one task (what the agent did in v2 and in v3), and what was not measured.
  These are sessions in which the agent locates code and does not edit it; the other agent's tests
  were fix runs. Say what that difference means for the comparison.
- Hand back at most 25 lines: the answer, the key numbers for Haiku and for Sonnet, what is inside
  the noise, and what you could not do.
