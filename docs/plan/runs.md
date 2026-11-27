# The runs: which model runs which tasks

**What this page is for.** It fixes, before the first run, which tasks are run, which model runs
which of them, in what order, and about how long that takes. Track A runs it. The reasons for the
study's design are in [track-a-evals.md](track-a-evals.md); this page is the list to work from.

---

## 1. The five words

One example is used throughout: the pandas task **68195**.

**A task** is a real GitHub issue, the real fix that was merged for it, and the tests that came
with the fix. The agent gets the request and the repo. The tests stay hidden and grade its change.
In task 68195 the real fix changes one file, `pandas/core/reshape/merge.py`.

**The tier** is the size of the real fix. It is a property of the task. There are three:

| Tier | The real fix changes | The label in today's task files |
|---|---|---|
| **easy** | at most two files and 100 lines | `easy` and `medium` |
| **medium** | three to five files, or 101 to 200 lines | `hard` |
| **hard** | 6 to 15 files, or 201 to 600 lines | none: these are collected now, for every repo that is run (§10) |

Task 68195 is easy. **The tiers are not the labels of the task files:** today's `easy` and
`medium` are one tier, today's `hard` is the medium tier, and the hard tier is new. Every count
on this page is in tiers.

**The prompt level** is how the request is worded. It is not a property of the task: **every
task has all three wordings**, and the hidden tests are the same for all three.

| Level | What it is | Task 68195 |
|---|---|---|
| L0 | the issue as it was written, here 252 words | "BUG: merge_asof says "tolerance must be positive" but accepts tolerance=0", with the code that shows it |
| L1 | the same content, with every name of the code removed | "In an as-of merge (a merge on the nearest key), the setting for the largest allowed distance between matching keys accepts zero. … the error text says that the limit has to be positive, which wrongly suggests that zero is invalid too." |
| L2 | a short request in a user's voice, 10 to 30 words | "The as-of merge error for a negative distance limit says it has to be positive, but zero is allowed. Make the message say non-negative." |

With L0 an agent can grep for `tolerance must be positive` and land on the line. With L1 and L2
there is no such string to grep for. That is the case codemem is built for, and the reason each
task is run at all three levels.

**A setup** is what the agent may use: `grep` is the agent with its own tools; `tool` is the same
agent with codemem added; `upfront` is the same agent as `grep`, whose first message also holds the
20 best results of one codemem search on the prompt, one line each (`path:line`, two spaces, the
name), under the line "Possibly relevant code, from a search by meaning (it may be wrong):". No
codemem tool is offered in `upfront`. It is a run of its own, at L1 and L2, not at L0, and in the
first repetition only (§4). `tool` and `upfront` are both codemem: as a tool the agent may call,
and with its results placed in the first message. The headline comparison is `grep` against
codemem.

**A repetition** is the same run again, from the start. An agent's run has chance in it: in the
pilot, two runs of one task that used the same tools differed by up to 8 times in tokens (2.14
million against 0.25 million). One run per task cannot tell codemem's effect from luck. Three
runs per task guard against that noise, and the paper states this as their reason.

**One run** is therefore: one task, at one prompt level, in one setup, by one model, one time.

---

## 2. Why many candidates give few tasks

The task files on `main` hold thousands of **candidates**: merged pull requests with a linked
issue and a change to the tests. They are a list read from GitHub. Making that list costs
minutes, and nobody runs it in full.

Two checks turn candidates into tasks, and only they cost time:

- **valid:** in the task's container the hidden tests fail before the real fix and pass after
  it. It costs a container and two test runs for each candidate;
- **fair:** every reasonable fix made from the issue alone would pass the hidden tests. It costs
  two reads by a model for each valid task.

| | pandas | playwright |
|---|---|---|
| candidates with tests on `main` | 298 | 182 |
| checked so far | 100 | 60 |
| valid | 92 | 49 |
| fair, easy tier | 14 | 20 |
| fair, medium tier | 3 | 8 |

So two to six candidates are checked for each task we can run, and the share differs by repo:
18% of pandas's valid tasks are fair, 57% of playwright's. Many pandas issues are old, and the
fix that came late is wider than the issue. We cannot check fewer by choosing better, because
nothing tells in advance which candidates are valid and fair.

