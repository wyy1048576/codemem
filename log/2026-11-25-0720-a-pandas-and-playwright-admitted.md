# pandas and playwright pass the admission check; `cmeval generate` is on main

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-25 07:20 UTC
- **Work package:** A9, the build and validate steps (plan §8.1 steps 3 and 4, §8.2)
- **Branch, commits, pull request:** pull request #20, merged as `e5c8ec0`

## Done

- **`cmeval generate RECIPE --tasks FILE`** builds one Docker image for each task (the repo at the
  task's commit) and runs the task's test files before and after the real fix, three times each.
  `--admission` runs the check of §8.2 on a fixed sample of 10 (3 easy, 4 medium, 3 hard).
- **Two recipes:** `eval/envs/pandas.toml` and `eval/envs/playwright.toml`. A recipe can have
  several test suites. playwright has three (library and page, mcp, playwright-test), on Chromium.
- **Both repos are admitted.**

| Repo | Sampled | Valid | Image build | Slowest test run |
|---|---|---|---|---|
| pandas | 10 | **10** | 1.4 to 7.0 min | 3.9 min |
| playwright | 10 | **8** | 3.0 to 4.8 min | 3.4 min |

## Checked

- Run on the PC (x86, 16 processors, Docker 29.10.1), with other load on the machine. Every
  number above is from the saved records in `~/.cmeval/generate/` on that machine.
- No test changed its result between the three runs of a phase, on any of the 20 tasks.
- Every pandas image compiled its own pandas (read in each build log), and a July image holds
  July's package versions (numpy 2.4.6, pyarrow 23.0.1).
- 480 unit tests of `eval/` pass, 14 of them new.
- Not checked: an ARM build. Docker Desktop on the Mac cannot pull images at present.

## Left

- **Two playwright tasks are not valid, and the cause is open.** 42856: the new test passes before
  the fix. 42859: the new test fails after the fix too. It can be the tasks, or a gap in the
  rebuild step of the recipe (`npm run build`).
- **Task 67471 of pandas has 28,465 fail-to-pass tests.** The fix adds a helper that the changed
  test files import, so before the fix the files do not load. Valid by the rule, but a different
  kind of task. Such tasks will get a mark.
- The validated tasks are not in a task file yet. No labels of step 5.
- Disk, measured: about 1.5 GB for each pandas task and about 2.3 GB for each playwright task,
  after shared layers.

## Blocked on, or needed from others

Nothing.

## For the other tracks: four things that a recipe must get right

Found by the trials. They will come up again for ruff, kubernetes and duckdb.

1. **A build cache keyed by path is unsafe.** uv keeps a local build by its path. Every task is
   built in `/testbed`, so with the cache one task got another task's pandas. The crash was the
   lucky outcome. The pandas build now uses `--no-cache`.
2. **An image without git history has no version.** pandas named itself `0+untagged`, and pyarrow
   then refused it. The image's commit now gets the nearest real tag.
3. **Dependencies are resolved as of the week of the task's commit.** Packages for documentation
   and lint are left out: they do not install at an older date, and no test needs them.
4. **Tests run with the network off.**

## Next

- Validate 60 candidates of each of the two repos, and write the task file.
- A1 and A2: the pipeline skeleton and the recording proxy, with bring-up runs on these tasks.
- The recipe for ruff.
