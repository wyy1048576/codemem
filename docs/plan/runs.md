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
| hard | more: three to five files, or 101 to 200 lines |
| large | more again: 6 to 15 files, or 201 to 600 lines |

Task 68195 is easy.

**"Hard" is the hard end of small fixes.** The task files on `main` stop there: the collector
kept only fixes of at most 5 code files and 200 changed lines. A request that touches many files
is what codemem is meant for, so a fourth level, **large**, is collected for the repos that are
run fully (§10).

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
| fair | 17: 9 easy, 5 medium, 3 hard | 28: 11 easy, 9 medium, 8 hard |

So two to six candidates are checked for each task we can run, and the share differs by repo:
18% of pandas's valid tasks are fair, 57% of playwright's. Many pandas issues are old, and the
fix that came late is wider than the issue. We cannot check fewer by choosing better, because
nothing tells in advance which candidates are valid and fair.

**The rule that saves time:** check each difficulty level only until it has 7 fair tasks (the 5
of the sample and 2 spare), then stop that level.

---

## 3. The sample

**15 fair tasks per repo: 5 easy, 5 medium, 5 hard. Each has its three prompts,** so a repo has
45 requests. **The six repos that are run fully also get 4 large tasks each,** 3 if no more are
fair (§10).

- Drawn once per repo with the seeded sampler, from tasks that are valid and fair. Tasks of the
  test split come first: they are the ones no track tuned codemem on. The list is committed
  before the first run and does not change after it.
- The five tasks of each level are numbered 1 to 5 in the order they were drawn. The table of §4
  uses these numbers.
- A task that breaks during the runs is replaced by the next spare of its level, in every setup.
- **A level that has fewer than 5 fair tasks gives all it has,** and the repo's sample is filled
  to 15 from its other levels, the nearer level first. pandas has 3 fair hard tasks, and only 8
  hard candidates are left to check: its sample is 7 easy, 5 medium and 3 hard.

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
| **Sonnet and Opus, the large tasks** | the 4 large ones, in the six repos run fully | L0, L2 | `grep`, `tool` | Sonnet 3, Opus 1 | 16 for each repetition |
| **Open models:** the 9B first, then the 27B, then the 14B | 8: numbers 1 to 4 of easy and of medium | L0, L1 | `grep`, `tool` | 3 | 96 for each model |
| **Open models, a probe** | 3: numbers 1 to 3 of hard | L0 | `grep`, `tool` | 1 | 6 for each model |

- The three Claude models are for the presentation. Codex is considered for the paper.
- **The Claude runs go on Andrew's PC, and they come first there.**
- **The open models run on a rented GPU** (Nebius), in their own harness, started by Andre. They
  use none of the Claude seats and nothing of the PC.

**What every run records:** whether the hidden tests pass; tokens; time; and the turn at which
the agent first sees a gold file in a result, first opens one, and first edits one. The last
three answer "did it reach the right place, and how fast", for the small models too.

---

## 5. The repos, ranked

All ten repos on `main` can carry tasks: each has enough candidates at every difficulty and a
written recipe. They are not equally worth the seats. The rank says in which order they run and
how far. Three things decide it:

- **the language:** Rust, Python, C++ and TypeScript come first;
- **how vague the issues are:** the share of issues that name the code that has to change. The
  lower it is, the more a task needs search by meaning, even at L0;
- **the size of the repo, and what its environment costs.**

| Rank | Repo | Language | Issues that name the code | Why this rank | How far |
|---|---|---|---|---|---|
| 1 | pandas | Python | 57% | medium size; its tasks are ready; the check run (§6) starts here | fully |
| 2 | ruff | Rust | 8% | the vaguest issues of all: even L0 gives little to grep for | fully |
| 3 | duckdb | C++ | 21% | vague issues, in C++ | fully |
| 4 | playwright | TypeScript | 64% | its tasks are ready; medium size | fully |
| 5 | vscode | TypeScript | 26% | very large and vague, with the most hard tasks: where an index should show most. Fifth only because its environment is the costliest: a long build, and tests that need a display | fully |
| 6 | home-assistant | Python | 54% | very large, 18,700 Python files; the largest pool | fully |
| 7 | kubernetes | Go | 55% | a fifth language, very large. The smallest pool of these: 86 candidates, 12 hard ones in the test split | Sonnet, once |
| 8 | trino | Java | 27% | a sixth language. A small pool: 64 candidates, 13 hard | Sonnet, once |
| 9 | airflow | Python | 60% | a third Python repo | reserve |
| 10 | vllm | Python | 76% | a fourth Python repo, with the issues that name the code most often | reserve |

- **fully:** every row of §4, with the three Sonnet repetitions.
- **Sonnet, once:** one Sonnet repetition, so that the language is in the table.
- **reserve:** runs only in place of a repo above it that cannot be built.

If a hard level falls short of 5 fair tasks in the test split (kubernetes, trino), tasks of the
dev split fill it and are marked.

Every fix in every pool was merged between July 1 and October 22, 2026.

---

## 6. First, a check run

Before the batches are automated, one small batch shows that the whole chain works with the
locked codemem, and that the agent calls codemem.

**What runs.** On pandas and on one more repo that is ready (playwright, or ruff if it is): the
three tasks numbered 1, one of each difficulty, at L0 and at L2, in both setups, with Sonnet,
once. That is 24 runs, about an hour on three seats.

