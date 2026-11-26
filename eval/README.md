# cmeval

Evaluation suite for repository-level code retrieval. It measures how well a search system finds the code that a real bug fix changed: accuracy (file, class, and function level), token cost, and latency.

cmeval works like a benchmark. Each search system (grep, codemem, or any other tool) plugs in through one small interface. cmeval does not depend on codemem, and codemem never imports cmeval.

## Install

```bash
cd eval
uv sync                  # or: uv sync --extra codemem (adds the codemem adapter, PyTorch, the embedding model)
uv run cmeval --help
uv run pytest
```

Python 3.11 or later. The grep baselines need ripgrep (`rg`) on PATH.

## Tasks

A task is one GitHub issue (the query), one repo snapshot (`base_commit`), and the gold answer: the files, classes, and functions that the real fix changed. Task files are JSON lines in `tasks/`, one task for each line. The schema and its rules are in `src/cmeval/tasks.py`.

Every task has a `split`:
- `dev`: for building and tuning. All SWE-bench Verified tasks and 20% of fresh tasks.
- `test`: for reported results only. The other 80% of fresh tasks. Do not tune on it.

The split of a fresh task comes from a hash of its ID, so it never changes.

Task files:

| File | Source | Split |
|---|---|---|
| `tasks/swebv-dev50.jsonl` | 50 SWE-bench Verified tasks, about the same number from each of its 12 repos, labeled with cmeval's rules. `swebv-dev50.meta.json` records the dataset revision, seed, skipped rows, and label statistics. | dev |
| `tasks/fresh-v1.jsonl` | 2,084 fresh tasks from 7 Python repos (home-assistant, vllm, pandas, airflow, ray, transformers, cpython): fixes opened and merged from 2026-07-01 to 2026-10-22, after the model cutoff. Made by `cmeval collect configs/fresh-v1.toml`. `fresh-v1.meta.json` records the settings, the funnel for each repo (13 steps, from 21,822 merged PRs), the drop reasons, and label statistics. Use tag `gold_all_python` for the main comparison (codemem reads Python only). | dev (399) and test (1,685) |
| `tasks/fresh-v1-py100.jsonl` | The Python sample of the main comparison: 25 all-Python dev tasks from each of pandas and transformers (medium) and home-assistant and airflow (large), drawn from `fresh-v1.jsonl` with `cmeval subset` (seed `cmeval-sample-1`). `fresh-v1-py100.meta.json` records the rule, the seed, and the chosen ids. |

Gold labels come from `src/cmeval/labels.py`: the files, classes, and functions that the fix changed, found with tree-sitter on the code at `base_commit`.

## Commands

