# Final pass on the plan: five languages first, a soft and a hard deadline, Java as a bonus

- **Track:** shared: for everyone to read
- **Who:** Andre, with Claude Code
- **When:** 2026-11-23 03:39 UTC
- **Work package:** none: planning
- **Branch, commits, pull request:** `main`. The edits to `docs/plan/` are in Andre's working tree, for him to commit with the earlier ones

## Done

- **The deadline has two parts.** Nov 30, 23:59 is the freeze we aim for, and it is soft. The hard
  limit is the presentation on Dec 1 at 14:00. The morning of Dec 1 is for preparing the
  presentation, not for runs.
- **Five languages come first in the repo order** (track A §8.3): pandas (Python), playwright
  (TypeScript), ruff (Rust), kubernetes (Go), duckdb (C++). Then home-assistant and vscode,
  then airflow and vllm. The entry that follows this one says why the C++ repo is duckdb.
- **Java is a bonus,** in all three tracks. It has no date.
- **Search beyond code** (PDFs, documents, everything on a computer) is future work, with no
  date.
- **Tracks B and C work at the same time** (overview §6). Two things are settled between them on
  Nov 23: the vector store interface, and which vectors exist.
- **Which open models run in the model gap** is settled by Andrew with Andre. The plan's order
  (9B, 27B, 14B) is the starting point.

## Checked

- Every section reference in the four plan files points to a heading that exists (checked by
  script). Tables, code fences and links were checked as well.
- Nothing was run.

## Left

Nothing.

## Blocked on, or needed from others

Nothing.

## Next

- Andrew: the recipes in the new order. duckdb comes after kubernetes.