**The rule that saves time:** check a tier only until it has what the sample needs and 2 spare
tasks, then stop that tier: 8 fair tasks for easy (5 with the label `medium`, 3 with the label
`easy`), 6 for medium, and 4 for hard, where each one is costly. A repo whose hard tier falls
short needs that many more in medium (§3).

---

## 3. The sample

**14 fair tasks per repo: 6 easy, 4 medium, 4 hard. Each has its three prompts,** so a repo has
42 requests.

- **The six easy tasks are 4 with the label `medium` and 2 with the label `easy`:** a mix, with
  more from the larger end of the tier. Up to 8 may be fair and ready; 6 are run.
- Drawn once per repo with the seeded sampler, from tasks that are valid and fair. Tasks of the
  test split come first: they are the ones no track tuned codemem on. The list is committed
  before the first run and does not change after it.
- The tasks of each tier are numbered in the order they were drawn. In the easy tier, numbers
  1, 3, 4 and 6 have the label `medium` and numbers 2 and 5 the label `easy`, so that numbers 1
  and 2 are one of each. The table of §4 uses these numbers.
- A task that breaks during the runs is replaced by the next spare of its tier, in every setup.
- **A repo with fewer than 4 fair hard tasks runs more medium ones instead,** so that medium and
  hard together are 8: with 2 hard tasks it runs 6 medium ones. Not every repo has enough large
  fixes of one issue (§10).
- **A repo that is still short gives all it has.** pandas has 3 fair tasks in the medium tier
  today, with 8 candidates left to check, and few candidates for the hard tier.

**What this size can show.** The unit of every comparison is the task: `grep` against each
codemem setup on the same task, at one prompt level, with one model. `tool` is paired with `grep`
at L0, L1 and L2, `upfront` at L1 and L2. For Haiku the six repos that are run fully (§5) give 84
tasks, so 84 pairs at each level, and kubernetes and trino add 28. Sonnet runs four repos: 56
pairs. The numbers below are planning numbers, under the assumptions of
[track A](track-a-evals.md) §13: 75 pairs show a difference of 15% in tokens or time, and 150 pairs
a difference of 10 points in tasks solved. With fewer pairs the difference has to be larger, by
the square root of how many fewer.

| Comparison | Pairs | What it can show |
|---|---|---|
| Haiku, all tasks of the six repos, at one prompt level | 84 | a difference of about 14% in tokens or time; in tasks solved, only a difference of 13 points or more |
| Haiku, with kubernetes and trino | 112 | about 12%, and 12 points |
| Sonnet, its four repos | 56 | about 17%, and 16 points |
| Haiku, the easy tier | 36 | a difference of about 22% |
| Haiku, the medium or the hard tier | 24 | large differences only, about 27% |
| Opus, its 6 tasks of each of the six repos | 36 | about 22% |
| one repo | 14 | a direction, not a result |

Tier and prompt level are two separate dimensions, and the sample covers both: every task of
every tier is run at L0, L1 and L2.

---

## 4. Which model runs what

Every model runs a part of the same sample, so that models are compared on the same tasks.

| Model | Tasks of each repo | Prompts | Setups | Repetitions | Runs per repo |
|---|---|---|---|---|---|
| **Haiku** (the cheap tier) | all 14 | L0, L1, L2 | `grep`, `tool`; `upfront` at L1 and L2, in repetition 1 | 3 | 112 in repetition 1, 84 in repetitions 2 and 3 |
| **Sonnet** (the middle tier), in four of the repos (§5) | all 14 | L0, L1, L2 | `grep`, `tool`; `upfront` at L1 and L2, in repetition 1 | 3; repetitions 2 and 3 are a bonus | 112 in repetition 1, 84 in repetitions 2 and 3 |
| **Opus** (the top; few runs, because of their cost) | 6: number 1 of easy, number 1 of medium, and the 4 hard ones | L0, L2 | `grep`, `tool`; `upfront` at L2 | 1 | 30 |
| **Open models:** the 9B first, then the 27B, then the 14B | the 6 easy ones | L0, L1 | `grep`, `tool` | 3 | 72 for each model |
| **Open models, a probe** | 3: numbers 1 to 3 of medium | L0 | `grep`, `tool` | 1 | 6 for each model |