| Command | Status |
|---|---|
| `cmeval validate FILE` | Check a task file and print counts by source, split, and repo |
| `cmeval import swebench-verified [--n 50] [--seed 0]` | Sample and label SWE-bench Verified tasks (pinned dataset revision) |
| `cmeval systems FILE` | Check a system config and list its systems (adapter, granularity, index key) |
| `cmeval repo-stats [--candidates FILE] [--repo R ...] [--since DATE] [--until DATE] [--functions]` | Numbers for choosing repos for fresh tasks: size, languages, a PR funnel after the cutoff, and (with `--functions`) the Python files, lines, and chunks that codemem indexes, from a shallow clone. GitHub answers are cached in `CMEVAL_HOME/gh-cache`. Needs `gh` with a login. |
| `cmeval collect CONFIG [--repo R ...] [--dry-run] [--refresh]` | Fresh candidates for each repo in a collection config (`configs/fresh-v1.toml`): merged PRs after the cutoff, their one linked issue (GitHub's list or SWE-bench's regex), and the query from the issue as it was when the fix PR was opened. Then, from the full clone: base commit and patch (Decision 7), file-list and apply checks, size filters, gold labels, split. Writes `tasks/<config>.jsonl` and its meta file, and keeps candidates and funnels in `CMEVAL_HOME/collect/`. `--dry-run`: GitHub steps only. |
| `cmeval review` | Not built yet |
| `cmeval run --tasks FILE --config FILE --run-id ID [--split dev\|test] [--repo R] [--limit-per-repo N] [--index-mode update\|rebuild]` | Run every system on every task; saves hits and timings (see "Run files") |
| `cmeval score RUN [--tokens anthropic\|estimate] [--iou T ...]` | Score a run: accuracy, tokens, latency (see "Metrics") |
| `cmeval report RUN [--baseline grep-fn-plus] [--split dev\|test] [--cutoff DATE] [--tasks FILE] [--where KEY=VALUE ...]` | Write `report.md` for a scored run: tables, intervals, paired tests, and groups (repo, language, issue date, identifier in query, gold all Python, repo size, fix size, gold files). `--where` keeps only the tasks whose tag has that value; the main comparison on fresh tasks uses `--where gold_all_python=true` (the labeler finds functions in Python only, and grep-fn-plus reads `.py` files only). The tasks left out get their own section. The primary tests use the family of the run's codemem version: `cm3-full` for v3, or `cm-bm25`, `cm-bm25-code`, `cm-bm25-code-usage` for the MVP (`--primary` chooses others). A run with no codemem system has no primary tests. |
| `cmeval merge BASE EXTRA --run-id ID [--system S ...]` | Copy systems of one run into a copy of another run, for one report |
| `cmeval compare RUN_A RUN_B [--tasks FILE]` | Update vs. rebuild check: compare two scored runs of the same tasks |
| `cmeval subset TASKS --out FILE --per-repo N --seed S [--split dev] [--where KEY=VALUE ...] [--repo R ...]` | A fixed random subset of a task file: N matching tasks for each repo (all of them if a repo has fewer), drawn with a seeded generator per repo. Writes a new task file and a `.meta.json` with the source, rule, seed, and chosen ids. The Python sample `tasks/fresh-v1-py100.jsonl` is made this way. |
| `cmeval generate RECIPE --tasks FILE [--admission] [--id ID ...] [--split dev\|test] [--limit N] [--jobs 2] [--repeats 3] [--force \| --rebuild]` | Tasks with a test environment, for end-to-end runs. For each task of the recipe's repo that has a test change: build a Docker image of the repo at the task's commit, then run the task's test files before and after the real fix, three times each. A task is valid when at least one test fails in every run before the fix and passes in every run after it, and no test that passed before fails or changes between runs. `--admission` takes a fixed sample of 10 tasks (3 easy, 4 medium, 3 hard) and passes when 6 are valid. Recipes are in `envs/`, one TOML file for each repo; the fields are described in `src/cmeval/generate.py`. Images are named `cmeval-env/<recipe>:<task id>`. Records and logs go to `CMEVAL_HOME/generate/<recipe>/<task id>/`. Each image that a task gets is added to `image-builds.json` there, newest last: image id, creation time, size, fingerprint, the build time, and the digest of the recipe's base image; `result.json` has the id of the image that the validation used. `--rebuild` builds the image again for each valid task whose image is missing, and does not validate again: the saved `tests.json` stays. It refuses a task whose saved record or `tests.json` has another fingerprint than the recipe and the task give now, prints each build and its time, and exits with 3 when a task is refused or a build fails. Needs Docker |
| `cmeval e2e grader-check RECIPE --tasks FILE [--id ID ...] [--jobs 1] [--cpus 8]` | A check of the grader of end-to-end runs. For each valid task of the recipe's repo (a task with `tests.json` from `cmeval generate`): grade the real fix and an empty change. To grade a change, a fresh container of the task's image applies the change, puts the hidden test files of the real pull request in place (they overwrite the agent's version of those files), runs the refresh commands, and runs the task's test command. The change completes the task when every fail-to-pass test and every pass-to-pass test passes. An empty change never completes a task. The check also compares each saved test of `tests.json` with its result on the image as it is now: with the real fix every fail-to-pass and pass-to-pass test must pass, and with the empty change no fail-to-pass test may pass. A task passes the check when the real fix completes it, the empty change does not make the tests pass, and no test differs. Prints one line for each task (with the count of tests that differ, and the first ones with their saved and new state) and a summary with the count of tasks that pass and that differ. Exit code 3 when a task does not pass. The record of each task (`check.json`: the per-test comparison, the image id and its place in `image-builds.json`) goes to `CMEVAL_HOME/e2e/grader-check/<recipe>/<task id>/`, the records of the two gradings (`grade.json`) and their logs to `{gold,empty}/` below it. Needs Docker |
| `cmeval e2e grade RECIPE --tasks FILE --patch FILE --id TASK [--out DIR] [--cpus 8]`, or `--patch DIR [--id TASK ...]` | Grade a change that was made outside `cmeval e2e run`, with the same grader. The change is a git diff against the task's base commit, with the default `a/` and `b/` prefixes (`git diff`, not `git diff --no-prefix`). A diff without a `diff --git` line or without the prefixes is refused. As for an agent's change, the files that the hidden test change touches are dropped from the diff before it is applied. The task needs a valid saved validation (`tests.json` from `cmeval generate`) and its image; a removed image is built again with `cmeval generate RECIPE --tasks FILE --id TASK --rebuild`. `--patch DIR` grades each `<task id>.patch` file of the folder, and each `<task id>/<label>.patch` file of its subfolders (`.diff` works as well); a change whose task is of another repo is skipped with a note. Prints one line for each change: completed or not, the reason, the passed fail-to-pass and pass-to-pass tests, the first failed tests, and the test files dropped from the diff. The records go to `DIR/<task id>/<patch name>/` (default `CMEVAL_HOME/e2e/grades/<recipe>/`): the grader's inputs and logs, `input.patch` (the diff as given), and `grade.json` (the grader's record, with the patch file, its sha256, and the dropped test files). Exit code 0 when every change completed its task, 3 when one did not, 1 for an error. Needs Docker |
| `cmeval e2e run RECIPE --tasks FILE --run-id ID [--id ID ...] [--setup grep ...] [--model claude-haiku-5-5] [--reps 1] [--limit N] [--dry-run]` | End-to-end runs (see "End-to-end runs"). For each task of the recipe's repo that has `tests.json`: start Claude Code in the task's container, record its stream, its model requests (through the recording proxy) and its clocks, then grade its change with the grader of `grader-check`. One run at a time. The order is by repetition: all of repetition 1 first. Inside one task the setups take turns. A run that has `run.json` is skipped; a discarded run is done again, and its old folder is kept as `<rep>.discarded-<n>`. Only full model ids (no `haiku`, `sonnet`, `opus`). The setups `grep` and `tool` are built; `--setup grep --setup tool` gives both. `--dry-run` prints the runs and how many exist, and for `tool` whether the task's index exists (`index ok`, `index missing`, `index another commit`). Prints one line for each run on stderr. Exit code 4 at a usage limit (the batch stops and prints the reset time if the API gave one), 5 after three runs in a row that ended in an error. Needs Docker |
| `cmeval e2e index RECIPE --tasks FILE [--id ID ...] [--force]` | The codemem index of each valid task of the recipe's repo, for runs of the setup `tool`. For each task: make a git worktree of the base commit in `CMEVAL_HOME/e2e/indexes/<recipe>/<task id>/src/` if it does not exist, run `codemem index` on it into `index/` beside it, and write `index.json` (task id, repo, base commit, codemem commit, seconds, and the last line of codemem's output). A task is skipped when its `index.json` has the same base commit and the same codemem commit (with `-dirty` when codemem's `src/` has changes). `--force` builds again. A build always starts from an empty index folder; codemem's vector cache makes later builds of the same repo fast. One task at a time, because codemem uses the GPU. The program is `CMEVAL_CODEMEM_BIN`, or `.venv/bin/codemem` in the root of this repo. Prints one line for each task on stderr |
| `cmeval e2e score RUN_ID [--screen FILE ...] [--tasks FILE ...] [--facts FILE]` | Tables of an end-to-end run, from its `run.json` files. For each setup: runs, discarded runs, flagged runs, the share of completed runs, mean and median processed tokens and agent seconds, mean turns, and how the runs ended. A second table shows the search behaviour: mean content searches, file searches and files viewed, the share of runs that opened a gold file, the mean turn of the first gold open, the mean turns before the first edit, and, for a setup with codemem or when a run called codemem, the share of runs that called it, its mean calls, and the mean turn of the first call. With two setups: the paired difference for each task (mean over repetitions, then the mean over tasks) against `grep`. Writes `score.json` in the run folder. With `--screen` (see "The screen for unfair hidden tests"), the completion numbers count only the tasks that the screen calls fair, also in the paired difference; tokens, time, turns and behaviour keep every task. The output names the screen files and says how many tasks left the completion score, and why. A second line gives the conservative variant, a sensitivity number: completion over the fair tasks that had no "unfair" read at all. `--screen` needs `--tasks` (every task file of the run): each read is checked against the task and its facts as they are now, and a read of a changed or reopened task is not used. Without `--tasks` the command is refused, so a stale read never counts in a reported number |
| `cmeval e2e screen-pack RECIPE --tasks FILE --out DIR [--id ID ...] [--batches 1] [--facts FILE]` | The reading material of the screen. For each valid task of the recipe's repo (its `result.json` is valid and has the fingerprint of today's recipe and task, and its `tests.json` passes the grader's check): a folder `DIR/<task id>/` with `issue.txt`, `real-fix.patch`, `test.patch` and `packet.json` (difficulty, content hash, the files of the fix and of the test change, the two test lists with the first 200 names and a count for each test file or class, how the fail-to-pass tests did before the fix, the flag `fix_changes_only_tests`, and the task's `facts` from `--facts`, default `tasks/screen/facts.jsonl`). `DIR/index.json` lists the packets of the last call for each recipe, the tasks left out and why, and the candidates with tests per level (in the task file, validated, valid). `DIR/batches/<recipe>-<k>.txt` split the packets between `--batches` readers, with a mix of levels in each |
| `cmeval e2e screen-add OUTPUT --packets DIR --screen FILE --read N --reader LABEL [--batch FILE] [--date D] [--note TEXT] [--rules VERSION]` | Store a reader's verdicts as read N in a screen file (`tasks/screen/<name>.jsonl`). `OUTPUT` is the reader's JSON list (or JSON lines) in the format of `tasks/screen-rules-v1.md`. Every packet of the batch (`--batch`, else every packet of the index) must have exactly one verdict, with the packet's content hash. A read that the file already has, or a reader who already read the task, is refused. On any problem nothing is written. `--rules` names other rules than the packets' rules, for reads made under other instructions |
| `cmeval e2e screen-table --screen FILE [...] [--packets DIR ... \| --tasks FILE ... [--facts FILE]] [--need-repo 20] [--need-level easy=6,medium=8,hard=6] [--early-factor 1.25] [--floor-repo 12]` | Merge the reads and print a Markdown table for the work log: for each repo and each of the three levels, the valid tasks, kept (fair), removed (unfair), disagree, and not done (one read or none). Then the kept share by level, how read 1 and read 2 agree (raw share and Cohen's kappa), the tasks decided by a majority (for example 2 to 1), and the ids that need a third read. One warning line for each repo or level that runs short: an early warning below 1.25 times the need (25 per repo; levels 8, 10, 8), a stronger line below the need (20; 6, 8, 6), and, for a repo, a line below the plan's floor of 12. Each line gives the keep rate and what is missing: with `--packets`, in candidates to validate (divided by the validity rate of the packet index), else in valid tasks. With `--packets` the valid tasks and their hashes come from the packet index: a task with no read counts as not done, and a read of a changed task is left out. Without it, `--tasks` gives the hashes, with the facts. With neither, the table still prints, after a first line that says stale reads cannot be seen in this call |
| `cmeval e2e recount RUN_ID [--tasks FILE]` | Count the steps of each run of a run id again, from its `stream.jsonl`, with the rules of today (`src/cmeval/e2e_steps.py`, `STEPS_VERSION`). Writes the new `steps` into `run.json` and changes nothing else in the record. The gold files come from the record; a record made before they were stored needs the task file (`--tasks`). Prints one line for each run with the old and new content searches, files viewed, gold opened, first edit turn, first gold surfaced turn and steps version. `steps.steps_version` in each record says which rules made its counts |
| `cmeval e2e turns RUN_ID --id TASK [--setup S] [--rep 1] [--with RUN_ID2] [--format md\|csv\|json] [--width 100] [--tasks FILE]` | One table for one run, one row for each turn of the main agent, from `stream.jsonl`, `proxy.jsonl`, `run.json` and `clock.txt` of its folder. Columns: the turn; `start_s` (when its model request reached the proxy, from the start of the agent), `turn_s` (to the next turn's request, or to the end of the agent for the last turn: the answer and the tool calls), `model_s` (to the last byte of the answer); the input, output, cache read and cache write tokens of its request; its tools (`codemem.search_code` for codemem's search); the command, query or file of each call (cut to `--width`, several calls share it); the kinds of its actions as `e2e_steps` classes them, with today's rules; and `first` or `yes` when the turn surfaced, opened or edited a gold file (`first`: the first turn for a gold file). A turn and a request are matched by the id of the model's answer, which both files hold. A log without these ids is matched in order, only when the counts are equal; else no turn gets a request. The requests are those whose tokens the proxy's sums count; the ones that no turn matched (for example a subagent's) are the row `other requests`. The last row has the sums, and the last line says whether the token sums and the turns equal those of `run.json`. `RUN_ID` can be the path of a run id's folder. `--setup` is needed when the task has runs of several setups. `--rep 1.discarded-1` shows a discarded attempt. `--with RUN_ID2`, or two `--setup`, show two runs of the task side by side (start, tokens, tools, command and the gold marks S, O, E of each turn). `--tasks` gives the gold files when `run.json` does not hold them |
| `cmeval dashboard [--port 8765] [--open]` | A local web page with the live progress of long jobs (see "Watch a long job") |
| `cmeval proxy --log FILE [--host 127.0.0.1] [--port 8787] [--upstream URL] [--bodies DIR]` | A recording proxy for the model API, for end-to-end runs (see "Record the model requests of an agent") |
| `cmeval proxy-summary FILE` | Token sums, errors, and checks of a proxy log, as JSON |

