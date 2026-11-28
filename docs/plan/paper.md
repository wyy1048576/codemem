# The paper: its argument, the results to show, and what is still to run

This file plans the paper and the presentation of December 1. It says what the paper argues, what
each section shows, which table or figure carries it, which experiment feeds that, who owns it, and
where it stands. The runs themselves are planned in [runs.md](runs.md); the evidence from other
work and its sources are in [overview.md](overview.md) §3.

- **Dates:** the results are frozen on Mon Nov 30 at 23:59 Pacific (soft). The presentation is on
  Tue Dec 1 at 14:00 Pacific. The paper is first submitted on Mon Dec 7 (soft), and is at the level
  of a conference by Thu Dec 10.
- **One rule for every number:** it is reported whichever way it comes out. The hypotheses of §2
  were written before the results.

---

## 1. The argument on one page

**The question.** When does an index help a coding agent that already has grep? We do not try to
replace grep. We measure what a local index adds next to it, and we explain what we find.

**Why it needs asking.** The products disagree, and almost nobody shows data (§3.2). The papers
that promote embeddings report how well they retrieve. A developer who adds an index to an agent on
the strength of those numbers may see no gain, and nothing published tells them why. We want them
to know before they try, not after.

**The claim, in one sentence.**

> An end-to-end study of when an optional, locally built code index helps an agent that already
> has grep, from small open models to frontier models, on tasks newer than the models, with
> precise and vague requests; and an explanation of why grep alone does so well: a large model
> already knows where things are in a public repo.

**Contributions, in the order the paper argues them.**

1. **The study.** grep against grep plus codemem, end to end: tasks solved, turns, tokens and
   cost. Three Claude models, a second agent (Codex) on a subset, and open models. Three levels of
   vagueness. Repos of different size and language. Every run record is published, so that others
   can analyse it.
2. **Why grep works so well.** A large model has read the public repos. Asked with no repo and no
   tools, it often names the file to change. So its first grep is already aimed. We show this in
   three ways, and we test it: on a renamed repo and with small models, that knowledge is gone
   (§4.5 to §4.7).
3. **The tasks, and a way to make a known repo unseen.** Fresh tasks from real issues, each in
   three wordings that are checked to stay solvable. And renaming: the same repo and tasks under
   new names and paths, so that a model's memory of the public repo no longer points anywhere.
4. **The system.** codemem, a local index that stays fresh and fits a laptop. It is the instrument
   of the study, and a small part of the paper.

**What we expect, stated as a guess.** The index should matter most where memory cannot help:
vague requests, very large or unseen code, and smaller models. The first results do not show the
first two (§2).

**What is new against the earlier plan** (the former §9 of overview.md):

- Contribution 2, why grep works, and renaming as its test.
- **Tasks solved is a primary measure,** beside tokens, turns and cost. It is the first thing a
  reader asks.
- **Time is not a headline measure** (§5).

---

## 2. The hypotheses, and where they stand on Nov 28

H1 to H5 are those of [overview.md](overview.md) §4. H6 and H7 are new. "So far" is Haiku,
repetition 1, on pandas and home-assistant (51 pairs), unless it says otherwise.

