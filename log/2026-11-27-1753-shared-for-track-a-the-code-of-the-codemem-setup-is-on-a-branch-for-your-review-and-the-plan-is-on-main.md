# For track A: the code of the `codemem` setup is on a branch for your review, and the plan is on main

- **Track:** shared: from the lead, for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 17:53 UTC
- **Work package:** A6 (the setups), A12 (the runs)
- **Branch, commits, pull request:** `andre/eval-codemem-block` at `f79208b` (two commits on `main` at `c03262b`). Not merged: it is your code, so the review and the merge are yours and Andrew's. The plan is merged: #75

## Done

**1. The plan is on `main`** (#75): `docs/plan/runs.md` with two setups, `grep` and `codemem`, the repos and the order of our entry of 17:16 UTC, and the dates. Work from `main` now.

**2. The code that puts codemem's results into the first message is written,** on the branch above, so that you only have to review it, try it once and merge it. It has not been run in a container.

- **`cmeval e2e block <recipe> --tasks FILE [--sample FILE] [--prompts FILE] [--prompt-level L0|L1|L2] [--id ID] [--force]`** makes the block of each task and level before the runs: one `codemem search --json` on the task's index, the prompt text of that level as the query, 20 results. It writes `block-<level>.json` beside the task's index and skips a block that a run can use.
- **Two setups in `SETUPS`:** `codemem` (today's `tool` plus the block) and `upfront` (`grep` plus the block, for a side sample later; it gets no runs now). `grep` and `tool` do not change.
- **The first message** is the block, one empty line, then the prompt as the other setups send it.
- **Never without the block:** a run stops before its folder is made when its block is missing, empty, made without the embedding model, made from another prompt text, or changed since. A batch does not start while a block of one of its tasks cannot be used.
- **The record:** `identity.block` (the file, the sha256, the lines, the seconds, `searches_made_for_agent: 1`, the rank of the first result in a gold file and on a gold function, the results) and `integrity.block_in_first_message`.
- **The counts:** in a run with a block, the search made for the agent is one codemem search at turn 0. `codemem_calls` is one more than the agent's own calls, and a gold file in the block is surfaced at turn 0. Without a block nothing changes.

**3. What to check on the first real run, please.**

1. **`opens_with_text` in `proxy.jsonl`.** The proxy says of each request whether its first user message begins with the block. On our Mac, Claude Code puts the prompt in the third text block of the first user message, and the check finds it there. If your container's Claude Code sends it differently, every run with a block gets the flag "block not in the first message", and flagged runs leave the tables. Look at this in the first `codemem` run before the check run goes on.
2. **A real `codemem search --json` on a real index:** its timings must hold a key that starts with `embed_query:` (the block is refused otherwise), and its results should be those of `search_code` for the same query.
3. **The seconds of a block** are those of one cold command, so they hold the load of the model: 8 to 11 seconds each on our Mac. For the check run that is 12 blocks.

**4. Two questions for you.**

- With the search made for the agent counted, the score's columns "used" and "1st call" no longer say whether the agent itself called codemem in `codemem` runs. Its own calls are `codemem_calls` minus `searches_made_for_agent`. Do you want a column of its own?
- The mount of the codemem checkout in the containers (our entry of 15:13 UTC, point 1) applies to `codemem` as it does to `tool`. This branch does not touch it.

## Checked

- `eval/tests` on the branch: 927 passed, 20 skipped (on `main`: 909 passed, 20 skipped). No model, no index and no container was used.
- `grep` and `tool`: the prompt, the proxy's log lines and the counts are the same as before, by test.
- The first user message of Claude Code in 60 saved sessions on our Mac: three text blocks, the block in the third.

## Left

Nothing on our side until you have tried it.

## Blocked on, or needed from others

- **Track A:** your review of the branch, one real run with it, and your report before 17:00 Pacific (our entry of 16:38 UTC).

## Next

We answer your review here.
