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
| `cmeval report RUN [--baseline grep-fn-plus] [--split dev\|test] [--cutoff DATE] [--tasks FILE] [--where KEY=VALUE ...]` | Write `report.md` for a scored run: tables, intervals, paired tests, and groups (repo, language, issue date, identifier in query, gold all Python, repo size, fix size, gold files). `--where` keeps only the tasks whose tag has that value; the main comparison on fresh tasks uses `--where gold_all_python=true` (codemem reads only Python). The tasks left out get their own section. The primary tests use `cm3-bm25`, `cm3-bm25-code`, and `cm3-full` (codemem v3); for an MVP run, name its systems with `--primary cm-bm25 --primary cm-bm25-code --primary cm-bm25-code-usage`. A run with no codemem system has no primary tests. |
| `cmeval merge BASE EXTRA --run-id ID [--system S ...]` | Copy systems of one run into a copy of another run, for one report |
| `cmeval compare RUN_A RUN_B [--tasks FILE]` | Update vs. rebuild check: compare two scored runs of the same tasks |
| `cmeval dashboard [--port 8765] [--open]` | A local web page with the live progress of long jobs (see "Watch a long job") |

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