## Record the model requests of an agent

An end-to-end run measures the tokens that the agent uses. The recording proxy sits between Claude Code and the API (`docs/plan/track-a-evals.md`, section 5):

```
cmeval proxy --log run.jsonl --port 8787
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 claude -p "..."
```

- The proxy sends each request to `--upstream` (default `https://api.anthropic.com`) and streams the answer back as it arrives. Headers and body go through unchanged. Only the hop-by-hop headers and `Host` change, and the proxy asks for an uncompressed answer (`accept-encoding: identity`).
- For each request it appends one JSON line to the log: the clocks (headers, first byte, end), the shape of the request (model, number of messages and tools), the API's `usage` block, the stop reason, `request-id`, the rate-limit headers, and an error's type and message. The fields are described at the top of `src/cmeval/proxy.py`.
- The log never holds a credential: only whether `Authorization` and `x-api-key` were present. It holds no bodies either. `--bodies DIR` writes each request and answer body to DIR, to debug a mismatch.
- Ctrl-C or SIGTERM stops the proxy and prints the summary. `cmeval proxy-summary FILE` prints it for any log: requests by path and status, token sums for `/v1/messages` (all models and each model), requests with no usage block, streams that did not end, errors (429 and 529 show a usage limit or an overload), and the first and last request time. `count_tokens` requests are counted apart and are not in the token sums.
- The runner uses the same proxy from Python: `with RecordingProxy(log) as proxy:` gives `proxy.url` on a free port. `cross_check(summarize(log), model_usage)` compares the sums with the `modelUsage` object of Claude Code's final `result` event, class by class, within 1%.

