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

Python 3.11 or later.

## Tasks

A task is one GitHub issue (the query), one repo snapshot (`base_commit`), and the gold answer: the files, classes, and functions that the real fix changed. Task files are JSON lines in `tasks/`, one task for each line. The schema and its rules are in `src/cmeval/tasks.py`.

Every task has a `split`:
- `dev`: for building and tuning. All SWE-bench Verified tasks and 20% of fresh tasks.
- `test`: for reported results only. The other 80% of fresh tasks. Do not tune on it.

The split of a fresh task comes from a hash of its ID, so it never changes.

## Commands

| Command | Status |
|---|---|
| `cmeval validate FILE` | Check a task file and print counts by source, split, and repo |
| `cmeval import` | Not built yet |
| `cmeval collect` | Not built yet |
| `cmeval review` | Not built yet |
| `cmeval run` | Not built yet |
| `cmeval score` | Not built yet |
| `cmeval report` | Not built yet |

## Local data

Large data (repo clones, snapshots, indexes, raw runs, token cache) lives in `CMEVAL_HOME`, default `~/.cmeval/`. It is not part of git.