**It passes when:**

1. every run has a record and a grade, and none is discarded;
2. the proxy's token count equals the agent's own in every run;
3. **codemem is called:** `search_code` is called in at least 5 of the 6 `tool` runs at L2. In
   the pilot it was 17 of 18. At L0 the number is reported and not required: with a name to
   grep for, an agent often greps;
4. **every search is a search by meaning:** no `search_code` result holds `still loading` or
   `codemem cannot embed right now`, and `index_status` in one container says `watching: true`;
5. a person has read two `tool` transcripts: the search's result reaches the agent, and the
   agent uses it.

**What it also gives:** the first numbers for Sonnet: minutes and tokens per run, and how much
of a seat's limit 24 runs used. §8 is corrected from them.

**After it.** If it passes, its 24 runs are the first runs of the plan, not extra ones. If point
3 or 4 fails, the batches wait: track B fixes the wording that makes the agent call codemem, or
track C the index, before any more seats are spent.

---

## 7. The order

1. the check run (§6);
2. Sonnet, repetition 1, on repos 1 to 6 in the order of their rank;
3. Haiku, then Opus, on repos 1 to 6;
4. the large tasks of repos 1 to 6: Sonnet, repetition 1, and Opus;
5. Sonnet, repetition 1, on kubernetes and trino;
6. Sonnet, repetitions 2 and 3, on repos 1 to 6 in the order of their rank, the large tasks last.

A repo that is not ready when its turn comes is passed over and taken up when it is. A batch
that is cut short leaves a complete table with fewer repetitions, never a table with holes. The
`grep` run and the `tool` run of a task go turn about in the same batch, so that their times
can be compared.

---

## 8. How long

| | Runs | On three seats, at 5 to 7 minutes a run |
|---|---|---|
| steps 1 to 3 | 828 (Sonnet 540, Haiku 216, Opus 72) | 23 to 32 hours |
| step 4, the large tasks | 192 (Sonnet 96, Opus 96) | 5 to 7 hours, and more if large tasks run longer |
| step 5 | 180 | 5 to 7 hours |
| step 6 | 1,272 (1,080, and 192 on the large tasks) | 35 to 49 hours |
| all Claude runs | 2,472 | 2.9 to 4.0 days without a pause |
| the open models, on the rented GPU | 612 for each model | about half a day for each model, if a run takes as long as a Claude run and six run at once |

- **The 5 to 7 minutes are an assumption.** The pilot measured 4.3 to 5.5 minutes for Haiku at
  L0. Nobody has measured Sonnet or Opus, and vague prompts took more tokens in the pilot. The
  check run measures it.
- **Usage limits are the unknown.** A seat pauses when it reaches its limit. So steps 1 to 5 are
  what the presentation counts on, and step 6 fills the time that is left until Nov 30, 23:59.
- Checking candidates, writing the L1 and L2 prompts and building the indexes come before a
  repo's runs and are not in these numbers.

---

## 9. What track A is asked to do

1. **For each repo, in the order of its rank (§5):** draw 20 candidates of each difficulty,
   validate and screen them, and stop a level at 7 fair tasks. Post the table of fair tasks per
   repo and level as each repo ends.
2. **Draw the sample** (§3), write its L1 and L2 prompts, and commit the list.
3. **Build each task's index** with the locked codemem.
4. **Run the check run** (§6) and post its five points and the first Sonnet numbers. Go on only
   when it has passed.
5. **Then run in the order of §7.**
6. **The large level** (§10): collect again with the higher limit now; check a repo's large
   candidates when its sample of 15 is ready.

---

## 10. The large level

**Why.** No task on `main` has a real fix of more than 5 code files or 200 changed lines. That
is a setting of the task collector (`max_code_files = 5`, `max_code_lines = 200`), from the first
collection in October, which was made for the retrieval eval. A request such as "add OCR to the
upload pipeline", which touches many files, is what codemem is meant for.

**What the limit removed.** Among merged pull requests that fix exactly one linked issue and
change code:

| Repo | Such fixes | Larger than the limit | Share |
|---|---|---|---|
| pandas | 371 | 19 | 5% |
| home-assistant | 805 | 49 | 6% |
| duckdb | 231 | 22 | 10% |
| playwright | 244 | 35 | 14% |
| ruff | 285 | 55 | 19% |
| vscode | 1,026 | 253 | 25% |

Most fixes of one issue are small. The limit removed about 430 candidates in these six repos,
more than half of them in vscode. Larger work often comes as a pull request without a linked
issue, and such a pull request cannot be a task: there is no request to give the agent.

**How the level is made.**

1. The same collection again, for the six repos that are run fully, with the limit at 15 code
   files and 600 changed lines. Nothing else changes, so every task of today is found again.
2. A fix of more than 5 code files or more than 200 changed lines is **large**.
3. A repo's large candidates are validated and screened after its sample of 15 is ready, until
   4 are fair. Fewer large tasks pass the screen than small ones (of pandas's valid hard tasks
   11% are fair, of its easy ones 32%), so a repo may end with 3, and pandas, with 19
   candidates, with fewer.
4. Each large task gets its L1 and L2 prompts like any other. Sonnet and Opus run it at L0 and
   L2 (§4).
