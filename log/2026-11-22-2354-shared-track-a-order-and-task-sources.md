# Track A's plan: our own tasks are the main source, and the order of work is fixed

- **Track:** shared: a plan change that concerns track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-22 23:54 UTC
- **Work package:** none: planning. It moves A9 to the front
- **Branch, commits, pull request:** `main`. The edits to `docs/plan/` and `CONTRIBUTING.md` are in Andre's working tree, for him to commit

## Done

- **The order of work in track A** (top of `track-a-evals.md`):
  1. the eval set-up: our own tasks, and the pipeline that runs them;
  2. the first end-to-end test, on two repos with today's codemem;
  3. the main comparison, once tracks B and C deliver the improved codemem;
  4. afterwards, the model gap with open models in open harnesses.
- **Task sources, §8 rewritten.** Our own generated tasks are the main source. SWE-bench-Live is
  an add-on: a control while the pipeline is built, and an outside check.
- **One recipe per repo** (§8.2) replaces an agent that builds every environment. No extra model
  key is needed.
- **The repo order** (§8.3): pandas, playwright, home-assistant, vscode, ruff, kubernetes,
  airflow, vllm, llama.cpp, kafka. The first two are the first end-to-end test.
- **Counted from `eval/tasks/`:** of 3,788 collected tasks, about 2,550 come with tests. Godot has
  7 and duckdb 9, so those two stay in the retrieval eval only.

## Checked

- The counts per repo were computed from the task files on Nov 22 (the `has_test_patch` tag, and
  the difficulty rule of track A §10).
- How hard each repo's environment is to build is an expectation. No recipe has been written or
  run. The admission check of §8.2 decides.
- ruff, kubernetes and kafka are not collected yet, so their numbers are unknown.

## Left

- Recipes for every repo, and the build and validate steps of the generator.
- A file-level labeler for Rust, Go and Java.
- The collected tasks stop at 5 code files and 200 lines, and almost none adds a new file. Larger
  changes need a second collection pass with a higher limit.

## Blocked on, or needed from others

Nothing.

## Next

- Andrew: run the admission check on pandas and playwright (track A §8.2), then generate their
  tasks and build the pipeline skeleton beside it.