## End-to-end runs

**Validated once, checked again on the image that the runs use.** A task image can be removed after its validation to save disk, and built again with `cmeval generate --rebuild` before the runs. The new image is not validated again: `cmeval e2e grader-check` compares it test by test with the saved `tests.json`, and only this check counts. A task whose tests differ goes back to validation or leaves the completion score.

`cmeval e2e run` starts Claude Code on a real issue in the task's container and records completion, tokens and time (`docs/plan/track-a-evals.md`, sections 4 to 7). The machine needs:

- Docker, and the task images from `cmeval generate`. The runner makes the Docker network `cmeval-run` with `--internal` if it does not exist. A container on it reaches only the recording proxy, which listens on the network's gateway address on the host.
- A login token from `claude setup-token`, in `CMEVAL_HOME/secrets/claude-token` with mode 600 (or the file in `CMEVAL_CLAUDE_TOKEN_FILE`). The token goes to the container only through the environment of the Docker client. It is never written to a run's files; the runner replaces any copy that it finds there.
- The Claude Code binary for Linux. The default is the real path of `claude` on PATH; `CMEVAL_CLAUDE_BIN` gives another one. It is mounted read-only into the container.

In the container the runner removes `.claude/`, `CLAUDE.md`, `AGENTS.md` and `.mcp.json` from the checkout, makes a user that is not root, and starts Claude Code as that user with an empty settings folder and the flags of plan section 4.3. The limits are 50 minutes and 150 turns. The runner counts the turns in the stream and stops the agent after the limit. After the agent stops, its changes become `agent.patch`.

