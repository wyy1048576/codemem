# cmeval

Evaluation suite for repository-level code retrieval. It measures how well a search system finds the code that a real bug fix changed: accuracy (file, class, and function level), token cost, and latency.

cmeval works like a benchmark. Each search system (grep, codemem, or any other tool) plugs in through one small interface. cmeval does not depend on codemem, and codemem never imports cmeval.

## Install

```bash
cd eval
uv sync
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

Gold labels come from `src/cmeval/labels.py`: the files, classes, and functions that the fix changed, found with tree-sitter on the code at `base_commit`.

## Commands

| Command | Status |
|---|---|
| `cmeval validate FILE` | Check a task file and print counts by source, split, and repo |
| `cmeval import swebench-verified [--n 50] [--seed 0]` | Sample and label SWE-bench Verified tasks (pinned dataset revision) |
| `cmeval systems FILE` | Check a system config and list its systems (adapter, granularity, index key) |
| `cmeval collect` | Not built yet |
| `cmeval review` | Not built yet |
| `cmeval run` | Not built yet |
| `cmeval score` | Not built yet |
| `cmeval report` | Not built yet |

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
| `codemem` | Not built yet |

To add a system: write a class with the methods above in `src/cmeval/adapters/`, and add one line to `ADAPTERS` in `src/cmeval/systems.py`.

## Local data

Large data (repo clones, snapshots, indexes, raw runs, token cache) lives in `CMEVAL_HOME`, default `~/.cmeval/`. It is not part of git.
