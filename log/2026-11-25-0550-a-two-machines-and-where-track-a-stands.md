# Track A: both machines are ready, the split of repos, and where we stand against the run sheet

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-25 05:50 UTC
- **Work package:** none yet: this is the start of A9 and A1
- **Branch, commits, pull request:** none. Pull request #19 is closed, because `3d9f42b` includes it

## Done

- **The PC is reachable from the Mac.** SSH over the tailnet works with a key, and commands run
  inside Ubuntu from the Mac session. This closes the "SSH is not tested" point of the entry of
  2026-11-24 23:41.
- **One session drives both machines.** The Mac session starts the PC's jobs over SSH, inside
  `tmux`. There is no second agent on the PC that the others need to follow.
- **The split, to start:** pandas is validated and run on the PC. playwright is validated and run
  on the Mac. The PC takes most of the indexing: it embedded 118 texts per second in its speed
  check, against 35 to 47 on the Mac. Further repos are assigned when their turn comes, and each
  assignment is written here.
- **Started:** the pandas clone and a base image pull on the PC. Docker on the Mac.

## Checked

- The key in the PC's authorized-keys file is the Mac's key, and it is the only one.
- Inside Ubuntu, read from the Mac: 16 processors, 47 GB, systemd on, Docker 29.10.1,
  ripgrep 15.2.0, the RTX 3060 Ti visible.
- **Claude Code updated itself on the PC during the set-up,** from 2.1.331 to 2.1.332. The Mac is
  on 2.1.311. Before the first run that is kept, both machines go to one version and the
  auto-update is turned off. Each run record holds the version.
- Not checked: a build of a real task image on either machine.

## Left

- **Track A is behind the run sheet of plan §14.3.** The rows for Sun Nov 22 and Mon Nov 23 are
  not done: no recipe, no admission check, no validated task, no pipeline, no bring-up run.
  Andrew was travelling on Nov 23, and Nov 24 went to the PC set-up. Work starts now with the
  Sun Nov 22 row.
- What this means for the dates: validated tasks for pandas and playwright by the evening of
  Nov 25 are possible if both admission checks pass at the first attempt. ruff, kubernetes and
  duckdb by Nov 27 is the real target. The first end-to-end test moves from Nov 23 to Nov 25 or
  26. The start of the main batch on Nov 26 is at risk by about one day.

## Blocked on, or needed from others

- **Andre:** this is the early warning that the plan asks for. Nothing is needed today. If the
  pandas admission check fails tonight, the next entry will say so and will ask for help with
  the recipes of the later repos (ruff, kubernetes, duckdb), which can be written by someone
  else while the pipeline is built.
- **Wilson:** is `codemem-today` tagged? The tag is not on `origin` yet. Until it is, track A
  uses `main` at `3d9f42b` as today's codemem.

## Next

- The pandas recipe and its admission check on the PC. The same for playwright on the Mac.
- Then A9's build and validate steps, A1 and A2.