| # | Hypothesis | Tested by | So far |
|---|---|---|---|
| H1 | **Savings.** With codemem the same tasks take fewer tokens and turns, with no loss in tasks solved | the runs of [runs.md](runs.md) | turns −7%, tokens +2%, cost +9%, solved 39 against grep's 41. Not beyond chance |
| H2 | **Where.** The saving grows with the size of the repo and the vagueness of the request | the same runs, by repo and level | not so far. L1 is codemem's best level and L2 its worst. The large repo is no better than the mid-size one |
| H3 | **The model gap.** The index helps a small open model more than a frontier model | open models (§4.7) | not run |
| H4 | **Asking.** Results placed up front matter more than the tool | the records; the side sample of runs.md §11 | with the 20 lines, Sonnet called the tool in 0 of 61 sessions (the v3 check); Haiku called it in 17 of 51 runs |
| H5 | **Cost.** A local index is cheap enough to be worth it | track C | the compact index returns the same top results on vLLM in 106 MB against 278 MB ([track C's results](../analysis/track-c-results.md)) |
| H6 | **Memory.** grep does well because the model already knows where things are | the memory probe, the first command, the oracle (§4.5) | Haiku's first command names a fix file that the prompt does not hold in 16 of 27 pandas runs and 4 of 24 home-assistant runs. With no repo and no tools, Sonnet named the right file in 15 of 17 pandas tasks |
| H7 | **Unseen.** When memory is removed, the index helps more | renamed repos (§4.6); small models (§4.7) | not built |

**If the answers are "no".** A careful negative result is worth reporting. The industry has
settled this question without publishing data. "A local index does not help a frontier agent on a
public repo, here is by how little, and here is why" is a finding with intervals around it. H6 is
what turns it from a number into an explanation.

---

## 3. The paper, section by section

### 3.1 Introduction

- The question, and that the goal is a study, not a replacement for grep.
- The motivation of §1: a reader should not get a rude shock.
- The four contributions, and the main results in three sentences.

### 3.2 Background and related work

Three points, each with its evidence in [overview.md](overview.md) §3.

1. **The long contention.** Claude Code and Codex have used grep from the start. Cursor used
   embeddings until July 2026 and now uses a local text index for fast grep. GitHub Copilot keeps
   a semantic index on its servers. So is there merit left in an index?
   - **Say exactly this:** only Anthropic has said that grep works better, and it gave no numbers.
     OpenAI uses grep and has published no comparison.
2. **We have to be fair to the literature.** We cannot say "use grep because the large labs do".
   - Work that promotes embeddings shows that they retrieve well, and stops there.
   - A few studies go end to end (overview.md §3.2). Each covers one model tier, uses issue texts
     as prompts, and most use SWE-bench Verified, which the models may have seen.
   - **So the gap is the combination,** not "nobody ran an agent": tasks solved, tokens and cost
     together; from small open models to frontier models; tasks newer than the models; vague
     requests; the index's own cost; and an explanation of the result.
3. **An open record.** The labs and most studies publish no run records. We publish every run:
   the request, each turn, each tool call, the tokens, and the grade.
4. **grep itself changed, and for the reason we measure.** *(reported: from search results; the
   pages are still to be read)*
   - **2024, research agents.** SWE-agent wrapped search in purpose-built commands (`find_file`,
     `search_file`, `search_dir`) with simple arguments and capped output, because raw grep was
     hard for the models of the time
     ([paper](https://arxiv.org/abs/2405.15793v3),
     [its interface](https://princeton-nlp.github.io/SWE-agent/background/aci)).
   - **Claude Code, until April 2026,** had dedicated Grep and Glob tools beside its shell tool,
     each with a description in the prompt.
   - **From version 2.1.117,** on native macOS and Linux builds, those two tools are gone. Search
     goes through the shell, with fast search programs built in. The release note gives the
     reason: "faster searches without a separate tool round-trip"
     ([what's new, 2026 week 17](https://code.claude.com/docs/en/whats-new/2026-w17)).
   - **Our runs use 2.1.332.** The agent has no search tool at all: it types `grep` into the
     shell. §4.5 shows what that buys it.

**How we differ from the closest work.**

| Study | It has | It lacks |
|---|---|---|
| Code Isn't Memory | end to end; tokens and time | one model; 91 tasks; issue texts; index cost not counted; a closed system |
| Bellam | model sizes from 0.6B to 32B; a placebo; pre-registration | localization only; Python; no completion |
| CodeNib, CodeGrep | completion for mid-size models; index build cost | results up front only; SWE-bench Verified; one model each |
| ColGREP | a local tool; time and tokens | models under 2B; file localization only |
| Sourcegraph CodeScaleBench | 370 tasks, 9 languages | the two setups had different access to the code; a vendor's product |

### 3.3 The benchmark

- **A task** is a real GitHub issue, the fix that was merged for it, and the tests that came with
  the fix. The tests stay hidden and grade the agent's change. Every fix was merged between July 1
  and October 22, 2026, after the models were trained.
- **Three wordings of each task** (runs.md §1): L0 is the issue as written; L1 has every name of
  the code removed; L2 is a short request in a user's voice. Each wording is checked to stay
  solvable.
- **Three tiers, by the size of the fix:** easy (at most two files and 100 lines), medium (three
  to five files, or 101 to 200 lines), hard (6 to 15 files, or 201 to 600 lines). The tier belongs
  to the task, not to the repo.
- **The repos** are described by language, size, and the share of issues that name the code
  (runs.md §5).
- **What a task is checked for** before it runs: it builds, its tests fail before the fix and pass
  after it, and a screen judges it solvable from the repo. Case 1 of the case studies shows one
  that passed the screen and is not.
- **Renaming** (§4.6), with its own checks.

### 3.4 The system

Short: one figure, half a page, and the appendix for the rest.

- **What codemem is:** a local index with three representations (vectors, keywords, structure),
  kept fresh while the agent edits.
- **How an agent gets it:** the 20 best results of one search at the top of the first message,
  and a search tool for more. The first search is made for the agent, because not every model
  asks for one.
- **Why local.** Private code cannot always leave the machine. We also expect personal agents and
  locally run models to grow, and an index for them has to live where they do.
- **What makes it fit a laptop** (track C): the compact index, vectors at half size, a memory
  budget, and a build that a faster machine can share. Reported in T6.

### 3.5 Results and analysis

The tables and figures of §4, in that order: the tasks; retrieval alone; the main comparison;
where the effect is; why grep works; unseen repos; the model gap; the second agent; the index's
cost; the case studies.

### 3.6 Limits

- One index stands for "indexed search". T2 shows that it retrieves well, so a small effect is
  not a weak retriever.
- One main harness (Claude Code), with Codex on a subset.
- The samples are small: an effect under about 12 to 15 points in tasks solved cannot be shown.
- The repos are public, even if the tasks are new. That is the subject of §4.5 and §4.6.
- Time was measured under load (§5).

---

## 4. The results: each table and figure

"Owner" is the track that makes it. "Status" is on Nov 28.

### 4.1 T1: the tasks

- **Shows:** the repos (language, size, share of issues that name the code) and the tasks per tier
  and level.
- **From:** `eval/tasks/run-sample-v1.jsonl`. **Owner:** track A. **Status:** have.

### 4.2 T2: retrieval alone

- **Shows:** on the same requests, how often each search puts a fix file or function near the
  top: grep with keywords from the request, keywords alone (BM25), vectors alone, and codemem.
  Per level L0, L1 and L2. This is the comparison that other papers stop at, and it shows that
  codemem is a competent retriever.
- **From:** the retrieval eval at the locked codemem (`463171c`) on the run sample. Two parts are
  in hand: the October runs on three languages at an earlier codemem, and, from the run records,
  the rank of the first fix file in the 20 lines of every task and level.
- **Owner:** track B, or track C if track B is still on its audit on Nov 29. **Status:** to run.
  No seat is needed.

### 4.3 T3 and F1: the main comparison

- **Shows:** grep against grep plus codemem, per model and level: tasks solved, turns, tokens,
  cost. F1 is the same as one picture: the ratio of codemem to grep with its interval, one row per
  model and level.
- **From:** the runs of runs.md. **Owner:** track A for the runs and their reports; track C for the
  paper's tables.
- **Status:** Haiku, repetition 1: pandas and home-assistant done; ruff, duckdb, playwright and
  kubernetes running or queued. Sonnet starts when a stream's Haiku steps are done. Opus is not
  queued yet.

### 4.4 T4 and F2: where the effect is

- **Shows:** the same effect by level, by repo and by tier. And where the turns go: before and
  after the first edit, and the turn at which the first fix file is opened.
- **From:** the same records. **Owner:** track C. **Status:** have for two repos.
- **So far:** codemem opens a fix file on turn 1 in 29 of 51 runs, against grep's 6. It spends
  about as much before the first edit and less after it on pandas, and the reverse on
  home-assistant. Finding gets faster; the total does not follow.

### 4.5 Why grep works so well (H6)

Seven pieces. All but the oracle come from records we have or from runs that cost little, and the
first results are in.

**What they add up to so far** (Haiku, repetition 1, pandas and home-assistant): grep is not
optimal in general, but in these runs it is within one or two turns of a perfect search. Five
reasons, each measured below: finding is a small part of the job; the model often knows where to
look; where it does not, the request's own words lead grep there; in the shell, search and read
are one turn; and a new tool has a price on every request.

1. **T5, the memory probe.** Each task's request is given to each model with no repo and no tools,
   and the model names the file it would change.
   - **So far**, on the tasks that were ready on Nov 27: Sonnet named the right file first in 15
     of 17 pandas tasks, 13 of 20 kubernetes, 10 of 28 playwright and 12 of 41 duckdb. On duckdb,
     Haiku named 7 of 41 and Opus 22.
   - **To do:** the run sample, all three levels, all three Claude models. **Owner:** track C. It
     uses no seat of the eval's machine.
2. **F3, the first command.** In a grep run, does the agent's first command already name a fix
   file that the prompt does not hold?
   - **So far** (Haiku): 16 of 27 pandas runs and 4 of 24 home-assistant runs. At L1, where the
     prompt has no name of the code, it is still 7 of 9 on pandas.
   - grep opens a fix file by turn 3 in 23 of 27 pandas runs and 22 of 24 home-assistant runs. So
     finding costs grep two or three turns, and that is all a better search can save.
   - **To do:** every record, every model. **Owner:** track C.
3. **The oracle, proposed.** A third setup on a subset: the first message names the fix files, as
   a perfect search would.
   - grep against the oracle is the most that any index could save. grep against codemem, set
     beside it, says how much of that codemem gets.
   - It needs seats. **Decision:** §8, point 1.
4. **F4, memory against effect.** One point per model and repo: how often the model names the file
   from memory, against what codemem saves there. H6 predicts that the saving falls as memory
   rises.
5. **The ceiling, from grep runs alone.** How much of a grep run is spent before the fix file is
   open, beyond the first turn. That is the most a perfect search could save, with no oracle run.
   - **So far:** 8% of the turns and 6% of the tokens, in 54 runs. codemem wins back about 2 of
     those 6 points.
   - **It is the first thing to measure in any new setting** (§4.6, §4.7): it needs grep runs
     only, and it says whether an index has room to help there.
6. **Search and read in one turn.** In 49 of 51 grep runs, the agent's first command chains a
   search and a read (`grep ... && sed -n ...`). A codemem search is one call, and reading the
   file is another. This is the reason the release note of §3.2 gives for dropping the search
   tools.
7. **The price of a new tool.** The model knows grep from its training, so the shell needs no
   words about it. A tool the model has never seen has to be described on every request.
   - Every request carries about 36,000 tokens of standing prompt in both setups. codemem adds
     about 2,500: its four tool descriptions, three resource tools that Claude Code adds for any
     MCP server, and the 20 lines.
   - Over the 778 requests of the codemem runs that is about 1.9M tokens, against a gap of 1.6M
     between the setups. Without it the two would be even.
   - **For the paper:** an index's fixed prompt is paid on every turn, and can cancel what its
     search saves. Trimming it is a change for after the freeze (codemem is locked for the runs).

### 4.6 Unseen repos: renaming (H7)

**The idea.** Take a repo that the models know, and give every file, folder, class and function a
new name, the same way everywhere: in the code, the tests, the request and the real fix. The code
works as before. But what a model remembers of the public repo, its paths and names, no longer
points anywhere. It stands in for a private codebase.

**What has to hold, for each renamed task:**

- the tests fail before the renamed fix and pass after it, as in the original;
- the request names nothing that no longer exists;
- **memory is gone:** the memory probe on the renamed task falls to about zero. This is the check
  that the renaming did what it is for.

**Two kinds of new names**, because the choice matters for a search by meaning:

- **names that keep the meaning** (`merge_asof` becomes `join_nearest`): the fair test. A search
  by meaning can still work, and a remembered name cannot;
- **names with no meaning** (`fn_4821`): the stress test, which also takes away what grep and a
  search by meaning both read in a name.

**What it shows:** T7, the main comparison again on the renamed tasks, beside the original ones:
tasks solved, turns, tokens, the memory probe, and the first command.

**Order:** a pilot on pandas and its 9 tasks. **grep alone first, to measure the ceiling**
(§4.5, piece 5): if grep still opens the fix file in two or three turns on a renamed repo, an index
has no room there either, and that is the finding. If it needs many more, both setups run. Then
the decision on a second repo. **Owner:** to be named (§8, point 2). **Status:** not built. The presentation shows
it as pending.

### 4.7 The model gap: open models (H3), and F5

- **Shows:** T8, grep against codemem for the open models of runs.md §4: the 9B first, then the
  27B, then the 14B. Tasks solved where they solve any; else the turn at which the fix file is
  found.
- **F5, the trend:** the saving from codemem against the size of the model, from 9B to Opus, one
  line per level. With F4 it is the paper's answer to "when": the less a model knows of the repo,
  or the smaller it is, the more an index should help. Both are guesses until the runs are in.
- **Order:** grep alone first, for the ceiling (§4.5, piece 5), as with the renamed repos.
- **From:** the open harness on the rented GPU. **Owner:** Andre. **Status:** the harness is
  paused work; the presentation shows it as pending.

### 4.8 A second agent: Codex

- **Shows:** T9, the main comparison in Codex on a subset, to see whether the result belongs to
  Claude Code or to agents with grep.
- **Owner and subset:** §8, point 4. **Status:** not started.

### 4.9 T6: what the index costs

- **Shows:** build time, disk and memory against the size of the repo, for the exact and the
  compact index, and the time of one search. And job 1: the two indexes end to end on kubernetes
  (runs.md §12).
- **Owner:** track C for the table; track B for job 1. **Status:** the table has its numbers; job 1
  waits for a machine.

### 4.10 The case studies

- **Shows:** two or three runs that explain a number, from `case-studies.md` on the `worklog`
  branch. Today: a fix that needs a fact outside the repo; the right function found and a bigger
  fix than the tests want; look-alike results that the agents ignore.
- **Owner:** track C.

---

## 5. Measures, and how they are reported

- **Primary:** tasks solved, tokens, turns, and cost at list prices. A run at the turn or the time
  limit counts as not solved.
- **The unit is the pair:** the same task at the same level by the same model, once in each setup.
  Repetitions are averaged per task first.
- **Every difference comes with:** an interval (a bootstrap over tasks), the number of pairs in
  which codemem was lower, and a sign test.
- **A task of a case study stays in every total.** The numbers without it stand beside the total,
  not in its place.
- **Time.** The runs so far had builds and a second stream beside them, unevenly between the two
  setups (the marks of each archive). So seconds from these runs are shown only with their marks,
  in the appendix.
  - Most of a run's time is the model's own latency, which turns already count.
  - If the paper is to make a claim about time, it needs its own small measurement: a subset of
    tasks, one stream, nothing beside it, both setups, three repetitions, with codemem's start
    and each search timed apart. **Decision:** §8, point 3.
- **What reviewers of a benchmark track check** *(reported; overview.md, Sources)*: the claim and
  its limits are stated; another team can rerun it; contamination is addressed; variance is
  reported with repetitions and paired intervals; the grading tests are sound; novelty is argued
  against named work. Negative results count "when rigorously supported".

---

## 6. One paper, and where it could go

**One paper.** The study, the explanation and renaming are one argument: a result, why it is so,
and a test of the why. Split in two, each half is weaker. The system is the instrument: a short
section here, and a tool paper later if we want one.

**The paper is also the course's final report,** first submitted on Dec 7.

**Where it could go afterwards.** Not part of this plan's deadlines. All *(reported)*.

| Venue | Deadline | Fit |
|---|---|---|
| **NeurIPS 2027, Evaluations & Datasets** | not announced. In 2026 the abstract was due May 4 and the paper May 6. Nine pages | the best fit for the study. It needs the renamed repos and the open models to be in |
| ICLR 2027 workshops | papers suggested for Feb 1, 2027 | the December paper as it stands |
| FSE 2027 tool demonstrations | Jan 26, 2027; 4 pages | codemem as a tool: the second, smaller paper |
| TMLR | rolling | no deadline to meet |

**What decides the level.** With H6 shown and H7 tested on renamed repos and open models, this is
a study with an explanation and a test of it, which a main benchmark track can take. Without them
it is a careful comparison on two setups: a workshop paper, or a tool demonstration.

**What the NeurIPS track requires** *(reported)*: the data hosted and reachable without asking the
authors; a Croissant metadata file; code at submission. Review is double-blind by default.

---

## 7. The presentation of December 1

Five minutes and two for questions, to a small audience. The same deck as the checkpoint, brought
up to date. Results that are not in are named as pending, with the date of the paper.

| Slide | What it says | From |
|---|---|---|
| 1. The question | the contention in one table; "does an index still help an agent that has grep?"; a study, not a replacement | §3.2 |
| 2. What exists | embeddings are shown to retrieve well; few studies go end to end, each on one model tier; nobody explains the result | §3.2 |
| 3. Our design | the tasks and their three wordings; the two setups; what is measured | §3.3 |
| 4. codemem | the same picture as before, with what is new: the compact index and the memory budget | §3.4, T6 |
| 5. Results | T3 for the models that are in: tasks solved, turns, tokens, cost | §4.3 |
| 6. Why grep works | the memory probe and the first command: the model already knows where to look | §4.5 |
| 7. What comes next | renamed repos, open models, Codex, more repetitions: "in the paper, Dec 7" | §4.6 to §4.8 |

---

## 8. Decisions needed from Andre

1. **The oracle setup** (§4.5): yes or no, and on which subset. It is the one extra set of runs
   that bounds the whole question.
2. **Who builds renaming,** and whether the pilot is pandas.
3. **Time:** its own small measurement after the freeze, or no claim about time.
4. **Codex:** who runs it, and on which subset.
5. **A second retriever.** The 20 lines can come from keywords alone or vectors alone at no cost
   in code. One such setup on a subset would show that the result is not codemem's alone. Yes or
   no.

---

## 9. The order of work

| By | What | Owner |
|---|---|---|
| **Mon Nov 30, 23:59 Pacific** | Haiku's repetition 1 on every repo; Sonnet's repetition 1 as far as it is | track A |
| | T2, retrieval on the run sample | track B, or C |
| | T5, the memory probe on the run sample; F3, the first command on every record; the script that makes the paper's tables from the release archives; T6 | track C |
| | the slides | Andre, with track C |
| **Tue Dec 1, 14:00 Pacific** | the presentation | all |
| **Mon Dec 7** | the renaming pilot; the open models; Codex on its subset; the oracle if decided; Opus and the repetitions of runs.md; the paper's first submission | as named in §4 and §8 |
| **Thu Dec 10** | the paper at the level of a conference | all |
