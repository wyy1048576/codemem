# Second screen agrees on all 18 tasks (9 fair, 9 not); results of the vague-prompt runs

- **Track:** A. Answers Andre's entries of 2026-11-26 02:17 and 02:26
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-26 03:31 UTC
- **Work package:** A2 (task filters), A8 (vague prompts)
- **Branch, commits, pull request:** `main` at `bdd58d5`; no new commit

## Done

**1. The second screen.** A second Opus session screened the 18 pilot tasks without access to
the first verdicts. Question: does a correct, general fix made from the issue alone pass all
hidden tests? Both screens give the same answer on all 18 tasks.

**A correction to our entry of 02:05:** 9 tasks are unfair with the issue as written, not 8.
Playwright 42672 is the ninth: its tests pass a new setting value by name, which the issue does
not give. It stays in the vague prompt set, because one short line can name that value. Under
the decision of 02:17 it leaves the completion score like the other 8.

**2. The table that Andre asked for** (difficulty = size of the real fix, as in the plan):

| Repo | Difficulty | Validated | Kept | Removed |
|---|---|---|---|---|
| pandas | easy | 3 | 2 | 1 |
| pandas | medium | 4 | 1 | 3 |
| pandas | hard | 3 | 1 | 2 |
| pandas | all | 10 | 4 | 6 |
| playwright | easy | 2 | 1 | 1 |
| playwright | medium | 3 | 2 | 1 |
| playwright | hard | 3 | 2 | 1 |
| playwright | all | 8 | 5 | 3 |
| both | all | 18 | 9 | 9 |

- **By difficulty, both repos:** easy 3 of 5 kept, medium 3 of 7, hard 3 of 6. No tilt to easy
  tasks that 18 tasks can show.
- **Warning, as asked:** pandas keeps 4 of 10. At that rate, 60 validated candidates give about
  24 pandas tasks, close to the 20 that the matrix needs, with about 8 per level and no reserve.
  Playwright keeps 5 of 8, about 37 of 60. The rates rest on 10 and 8 tasks, so they are rough.
  The validation of 60 candidates per repo has not started.

**3. The runs of tonight** (Haiku, setup `tool`, codemem `041124e`, one repetition, 54 runs,
none discarded; thinking summaries on, so these are diagnostic runs):

| Prompt | Completed | Runs that called codemem |
|---|---|---|
| L0, the issue as written | 7 of 18 | 8 of 18 |
| L1, version 1 texts | 15 of 18 | 15 of 18 |
| L2, version 1 texts | 18 of 18 | 17 of 18 |

- **For Wilson, adoption:** on the 5 tasks whose prompt has no "Done when" line at any level,
  codemem was called in 1 of 5 runs at L0 and in 5 of 5 at L1 and at L2. With no code name in
  the prompt the agent has nothing to grep for, and it starts with codemem.
- **Still one call per run.** Every run that used codemem made one `search_code` call in its
  first three turns and then used grep (3 to 47 content searches). No run made a second call.
  The queries are plain-word descriptions. In the runs we sampled, the thinking after the call
  is already about the right function.
- **The runs agree with the screen.** The 9 unfair tasks: 0 of 9 completed at L0. The 9 fair
  tasks: 7 of 9. Completion at L1 and L2 with version 1 is not a result (the lines state what
  the tests check).
- Mean tokens per run rise with vagueness: 0.98 M, 1.44 M, 2.67 M.

## Checked

- Both screens are reads by a model; no test was run for them. They agree 18 of 18.
- The counts are from `cmeval e2e score` and from the tool calls in each run's stream.
- Not checked: a baseline arm at L1 and L2. These runs show behaviour, not benefit.

## Left

- 10 runs with the version 2 prompts are in progress (the 5 tasks whose prompt changed).
- The second screen's verdicts are not in the repo yet (`vague-pilot18-v2.meta.json`).
- A screen step in the task pipeline, so that each validated batch gets these marks.

## Blocked on, or needed from others

- Nothing.

## Next

- Track A: the results of the 10 runs; then the screen as a pipeline step, and Andrew's go for
  the validation of 60 candidates per repo.
