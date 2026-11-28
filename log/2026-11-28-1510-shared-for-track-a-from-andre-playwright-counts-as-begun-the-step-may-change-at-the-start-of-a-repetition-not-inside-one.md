# For track A, from Andre: playwright counts as begun and keeps the old step. The step may change at the start of a repetition, not inside one

- **Track:** shared: from the lead, for track A. Answers your entry of 14:28 UTC, points 5.3 and 6. Replaces point 2 of our entry of 12:54 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 15:10 UTC
- **Work package:** A12 (the runs)
- **Branch, commits, pull request:** none. The new step is `main` at `a2a0932` (#94)

## Done

**1. playwright counts as begun** (Andre). Its repetition 1 keeps the old step, for Haiku and for Sonnet: the check run made records of both with it. That is what you do already.

**2. The step may change at the start of a repetition, not inside one** (Andre).

- **The unit is a repo, a model and a repetition.** A unit that has begun keeps its method. A unit that has not begun starts with the new step.
- **Stay on the old step:**
  - Haiku's repetition 1 of pandas, ruff, home-assistant and playwright;
  - Sonnet's repetition 1 of pandas and playwright, which began in the check run.
- **Start with the new step:**
  - Haiku's repetitions 2 and 3 of every repo;
  - duckdb, kubernetes and vscode from their first run, for every model;
  - Sonnet's duckdb and kubernetes;
  - Opus.
- **Andre's reasons:**
  - By your count, the difference can reach the agent in about 1 run of 150, as one number in a folder line.
  - The 25 stream hours are needed for repetition 2.

**3. In every report, name the method of each repetition.** A record names its own already (`prep_steps_s`, `cmeval_commit`).

## Left

- None.

## Blocked on, or needed from others

- None. The switch itself stays yours to make, as in our entry of 12:51 UTC.

## Next

- None from this entry.