The files of one run go to `CMEVAL_HOME/e2e/runs/<run id>/<task id>/<setup>/<rep>/`:

| File | What it holds |
|---|---|
| `run.json` | The record: identity, how the run ended, integrity checks, tokens (proxy and agent), clocks, steps, outcome. The fields are described in `src/cmeval/e2e_run.py`. `steps` is what the agent did: its searches, views, edits and tests, the turns at which it first saw, opened and edited each gold file, and each Bash command with the kinds of its simple commands. Claude Code searches and reads through its Bash tool, so these counts come from the shell commands; the rules are in `src/cmeval/e2e_steps.py`, and its docstring defines each count in one line. From steps version 3: a search, a view or an edit is one of the repo under `/testbed` (a grep in a log in `/tmp` is `read_outside`, a script in `/tmp` is `write_outside`, `git checkout PATH` is a `revert`); a call that Claude Code blocked counts in `blocked_calls` and adds nothing else; a gold file is surfaced no later than it is opened |
| `stream.jsonl`, `stderr.txt` | Claude Code's events (`--output-format stream-json`) and its error output |
| `proxy.jsonl` | One line for each model request (see "Record the model requests of an agent") |
| `agent.patch` | The agent's changes against the task's commit, with new files |
| `grade/` | The grader's inputs, logs and `grade.json` |
| `prompt.txt`, `mcp.json`, `agent.sh` | What the container got |
| `clock.txt`, `prep.txt`, `removed.txt`, `after.txt` | The agent's start, end and exit code; the preparation marks; the removed configuration files; the count of changed files |

A run that hit a usage limit or failed the setup check (the first event of the stream must show the expected MCP servers, `bypassPermissions`, no API key, the requested model, and no web tools) is discarded: it is not graded, and the next batch does it again. For `grep` the agent must have no MCP server and no MCP tool. For `tool` it must have one MCP server, `codemem`, with the status `connected`, and the tool `mcp__codemem__search_code`.

The setup `tool` is the agent of `grep` plus codemem's MCP server, loaded before the first turn. The server runs inside the task's container, from the codemem installation of the host. The machine needs:

