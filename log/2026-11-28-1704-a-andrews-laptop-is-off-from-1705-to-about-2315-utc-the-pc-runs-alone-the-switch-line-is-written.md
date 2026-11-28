# Track A: Andrew's laptop is off from 17:05 to about 23:15 UTC; the PC runs alone; the switch line is written (duckdb, kubernetes and vscode start with the new step)

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 17:04 UTC
- **Work package:** A12 (the runs)
- **Branch, commits, pull request:** none. Old step: eval `739fbe3`. New step: eval `a2a0932` (#94). codemem `463171c`

## Done

**1. Nobody of track A reads this log from 17:05 to about 23:15 UTC.** Andrew drives, and his laptop is off. The PC goes on alone: two runners, the watchdog every 5 minutes, the guards, the copy of the records to D:. We read every entry when the laptop is on again, before we write.

**2. The switch line is written (17:03 UTC), as your entry of 15:10 UTC rules.** Andrew left it to us before he went, with our recommendation of yes.

- `~/.cmeval/queue/checkout` on the PC has three lines: duckdb, kubernetes and vscode take the checkout `codemem-runs3` (eval `a2a0932`), for every model.
- Checked with dry runs of the live launcher: the batches of duckdb's hard tasks, duckdb and kubernetes take `codemem-runs3`; playwright's batches take `codemem-runs` (`739fbe3`).
- **The first unit on the new step is Haiku's duckdb** (stream 1, after ruff, about 22:30 UTC). kubernetes follows in stream 2 after playwright.
- We check the first records when we are back: `prep_steps_s` has `copy_swap` and `sync`, no `git_busy`, no `copy_differs`; `cmeval_commit` is `a2a0932`.
- **If the new step fails in a real batch:** three runs in a row that end in an error stop the batch, the runner tries the step once more and then passes it over. After two steps in a row it holds the stream. No record is lost. The other stream goes on.

**3. Ready, not installed: the launcher for repetitions 2 and 3 and for the checkout per repo, model and repetition.** Tested with dry runs. A batch of repetition 2 does not start while a run of repetition 1 is not done, so no run of repetition 1 can get the new step. We install it after the drive.

**4. State at 17:03 UTC.**

- Stream 1: ruff, part a, level L1, old step.
- Stream 2: playwright's 13 tasks, level L0, since 16:49 UTC, old step. Its 13 images needed three load tries (30 minutes of waits); no run started before all were in Docker.
- Builds: the vscode validation goes on.
- **Disk: the margin is thin until ruff's part a ends (about 21:00 UTC).** The disk file is at 401 GB; its guard is at 420 GB. If the guard fires, it stops both streams and the builds, and nothing starts again before a person looks. That would cost the hours until about 23:15 UTC. No record would be lost.

## Left

- The check of the first records on the new step.
- The reports of ruff and playwright.

## Blocked on, or needed from others

- None.

## Next

- About 23:15 UTC: read this log, both stream logs and the restart log; report what finished.
