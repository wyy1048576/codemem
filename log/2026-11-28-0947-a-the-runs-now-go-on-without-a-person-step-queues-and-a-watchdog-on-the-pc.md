# Track A: the runs now go on without a person. Each stream has a step queue on the PC, and a watchdog starts everything again after a crash

- **Track:** A, for the lead and for track B. No answer is needed
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 09:47 UTC
- **Work package:** A12 (the runs)
- **Branch, commits, pull request:** none (scripts on the PC, outside the repo)

## Done

**1. Why.** Andrew drives for about 6 hours later today (Nov 28, Pacific morning), and the Mac that this agent works on is off in that time. Until now a person or this agent started each next step and looked after a fault. We post the exact hours when he leaves.

**2. What runs on the PC by itself now** (set up and tested 09:35 to 09:47 UTC).

- **A step queue for each stream.** A runner takes the steps of a text file one after the other. A finished step is written down and is not run again. Because a finished run is skipped and an unfinished run folder is set aside and done again, a stream can start again at any point and goes on where it was.
- **A step that fails** is tried once more after 10 minutes. After the second failure it is passed over, as §7 of the plan says for a repo that is not ready, and the next step starts. Two steps in a row that are passed over stop the stream: then the fault is not in one repo.
- **A watchdog on Windows, every 5 minutes:** it keeps WSL open, starts the build daemon, and starts every job that should run and does not (the two streams, the guards, the copy of the records to D:, the load log, the build queue). After a guard has fired, the jobs that it stopped are not started again: a person must look first.
- **Tested:** the runner with a fake launcher (queue, second try, pass over, stop after two); the move of both live streams to the runner; the watchdog started a job again that we had stopped on purpose (4 minutes). **Not tested: a real crash of WSL.**

**3. The queues.**

| Stream | Steps, in order |
|---|---|
| 1 (seat 1 first) | Haiku: ruff (8 tasks), ruff (the ninth), duckdb hard tier, duckdb. Then Sonnet: pandas, duckdb hard tier, duckdb |
| 2 (seat 2 first) | Haiku: home-assistant, its hard task, playwright's hard task, playwright, kubernetes. Then Sonnet: playwright's hard task, playwright, kubernetes |

- **One thing differs from §7:** a stream goes on to its Sonnet steps when its own Haiku steps are done. So Sonnet's pandas can start in stream 1 while Haiku's kubernetes still runs in stream 2. By our estimate that is after 03:00 UTC on Nov 29. Say so if you want Sonnet to wait for all of Haiku's repetition 1.
- vscode and trino have no run tasks and are not in a queue. Opus and Haiku's repetitions 2 and 3 are not in a queue yet; we add them before the queues end (by our estimate not before 09:00 UTC on Nov 29).
- The preparation step is the old one in every step. The draft pull request #92 is not in use.

**4. The move to the runner cost two set-aside folders without a record** ( 26631 ,  181276 , each ): each stream was stopped right after a finished run, and the run that was in preparation is done again. No agent time was lost.

**5. Status.** The 25 missing run images are all built and in the archive (09:34 UTC). Stream 1 is in ruff L0, stream 2 in home-assistant L1. The build queue goes on with home-assistant's hard tier.

**6. While the Mac is off, this log is not read and not written by track A.** The runs, the guards and the copies go on. Reports and uploads wait until the Mac is back.

## Checked

- The log of each runner shows the step it started and the batch that goes on (`haiku-ruff-L0`: 16 runs, finished ones skipped; `haiku-homeassistant-L1` the same).
- The Windows task ran with result 0 and its next run is set.

## Left

- The hours of the drive, when Andrew leaves.
- The reports on home-assistant and ruff.

## Blocked on, or needed from others

- **Andre:** still the answer on the preparation step (our entry of 08:06 UTC, draft pull request #92). A change of method is made only when the Mac is on.

## Next

- Opus and Haiku's repetitions 2 and 3 in the queues.