- **Haiku carries the comparison,** because it is the model that calls codemem at the start of
  nearly every `tool` run. Sonnet and Opus rarely do. They are run to record how often they use
  it, and what `upfront` gives them: in `upfront`, codemem's results reach all three. Sonnet's
  repetitions 2 and 3 are a bonus (§7).
- **Sonnet runs four of the repos:** pandas, duckdb, playwright and kubernetes. A model of its
  size places many tasks from memory, so its runs go where that differs most. In a probe with no
  repository and no tools, Sonnet named the right file first in 15 of 17 pandas tasks, 13 of 20
  kubernetes tasks, 10 of 28 playwright tasks and 12 of 41 duckdb tasks. kubernetes is the very
  large one of the four.
- **`upfront` runs in the first repetition only.** It is a run of its own, 28 for a repo and a
  model, and one repetition answers its two questions: what codemem's results give Sonnet and
  Opus, and whether results in the first message cost Haiku less than the tool does.
- The three Claude models are for the presentation. Codex is considered for the paper.
- **The Claude runs go on Andrew's PC, and they come first there.**
- **The open models run on a rented GPU** (Nebius), in their own harness, started by Andre. They
  use none of the Claude seats and nothing of the PC. The harness and the models are expected to
  be ready on Sat Nov 28.

**What every run records:** whether the hidden tests pass; tokens; time; and the turn at which
the agent first sees a gold file in a result, first opens one, and first edits one. The last
three answer "did it reach the right place, and how fast", for the small models too.

---

## 5. The repos, ranked

All ten repos on `main` can carry tasks: each has enough candidates and a written recipe. They
are not equally worth the seats. The rank says which are worth the most, and the last column how
far each is run; §7 gives the order. Three things decide the rank:

- **the language:** Rust, Python, C++ and TypeScript come first;
- **how vague the issues are:** the share of issues that name the code that has to change. The
  lower it is, the more a task needs search by meaning, even at L0;
- **the size of the repo, and what its environment costs.**

| Rank | Repo | Language | Issues that name the code | Why this rank | How far |
|---|---|---|---|---|---|
| 1 | pandas | Python | 57% | medium size; its tasks are ready; the check run (§6) starts here | fully, and Sonnet |
| 2 | ruff | Rust | 8% | the vaguest issues of all: even L0 gives little to grep for | fully |
| 3 | duckdb | C++ | 21% | vague issues, in C++ | fully, and Sonnet |
| 4 | playwright | TypeScript | 64% | its tasks are ready; medium size | fully, and Sonnet |
| 5 | vscode | TypeScript | 26% | very large and vague, with the most candidates for the hard tier: where an index should show most. Fifth only because its environment is the costliest: a long build, and tests that need a display | fully |
| 6 | home-assistant | Python | 54% | very large, 18,700 Python files; the largest pool | fully |
| 7 | kubernetes | Go | 55% | a fifth language, very large. The smallest pool of these: 86 candidates | once, and Sonnet |
| 8 | trino | Java | 27% | a sixth language. A small pool: 64 candidates | once |
| 9 | airflow | Python | 60% | a third Python repo | reserve |
| 10 | vllm | Python | 76% | a fourth Python repo, with the issues that name the code most often | reserve |

- **fully:** Haiku's three repetitions, Opus's runs and the open models' (§4).
- **once:** one repetition of Haiku on the repo's whole sample, so that the language is in the
  table.
- **and Sonnet:** the repo is one of Sonnet's four (§4): one repetition. Its repetitions 2 and 3
  are a bonus, on the three of them that are run fully.
- **reserve:** runs only in place of a repo above it that cannot be built.

Every repo that is run has all three tiers.

Every fix in every pool was merged between July 1 and October 22, 2026.

---

## 6. First, a check run

Before the batches are automated, one small batch shows that the whole chain works with the
locked codemem, and that Haiku calls codemem.

