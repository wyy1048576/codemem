# From Andre, as project lead: the lock date, what the project sets out to show, and the runs (which model runs which tasks)

- **Track:** shared. Point 4 is for track A, point 5 for track B
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 13:46 UTC
- **Work package:** none; it frames A1 to A9 and the open-model study
- **Branch, commits, pull request:** `andre/run-plan` (`78a9117`): one new page, `docs/plan/runs.md`. Andre opens the pull request

## Done

**0. The lock date, because track A asks for it again: codemem's design is locked on Friday
Nov 27 at noon Pacific** (20:00 UTC). We aim for tonight. It was in the entry of 09:56 UTC.
Track A, if your session has not read our entries since then, please read these four first:
09:56 (the lock, tasks first), 10:37 (all of track C is on `main`: run `uv sync`), 11:20 (three
new defaults, and one line in the eval's runner), 11:32 (four runs on the PC).

**1. What the project sets out to show.** A reminder for all of us, so that every run and every
change can be held against it.

- **Contribution 1: grep alone against grep plus an index (codemem),** across frontier agents and
  small open-weight models. codemem does not replace grep; the question is whether adding it
  helps. Three measures: does the agent solve the task, how long does it take end to end, and how
  many tokens does it use.
- **Contribution 2: does codemem narrow the gap between models?** If a frontier model gains
  little, a small model may gain more.
- **A third, for after Dec 1:** frontier models may solve tasks from memory of public repos. The
  counter is to disguise names and paths in the code and in the issue, in one consistent way.
  How to do it and how to check it is open. Wilson collects the evidence.

**2. The order of work.**

1. Track C is made ready for track A to take over: its last four branches, then a note for
   track A's agents.
2. The same for track B's part (point 5).
3. The large runs, from the night of Nov 27 to Nov 30.
4. Meanwhile the harness for the open-weight models is finished, so that they run right after.
5. Then the paper.

Dates, all Pacific: results freeze on Nov 30 at 23:59; the presentation is on Dec 1 at 14:00;
the paper is due on Dec 8.

**3. Decided today** (Andre).

| Question | Decision |
|---|---|
| Which models | For the presentation the three Claude models: Sonnet for most runs, Haiku as the cheap tier and Opus as the top, a few runs each. Cost is the limit on Opus. Codex is considered for the paper |
| Where they run | the Claude runs on Andrew's PC, and they come first there. The open models on a GPU that Andre rents; they use nothing of the PC |
| Repetitions | three for Sonnet. They guard against the noise between two runs of one task, and the paper will say so |
| Success for a small model | "reached the gold files", with the steps and tokens it took, beside "solved". Their tasks are the easy and medium ones, at L0 and L1 |
| A fourth difficulty level, **large** | yes, for the repos that are run fully: 3 to 4 tasks each (point 4) |
| The naive baseline, for the paper | memory and search time against the textbook setup: 4-byte numbers, a plain full scan, vectors of 1,024 or 2,048 numbers. And the agent with codemem against the agent with grep only, end to end: one grep is fast, an agent's trial and error with it over several turns is not |

**4. For track A: the runs, on one page.** `docs/plan/runs.md` on the branch `andre/run-plan`.
It is built on the task files and recipes of ten repos that track A put on `main`: thank you,
Andrew. Please read the page itself; in short:

- **The sample:** 15 fair tasks per repo, 5 easy, 5 medium, 5 hard, each with its L0, L1 and L2
  prompt. Checking candidates can stop at 7 fair tasks per level. A level that falls short gives
  all it has, and the sample is filled from the other levels: pandas, with 9, 5 and 3 fair
  tasks, runs 7, 5 and 3.
- **Who runs what, per repo,** always in both setups, `grep` and `tool`:

| Model | Tasks | Prompts | Repetitions |
|---|---|---|---|
| Sonnet | all 15 | L0, L1, L2 | 3 |
| Haiku | 6: two of each level | L0, L1, L2 | 1 |
| Opus | 3: one of each level | L0, L2 | 1 |
| Sonnet and Opus | the large tasks | L0, L2 | Sonnet 3, Opus 1 |
| Open models (rented GPU, started by Andre) | 8 easy and medium; 3 hard as a probe | L0, L1; the probe at L0 | 3; the probe 1 |

- **The repos, ranked:** 1 pandas, 2 ruff, 3 duckdb, 4 playwright, 5 vscode, 6 home-assistant
  are run fully. 7 kubernetes and 8 trino get one Sonnet repetition, for their language. airflow
  and vllm are the reserve. The page gives the reason for each rank.
- **First a check run, before anything is automated:** 24 Sonnet runs on two repos with the
  locked codemem. It passes when codemem is called in at least 5 of the 6 `tool` runs at L2, no
  search fell back to keywords, the token counts and grades are right, and a person has read two
  transcripts. The batches start only after it. Its runs count as the plan's first runs.
- **The order after it:** Sonnet once on repos 1 to 6; Haiku and Opus; the large tasks; Sonnet
  once on kubernetes and trino; Sonnet's repetitions 2 and 3.
- **The large level.** No task on `main` has a real fix of more than 5 code files or 200 changed
  lines: the collector's settings (`max_code_files`, `max_code_lines`) stop there. That limit
  removed 5% (pandas) to 25% (vscode) of the fixes of one issue, about 430 candidates in the six
  repos. For those six, please run the same collection again with the limit at 15 files and
  600 lines, now, because it needs no container. A fix beyond today's limit is "large". A
  repo's large candidates are checked after its sample of 15 is ready, until 4 are fair.
- **How long:** about 2,500 Claude runs, 2.9 to 4.0 days on three seats if no limit pauses one.
  The minutes per run are the pilot's, for Haiku: the check run measures Sonnet. So the first
  five steps are what the presentation counts on, and the repetitions fill the time left.

**What we ask of track A** is the list in §9 of that page: the table of fair tasks per repo and
level as each repo ends (your entry of 13:20 has the first two), the check run's result with
the first Sonnet numbers, and the second collection for the large level.

**5. For track B: thank you for pushing the loop work** (pull request #45, and the three
entries of 13:07 to 13:26). Wilson, we are reading it today, as you asked: the method, the
numbers, and what of it can go into codemem or into the runs before the lock. We post what we
find here, with a proposal branch where we see a change worth making. Whatever does not make the
lock is not lost: it can still be measured afterwards, for the paper.

**6. Proposed, not for the lock** (in `docs/plan/track-c-memory.md` on `andre/track-c-results`):
- **No saved copy for the exact search index.** It would save a quarter of an index folder
  (261 MB of vLLM's 909 MB). It stays for now, because every `codemem search` on the command
  line is a new process that would build the index again, and that command is how the
  open-weight models call codemem.
- **One codemem process per machine** that holds the embedding model and the open repos'
  indexes for every caller. With it nobody pays a start, and the saved copy can go.

## Checked

- The task counts are read from `eval/tasks/e2e/*.jsonl` and the collection's own records
  (`eval/tasks/fresh-*.meta.json`) on `main`; the fair counts are track A's, from 13:20.
- The run counts are arithmetic. The 5 to 7 minutes per run rest on the pilot's mean for Haiku;
  nobody has measured Sonnet or Opus.
- Not checked: how many large candidates are valid and fair. The 3 to 4 per repo is a target.

## Left

- The note for track A's agents on taking over track C, once its last branches are merged.
- The audit of pull request #45.
- The harness for the open-weight models.

## Blocked on, or needed from others

- **Andrew:** the list in §9 of `docs/plan/runs.md`: first the check run, and the second
  collection for the large level. And the four entries named in point 0, if they were missed.
- **Wilson:** nothing new; thank you for the push.

## Next

- Track C's session: the last branches, the note for track A, the audit of #45, then the
  open-model harness with Andre.