- codemem in a virtual environment: `uv sync` in the root of this repo makes `.venv/bin/codemem` (or set `CMEVAL_CODEMEM_BIN`). Its Python must be one that uv installed. The runner mounts the checkout and that Python into the container, read-only, at their own paths.
- codemem's embedding model in the Hugging Face cache (`~/.cache/huggingface`, or `HF_HOME`). The container gets it read-only at `/hf`, and has no internet.
- A GPU that Docker can give to a container (`docker run --device nvidia.com/gpu=all`: the NVIDIA container toolkit, and a CDI spec from `nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`). The index is tied to the device and number type of the model that built it. An index built on the GPU is `float16|cuda`; when codemem opens it on the CPU, it embeds every text again, which takes hours. The runner gives the GPU to the containers of every setup, so that the setups differ only in the tool. `CMEVAL_E2E_GPUS=0` turns this off, for example on a Mac; then `tool` cannot run.
- The index of each task, from `cmeval e2e index`. Each run copies the index to `cmindex/` in its folder and mounts the copy at `/cmindex`, writable, because codemem updates it when the agent edits files. After the run the runner records the size of the copy and deletes it.

The runner sets two things in codemem's environment, so that a run does not depend on where it happens:

- `CODEMEM_VECTOR_BACKEND=faiss`, for the build of an index (`cmeval e2e index`) and for the server of every run: the exact search index in both places. Left to itself, codemem picks the search index by the memory of the place it runs in. The build runs on the host with all its memory; a run's container has 16 GB, where codemem picks the compact index above 185,000 vectors. Such a run would rebuild the search index at its start, for tens of seconds on a large repo, and the agent's searches in that time get keyword results only, with a note that says so.
- `CODEMEM_MODEL_IDLE_MINUTES=0`, for the server of a run: the embedding model stays in memory for the whole run.

codemem's tool texts have three steering levels (`none`, `light`, `strong`) that say how hard they push the agent to codemem. Set `CMEVAL_CODEMEM_STEERING` to use one of them for a batch; when it is not set, codemem uses its default. Do not mix levels in one run ID.

`run.json` of a `tool` run records the codemem commit, the program, the task's `index.json`, the steering level and the index size before and after the run (`identity.codemem`). `outcome.unexpected_paths` lists files of the agent's patch such as `.codemem*` or `.mcp.json`, which codemem should never write.

### Prompt levels

A run gives the agent the issue as written (level L0) unless the batch names another level. L1 is the same content with the names removed (no paths, identifiers, traces or code). L2 is a short request in a user's voice. A prompt can end with one short "Done when:" line, only to name something new that the tests call and a user would name (rules: `tasks/vague-rules-v3.md`). Tasks whose hidden tests need more than that are not in the vague set.

```
cmeval e2e run pandas --tasks tasks/e2e/pandas.jsonl --run-id vague-b7-l1 --setup tool \
    --prompt-level L1 --prompts tasks/vague-b7-v3.jsonl
```

`vague-b7-v3.jsonl` holds the 45 pandas and playwright tasks that the screen calls fair. Its `.meta.json` names the rules and the review that changed 13 rows of `vague-b7-v2.jsonl` (`vague-b7-v3.changes.md` gives each change), and lists for each task the words of its L2 text that are also in the path of a gold file (`l2_words_in_gold_paths`), so that results can be shown with and without those tasks. `vague-pilot18-v2.jsonl` holds 10 of the 18 pilot tasks; its `.meta.json` gives the reason for each removed task. `vague-pilot18-v1.jsonl` is kept only because the runs `vague-l1-1` and `vague-l2-1` used it: its "Done when" lines state what the hidden tests check, so completion with it is not comparable with L0.

The prompts file has one JSON object per line: `id`, `level`, `prompt`. A valid task with no prompt of the level is skipped, with a note. `run.json` records the level and the file's name and hash (`identity.prompt_level`, `identity.prompt_source`). Use one level per run ID: a batch does not run a task again that the run ID already holds.

### The screen for unfair hidden tests

A valid task can still be unfair: a correct, general fix made from the issue alone does not pass all its hidden tests (for example, a test asserts an internal limit that the issue does not give). Such a task leaves the completion score and stays in the search measures (team decision, 2026-11-26). The screen asks one question for each task: "does a correct, general fix made from the issue alone pass all hidden tests?". Two independent readers answer it. The readers are model sessions that the person who runs the eval starts; cmeval calls no model. The steps:

```
cmeval e2e screen-pack pandas --tasks tasks/fresh-v1.jsonl --out ~/screen/batch-1 --batches 2
# each reader gets tasks/screen-rules-v1.md, a batch file and the packet folders, and writes a JSON list
cmeval e2e screen-add reader-a.json --packets ~/screen/batch-1 --batch ~/screen/batch-1/batches/pandas-1.txt \
    --screen tasks/screen/batch-1.jsonl --read 1 --reader "reader-a"
cmeval e2e screen-table --screen tasks/screen/batch-1.jsonl --packets ~/screen/batch-1
cmeval e2e score RUN_ID --screen tasks/screen/batch-1.jsonl --tasks tasks/fresh-v1.jsonl
```