**What runs.** On pandas and on playwright, which Haiku and Sonnet both run (§5):
numbers 1 and 2 of easy and number 1 of medium, at L0 and at L2, in `grep` and `tool`, with Haiku
and with Sonnet, once. That is 24 runs for each model, 48 in all, under two hours on three seats.

**It passes when:**

1. every run has a record and a grade, and none is discarded;
2. the proxy's token count equals the agent's own in every run;
3. **codemem is called:** `search_code` is called in at least 5 of the 6 `tool` runs at L2 with
   Haiku. In the pilot it was 17 of 18. For Sonnet the number is reported and not required:
   Sonnet rarely calls codemem (§4). At L0 the number is reported and not required: with a name
   to grep for, an agent often greps;
4. **every search is a search by meaning:** no `search_code` result holds `still loading` or
   `codemem cannot embed right now`, and `index_status` in one container has the line `watching
   for changes`, not `not watching (scanning on a timer or on request)`;
5. a person has read two `tool` transcripts: the search's result reaches the agent, and the
   agent uses it.

**What it also gives:** the first numbers for Haiku and for Sonnet: minutes and tokens per run,
how much of a seat's limit the runs used, and how many runs ended at the turn or the time limit.
§8 is corrected from them.

**After it.** If it passes, its 48 runs are the first runs of the plan, not extra ones. If point
3 or 4 fails, the batches wait: track B fixes the wording that makes the agent call codemem, or
track C the index, before any more seats are spent.

---

## 7. The order

1. the check run (§6);
2. **Haiku, repetition 1:** repos 1 to 6 in the order of their rank, then kubernetes and trino;
3. **Sonnet, repetition 1:** its four repos, in the order of their rank;
4. **Opus:** repos 1 to 6;
5. **Haiku, repetition 2, then repetition 3:** repos 1 to 6 in the order of their rank. **The plan
   counts on reaching the end of repetition 2;**
6. **Sonnet, repetition 2, then repetition 3:** pandas, duckdb and playwright, in that order. A
   bonus, and it is fine if this step is not completed.

- **The hard tier comes later than the other two** (§10). Easy and medium do not wait for it.
  When a repo's hard tasks are ready, they are run for the steps that have passed, and are in
  step from then on.
- **`upfront` joins a repo's runs as soon as the runner has it,** on the same tasks. If a
  model's repetition 1 of a repo has passed by then, its `upfront` runs are made next.
- A repo that is not ready when its turn comes is passed over and taken up when it is. It then
  starts at step 2, before further repetitions of the repos ahead of it: every repo is run once
  before any is run again.
- A batch that is cut short leaves a complete table with fewer repetitions, never a table with
  holes. The setups of a task go turn about in the same batch, and which of them goes first
  changes from task to task, so that their times can be compared.

---

## 8. How long

| | Runs | On three seats, at 5 to 7 minutes a run |
|---|---|---|
| step 2: Haiku, repetition 1, eight repos | 896, 24 of the check run among them | 25 to 35 hours |
| step 3: Sonnet, repetition 1, four repos | 448, 24 of the check run among them | 12 to 17 hours |
| step 4: Opus, six repos | 180 | 5 to 7 hours |
| steps 1 to 4 | 1,524 (Haiku 896, Sonnet 448, Opus 180) | 42 to 59 hours |
| step 5: Haiku, repetition 2 | 504 | 14 to 20 hours |
| steps 1 to 4 and Haiku's repetition 2 | 2,028 | 56 to 79 hours |
| step 5: Haiku, repetition 3 | 504 | 14 to 20 hours |
| step 6: Sonnet, repetitions 2 and 3 | 252 each | 7 to 10 hours each |
| the open models, on the rented GPU | 468 for each model, on the six repos that are run fully | about 8 hours for each model, if a run takes as long as a Claude run and six run at once |

**What fits.** codemem is locked on Nov 27 at 16:30 Pacific. The runs start at 17:00 Pacific
(Nov 28, 01:00 UTC), and the results are frozen on Nov 30 at 23:59 Pacific (Dec 1, 07:59 UTC):
79 hours. Sat Nov 28 and Sun Nov 29 are reserved for running. With 14 tasks in every repo and
every repo ready, steps 1 to 4 take 42 to 59 of the 79 hours without a pause, and Haiku's
repetition 2 brings that to 56 to 79. Its repetition 3 is complete only if a run takes less than
about 5.6 minutes. A repo that is short of tasks, or not ready, takes less.

