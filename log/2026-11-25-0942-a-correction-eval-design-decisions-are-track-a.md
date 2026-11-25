# Correction: the three eval design questions are track A's to decide, not questions for Andre

- **Track:** A. It corrects two entries of 2026-11-25: "two questions for Andre" (09:00) and "the first agent runs work end to end" (its section "Blocked on, or needed from others")
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-25 09:42 UTC
- **Work package:** A1
- **Branch, commits, pull request:** none

## Done

- **The three questions are withdrawn as questions.** The prompt frame, which of Claude Code's own
  tools stay on, and ripgrep in the task images are parts of the design of the eval. Track A owns
  the eval pipeline, so Andrew decides them. The earlier entries put them to Andre. That was this
  agent's mistake, not Andrew's instruction.
- **Nobody needs to answer them.** The decisions will be posted here when Andrew has made them,
  with their reasons, before the main batch. Views on them are welcome, as on any decision that
  changes every number.

## Checked

- Nothing was run for this entry. The facts in the two earlier entries stand: the tool list of
  Claude Code 2.1.332, the cost of an empty run, the missing ripgrep in the images.

## Left

- The three decisions.

## Blocked on, or needed from others

What track A does ask of the others, and only this:

- **Wilson:** the `codemem-today` tag. For the `tool` setup: the tool names, and the wording
  that ships (plan §4.1: the wording is track B's).
- **Andre and Wilson, if you have time:** a recipe for ruff, kubernetes or duckdb
  (`eval/envs/`, then `cmeval generate <repo> --admission`). This is a request for help.

## Next

- As in the entry before this one.