A screen file has one JSON row for each task and read; rows are only appended. Each row holds the verdict (`fair`, `kinds` of unfairness, `deciding_assertions`, `reason`, `confidence`), the read number, the reader label, the rules version, the date, and `content_hash`: a hash of the issue, the real fix, the test change and the task's facts, as the reader read them. The fields and the merge rule are in `src/cmeval/e2e_screen.py`. A task is fair when all its reads (at least two) say fair, and unfair when all say unfair. Two reads that do not agree give "disagree": the task needs a third read, and then the strict majority decides. Only a fair task counts in the completion score.

A fact is the result of a check that was run for a task, for example how the version that the issue names as the reference behaves on the hidden test's cases. Facts are in `tasks/screen/facts.jsonl`, one JSON row per fact: `id`, `fact`, `date`, `source`. A fact never holds agent results, pass or fail counts of runs, or verdicts.

**Reopening a task.** New facts or run evidence, in either direction, may reopen a decided task. Then:
1. The evidence becomes a fact in `tasks/screen/facts.jsonl`. The fact goes into the task's packet and into its content hash, so the earlier reads of the task become stale and no longer count.
2. Make the packet again, and get fresh reads (two, as for any task). They decide.
3. A reader never gets transcripts of agent runs, pass or fail counts, or earlier verdicts. Only the packet.
4. Log every reopened task: the task, the fact, why it was reopened, and the result of the fresh reads.

`tasks/screen/pilot18.jsonl` holds the two reads of the 18 valid pilot tasks (2026-11-25, made by hand before this step existed, under rules version `pilot-2026-11-25`): 9 fair, 9 not; pandas keeps 4 of 10, playwright 5 of 8. pandas 70742 was reopened on 2026-11-26 by a fact about its reference version: with `--tasks`, its two reads are stale, and 17 tasks are decided (8 fair, 9 not; pandas keeps 3 of 9 decided).

### Diagnostic runs

Two environment variables are for diagnostic batches. A run made with either is not comparable with other runs; `run.json` records them in `identity.diagnostic`. Use a run ID of its own.

- `CMEVAL_E2E_DIAG_ARGS`: extra arguments for `claude`. `--thinking-display summarized` puts a summary of the model's thinking in `stream.jsonl`; without it a headless run gets thinking blocks with no text.
- `CMEVAL_E2E_BODIES=1`: the proxy writes every request and answer body to `bodies/` in the run folder. This shows the system prompt and the tool texts as the model got them. The files are large, because each request repeats the conversation.

## Watch a long job

`run`, `score`, `collect`, and `repo-stats` can take minutes to hours. To watch them, start the dashboard in a second terminal:

```
cmeval dashboard --open
```

The page at `http://127.0.0.1:8765/` shows each running job: its stage, a progress bar, the speed, the time left, one bar for each repo, and the last log lines. Below it is a list of the jobs that finished. The page asks for new data every 2 seconds.

- Each job writes one status file in `CMEVAL_HOME/status/` every 2 seconds. The newest 20 finished files are kept.
- The dashboard only reads these files. It cannot change or stop a job. It listens on 127.0.0.1 only.
- A job shows as "stopped" when its process is gone or it has not written for 60 seconds (for example after `kill -9`, or when the machine sleeps). A job that spends more than 60 seconds in one call of a C library that holds Python's lock could also show as "stopped" until the call ends.
- The page answers only to the names 127.0.0.1 and localhost, so a web page from another site cannot read it.
- A failed status write never stops a job. The run files (`meta.json` and the results) stay the record.
- Jobs started from a cmeval commit before the dashboard write no status file, so they do not show.

## Systems (the plug)

Every retrieval system plugs in through one interface, `Retriever` in `src/cmeval/retriever.py`:

| Method | Does |
|---|---|
| `build(repo, index_dir)` | Full index of the repo at its current commit. Returns an `IndexReport` (time, size, items). |
| `update(repo, index_dir)` | Bring the index up to date after the repo moved. Must give the same results as `build`. |
| `search(query, k)` | At most k `Hit`s, best first. |
| `describe()` | Everything needed to repeat a run (versions, models, device, settings). |
| `index_key()` | Hash of index-time settings. Systems with the same key share one index. |

A `Hit` is a location, never a system's own ID: `path`, `start_line`, `end_line`, `symbol`, `score`, and `text` (exactly what an agent would see; token metrics count it). Each system declares its `granularity`: `"file"` (paths only) or `"line"` (line ranges on every hit).

Systems are listed in TOML configs in `configs/`. Every key except `name` and `adapter` goes to the adapter:

```toml
[[system]]
name = "fake-line"
adapter = "fake"
```

| Adapter | Status |
|---|---|
| `fake` | Test and dry-run stand-in (`src/cmeval/adapters/fake.py`) |
| `grep` | Offline grep baseline: ripgrep over keywords from the issue, files ranked by match count (`src/cmeval/adapters/grep.py`). Granularity `file`. Needs `rg` (`brew install ripgrep`). |
| `grep_fn` | grep plus the next step an agent takes: each matching line is mapped to the function around it, functions ranked by matches (`grep_fn.py`). Granularity `line`. |
| `codemem` | Wilson's codemem through its library API (`src/cmeval/adapters/codemem.py`, the only file that imports codemem). Granularity `line`. Settings: `signals` (for example `["bm25", "code", "usage"]`) and `config` (passed to codemem's `config_from_dict`; user config files and env vars are ignored). Systems with the same index-time settings share one index and one in-memory service. Needs `uv sync --extra codemem`. |