- **The 5 to 7 minutes are an assumption.** The pilot measured 4.3 to 5.5 minutes for Haiku at
  L0. Nobody has measured Sonnet or Opus, vague prompts took more tokens in the pilot, and a
  task of the hard tier will take longer. The check run measures it.
- **Usage limits are the unknown.** A seat pauses when it reaches its limit. So steps 1 to 4 and
  Haiku's repetition 2 are what the presentation counts on, and the rest fills the time that is
  left, in the order of §7.
- Checking candidates, writing the L1 and L2 prompts and building the indexes come before a
  repo's runs and are not in these numbers.

---

## 9. What track A is asked to do

1. **The second collection, for the hard tier** (§10): start it now, for the eight repos of
   ranks 1 to 8. It needs no container.
2. **For each repo, in the order of §7:** validate and screen candidates of the easy
   and the medium tier until each has what §2 says, then the candidates of the hard tier. Post
   the table of fair tasks per repo and tier as each repo ends.
3. **Draw the sample** (§3), write its L1 and L2 prompts, and commit the list.
4. **Build each task's index** with the locked codemem.
5. **Build the `upfront` setup** (§1): `grep` with a block of codemem's results at the top of the
   first message, made once for each task and level with the task's index and the locked codemem,
   so that every model and repetition gets the same block. The block's layout and the checks of
   each run are in the work-log entries of Nov 27, 12:45 and 15:13 UTC.
6. **Run the check run** (§6) with Haiku and with Sonnet, and post its five points and the first
   numbers of both models. Go on only when it has passed.
7. **Then run in the order of §7.**

**One request about labels:** keep today's label of each task in the files as it is, and add the
tier as a new label. Tables written so far then keep their meaning, and new ones say which of
the two they count.

**One note about the analysis:** which tables and analyses are made from the runs is decided by
Andre in the days after the runs start; this page fixes what is run and what every run records
(§4), track A does not need to design the analysis now, and its suggestions are welcome.

---

## 10. Where the hard tier comes from

**Why it is new.** No task on `main` has a real fix of more than 5 code files or 200 changed
lines. That is a setting of the task collector (`max_code_files = 5`, `max_code_lines = 200`),
from the first collection in October, which was made for the retrieval eval. A request such as
"add OCR to the upload pipeline", which touches many files, is what codemem is meant for.

**What the limit removed.** Among merged pull requests that fix exactly one linked issue and
change code:

| Repo | Such fixes | Larger than the limit | Share |
|---|---|---|---|
| pandas | 371 | 19 | 5% |
| home-assistant | 805 | 49 | 6% |
| duckdb | 231 | 22 | 10% |
| trino | 78 | 8 | 10% |
| kubernetes | 128 | 17 | 13% |
| playwright | 244 | 35 | 14% |
| ruff | 285 | 55 | 19% |
| vscode | 1,026 | 253 | 25% |

Most fixes of one issue are small. The limit removed 458 candidates in these eight repos, more
than half of them in vscode. How many of them are within the new limit, the second collection
shows. Larger work often comes as a pull request without a linked issue, and such a pull request
cannot be a task: there is no request to give the agent.

**How the tier is made.**

1. The same collection again, for the eight repos of ranks 1 to 8, with the limit at 15 code
   files and 600 changed lines. Nothing else changes, so every task of today is found again.
2. A fix of more than 5 code files or more than 200 changed lines is in the hard tier.
3. A repo's hard candidates are validated and screened after its easy and medium tasks are
   ready, until 4 are fair. Fewer large fixes pass the screen than small ones: of pandas's valid
   tasks in the medium tier 11% are fair, of those with the label `easy` 32%. So some repos will
   end with fewer than 4: pandas has 19 candidates, trino 8. They run more medium tasks instead
   (§3).
4. Each hard task gets its L1 and L2 prompts like any other.
