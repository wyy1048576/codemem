# The runs: which model runs which tasks

**What this page is for.** It fixes, before the first run, which tasks are run, which model runs
which of them, in what order, and about how long that takes. Track A runs it. The reasons for the
study's design are in [track-a-evals.md](track-a-evals.md); this page is the list to work from.

*Proposed on Nov 26. Not confirmed yet: Andre confirms it in the work log.*

---

## 1. The five words

One example is used throughout: the pandas task **68195**.

**A task** is a real GitHub issue, the real fix that was merged for it, and the tests that came
with the fix. The agent gets the request and the repo. The tests stay hidden and grade its change.
In task 68195 the real fix changes one file, `pandas/core/reshape/merge.py`.

**Difficulty** is the size of the real fix. It is a property of the task.

| Level | The real fix changes |
|---|---|
| easy | one file, at most 15 lines |
| medium | at most two files and 100 lines |
| hard | more: three to five files, or 100 to 200 lines |

Task 68195 is easy.

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
agent with codemem added.

**A repetition** is the same run again, from the start. An agent's run has chance in it: in the
pilot, two runs of one task that used the same tools differed by up to 8 times in tokens (2.14
million against 0.25 million). One run per task cannot tell codemem's effect from luck. Three
runs per task even that out.

**One run** is therefore: one task, at one prompt level, in one setup, by one model, one time.

---

## 2. Why many candidates give few tasks

The task files on `main` hold thousands of **candidates**: merged pull requests with a linked
issue and a change to the tests. They are a list read from GitHub. Making that list costs
minutes, and nobody runs it in full.

Two checks turn candidates into tasks, and only they cost time:

| Step | pandas, as expected | What it costs |
|---|---|---|
| candidates with tests on `main` | 298 | nothing more |
| drawn, the same number from each difficulty | 60 | nothing |
| **valid:** in the task's container the hidden tests fail before the real fix and pass after it | about 54 (9 in 10) | a container and two test runs for each |
| **fair:** a correct fix made from the issue alone would pass the hidden tests | about 27 (half; 9 of the 18 pilot tasks) | two reads by a model for each |
| in the sample | 15 | |

So about four candidates are checked for each task we run. We cannot check fewer by choosing
better, because nothing tells in advance which candidates are valid and fair.

**The rule that saves time:** check each difficulty level only until it has 7 fair tasks (the 5
of the sample and 2 spare), then stop that level.

---

## 3. The sample

**15 fair tasks per repo: 5 easy, 5 medium, 5 hard. Each has its three prompts,** so a repo has
45 requests.

- Drawn once per repo with the seeded sampler, from tasks that are valid and fair. Tasks of the
  test split come first: they are the ones no track tuned codemem on. The list is committed
  before the first run and does not change after it.
- The five tasks of each level are numbered 1 to 5 in the order they were drawn. The table of §4
  uses these numbers.
- A task that breaks during the runs is replaced by the next spare of its level, in every setup.

**What this size can show.** The unit of every comparison is the task: `grep` against `tool` on
the same task, at one prompt level. Six repos give 90 tasks, so 90 pairs at each level. The
numbers below are planning numbers, under the assumptions of [track A](track-a-evals.md) §13.

| Comparison | Pairs | What it can show |
|---|---|---|
| all tasks, at one prompt level | 90 | a difference of about 14% in tokens or time; in tasks solved, only a difference of 13 points or more |
| one difficulty | 30 | large differences only, about 25% |
| one repo | 15 | a direction, not a result |

Prompt level and difficulty are two separate dimensions, and the 15 tasks cover both: each
difficulty has 5 tasks, and each of them is run at L0, L1 and L2.

---

## 4. Which model runs what

Every model runs a part of the same sample, so that models are compared on the same tasks.

| Model | Tasks of each repo | Prompts | Setups | Repetitions | Runs per repo |
|---|---|---|---|---|---|
| **Sonnet** (most runs) | all 15 | L0, L1, L2 | `grep`, `tool` | 3 | 90 for each repetition |
| **Haiku** (the cheap tier) | 6: numbers 1 and 2 of each level | L0, L1, L2 | `grep`, `tool` | 1 | 36 |
| **Opus** (the top; few runs, because of their cost) | 3: number 1 of each level | L0, L2 | `grep`, `tool` | 1 | 12 |
| **Open models:** the 9B first, then the 27B, then the 14B | 8: numbers 1 to 4 of easy and of medium | L0, L1 | `grep`, `tool` | 3 | 96 for each model |
| **Open models, a probe** | 3: numbers 1 to 3 of hard | L0 | `grep`, `tool` | 1 | 6 for each model |

