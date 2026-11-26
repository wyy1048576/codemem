# Does the agent call codemem? Short probes of Claude Code on pandas

Date: 2026-11-26. For Andre, before the design lock (Fri Nov 27, noon Pacific). Nothing in `src/` or on any
branch changed. Nothing was pushed or posted. 80 probe runs of Claude Code on your subscription, each stopped
after 4 turns.

**Why.** If agents do not call codemem, the evaluation's `tool` runs measure nothing. The pilot left two
questions open: does the wording make agents call it at the right moment, and is "one call, then grep" a
problem?

## The finding

1. **Haiku finds the tool with the wording on main (`light`).** It called `search_code` in 11 of 12 runs
   with a Grep tool, and in 10 of 10 when it searched in the shell, as in the evaluation. The call came in
   turn 1 in 20 of those 21 runs. Without steering text (`none`) it called codemem in 2 of 12.
2. **Sonnet did not call it, in 5 of 5 runs.** It went straight to the right pandas file by grepping function
   names it remembers, in turn 1 or 2. Sonnet runs most of the evaluation, so this is the largest risk for
   the `tool` arm on pandas. It is a risk from the model's memory of pandas, not from the wording. The
   follow-up at the end of this report confirmed it on 11 tasks, vLLM included (0 of 11 without hooks).
   With codemem's own hooks, Sonnet called `search_code` in 11 of 11.
3. **At L0, not calling codemem was not a mistake.** The 11 Haiku runs that did not search first all reached
   a gold file within 4 turns, 8 of them in turn 1. So "8 of 18 at L0" in the pilot looks like a sensible
   agent, on a repo it knows.
4. **Keep `light`. My two own wordings were not clearly better,** so the branch `andre/adoption` was not
   made. One was shorter and called less. The other changed little.
5. **One fault, outside the wording: the result reaches the model as one escaped JSON string.** Read from
   the saved request bodies: `{"result":"1. pandas/io/json/_json.py:590-611  read_json ...\n   def ...`.
   Adding `structured_output=False` to the four tools in `server.py` makes it plain text. I checked this in
   the request bodies, and codemem's 8 MCP and steering tests pass with it.
6. **One call is enough when the first card is the right source function.** The agent then reads that file
   at the card's lines. When tests fill the top of the list, it goes back to its own guesses.

## The call rates

One run per cell. Haiku: 6 tasks at L0 and L2 with a Grep tool; 5 tasks with the shell. "Gold" means a file
the real fix changed. Cost is the extra prompt per request against `none`, measured in the requests.

| Setup | Wording | Called at L0 | Called at L2 | First call in turn 1 | Searched again | Gold in first result | Cost per request |
|---|---|---|---|---|---|---|---|
| Haiku, Grep tool | `none` | 1 of 6 | 1 of 6 | 2 of 2 | 0 | 1 of 2 | 139 words |
| | **`light` (main)** | **6 of 6** | **5 of 6** | 10 of 11 | 0 | 9 of 11 | 290 words, +267 tokens |
| | `strong` | 5 of 6 | 6 of 6 | 10 of 11 | 5 of 11 | 10 of 11 | 295 words, +293 tokens |
| | v1 (mine) | 4 of 6 | 4 of 6 | 7 of 8 | 0 | 6 of 8 | 212 words, +116 tokens |
| | v2 (mine) | 5 of 6 | 5 of 6 | 10 of 10 | 2 of 10 | 8 of 10 | as `light` |
| Haiku, shell | **`light` (main)** | **5 of 5** | **5 of 5** | 10 of 10 | 4 of 10 | 8 of 10 | as above |
| | `light` + the hooks of #26 | 5 of 5 | not run | 5 of 5 | 0 | 4 of 5 | hooks ran, refused nothing |
| Sonnet | `light` and v1, Grep tool | 0 of 2 | 0 of 2 | | | | |
| | `light`, shell | not run | 0 of 1 | | | | |