To add a system: write a class with the methods above in `src/cmeval/adapters/`, and add one line to `ADAPTERS` in `src/cmeval/systems.py`.

## Run files

`cmeval run` writes `CMEVAL_HOME/runs/<run-id>/`:

| File | Content |
|---|---|
| `meta.json` | Inputs with sha256 hashes, settings, each system's `describe()` and `index_key`, machine, start and end time, status |
| `<system>.jsonl` | One line for each task: `task_id`, `commit`, `search_ms`, `hits` (each hit with its text) |
| `index.jsonl` | One line for each index build or update: repo, commit, system, `index_key`, mode, `IndexReport` |

How a run works:
- Tasks are sorted by the commit date of their `base_commit`. For each repo, one worktree steps forward from task to task.
- Systems with the same `index_key` share one index: the first system of the group builds it once, then updates it at each next commit. `--index-mode rebuild` builds it again for every task.
- Before each search, the runner checks that the worktree is at the task's exact `base_commit`.
- The first search of each system is an untimed warm-up (it may load a model).
- A stopped run continues where it stopped: run the same command again. Changing the tasks file, the config, the split, the index mode, or k under the same run id is refused.
- `--split` is `dev` by default. Use `--split test` only for reported results.

## Metrics

`cmeval score` writes `scores.jsonl` (one row for each task, system, level, IoU, and metric), `summary.csv` (means), and `score-meta.json` into the run folder. It only reads the run files, so scoring can change without new searches.

**Levels.** File, class, and function.
- File level: a hit finds a gold file if the paths are equal; ranks are over unique paths.
- Class and function level: a hit finds a gold item if it is in the same file and either lies inside the gold range or overlaps it with line IoU (shared lines / covered lines) of 0.5 or more. Ranks are over raw hits. Scores at IoU 0.3 and 0.7 are also written, as a sensitivity check.
- Each gold item counts once, at its first matching hit.
- Left out (a row with the reason, never a 0): file-granularity systems at class and function level (n/a), tasks with `partial_labels`, and tasks with no gold at that level.

**Accuracy.** `recall@k`, `precision@k` (relevant positions in the top k / k), `success@k` (all gold in the top k), and `mrr`, for k = 1, 5, 10, 20, 50.

**Tokens.** Counted with Anthropic's `count_tokens` for the agent-study model (`DEFAULT_MODEL` in `src/cmeval/metrics/tokens.py`), on each hit's `text` only (the fixed request overhead is measured and subtracted). Counts are cached in `CMEVAL_HOME/token-cache/` by text hash. The API key comes from `ANTHROPIC_API_KEY` or, on macOS, the Keychain entry `anthropic-api-key`. Requests are paced to at most 3,000 per minute (`CMEVAL_TOKEN_RPM`). With 4 workers the real speed is about 1,700 per minute. For a key with a low limit (some accounts allow only 100 per minute), set `CMEVAL_TOKEN_RPM=90`. Without a key, scoring stops with a clear message. `--tokens estimate` gives rough numbers that are marked and must never be reported.
- `tokens_to_first`: tokens of all hits up to and including the first hit that finds gold (`found` = 0 or 1).
- `recall@budget<B>` for B = 500 to 8000: recall of the whole hits that fit in B tokens.

**Latency.** Search time (median, 95th percentile) and index cost (build, update, items re-embedded, size, most files that failed in one index report) of each system's index group.

Scoring uses only tasks that every system in the run finished, so all systems are compared on the same tasks. A run that is not `done`, or left-out tasks, give a warning.

## Runs on other machines

A run can be made on one machine and scored on another (for example a Windows laptop with an NVIDIA GPU, scored on a Mac that has the token cache and the API key):

1. On the other machine, clone this repo with `git clone -c core.autocrlf=false ...` (cmeval sets the same option on its own repo clones), so task files and checkouts keep Unix line endings and the task file has the same sha256.
2. Run `cmeval run ...` there, and copy the run folder (`CMEVAL_HOME/runs/<run-id>/`) to the scoring machine.
3. Score it with `cmeval score <run-id> --tasks tasks/<file>.jsonl`. The file must have the same sha256 as the run's.

Compare systems only within one machine: GPU and CPU round slightly differently, so embedding results can change a little between machines.

## Local data

Large data (repo clones, snapshots, indexes, raw runs, token cache, GitHub API cache, job status files) lives in `CMEVAL_HOME`, default `~/.cmeval/`. It is not part of git.