- The three Claude models are for the presentation. Codex is considered for the paper.
- The open models run in their own harness and on their own machine. They use none of the
  Claude seats.

**What every run records:** whether the hidden tests pass; tokens; time; and the turn at which
the agent first sees a gold file in a result, first opens one, and first edits one. The last
three answer "did it reach the right place, and how fast", for the small models too.

---

## 5. The repos

All ten repos on `main` can carry tasks: each has enough candidates at every difficulty and a
written recipe. They are not equally worth the seats.

**For the presentation: six repos, five languages.**

| # | Repo | Language | Why it is worth running | What it costs |
|---|---|---|---|---|
| 1 | pandas | Python | a medium-size repo; its tasks are ready | little |
| 2 | playwright | TypeScript | a second language; its tasks are ready | little |
| 3 | ruff | Rust | a third language. Only 8% of its issues name the code that has to change, so even L0 is vague here | a Rust build |
| 4 | kubernetes | Go | a fourth language, in a very large repo | the smallest pool: 86 candidates, and 12 hard ones in the test split. If hard falls short of 5, tasks of the dev split fill it and are marked |
| 5 | duckdb | C++ | a fifth language; 21% of its issues name the code | a long C++ build for each image |
| 6 | home-assistant | Python | very large, 18,700 Python files: where an index should matter most. The largest pool | a long install, and a large index |

**For the paper, if seats are left:**

| Repo | Language | Why | What it costs |
|---|---|---|---|
| vscode | TypeScript | very large; 26% of its issues name the code; the most hard tasks | the costliest environment: a long build, and tests that need a display |
| trino | Java | a sixth language | a small pool: 64 candidates, 13 hard |

**Least worth running: airflow and vllm.** They would be the third and fourth Python repos, and
vllm's issues name the code more often than any other repo's (76%). They stay as the reserve if
one of the six cannot be built.

For comparison, the share of issues that name the code: pandas 57%, playwright 64%, kubernetes
55%, home-assistant 54%, airflow 60%.

Every fix in every pool was merged between July 1 and October 22, 2026.

---

## 6. The order

A repo is run as soon as its sample is ready. For what is ready:

1. Sonnet, repetition 1;
2. Haiku;
3. Opus;
4. Sonnet, repetitions 2 and 3.

A batch that is cut short then leaves a complete table with fewer repetitions, never a table
with holes. The `grep` run and the `tool` run of a task go turn about in the same batch, so that
their times can be compared. The open models run beside all of this.

---

## 7. How long

| | Runs, six repos | On three seats, at 5 to 7 minutes a run |
|---|---|---|
| steps 1 to 3 | 828 (Sonnet 540, Haiku 216, Opus 72) | 23 to 32 hours |
| step 4 | 1,080 | 30 to 42 hours |
| all Claude runs | 1,908 | 2.2 to 3.1 days without a pause |
| the open models | 612 for each model | about half a day for each model, if a run takes as long as a Claude run and six run at once on one GPU |

- **The 5 to 7 minutes are an assumption.** The pilot measured 4.3 to 5.5 minutes for Haiku at
  L0. Nobody has measured Sonnet or Opus, and vague prompts took more tokens in the pilot.
- **Usage limits are the unknown.** A seat pauses when it reaches its limit. So steps 1 to 3 are
  what the presentation counts on, and step 4 fills the time that is left until Nov 30, 23:59.
- Checking candidates, writing the L1 and L2 prompts and building the indexes come before a
  repo's runs and are not in these numbers.

---

## 8. What track A is asked to do

1. **For each repo, in the order of §5:** draw 20 candidates of each difficulty, validate and
   screen them, and stop a level at 7 fair tasks. Post the table of fair tasks per repo and
   level as each repo ends.
2. **Draw the sample** (§3), write its L1 and L2 prompts, and commit the list.
3. **Build each task's index** with the locked codemem, and run in the order of §6.
4. **After the first Sonnet batch,** post tokens and minutes per run, and how much of a seat's
   limit it used. The numbers of §7 are corrected from it.
5. **Say whether the PC's GPU can serve the open models** beside the embedding model: the 9B
   needs about 7 to 10 GB, the 27B about 18 GB. If not, Andre rents a GPU.