- **v1** puts the rule in the `search_code` description ("Call it first when the task names no file,
  function or exact error text, and again when a grep finds nothing useful ... Once you have a name or
  message, grep for it") and cuts the server instruction to one line. **v2** is `light` with the result as
  plain text and a footer that names the next step ("Next: read the best hit with get_chunk(<id>), or Read
  its file at those lines. None fits? Call search_code again in other words.").
- Whole 4-turn runs cost about the same. Haiku with a Grep tool used 48,900 tokens per run with `none` and
  52,900 with `light` (+8%), with 9 s of model time either way.

## The queries the agents wrote

Five typical first queries, all from `light`:

| Task, prompt | Query | Gold file in the result |
|---|---|---|
| 70828, L0 | "read_json series typ parse null converted to NaT in Series from dict" | first |
| 67897, L2 | "convert pandas Interval array to pyarrow with timezone-aware datetime bounds" | first |
| 70734, L2 | "sas7bdat reader skip deleted rows" | first |
| 66352, L2 | "assert_index_equal MultiIndex tuple labels containing NaN compare equal" | not in the 10 |
| 69779, L0 | "groupby multiple keys float64 group index compression wrong results" | not in the 10 |

- **A description in the agent's own words, mostly with pandas names mixed in.** Of 57 first queries by
  Haiku, 34 mix words and names, 22 are plain words and 1 is mostly names. None is the issue's title.
- **The names are often guessed.** The L2 prompt of 66352 names no function. Haiku added `assert_index_equal`,
  but the fix is in `assert_attr_equal`. The issue of 69779 reads like a groupby bug, and every wording
  searched for groupby. The fix is in how a MultiIndex is printed.
- 49 of 73 queries hold a name. When a first query held a name, the gold file was in the top 10 in 31 of 35;
  without one, in 15 of 22. Different tasks sit behind the two groups, so this does not test the paper's
  claim that guessed names help.

## The four questions

**1. Is the tool found?** Yes by Haiku, no by Sonnet. Haiku: see the table. It calls once, in turn 1, with a
description. `strong` and the shell made it search again more often (5 of 11 and 4 of 10). Sonnet: 0 of 5.
The tool set of a probe is smaller than the evaluation's (point 1 of the limits). That may raise Haiku's
rates, since the pilot saw 8 of 18 at L0. Compare wordings within a row group, not with the pilot.

**2. At L0, does not calling it look like a mistake?** No, on pandas. With a Grep tool, 11 of 30 Haiku runs
at L0 did not search in turn 1. All 11 reached a gold file within 4 turns, 8 in turn 1, and 4 by grepping
straight inside the gold file by a path the model remembered. The 19 that searched first had the gold file
as the first card in 13. Five of the six misses are task 69779, whose issue misleads every query. The sixth
passed an absolute `path_prefix` and got "No results". All 5 Sonnet runs grepped first and reached a gold
file in turn 1 or 2. The model's memory of pandas does that work; on a repo it does not know, or with
disguised names, this can flip.

**3. Which wording?** `light`, as it is on main. Nothing changes in `prompts.py`. It costs 290 words in every
request: 183 in the four tool descriptions and 107 in the server instruction, 267 tokens more than `none`.
- v1 does what you describe as intended. It skipped codemem in 4 runs: where the prompt named a function
  (66352 and 67897 at L0), an error text (68195 at L2) or a file format (70734 at L2). All 4 reached a gold
  file by grep in turn 1. It is also 151 tokens shorter.
  But it called in 8 of 12 runs against 11. With one run per cell that difference may be noise, and it
  lowers use at L0, the evaluation's main prompt. Worth a run after the lock, not before.
- v2's footer changed little within 4 turns. No agent called `get_chunk` although the footer names it; they
  used Read.
- `strong` adds repeat searches and `get_chunk` calls. That cost about 3,200 more tokens per run at L0 than
  `light`, for the same call rate.

**4. What one call needs to contain.** In the transcripts, after a first search the agent opened a file from
the cards in most runs (7 of 11 with `light` and a Grep tool), mostly with Read at the card's line. When the
first card was the gold function, no second search was needed. That matches the pattern you intend. One call
is enough when:
- **the source function comes first.** Over 57 first searches, the gold file was first in 34 and in the
  top 10 in 46. A third of all cards were tests or benchmarks (193 of 535). When the first card was a test
  (14 searches), the gold file was further down or missing;
- **the cards are readable.** Today they arrive as one escaped line (finding 5);
- **the line range can be opened directly.** It can: agents passed the card's line to Read as its offset;
- **a filter never empties the answer.** One `path_prefix` given as an absolute path returned "No results".

## How it was measured

- **The agent.** `claude -p` 2.1.285 on this Mac, Haiku `claude-haiku-5-5`, Sonnet `claude-sonnet-5-5`. It
  used the runner's prompt frame, flags and environment, with effort `medium`. It ran in the pandas checkout
  (`.cache/repos/pandas`, `a0885a1`) and stopped at 4 turns (`--max-turns 4`).
- **Clean and read-only.** `--setting-sources project`, `--strict-mcp-config`, `--disable-slash-commands`,
  `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` and `--permission-mode dontAsk` were set, so no hooks, plugins, MCP
  servers or CLAUDE.md of yours were loaded. A gate read the first event of every run (tools, MCP servers,
  plugins, mode) and stopped the run on any difference. Claude Code's own three built-in plugins were
  allowed. A second check read the first request: no `AGENTS.md`, `CLAUDE.md` or plugin text in any run.
  Two conditions:
  - "Grep tool" (`--tools Read,Grep,Glob`): 64 runs;
  - "shell" (`--tools Read,Bash`, as the evaluation searches): 16 runs. Only these commands were allowed,
    each by its own rule: `grep`, `ls`, `cat`, `head`, `tail`, `wc`, `cut`, `xargs grep`. `dontAsk` refuses
    everything else.
- **The fence was proven with no model call.** A fake API asked Claude Code to run 51 commands, through the
  real permission check. 39 tried to write or run a program and all were refused: `touch`, `>`, `>>`, `;`,
  `&&`, `$(…)`, backticks, `tee`, `find -exec`, `sort -o`, `env touch`, `| sh` and others. 12 reads ran.
  No file appeared. This found two holes, which I left out of the allow list: `sed -n '1w file'` writes a
  file, and `rg --pre=<script>` runs a program. In the real runs 13 commands were refused: 10 `python -c`
  and 3 `git`. No harmless pipe was refused, so nothing was added.
- **The server.** It ran the code of today's main (`8d86da8`), from `.cache/wt/adopt-main`. Each run had
  its own `cp -c` clone of `.cache/bench/real-pandas-gate` and its own `CODEMEM_HOME`. The environment was
  `CODEMEM_VECTOR_BACKEND=faiss`, `HF_HUB_OFFLINE=1`, `CODEMEM_MODEL_IDLE_MINUTES=0` and
  `OMP_NUM_THREADS=1`. A wrapper (`bin/mcp_hold.py`) held the MCP handshake until the model had loaded,
  13 to 17 s, as the runner will. No search came back keyword-only, and no server crashed.
- **The hooks arm.** The two hooks of #26 were written by `agents.py`'s own code and passed with
  `--settings`, so the shared checkout was not touched. They ran in every run (4 to 7 hook events), but the
  first-search refusal never applied: each agent called `search_code` before its first grep.
- **Recorded per run.** A recording proxy (track A's `cmeval.proxy`) kept each run's requests. The records
  hold every tool call with its query, pattern or command, the turn of the first search, repeat searches,
  the gold file's rank in each result, and refusals. They also hold the names in each query, and tokens and
  seconds from the result event. The files are in `.cache/review/adopt/`: `runs/<run>/record.json`, the
  scripts in `bin/`, and the fence in `fence-result.txt`.
- **The tasks.** These six pandas tasks of `vague-b7-v2`: easy 70828 and 68195, medium 69779 and 66352, hard
  70734 and 67897. Per level, the one task whose issue names no gold identifier, and the first by id that
  names one. L0 is the issue as written, L2 the short request. The shell and Sonnet runs left out 68195:
  this checkout already has its fix, so the error text the issue quotes is gone.
- **Runs.** 80 of 80. Grep tool: 60 Haiku, then 4 Sonnet, stopped when the shell condition was asked for.
  Shell: 15 Haiku and 1 Sonnet. There were also 13 starts with no model call: dry starts against an
  unreachable API, and fake-API checks.

## Limits, and what I could not check

1. The tool set is smaller than in the evaluation (Read with Grep and Glob, or with Bash, against about 20
   tools there), and the probes ran on Claude Code 2.1.285, not 2.1.332. Absolute rates may be higher here.
2. Four turns show the start of a run, not whether codemem helps it finish. One run per cell shows large
   effects only.
3. Only pandas, at a commit after every task's fix: the bugs are already fixed in the files the agent read.
4. Not run: Sonnet with the hooks. That is the case where the first-search refusal could matter, since
   Sonnet greps first. Also not run: L1, playwright, and more than 5 Sonnet runs.
5. The real index's `index.db-shm` got a new time at 06:33, before I started, and again at 07:43. Its data
   files are unchanged. My runs only cloned the folder, and a clone does not change the source's time
   (tested). No process had it open when I checked.
6. A Python crash at 06:52 was mine: a test of the wrapper, with no agent, started with
   `OMP_NUM_THREADS=4`. No probe run was lost. Every probe server had `OMP_NUM_THREADS=1` and
   `MKL_NUM_THREADS=1`.

## Sonnet: the hooks, the strong wording, and a second repo

A follow-up of the same day (08:43 to 08:57 Pacific), on the finding that Sonnet did not call codemem.
Sonnet (`claude-sonnet-5-5`) ran in the shell condition for 6 turns, at L2 (a short request that names no
code), on today's main `09c4ef0`, which answers in plain text. There were 11 tasks: the 5 pandas tasks of
the shell runs and 6 vLLM requests (`.cache/review/adopt/vllm-l2.jsonl`). Each task ran in three arms,
once each: 33 sessions.

**The finding.**
1. **Without hooks, Sonnet does not call codemem: 0 of 11,** on vLLM as on pandas. Its first move is a grep
   for code it remembers. Of its 11 first greps, 7 held a real name from the gold file's code and 4 named
   the gold file's path.
2. **With codemem's two hooks, it calls codemem every time: 11 of 11.** The hook refused the first grep in
   all 11. In all 11 Sonnet's next turn opened with `search_code`, never with the same grep again, although
   the refusal text allows a repeat. That search held a gold file in 10 of 11, as the first card in 8.
3. **The hook costs a turn, not time to the gold file.** With and without hooks, a gold file was reached at
   turn 2 (median). Tokens over 6 turns: median 48,600 with hooks against 45,700 without (+6%).
4. **`strong` without hooks is half-way: 5 of 11,** 4 of them in turn 1. One more came after the fence had
   refused its first command. Arm D (`strong` + hooks) was not needed under the brief's rule.

| Repo | Arm | Runs | Called `search_code` | In turn 1 | First search refused by the hook | Next turn after the refusal: `search_code` / grep repeated | Gold file within 6 turns | Median tokens |
|---|---|---|---|---|---|---|---|---|
| pandas | A: `light` | 5 | 0 | 0 | – | – | 5 | 49,400 |
| pandas | B: `light` + hooks | 5 | 5 | 0 | 5 | 5 / 0 | 5 | 53,000 |
| pandas | C: `strong` | 5 | 3 | 2 | – | – | 4 | 54,000 |
| vLLM | A: `light` | 6 | 0 | 0 | – | – | 6 | 40,700 |
| vLLM | B: `light` + hooks | 6 | 6 | 0 | 6 | 6 / 0 | 6 | 47,200 |
| vLLM | C: `strong` | 6 | 2 | 2 | – | – | 6 | 43,700 |

"Gold file within 6 turns" means it appeared in a tool result, or the agent read or grepped it by path.

**Three first moves that show the pattern.**
- A, vLLM 51573 ("options set to false in my YAML config file are silently ignored"). Sonnet's first call
  was `grep -rn "yaml" vllm/utils/argparse_utils.py`. That file is the gold file, named from memory.
- B, pandas 70828. Its first command was `cd pandas/io/json && grep -n "_try_convert_to_date\|def _try_convert_data\|NaT..." _json.py`,
  real names in the gold file. The hook refused it. Next turn: `search_code("read_json converts null to NaT
  in Series with object orient")`, which put the gold file first.
- C, vLLM 60310. Even with `strong`, it opened with `grep -rn "max_log_len" vllm --include=*.py`, a real
  name in the gold file.

**Limits.** One session per cell, 11 tasks, and only the first 6 turns. The tool set is still smaller than
the evaluation's. The fence refused 22 commands the evaluation would run, each costing the agent a turn: 10
began with `cd`, 7 with `python`, and 5 others. The vLLM snapshot (`e9acf48`, Oct 24) already holds the
fixes, as the pandas checkout does: what was measured is the first moves. Session `S-p-70828-A` overlapped
with a foreign `pytest` that started during it; it is marked, and it counts. No search came back keyword-only.
No server crashed. Records: `.cache/review/adopt/runs/S-*`. Progress: `.cache/review/adopt/progress-sonnet.md`.
