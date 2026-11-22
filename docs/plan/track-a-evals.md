# Track A: the evaluation pipeline

**Status:** a plan, written Nov 22, 2026. Nothing here is built yet. The shared context is in
[overview.md](overview.md). The eval that exists today is described in
[eval/README.md](../../eval/README.md).

**Goal.** One pipeline that hands a real task to a coding agent, with and without codemem, and
records whether the agent completed it, how long it took and how many tokens it used. The pipeline
comes first. Once it runs, tracks B and C change codemem and rerun it, many times.

**Done means, in this order:**
1. **the pipeline:** one command runs a chosen set of tasks, setups and models, and can be stopped,
   resumed and repeated; flags and a plan file choose what runs;
2. **trusted measurement:** tokens and time for every run, from two independent sources that must
   agree;
3. **tasks:** from public sets that already ship containers. Our own, generated from a GitHub
   repo link and newer than the models, get a trial at most in this phase (§8.2);
4. **labels** on every task, so a plan can say "medium tasks only" before anything runs;
5. **vague versions** of each prompt, checked to be still solvable;
6. **the small-model study** at about 9B and 14B, which are today's models in the 7B and 13B
   classes, with a 27B follow-up;
7. the retrieval eval kept short, with a vague query per task and two stronger baselines;
8. a release with the paper: the pipeline, the task list with its labels and vague prompts, and
   the run records.

**When.** Items 1 and 2 by Nov 25. First results on the rest by December 1, refined by December 8,
when the paper goes to arXiv (§14).

**Where to start.** Not with everything: with a pilot on two or three repos (§2.2), on the codemem
that exists today (§2.3).

**What this track does not judge.** Retrieval accuracy is not the goal here. The agent may solve a
task any way it likes. What counts is whether it solved it, how long it took, and how many tokens
it used.

---

## 1. In plain words

Today's eval asks a search system one question per task: given this issue, which code would you
show? It grades the answer against the code the real fix changed. No agent is involved. That says
whether codemem *can* find code. It does not say whether an agent with codemem does its job
better.

The new pipeline hands the whole task to an agent and watches what happens.

**The running example.** A repo with an upload service. Audio uploads already go through a
"transcribe" stage. A developer merged a pull request that adds an OCR stage for images, with
tests. That pull request becomes a task:

| Part of the task | In the example |
|---|---|
| the repo, frozen just before the pull request | the upload service at commit `a1b2c3` |
| the prompt | "Add OCR to the upload pipeline, so that text in uploaded images can be searched." |
| the hidden tests | the pull request's own tests for the OCR stage, which fail before it and pass after it |
| the answer key, for analysis only | the files the real change touched, and the existing stage it was modelled on |

One **run** is one agent working once on one task in one setup:

```
 setup "grep"                              setup "codemem"
 the agent as shipped:                     the same agent,
 grep, file listing, file reads, shell     plus codemem's search tools
        │                                         │
        ▼                                         ▼
   works on the repo until it says it is done, or hits a limit
        │                                         │
        ▼                                         ▼
   the hidden tests run on what it left behind
        │                                         │
        ▼                                         ▼
   completed? · seconds · tokens · what it searched and read
```

If codemem helps, the second run reaches the transcribe stage and the registry in one search
instead of several greps and file reads, and the difference shows up as fewer tokens and seconds.
If it doesn't, the two runs look the same, and that is a finding too.

---

## 2. The pipeline at a glance

```
  a plan file                tasks (JSON lines)            codemem configurations
  what to run                with labels                   today · final · any branch
       └──────────────┬───────────┴───────────────────────────────┘
                      ▼
   1. PLAN     expand the plan into a list of runs; show how many, and what they will cost
                      ▼
   2. INDEX    build or reuse the codemem index for each task and configuration
                      ▼
   3. RUN      one container per run: the agent works; the recorder captures everything
                      ▼
   4. GRADE    a clean container applies the agent's changes and runs the hidden tests
                      ▼
   5. SCORE    tokens, time and steps, computed from the records
                      ▼
   6. REPORT   tables with intervals; any two setups compared on the same tasks
```

Each stage is its own command, writes its results to disk, and can be rerun alone. Scoring and
reporting never call a model, so they can change without spending anything.

```bash
cmeval e2e plan   plans/main.toml --dry-run      # how many runs, estimated tokens and hours
cmeval e2e index  plans/main.toml                # build what is missing, reuse the rest
cmeval e2e run    plans/main.toml --run-id main-1 --seats seat-1,seat-2,seat-3
cmeval e2e grade  main-1
cmeval e2e score  main-1
cmeval e2e report main-1 --compare grep tool --by difficulty,repo_size,vagueness
cmeval e2e check  main-1                         # did every run pass its integrity checks?
```

It lives in `cmeval`, next to the retrieval eval, and shares its task format, token cache,
dashboard and statistics code (§2.1).

### 2.1 What is reused from today's eval

`cmeval` was built to grade search systems. Its frame carries over. The part that runs an agent is
new.

| Reused as it is | New |
|---|---|
| task files, dev and test splits, `subset` and `--where` selection | running an agent: the container, the Claude Code launch, mini-SWE-agent |
| `collect`, `repo-stats` and the gold labels | the recording proxy and the cross-check (§5) |
| `report`: intervals, paired tests, grouping by label | grading with hidden tests |
| `dashboard`, for long jobs | an importer for SWE-bench-Live (today's knows SWE-bench Verified only) |
| the token counter and its cache | the vague-prompt rewriter (§9) |
| the codemem adapter and the grep baselines | |

The existing plug is a `Retriever` with `build`, `update` and `search`. An agent run does not have
that shape, so the end-to-end runner is a new module beside it, not a new adapter. The
localization tier (§12.1) is the cheapest bridge: it grades an agent's answer with the gold labels
and accuracy metrics that exist.

### 2.2 Start small: two or three repos first

This file designs the whole study. The build does not start with the whole study. Before any large
batch, and before every task's repo is indexed, the whole chain has to run on a small pilot, where
an error is cheap to see and to fix.

**The first job of whoever picks up this track, person or agent: propose the pilot repos, with
reasons, before building on them.**

| The pilot | |
|---|---|
| Repos | two or three, each in a different language: Python, TypeScript, and one of Go, Rust, Java or C++ |
| Tasks | 3 to 5 per repo, 10 to 12 in all, of mixed difficulty: easy, medium, and at least two hard ones (§10) |
| Setups | `grep` and `tool` |
| codemem | what exists today, with its local embedding model (§2.3) |
| Agent model | Haiku 5.5 while the chain is being built, then Sonnet 5.5 |

**How to choose the repos:**
1. **From SWE-bench-Live** (§8.1), so every task already has an image, test commands and a grader.
2. **A language codemem indexes:** Python, JavaScript or TypeScript, Go, Java, Rust, C or C++
   (`src/codemem/languages/`).
3. **Medium size.** Large enough that search matters: at least 1,000 source files. Small enough
   that today's codemem indexes it in minutes with the local model, not hours.
4. **At least five tasks, spread over easy, medium and hard,** counted from the files and lines of
   the real change (§10).
5. **It works on our machine.** For one task per repo, pull the image, apply the real change and
   run its tests by hand. Keep the repo only if they pass, in under 5 minutes.
6. **If possible, one task of the OCR kind:** a change that adds something modelled on code that
   already exists.

**The pilot has passed when all of this is true:**
- every stage runs for every pilot task in both setups: plan, index, run, grade, score, report;
- the grader is right: for every pilot task the real change passes, and an empty change fails;
- the two token counts agree within 1% on every run (§5.3);
- the first event of every `tool` run lists codemem's tools, and some runs call them;
- a batch can be stopped and resumed, and a deliberately broken setup is caught (§7);
- one of us has read three whole transcripts, one per repo.

Only then do more tasks, more repos and the dev batch follow.

**Small also because the index is about to shrink.** Today's index keeps every vector in memory at
full size and loads a 2.2 GB model: for 200,000 vectors, 358 MB of memory and 717 MB of disk
([track C](track-c-memory.md) §3). Tracks B and C are changing what is indexed and how it is
stored, and track C's target for the same vectors is under 30 MB of memory. Every repo indexed
today is indexed again when that lands. So index the pilot repos now, and the rest when a batch
needs them. Tracks B and C announce each new configuration in the work log
([CONTRIBUTING.md](../../CONTRIBUTING.md) §3), and the pilot repos are where it is tried first.

### 2.3 Which codemem, and which embedding model

**The pipeline is general on purpose.** It does not know what is inside codemem. It is handed a
codemem configuration file and treats codemem as a black box: an MCP server, a command and an
index folder (§15). So it runs whatever codemem can build: today's version, a branch of track B or
C, the final one. Tracks B and C are still changing retrieval and storage, and the pipeline must
not need a change when they do.

**Now: what exists today, with a local embedding model.** The first runs use today's codemem and
its default local model (`jinaai/jina-code-embeddings-0.5b`), or the local model track B chooses
in its place ([track B](track-b-retrieval.md) §5).

**Later: Qwen3-Embedding-8B through Nebius.** codemem can already do this. Its configuration takes
any OpenAI-style embedding API:

```toml
[embedding]
provider = "openai"
base_url = "https://api.tokenfactory.nebius.com/v1"
model = "Qwen/Qwen3-Embedding-8B"
api_key_env = "NEBIUS_API_KEY"
dimensions = 1024
```

So for the pipeline, another embedding model is another codemem configuration, and nothing else.
Four things make that swap work, and they are built from the start:

1. **Embedding settings live in the codemem configuration,** never in pipeline code.
2. **The key travels safely.** The runner passes the variable named by `api_key_env` to wherever
   codemem runs, which is the index stage and the agent's container, and never writes it to disk.
3. **The network rule has one exception.** A run may reach the embedding API's host, and nothing
   else besides the model API (§4.5).
4. **Every run records its index key,** so a result always says which model made its vectors.

**One index holds one embedding model's vectors.** Vectors from two models cannot be compared, so
they never share an index.
- *In codemem,* a repo has one index. Changing the model embeds the repo again and replaces the
  old vectors. Keywords and structure stay.
- *In the pipeline,* indexes are stored per configuration key, and that key includes the embedding
  provider, the model and the vector length. Two models give two separate indexes of the same
  repo, side by side. Neither replaces the other.

Comparing embedding models is worth doing, and it costs one full build per model for every repo.
So it is done on the pilot repos first.

**Where the embedding happens during a run.** The index is built before the run, on the host. At
search time codemem still embeds the query, and any code the agent has edited, inside the
container, which has no GPU. With a local model there are two ways, and the pilot decides:
- **in the container, on the CPU:** the simplest. Measure how long one search takes there;
- **from a server on the host:** the local model behind an OpenAI-style endpoint, which codemem
  reaches through the same `provider = "openai"` setting with no key. It uses the host's GPU,
  keeps PyTorch out of the container, and is the same path as Nebius.

Either way, codemem's own log splits a search into its steps (§5.5), and the embedding step is
reported apart. A slow CPU in a container must not be mistaken for codemem's cost on a laptop.

### 2.4 Which tasks serve which measurement

Three measurements, two sources of tasks. The split follows from one fact: to know whether an
agent fixed an issue, the project's tests must run on what it wrote, and that needs a working
build of the project for every task.

| Measurement | The question | An agent? | Tests? | Tasks come from |
|---|---|---|---|---|
| Retrieval | given the issue text, does codemem rank the right function near the top? | no | no | our own task sets: 12 repos, 3,788 fresh tasks |
| Agent localization (§12.1) | how much does an agent spend to name the functions it would change, and is it right? | yes | no | our own task sets |
| End to end | does the agent fix the issue, and at what cost in tokens and time? | yes | yes | SWE-bench-Live, which ships an image and tests for each task (§8.1) |

Our own tasks are newer than the models and come from large repos, but they have no test
environment. The public tasks have one, and most of them are older than the models. So the two
sources are not rivals: each serves the measurement the other cannot.

### 2.5 The proposed pilot, in two steps

This answers §2.2. Step 1 needs no container, so it can start today. Step 2 is the pilot of §2.2.

**Step 1: the index and localization check, on pandas and playwright.** These are two repos of
our own task sets, so this step uses no public task and no test.

- **Why these two.** They are the smallest repos of the retrieval eval: 43,870 and 27,483 texts to
  embed at the first build, 16 and 12 minutes cold on the M5. They are Python and TypeScript. Both
  have October results to compare with (`eval/results/2026-10-26-py100` and `-ts50`).
- **Passed when,** for both repos: (1) the index builds cold with the local model, and a stopped
  build resumes; (2) the update-against-rebuild check passes; (3) one task runs through the runner
  in the localization tier in both setups, `grep` and `tool`, and the agent's codemem calls are
  answered from that index; (4) build time and update time are recorded.
- **What it does not test.** Both builds are short. They have no update as large as vscode's (a
  median of 8,730 texts for each step), and they say nothing about an API's rate limit over hours.
- **After it passes,** the other seven repos of the retrieval eval are indexed when a batch needs
  them. For the later API route (§2.3), one machine runs three processes, each with its own key
  and its own repos, and `cmeval merge` combines the run folders: vscode; Godot and
  home-assistant; duckdb, transformers, airflow and llama.cpp. That split balances the texts to
  embed (about 518,000, 600,000 and 566,000, from the October run logs). Three processes that
  share one vector cache have not been tried yet.

**Step 2: the graded pilot, on three repos from SWE-bench-Live.** The task tables were downloaded
on Nov 22 (the `verified` split of the Python set, and the `ts`, `go` and `rust` splits of the
multi-language set). Difficulty is the rule of §10, counted from each task's real change.

| Language | Proposed | Files in the language | Tasks: easy, medium, hard | Reserve |
|---|---|---|---|---|
| Python | **keras-team/keras** | 1,001 (12.0 MB) | 13: 4, 3, 6 | conan-io/conan (1,110 files; 29 tasks: 19, 8, 2), pylint-dev/pylint (29 tasks: 13, 9, 7) |
| TypeScript | **mui/base-ui** | 2,171 (10.1 MB) | 5: 1, 3, 1 | TanStack/router (8,993 files; 8 tasks: 4, 1, 3) |
| Rust | **rust-lang/rust-analyzer** | 1,510 (17.8 MB) | 12: 7, 3, 2 | biomejs/biome (5,568 files; 8 tasks: 2, 5, 1) |

- **Why keras.** It is the Python repo that passes the size rule with real product code and has
  the most hard tasks. matplotlib (26 tasks) has 914 files and is also in SWE-bench Verified, so
  models know it better. pylint's 2,539 Python files are 4.1 MB in all: most are small test inputs.
- **Why base-ui.** Of the six TypeScript repos with five tasks or more, it is the one with tasks
  at all three levels and a medium size.
- **Why Rust as the third language, and rust-analyzer.** Rust has 12 repos with five tasks or
  more; Go has 3. And 7 of rust-analyzer's 12 tasks were created after June 2026, so they are
  newer than the model. Go's best repo is gohugoio/hugo (913 files; 7 tasks: 3, 3, 1).
- **No overlap with our own repos,** except apache/datafusion (9 Rust tasks, none easy).
- **Not checked yet.** Rule 5 of §2.2: nobody has pulled an image and run a task's tests on our
  machine. The images are x86 only, so this is done on the x86 machine, and a repo whose tests
  take over 5 minutes gives way to its reserve. The file counts are from today's default branch
  and include test files. Index times are not measured.

---

## 3. Choosing what to run

Not every setup deserves every task. A run costs usage and minutes, so the pipeline's first job is
to make selection easy and explicit.

### 3.1 Flags

Every flag narrows the list of runs. They combine.

| Flag | Chooses | Example |
|---|---|---|
| `--tasks FILE` | the task file | `tasks/e2e-v1.jsonl` |
| `--where KEY=VALUE` | tasks by label, repeatable | `--where difficulty=medium --where language=python` |
| `--sample N --seed S` | a fixed random subset, the same every time | `--sample 20 --seed pilot-1` |
| `--limit-per-repo N` | at most N tasks per repo | `--limit-per-repo 10` |
| `--setups LIST` | the tool setups (§4.1) | `--setups grep,tool` |
| `--codemem NAME` | which codemem configuration | `--codemem today`, `--codemem final`, `--codemem ./my-branch.toml` |
| `--models LIST` | the models | `--models claude-sonnet-5-5` |
| `--harness NAME` | the agent harness (§4.2) | `--harness claude-code` |
| `--prompt-level L0\|L1\|L2` | how vague the prompt is (§9) | `--prompt-level L2` |
| `--reps N` | repetitions of each run | `--reps 3` |
| `--tier locate\|e2e` | ask only where the change belongs, or do the whole task (§12) | `--tier locate` |
| `--stage LIST` | only some stages | `--stage run,score` to measure tokens and time without grading |
| `--resume` / `--only-missing` | skip runs that already finished | |
| `--max-turns N`, `--timeout-min N` | limits per run | `--max-turns 150 --timeout-min 50` |
| `--seats LIST` | which subscription logins to use; each runs one task at a time and pauses at its usage limit | `--seats seat-1,seat-2,seat-3` |
| `--max-runs N` | stop the batch after N runs | `--max-runs 200` |
| `--endpoint NAME` | for open models only: where the model is served, a hosted API or a server we host (§11). Its key, if it needs one, is read from the environment | `--endpoint hosted` |
| `--dry-run` | print the runs and the estimate, start nothing | |

### 3.2 A plan file

Flags are for trying things. Anything we will report is written down as a plan: a file that lists
cells, where each cell is "these setups, these models, on these tasks".

```toml
# plans/main.toml
[plan]
tasks = "tasks/e2e-v1.jsonl"
reps = 3
harness = "claude-code"
models = ["claude-sonnet-5-5"]
where = { split = "dev" }      # "test" for the one run before the paper

[[cell]]                       # the reference: Claude doing its thing, on every task
name = "baseline"
setups = ["grep"]

[[cell]]                       # our final solution, on every task
name = "final"
setups = ["tool"]
codemem = "final"

[[cell]]                       # today's codemem: medium tasks are enough to show the difference
name = "today"
setups = ["tool"]
codemem = "today"
where = { difficulty = "medium" }

[[cell]]                       # small models: tasks they have a chance on
name = "small"
harness = "mini-swe-agent"
endpoint = "hosted"            # or "local": a server on one of our Macs
models = ["qwen3.5-9b", "qwen3-14b"]
setups = ["grep", "tool"]
codemem = "final"
where = { difficulty = ["easy", "medium"] }

[[cell]]                       # a few hard tasks, to see whether a small model can do them at all
name = "small-probe"
harness = "mini-swe-agent"
endpoint = "hosted"
models = ["qwen3-14b"]
setups = ["grep", "tool"]
codemem = "final"
where = { difficulty = "hard" }
sample = 10
```

A `where` under `[plan]` applies to every cell, on top of the cell's own. `endpoint` says where an
open model is served: a hosted API, or a server we host (§11).

### 3.3 The run matrix

The plan above, as a table. This is the proposal for what the paper's numbers come from.

| What runs | On which tasks | Why |
|---|---|---|
| **Baseline:** Claude with its own tools, no codemem | every task, including the large and hard ones | the reference for everything |
| **Final:** Claude with the final codemem | every task | the headline: tokens and time against the baseline, and completion |
| **Today's codemem,** the simple version that exists now | medium tasks only | enough to show the step from today's version to the final one. The large tasks would be wasted on it |
| **Small models** (9B and 14B), with and without codemem | easy and medium tasks | the model-gap question. A 14B model is not expected to finish hard, spread-out tasks |
| **Small models, a probe** | about 10 hard tasks | to check that expectation instead of assuming it |
| **Mechanism setups:** results up front, placebo, stronger wording (§4.1) | a medium subset | to explain the headline, not to be it |

**Dev tasks first, test tasks once.** The task file marks every task as dev or test, split at
random within each language before any run. The matrix runs on the dev tasks by December 1. It
runs once on the test tasks in the week before arXiv, with the frozen configuration
([overview.md](overview.md) §8.2). Planning sizes, to be replaced by what the first batch
measures: about 50 dev tasks and 75 to 100 test tasks.

**The baseline is run once and reused.** A baseline run does not depend on codemem. So when track
B or C changes codemem, only the codemem cells are rerun, and they are compared with baseline runs
already on disk. This roughly halves the cost of every iteration.

### 3.4 The loop tracks B and C use

Tracks B and C should not need track A's owner to try a change. The pipeline ships a small fixed
plan for that:

```bash
cmeval e2e run plans/iterate.toml --codemem ./my-branch.toml --run-id try-stemming
cmeval e2e report try-stemming --compare baseline tool
```

`plans/iterate.toml` is 20 to 30 medium dev tasks, one cheap model, the `tool` setup, 2
repetitions. The baseline side is already on disk. One try should take under an hour and a small
part of one seat's usage window. It is a smoke signal, not a result: nothing is claimed from it.

---

## 4. What a run is

### 4.1 The setups

| Setup | The agent has | Why |
|---|---|---|
| `grep` | its shipped tools: grep, file listing, file reads, a shell, and its own built-in search subagent if it has one | the baseline is the agent as people use it |
| `tool` | the same, plus codemem's tools, loaded before the first turn, with the `light` wording. The agent decides whether to call them | this is how codemem ships |
| `upfront` | the same as `grep`, but the first message also holds the top results of one codemem search on the prompt. No codemem tool | separates two questions that `tool` mixes: does the information help, and does the agent choose to ask for it |
| `placebo` | a tool with codemem's name and card format that returns random chunks | is a gain from what codemem returns, or from merely having one more tool? |
| `tool-strong` | `tool`, with the `strong` wording | how much depends on telling the agent to use the tool? |
| `grep-nosub` | `grep`, with the built-in search subagent switched off | does codemem replace what that subagent does? |
| `grep-map` | `grep`, plus a short generated map of the repo in the agent's context | is a map enough on its own? |

`grep` and `tool` are the two that matter most. The others exist because of what other studies
found *(reported)*:
- Every published end-to-end gain for mid-size models put the search results into the prompt up
  front (CodeNib, CodeGrep, Physical Cost of Context).
- Tools that the agent may choose are often left unused: 0 to 6% of runs in one study of a
  language-server tool, 0 to 40% in Sourcegraph's. JetBrains withdrew an explanation of its own
  results after finding its tools "were not actually called".
- In Bellam's study, a placebo tool that returned random code hurt two small models.

If `upfront` helps and `tool` does not, the problem is adoption, not retrieval, and the fix is
different.

### 4.2 The agents

Two harnesses, because no single one fits every model.

| Harness | Models | codemem reaches the agent as | Why this one |
|---|---|---|---|
| **Claude Code, headless** | Claude models: a frontier one and a cheap one | MCP tools | it is the product people use, and every team member has it |
| **mini-SWE-agent, in its text mode** | the open models: 9B, 14B and 27B | a shell command, `codemem search "..."`, on the sandbox's path and described in the system prompt | it asks nothing of the model but to write one shell command per turn, so small models that are bad at tool calls can still be compared fairly. It is also the harness the official SWE-bench board uses to compare models |

Claude runs only in Claude Code, under our subscriptions. The open models run only in
mini-SWE-agent, through an API or a server we host. So the model gap is measured inside
mini-SWE-agent, from the 9B model up to the 27B one, and the Claude results stand beside it.

Two details about mini-SWE-agent *(reported)*: since version 2 its default is native tool calling,
so the text mode has to be selected (`mini_textbased.yaml` or `swebench_backticks.yaml`); and it
has no MCP support, which is why codemem reaches it as a command.

**The harness matters as much as the model.** One 2026 study of 1,100 failed runs found that
changing the harness moved the same open model by 28 to 44 points *(reported)*. So results are
never compared across harnesses, only within one.

**Why not Claude Code for the small models.** Ollama documents how to point Claude Code at a local
model. But Anthropic's documentation says routing it to non-Claude models through a gateway is not
supported, and in one report an 8B model answered in plain text instead of calling tools once many
tools were loaded *(reported)*. A result that depends on an unsupported setup would be hard to
defend.

### 4.3 Running Claude Code under a subscription

Claude Code runs under the subscriptions we already have, each of us on our own, not under an API
key ([overview.md](overview.md) §7). That changes how a run is started, and how it is kept clean.
The facts below are *(reported, from Claude Code's documentation)* unless marked otherwise.

```bash
# once per seat, on a machine with a browser:   claude setup-token    (prints a one-year token)
export CLAUDE_CODE_OAUTH_TOKEN=...             # that token; never written into a run's files
unset ANTHROPIC_API_KEY                        # a key in the environment silently wins over the token
export CLAUDE_CONFIG_DIR=/run/claude-empty     # a fresh, empty settings folder for every run
export CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
export CLAUDE_CODE_EFFORT_LEVEL=medium         # pinned. It is today's default, and defaults move
export ENABLE_TOOL_SEARCH=false DISABLE_AUTOUPDATER=1
export ANTHROPIC_BASE_URL=http://127.0.0.1:$PROXY_PORT    # the recording proxy (§5)

claude -p "$PROMPT" \
  --model "$MODEL_ID" \
  --output-format stream-json --verbose \
  --setting-sources user \
  --strict-mcp-config --mcp-config "$MCP_JSON" \
  --disable-slash-commands --no-session-persistence \
  --exclude-dynamic-system-prompt-sections \
  --permission-mode bypassPermissions \
  --disallowedTools "WebSearch,WebFetch"
```

| Flag | Why |
|---|---|
| `--model` | a full model id, never an alias that can move |
| `--output-format stream-json --verbose` | every message and tool call, as it happens |
| `--setting-sources user` | with an empty user folder, nothing is read from the repo's own settings |
| `--strict-mcp-config --mcp-config` | only the MCP servers we name |
| `--disable-slash-commands --no-session-persistence` | no skills, and nothing kept between runs |
| `--exclude-dynamic-system-prompt-sections` | the same system prompt on every machine |
| `--permission-mode bypassPermissions` | unattended. Only inside the task's container, as a non-root user |
| `--disallowedTools "WebSearch,WebFetch"` | the real fix is on the web |

`$MCP_JSON` is `{"mcpServers": {}}` for every setup without a codemem tool. For `tool` it is:

```json
{"mcpServers": {"codemem": {"command": "codemem", "args": ["mcp"], "alwaysLoad": true}}}
```

**Why not the two shortcuts.**
- `--bare` switches off everything from the machine and the repo in one flag, but it does not
  read the subscription token. It works only with an API key.
- `--safe-mode` works with a subscription and also switches everything off, **MCP servers
  included**. The documentation does not say whether a server named on the command line survives
  it, and the setup that needs codemem cannot depend on that.

So every setup gets the same explicit switches above. Two more safeguards do not depend on any
flag:
- before a run, the runner removes from the checkout whatever would configure the agent:
  `.claude/`, `CLAUDE.md`, `AGENTS.md`, `.mcp.json`;
- the first event of the stream lists the tools and the MCP servers with their status. The runner
  checks it on every run and discards a run whose setup is not what it should be.

**Three more details that decide whether the comparison is fair:**
- **Since Claude Code 2.1.302, a headless run with no permission mode set denies every action
  that needs approval.** The mode must be set.
- **Tools must be loaded up front.** By default Claude Code hides MCP tools behind a tool-search
  step. `alwaysLoad` and `ENABLE_TOOL_SEARCH=false`, set for every setup alike, remove that step,
  so the agent sees codemem's tools from the first turn.
- **The runner enforces the time limit itself.** A turn limit is passed as well where the
  installed version accepts `--max-turns`; version 2.1.285's help no longer lists it *(checked on
  our machine)*.

**Usage limits.** A seat has a limit per session window and a limit per week, and the
documentation does not treat headless runs differently.
- **A run that hits a limit is stopped and thrown away, never scored.** Waiting for the reset
  inside a run would ruin its time measurement. Claude Code has a setting that makes it wait and
  retry; it stays off.
- **The scheduler pauses that seat** until its reset, then starts the task again from the
  beginning.
- **Three seats, one per team member,** each with its own token, share a batch.
- **How a limit shows up in a headless run is not documented:** no exit code or event is named.
  The recording proxy sees the API's refusal directly, so that is the signal the runner uses.

**To check on the first day**, because the documentation is silent: that the end-of-run summary
still carries its token counts under a subscription; that `--setting-sources user` really keeps a
repo's hooks out; and that the proxy passes the subscription's `Authorization` and
`anthropic-beta` headers through untouched, which is what a login needs.

**Keys.** Claude Code needs none. The runner unsets `ANTHROPIC_API_KEY` in the agent's
environment, so that a stray key cannot take over from the login. Model calls with an API key
happen in two places only: codemem's embedding API, when embeddings are not local, and the open
models of the small-model study, when they are not self-hosted (§11). The token counter of §5.4
also reads an Anthropic key, in the scoring step. It only counts, and counting is free.

**Codex** runs the same way under its own subscription: `codex exec --json` reports token use per
turn, and it reads MCP servers from its config file *(reported)*. It is a second agent for
later: nothing in the paper depends on it.

### 4.4 Where a run happens

```
 one container per run
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ the repo at the task's commit, dependencies installed, tests runnable     │
 │ the agent (Claude Code, or mini-SWE-agent)                                 │
 │ codemem (CLI and MCP server), with a copy of the prebuilt index            │
 │ a file watcher, which notes the time of the first change to a source file  │
 └──────────────┬───────────────────────────────────────────────────────────┘
                │ model calls only, through the recording proxy (§5)
                ▼
           the model API                  after the agent stops: a clean container
                                          applies its changes and the hidden tests
```

- **The agent runs inside the container**, so it can build and run code the way a developer would.
- **codemem embeds the query, and the agent's own edits, during a run.** First with the local
  model. Later through an API, where the container needs no GPU and no PyTorch and every machine
  produces the same vectors (§2.3).
- **Run on x86 Linux, not on the Macs.** Published test images are built for x86 only: SWE-bench's
  maintainers closed ARM support as "not planned" in August 2026, and a contributor measured tests
  6 to 9 times slower under emulation *(reported)*.
- **Containers are cheap next to model calls.** At 4 cores, 16 GB and 10 minutes a run, 100 runs
  cost about $11 on Modal's sandboxes, or $3 to $6 on one rented cloud machine *(reported prices,
  our arithmetic)*.
- **Use a task format others already use.** SWE-bench Pro's second version ships its tasks in the
  Harbor format: one folder per task, an agent phase with no network, grading on a clean image,
  and a time cap. Harbor already runs Claude Code, and a task can declare an MCP server
  *(reported)*. Writing our tasks in that format means we write a task exporter and a recorder,
  not a container harness.

### 4.5 Rules that keep the comparison fair

1. **One difference.** The same prompt, repo snapshot, model, limits and container. Only the
   setup changes.
2. **The index is built before the clock starts**, once per task and configuration, and every run
   starts from a copy of it. Its build time, disk and memory are reported separately, and added
   back in one analysis that spreads the build over the tasks of a repo.
3. **The agent cannot look up the answer.** No web tools, no network except the model API (and the
   embedding API, when codemem uses one), and a clone whose history ends at the task's commit.
4. **The tests stay hidden** until the agent stops.
5. **At least three repetitions** of every run. Current Claude models reject a temperature
   setting, so repetitions are the only way to see run-to-run noise.
6. **Tool use is measured, not assumed.** The main analysis keeps every run of the `tool` setup,
   whether or not the agent called codemem. A second analysis looks only at the runs that did.
7. **Freshness is recorded.** Every task carries the date its fix was merged, and every table
   says how many of its tasks are newer than the model's training cutoff. The public sets are
   mostly older (§8.1).
8. **Setups take turns.** The runs of one task are started alternately (`grep`, `tool`, `grep`,
   `tool`), not one whole setup after the other, so a slow hour at the API hits both.
9. **A dev split for building, a test split run once.** Prompts, limits and codemem settings are
   fixed on the dev split before any test-split run.

---

## 5. How tokens and time are measured

This is the part of the pipeline everything else rests on, so it is spelled out.

### 5.1 Four instruments

| We want to know | Instrument | Why this one |
|---|---|---|
| How many tokens the model processed, per request | **a recording proxy** between the agent and the model API. It saves every request and every response, and each response carries the API's own token count | it is the provider's number, not ours and not the agent's. It is there under a subscription just as under a key. It sees every call, including subagents, context compaction and retries. It works the same for any agent and any provider |
| Whether we missed anything | **the agent's own end-of-run summary** (in Claude Code, the `modelUsage` block of the final message, which includes subagents) | a second count from an independent place |
| Which tool brought which tokens into the context | **the transcript:** the text of every tool result, counted with one reference tokenizer | the API counts per request, not per tool |
| Where the time went | **four clocks**, each where the thing happens (§5.5) | no single clock sees everything |

```
 the agent ─────────► recording proxy ─────────► the model API
 (in the container)   for each request it saves:
                      · what was sent: system prompt, tool list, messages
                      · what came back, with its usage block
                      · three times: sent, first byte received, finished
```

**We have done this before.** For the CS146S trace assignment we pointed Claude Code's
`ANTHROPIC_BASE_URL` at mitmproxy and saved every request and response. Each response held a usage
block like this one, taken from those traces:

```json
"usage": {
  "input_tokens": 2,
  "cache_creation_input_tokens": 828,
  "cache_read_input_tokens": 39123,
  "output_tokens": 1629,
  "output_tokens_details": {"thinking_tokens": 241}
}
```

The pipeline does the same thing without a person watching: `mitmdump` with a short script that
writes one JSON line per request, or a small pass-through server of our own. The agent's
environment sets `ANTHROPIC_BASE_URL` to the proxy, exactly as in the assignment.

### 5.2 Exact where we can, and the same on both sides

What we report in the end is a **saving**: the difference between two runs of the same task. A
difference is only as good as the two measurements are alike. So four rules:

1. **Exact first.** The API's own count is exact. It exists for every Claude run and for every
   hosted or local open model.
2. **Both setups of a task are measured by the same instrument, in the same way.** An exact count
   is never compared with an estimate. If one run of a pair lost its proxy record, both runs fall
   back to the agent's own summary.
3. **Where only an estimate exists, it is the same estimate everywhere.** "Tokens read" uses one
   reference tokenizer for every model and every setup. Its error is then nearly the same on both
   sides and largely cancels in the difference.
4. **A saving is reported per task, as a paired difference and a ratio, with an interval.** Never
   as two separate averages set side by side.

### 5.3 The cross-check

For every run, the runner adds up the proxy's usage blocks and compares the totals with the
agent's own summary, class by class.

- **They agree within 1%:** the run is valid, and the proxy's numbers are used.
- **They disagree:** the run is flagged and kept out of the tables until someone has looked. A
  mismatch means a missed request, a retry counted twice, or a change in the agent.
- **The proxy failed:** the agent's summary is the fallback, and the run is marked as such.

Two independent counts that agree are worth more than one careful count. They also protect us
when Claude Code changes its output format, which it does often.

### 5.4 What "tokens" means: six numbers, each with a job

| Number | Definition | What it is for |
|---|---|---|
| **Processed tokens** | fresh input + cache writes + cache reads + output, summed over every request of the run | **the primary token measure.** It is what the model had to read and write, and it does not depend on cache luck |
| The four classes | the same sum, kept apart: fresh input, cache writes, cache reads, output (thinking tokens noted inside output) | cache reads are the largest class in agent runs and the cheapest per token |
| Cost at API prices | each class times its list price | not reported in this phase: our runs are on subscriptions, where the agent's own dollar figure is an estimate that has nothing to do with billing. It can be computed later from the four classes |
| **Tokens read** | the text of every tool result, counted with the reference tokenizer, by tool: grep, file reads, shell, codemem | what entered the context because of a search or a read. This is where codemem should show |
| Peak context | the largest input of any single request | how close the run came to the model's window. For small models this decides success |
| **Tokens before the first edit** | processed tokens of the requests that finished before the first change to a source file | the cost of finding out where to work |

**Why processed tokens are primary, and the classes are kept apart.** An agent resends the whole
conversation on every turn, and the API serves the repeated part from a cache. Whether the very
first request finds the system prompt already cached depends on whether another run started a
minute earlier. And the `tool` setup has four more tool definitions than `grep`, so its first
request is cached separately. Two identical runs can therefore split their tokens differently
between "cache read" and "cache write". Their sum, the processed tokens, does not depend on that
luck. The classes are still recorded, because a later cost breakdown needs them, and because how a
plan's usage limit weighs cached tokens is not public.

**The reference tokenizer** for "tokens read" is Anthropic's token-counting endpoint, cached by
text hash, as `cmeval` already uses for the retrieval eval. It is the same for every model, so
"tokens read" can be compared between a Claude run and a 9B run. Counting is free. The endpoint
asks for an Anthropic key, which `cmeval` already reads from the environment or the Keychain, and
no model is called with it. A fixed local tokenizer would be the alternative if we wanted no key
at all.

### 5.5 What "time" means: four clocks

| Clock | Measures | Sits in |
|---|---|---|
| **Wall time** | from the agent's start to its exit | the runner. **The primary time measure** |
| Model time, and time to first byte | each request's duration, and how long until the answer began | the proxy |
| Tool time, by tool | each tool call's duration | Claude Code's telemetry events (`tool_result` carries the tool's name and duration). For codemem also its own log, split into catch-up, keywords, query embedding, vector search and merging |
| **Time before the first edit** | from the start to the first change of a source file | a file watcher inside the container, so it means the same thing in every harness |

Container start-up and copying the index are timed and kept out of wall time.

**Time is noisier than tokens.** The API is faster at some hours than others, and a laptop model's
speed depends on what else is running. So: runs of a task take turns between setups (rule 8), the
number of runs in parallel is fixed for a whole batch, and every time result is reported next to
turns and tokens, which do not depend on the clock.

Claude Code's telemetry is switched on with `CLAUDE_CODE_ENABLE_TELEMETRY=1` and an exporter for
its events. It reports each model request (duration and tokens) and each tool result (name,
duration, success) *(reported, from its monitoring documentation)*. It is a third view of the same
run, and the source for per-tool time.

### 5.6 Rules for the proxy

1. **Change nothing.** Every header and every byte of the body passes through, including the
   `Authorization` and `anthropic-beta` headers a subscription login depends on. Anthropic's
   documentation warns that a gateway which drops the cache markers makes requests count as
   uncached, with no error.
2. **Never write a credential to disk.** Strip the `Authorization` and key headers before saving
   a request.
3. **Do not hold back streamed answers.** The proxy must pass each piece on as it arrives. Check
   this once: time to first byte with and without the proxy, on 20 requests.
4. **One proxy per run,** on its own port. A request can then never be counted for the wrong run.
5. **Keep full bodies for dev runs, and a summary for large batches:** the usage block, the three
   times, and the tool results. A full body repeats the whole conversation in every request.

### 5.7 The same thing for open models

mini-SWE-agent talks to open models through an OpenAI-style endpoint. The same proxy sits in
front of it, and those responses carry their own usage counts. A model running locally also
reports, for each request, how many tokens it read and wrote and how long each took. So the six
numbers and four clocks are defined for every model in the study.

---

## 6. What one run records

One JSON file per run, plus the raw transcript and proxy log beside it.

| Group | Fields |
|---|---|
| Identity | task, setup, model id, harness and its version, codemem configuration and index key, prompt level, repetition, the plan and cell it came from |
| Outcome | completed (yes or no); tests that had to start passing, and did; tests that had to keep passing, and did; how the run ended: finished, turn limit, time limit, context full, repeated command, error |
| Tokens | the six numbers of §5.4, and the agent's own summary beside the proxy's |
| Time | the four clocks of §5.5 |
| Steps | turns; tool calls by tool; turns before the first edit |
| Search behaviour | files read; whether and when a gold file was read; whether codemem was called, how often, and what it returned |
| Integrity | setup check passed; cross-check passed; proxy complete; container and network checks passed |

A run can be repeated from its record alone.

---

## 7. What makes the pipeline robust

Track A's owner will run this a great deal, often unattended. These are the properties that make
that safe.

| Property | How |
|---|---|
| **Stop and resume** | a run's name is a hash of everything that defines it (task, setup, model, harness version, codemem index key, prompt level, repetition). Starting a plan again runs only what is missing |
| **No half results** | a run's files are written to a temporary folder and moved into place only when complete |
| **A broken setup is not a failed task** | every run is checked: were the right tools loaded, did the MCP server start, was the context window what we set, did the proxy see every request. A run that fails a check is discarded and rerun, never scored |
| **Infrastructure failures are not agent failures** | a container that would not start, a rate limit, an API outage: these are retried with a wait, and counted separately |
| **Usage limits are expected, not errors** | a run cut off by a seat's limit is discarded and rerun after the reset; the batch carries on with the other seats; `--dry-run` shows how many runs a plan needs before it starts |
| **A canary** | ten fixed tasks are rerun after any change to the harness, the agent's version or the pipeline. If their numbers move, nothing else is run until we know why |
| **Pinned versions** | the agent's version, model ids, codemem commit and container images are fixed for a batch and recorded in every run |
| **Watching a batch** | the existing `cmeval dashboard` shows progress, tokens so far, which seats are paused, and failures by kind |
| **Nothing is recomputed needlessly** | indexes are reused by key; baseline runs are reused across codemem versions; scoring and reporting cost nothing |

---

## 8. Tasks: where they come from

### 8.1 Tasks that already exist

The pipeline does not wait for our own tasks. Its runs use a public set that already ships a
container and hidden tests for each task. In this phase, these are the tasks the results come
from.

**SWE-bench-Live is the first choice** *(checked on its pages, Nov 22)*:

| Set | Tasks | Languages |
|---|---|---|
| the Python set | about 1,890 in its full split, with frozen splits of 300 and 500 | Python |
| the multi-language set | 1,077, from 431 repos | C 111, C++ 142, C# 136, Go 138, Java 160, JavaScript 108, Rust 171, TypeScript 111 |

Each task names an x86 Docker image, its test commands and a log parser, and the project's own
script grades a patch. So all six of our languages are a matter of choosing tasks, not of building
environments. SWE-bench Pro's second version is the alternative: it already runs Claude Code in
the Harbor format *(reported)*.

**Two limits, both stated in the paper.**
- **Most of these tasks are older than the models.** The newest Python task we saw was created in
  August 2025, and the multi-language page shows no dates. The task tables do (downloaded Nov 22):
  the `verified` Python split runs from July 2024 to April 2025; the TypeScript and Go splits end
  in April 2026; the Rust split ends in July 2026, and 68 of its 171 tasks were created after
  June 2026. Both setups run the same model on the same
  task, so a memorized fix cannot favour one side. It can hide a saving, because a model that
  remembers a fix has less to search for. Every table says how many of its tasks are newer than
  the model.
- **Public sets have flaws** (§16). Tasks are spot-checked by hand before they enter the test
  split.

### 8.2 Our own: the generator

**In this phase: a trial at most.** What follows is the design the trial would test. Building
tasks at scale waits until after the paper ([overview.md](overview.md) §8.3).

**In plain words.** Point it at a GitHub repo. It finds merged pull requests that fixed an issue
and came with tests, rebuilds the repo as it was just before each one, checks that the tests fail
before the change and pass after it, and writes out a task.

```
 a GitHub repo link, and a date range after the model's cutoff
      │
      ▼
 1. COLLECT    merged pull requests with one linked issue written before the fix   ┐ exists in
 2. SPLIT      the change into code and tests; record the commit just before it    ┘ cmeval collect
      │
      ▼
 3. BUILD      a container image of the repo at that commit; find the test command  ┐ reuse
 4. VALIDATE   run the new tests before and after the real change, three times:      │ RepoLaunch
               keep the task if some tests go from failing to passing, and none      │ (below)
               that passed before now fail or flicker                                ┘
      │
      ▼
 5. LABEL      gold files and functions (exists); size, kind and difficulty (§10)   ┐ ours:
 6. REWRITE    the vague versions of the prompt, with their checks (§9)             ┘ the new part
      │
      ▼
 7. PACKAGE    one JSON line per task, a task folder in the Harbor format, a datasheet
```

**What our own funnel says about yield.** For the nine repos of the retrieval eval:

| Step | Kept |
|---|---|
| merged pull requests, July to October 2026 | 33,568 |
| with one linked issue, written before the fix | 5,334 |
| small enough, and labelled | 3,788 |
| of those, with tests in the same pull request | 80% of Python tasks, 84% of TypeScript tasks, **8% of C++ tasks** |

So steps 1 and 2 already give about 2,500 candidates with tests. Steps 3 and 4 are the unknown.
The C++ row is a warning: Godot, duckdb and llama.cpp rarely add a test in the same pull request,
so C++ needs repos chosen for their test habits.

### 8.3 What to build on

Steps 3 and 4 are the expensive part, and others have built them. All *(reported)*.

| Pipeline | What it automates | Languages | Yield and cost | Can it take any repo? |
|---|---|---|---|---|
| **SWE-bench-Live with RepoLaunch** (Microsoft; MIT; updated Nov 2026) | pairing issues and pull requests after a date, a quality filter, an agent that builds the Docker image and finds the test command and log parser, validation over 3 runs | C, C++, C#, Python, Java, JavaScript and TypeScript, Go, Rust | the build succeeds on 72 to 92% of filtered candidates; 8 to 20% of candidate pairs become tasks; about $1.70 per task with a frontier model, less when one build is reused per repo | **yes:** it takes a list of repos and commits |
| SWE-rebench V2 (MIT; updated Nov 2026) | mining, a setup agent, validation, difficulty and category labels | 20 | 32,079 tasks from 583,809 pull requests (5.5%) | **not as published.** The repo holds prompts, base images, log parsers and the grader, not the collector. Its newest task is from October 2025 |
| SWE-Factory (AGPL, non-commercial) | a multi-agent builder of Dockerfiles and test scripts | Python, Java, JavaScript, TypeScript | 42 to 50% of issues; $0.04 to $0.06 and about 25 minutes each | yes |
| SWE-smith (MIT) | one image per repo, then **synthetic** bugs with generated issue texts | Python, plus profiles for C, C++, Go, Java, JavaScript, Rust, TypeScript | half of candidate bugs are valid; $1,360 for 50,000 tasks | yes, but the tasks are made up |
| SWE-bench's own scripts (MIT) | scraping and validation; the install steps are written by hand | Python | 2.5% of pull requests | not the environments |

**The recommendation.** Build on SWE-bench-Live's scripts and RepoLaunch, and feed them the
pull-request list that `cmeval collect` already produces. It is the only maintained, permissively
licensed pipeline that covers all six of our languages from an arbitrary repo. Borrow log parsers,
base images and labelling prompts from SWE-rebench V2.

**Three cautions.**
- An independent benchmark measured RepoLaunch much lower, at 8.9% of tasks validated on average,
  with older models and an earlier version. So the first step is a trial on about 20 pull requests
  per language, before the plan depends on it.
- The two research passes behind this plan read SWE-rebench V2's repository differently. One took
  the paper's word that the collection code is released. The other opened the repository and did
  not find it. Check before relying on either.
- RepoLaunch needs keys of its own: a model API key, through LiteLLM (any provider, or an
  OpenAI-style endpoint), and a Tavily search key *(checked Nov 22)*. A subscription login does
  not serve it. The open-model endpoint of §11 is one way to feed it.

**What we add, which none of these has.** Steps 5 and 6: prompts at three levels of vagueness that
are checked to be still solvable, and labels for how hard a task is to *search* for. That layer
works on any task that has a container and hidden tests, whoever harvested it. It is the part we
release as ours.

**Why our own fresh tasks still matter.** The public sets are older than the models we test
(§8.1). Only tasks we harvest ourselves can be newer. That is the case for building the generator
after the paper.

**Synthetic bugs have one use here:** as a pool of easy tasks for the small models, if real fresh
pull requests give too few that pass the small-model filter.

### 8.4 Choosing repos

The retrieval eval chose repos for size. End-to-end tasks also need repos that build and test
inside a container in minutes. Proposed criteria, each checked before a repo is admitted:

| Criterion | Threshold |
|---|---|
| size | at least 1,000 source files in the main language |
| activity after the cutoff | at least 50 merged pull requests with a linked issue and tests |
| build | a clean image builds in under 20 minutes |
| tests | the tests of one pull request run in under 5 minutes, with stable results |
| languages covered | Python, C++, Go, Java, Rust, TypeScript: two or three repos each |

---

## 9. Vague prompts

**The problem.** An issue text is long and usually names the file, the function or the error. A
user's request is short and names nothing. codemem is built for the second kind, and we have no
tasks of that kind.

**The ladder.** Every task gets three prompts for the same change and the same hidden tests:

| Level | What it is | In the example |
|---|---|---|
| L0 | the issue as written | the original issue, with its code snippets and file names |
| L1 | the same content with names removed: no paths, identifiers, stack traces or code from the area of the fix | "Uploaded images are stored but their text is never extracted. Image uploads should go through a text-extraction step like audio uploads do, and the extracted text should be searchable." |
| L2 | a short request in a user's voice, plus one "done when" line if the tests need it | "Add OCR to the upload pipeline, so that text in uploaded images can be searched." |

A model writes L1 and L2 from the issue and from what the hidden tests check. Two rules for the
writing:
- **Sound like a user.** One study mined 11 templates from 10,000 real chat requests to coding
  assistants and rewrote issues into 10 to 30 words in those shapes *(reported: Saving
  SWE-Bench)*. L2 uses templates of that kind, so it is vague in the way real requests are.
- **Keep the interface the tests need.** If the hidden tests call a new function, flag or route by
  name, that name goes into the "done when" line. Otherwise no agent could pass, however well it
  searched.

Three checks follow:

1. **No leak.** L1 and L2 contain no file name or identifier from the *existing* code in the gold
   answer. This reuses the check behind today's `identifier_in_query` tag.
2. **Still solvable.** A frontier model is given the L2 prompt *together with the gold files* and
   must still pass the hidden tests about as often as with L0. If it cannot, the rewrite dropped
   something the tests need, and the prompt is fixed or the task is dropped.
3. **A human look.** Two team members read 50 rewrites each, and their agreement is reported.

**Why check 2 matters.** An agent can fail a vague task for two reasons: it could not find where
to work, or the prompt no longer said what to build. Only the first is what we study. Check 2
removes the second.

**What others found, and what they left out** *(reported)*.

| Study | How it made prompts vague | Checked that tasks stay solvable? | What happened |
|---|---|---|---|
| Saving SWE-Bench | rewrote issues to 10 to 30 words in the shape of real chat requests | no | completion fell from 35.6 to 22.6% for one model and from 65.4 to 50.2% for another |
| Ask or Assume? | removed code, paths and traces from issues | no | 70.8 to 54.8%; back to 69.4% when the agent could ask questions |
| SWE-bench Pro, ablation | removed the requirements and the interface | — | 25.9 to 8.4% |
| FeatBench | a first-person feature request written from the pull request, about 1,850 characters | people rated 28 of 30 sampled tasks solvable | best agent 29.9% on 157 Python tasks |

None of them varies the search tool, and none pairs a short request with a solvability check. We
found no benchmark with a short, vague feature request on an existing repo, graded by hidden
tests.

---

## 10. Labels on every task

**Why.** So that a plan can choose tasks before anything runs ("medium only", "the small-model
set"), so that results can be reported by kind of task, and to test the hypothesis that an index
helps most on large repos and vague requests.

| Label | Values | How it is set |
|---|---|---|
| **Difficulty** | easy: one file, at most 15 changed lines. Medium: one or two files, at most 100 lines. Hard: three or more files, or more than 100 lines, or a model's estimate of more than an hour of work | from the real change, before any run. On SWE-bench-Live, single-file changes under 5 lines were solved 48% of the time, and changes of 3 or more files or 100 or more lines under 10% *(reported)* |
| Repo size | small (under 1,000 files), medium (1,000 to 5,000), large (5,000 to 20,000), very large | counted at the task's commit |
| Kind of task | bug fix; feature that follows an existing pattern; feature with no pattern; refactor or follow-up | pull-request labels and a model's reading, spot-checked by hand |
| Vagueness | L0, L1, L2 | by construction |
| Named in the prompt | four tiers: the prompt gives the full path, the file name, the module, or nothing | extends today's `identifier_in_query` tag; always "nothing" for L1 and L2. On SWE-bench Lite, 51% of issues name nothing, and keyword search finds the right file in its top 10 for 8% of those, against 75% when the path is given *(reported)* |
| Reach by keywords | the rank of the first gold function when the prompt is run as a plain keyword search | from the retrieval eval |
| Spread | number of gold files, and how far apart they are in the folder tree | from the real change |
| Test strength | number of tests that must start passing | from validation |
| Small-model set | yes if one file, at most three separate edits, no new file, a prompt that names no file, and tests under 60 s | computed |
| Measured difficulty | easy, medium, hard | the frontier model's completion rate over all its baseline runs, added after the runs. Reported next to the first label, never used to choose tasks |

**"Feature that follows an existing pattern"** is the OCR case: the change adds a new piece that is
modelled on an existing one. It is detected when the real change adds a new file or class, and a
similar one (same base class, same folder, similar code) already exists at the task's commit. The
existing one is recorded as the **pattern** in the answer key. This is the kind of task where we
expect search by meaning to help most, and the label lets us test that.

**Difficulty is logged for every task we create.** The retrieval eval asked only whether the right
code was found, so it did not need this label. An end-to-end run asks whether the agent solved
the issue, and that depends first on how hard the issue is. So:
- the collector writes `difficulty` into each task's tags when the task is made, from the real
  change, with the rule in the table above;
- the task set's statistics (`*.meta.json`) give the count of easy, medium and hard tasks for each
  repo and each split, and a sample drawn with `cmeval subset` reports its own counts;
- every end-to-end report has its results by difficulty, next to the overall numbers;
- measured difficulty is added after the baseline runs and is logged beside the first label, so
  the two can be compared.

Our fresh tasks do not carry the label yet. The tags they have (`n_code_files`,
`code_lines_changed`) are enough to compute it, without the model's estimate of working time:

| Task set | Tasks | Easy | Medium | Hard |
|---|---|---|---|---|
| Python (`fresh-v1`) | 2,084 | 916 (44%) | 827 (40%) | 341 (16%) |
| C++ (`fresh-cpp-v1`) | 724 | 391 (54%) | 221 (31%) | 112 (15%) |
| TypeScript (`fresh-ts-v1`) | 980 | 344 (35%) | 353 (36%) | 283 (29%) |
| The three dev samples (100, 68 and 50 tasks) | 218 | 102 (47%) | 75 (34%) | 41 (19%) |

Files are changed code files, and lines are changed code lines; test files do not count. The
collector keeps only fixes of at most 5 code files and 200 changed code lines, so our hard tasks
are bounded: none is a change of ten files.

---

## 11. The small-model study

**The question.** grep may work so well only because the models using it are huge. Does codemem
help a small model more than a large one?

**What "small model" means here.** The small model is the agent's brain: it reads the task, picks
every command and writes the patch. It is not a helper to a larger model.

**The models.** Open-weight models have moved on from the 7B and 13B sizes of two years ago. The
strongest current models near those sizes, as of November 2026 *(reported)*:

| Size class | Pick | Why this one | Where it runs |
|---|---|---|---|
| about 9B | **Qwen3.5-9B** (Apache-2.0, 262K context) | the strongest open model of its size with published agent scores: 53 to 60% on SWE-bench Verified, as reported by vendors, depending on the harness | hosted, at about $0.08 to $0.17 per million input tokens; locally 6.6 GB at 4 bits |
| about 14B | **Qwen3-14B** | the newer Qwen generations have no size between 9B and 27B. In a published 30-turn agent loop it finished 99.4% of episodes, where Gemma 4 12B finished 44.5% | hosted, at about $0.12 per million input tokens; locally 9.2 GB at 4 bits |
| about 27B: the top of the curve in this harness | **Qwen3.8-27B** (Apache-2.0) | 86% on SWE-bench Verified with mini-SWE-agent; served by Nebius. Qwen3.6-27B is the runner-up and the only one with an independent score on fresh tasks (31%) | hosted only: Nebius, $0.45 in and $3.00 out per million tokens. At 18 GB it does not fit a 24 GB Mac next to anything else |
| for context | Claude Haiku 5.5 and Claude Sonnet 5.5 | the cheap and the frontier end, from the main runs. A different harness, so they are shown beside the open models and not compared with them | Claude Code, under our subscriptions |

A 4B model of the same family (Qwen3.5-4B) is a cheap optional fourth point: the largest published
gains from search tools are at 4B.

**No independent score on fresh tasks exists for any model under 20B.** The scores above for the
9B class are on SWE-bench Verified, which models have partly memorized, and are vendor-reported.
So the first result of this study is the plain baseline: what a 9B and a 14B model complete on
tasks newer than they are.

**Which tasks.** Easy and medium tasks, as in the run matrix (§3.3), and about ten hard ones as a
probe. Small models complete a narrow kind of task: on SWE-bench Verified, the tasks that weak
models solve are 95 to 100% single-file, with a median real change of 2 to 4 lines, and a 32B
model from 2024 solved 16.5% of the tasks humans rate under 15 minutes and none of those over an
hour *(reported)*. The small-model set of §10 marks the tasks with the best chance. Each is run at
L0 and L1.

**Where they run.** Through an API or self-hosted. This study is the one part of the plan where
the agent's own model is not on a subscription.
- **A hosted endpoint,** for the batches: the same open weights, at cents per run, many runs side
  by side. Which provider serves the 9B and the 14B is to be checked on day one. Nebius's
  documentation names the 27B (`Qwen/Qwen3.8-27B`), and we did not find the two smaller ones
  there *(checked Nov 22)*.
- **Self-hosted on our Macs,** for a repeat of a subset, and for everything if no provider serves
  a model. This is the point of these sizes: they are the models people can run themselves, and
  it costs nothing. A laptop is slow, though: an M1 generates about 14 tokens a second and reads
  a prompt at about 108 tokens a second with a 7B model at 4 bits, and an M5 about 32 and 723
  *(reported)*. So local batches run overnight.

Tokens, turns and completion mean the same in both places. Time does not: it is reported per
place, and the claim about laptops rests on the local runs only.

**What fits on a Mac** *(reported measurements, plus arithmetic)*:

| Mac | Fits |
|---|---|
| 16 GB | the 9B at 4 bits (5.6 to 6.6 GB) with a 32K context, **if** embeddings come from an API or a light embedding model. With today's 2.2 GB embedder it is tight |
| 24 GB | the 9B at 8 bits, or the 14B at 4 bits (9.2 GB), with the embedder |
| neither | the 27B (18 GB), or a 35B model with 3B active (17 to 24 GB) |

**Two settings that silently break small-model runs:**
- **The context window.** Ollama defaults to 4,096 tokens on machines with under 24 GB of video
  memory, and drops what does not fit without an error. Set it to at least 32,768
  (`OLLAMA_CONTEXT_LENGTH`). The runner checks it on every run (§7).
- **The turn limit.** At 30 turns and 32K tokens, one study saw Qwen3-8B hit the limit in 21% of
  episodes and Gemma 4 12B in 48% *(reported)*. Every run records whether it ended at a limit.

**What the evidence says so far, both ways.** All *(reported)*.

| For "search helps small models more" | Against |
|---|---|
| Bellam's pre-registered study (9 models, 500 tasks, 5 repetitions): search tools add 6 to 10 points of function-level localization from 0.6B to 14B, and 2.6 points at 32B, which is not significant. On tasks from June to October 2026: +11.4 points at 4B, +0.7 at 32B | In the same study, in a shell-only harness, the 32B model gained as much as the 4B (+10.2 against +12.8). Thinking mode halved the 4B gain. Gemma 4 12B gained nothing |
| A 4B model with tools took 8.4 steps instead of 15.1 | Small models act on the right code less often even when it is shown to them: 9% of the time at 1.7B, 40% at 32B. Given the gold files, small models repaired 2 tasks of 100 |
| With a trained retriever in front, a 30B agent resolved 27.0% against 25.8%, with 19% fewer tokens (CodeGrep) | In the same study a keyword retriever made the agent *worse*, and an off-the-shelf embedding retriever changed nothing. What was retrieved had to be precise to help |
| Search results placed up front cut tokens by 50 to 87% across five models from 9B to Haiku 4.5, on localization (CodeNib) | In a study of failed runs by 24 to 80B agents, only 12% of failures came from looking in the wrong place. Loops and running out of budget caused 35%, wrong fixes 33% |

**What follows for the design:**
1. **Localization is the primary measure for the small models, completion the second.** If a 9B
   model completes almost nothing even with the right code in front of it, completion cannot show
   an effect, and the localization tier (§12) can. The first small-model run measures this floor
   before anything else is built on it.
2. **The placebo setup is not optional here.** Random results hurt small models in Bellam's study,
   so "a tool was present" and "the tool returned the right code" must be told apart.
3. **How each failed run ended is a result,** not a footnote.

**The measure.** For each small model:

```
 gap closed = (small model with codemem − small model alone)
              ÷ (27B model alone − small model alone)
```

computed for localization and for completion, and reported next to the plain differences in
tokens, time and turns. The 27B model is the larger model here because it runs in the same
harness. Until it has run, the plain differences are the result.

**What else to record for small models.** How each failed run ended: a repeated command, a
malformed command, a full context window, or the turn limit. The hypothesis behind the study is
that grep floods a small context with matches. If that is right, the codemem setup should show
fewer "context full" and "turn limit" endings, and that is checkable.

**A control.** A small set of tasks where search should not matter: a new, self-contained module
with nothing in the repo to find. If codemem changes results there, something other than search is
causing it, such as a longer prompt.

---

## 12. The two cheaper tiers

End-to-end runs are the headline. Two cheaper measurements exist to make them affordable.

| Tier | Question | Needs | Cost per task | State |
|---|---|---|---|---|
| **Retrieval** | Can the search system find the code? | an index | seconds; no agent | exists: `cmeval` |
| **Agent localization** (`--tier locate`) | How much does an agent spend to find where a change belongs? | an agent; no test environment | about a minute of agent time | new, small |
| **End to end** (`--tier e2e`) | Does the agent finish the task, and at what cost? | an agent and a test environment per task | several minutes of agent time | new: the headline |

### 12.1 Agent localization

It asks the agent one thing: "which files and functions would you change for this request?" The
answer is graded against the gold labels `cmeval` already produces for 3,788 fresh tasks. It needs
no container and no tests, so it runs on every existing task and on a laptop. It uses the same
runner, the same setups and the same measurement as the end-to-end tier. It isolates the search
phase, which is where codemem acts, and it gives the time to a first located answer. It is the
primary measure for the small models (§11). It cannot say whether the task would have been
completed, which is why it supports the end-to-end tier and does not replace it.

### 12.2 The retrieval eval, kept short

**Keep** the method: fresh tasks from merged pull requests, gold files, classes and functions, the
tuned grep baseline, paired tests, and the two headline numbers (function MRR, and tokens read
before the first right function).

**Add languages, after the paper.** codemem indexes nine languages. The eval grades three.

| Language | Graded today | To add | Candidate repos (to check with `cmeval repo-stats`) |
|---|---|---|---|
| Python | yes: pandas, transformers, home-assistant, airflow | — | — |
| C++ | yes: Godot, duckdb, llama.cpp | — | — |
| TypeScript | yes: vscode, playwright | — | — |
| Go | no | a labeler; three repos | kubernetes, tidb, gitea (probed, below) |
| Java | no | a labeler; two repos | kafka, elasticsearch, spring-boot |
| Rust | no | a labeler; three repos | rust, zed, datafusion; ruff as a medium repo (probed, below) |

"A labeler" is the part of `cmeval` that turns a fix into gold line ranges with tree-sitter. It is
written separately from codemem on purpose, so that a codemem bug cannot grade itself. Each new
language needs one, as C++ and TypeScript did.

**Go and Rust go first of the three, from big repos.** A probe of 24 candidate repos on GitHub
(Nov 22) gave the counts below, for the window of the other task sets (fixes merged from
2026-07-01 to 2026-10-22). "Linked" is the number of merged pull requests with a linked issue. It
is an upper limit on tasks: in our other sets, 58 to 87% of the pull requests with exactly one
linked issue became tasks.

| Language | Repo | Code in the language | Merged pull requests | Linked | Role |
|---|---|---|---|---|---|
| Go | kubernetes/kubernetes | 109 MB (98%) | 1,421 | 246 | the largest |
| Go | pingcap/tidb | 64 MB (95%) | 851 | 280 | large |
| Go | go-gitea/gitea | 16 MB (83%) | 970 | 238 | medium |
| Rust | rust-lang/rust | 152 MB (91%) | 3,211 | 707 | the largest |
| Rust | zed-industries/zed | 68 MB (98%) | 2,017 | 485 | large |
| Rust | apache/datafusion | 40 MB (99%) | 1,531 | 607 | large |
| Rust | astral-sh/ruff | 30 MB (97%) | 1,806 | 395 | medium |

What the probe ruled out:
- **golang/go and cockroachdb/cockroach** do not merge through GitHub pull requests (0 and 17 in
  the window), so the collector finds nothing there;
- **prometheus and tokio** have too few linked pull requests (74 and 34);
- **grafana** is 47% Go and half TypeScript, so many of its fixes are not all Go. It is a reserve,
  with servo, bevy, deno and nushell.

What each language needs beyond a labeler:
- **Go:** skip generated files (the `// Code generated ... DO NOT EDIT.` header) and `vendor/`;
- **Rust:** unit tests live in the same file as the code, in `#[cfg(test)]` modules. Today a file
  is code or test by its path. Rust needs a rule inside the file, so that a change to a test
  module counts as a test change. Code inside a macro call is not parsed, and the share of fixes
  that land there is reported.

File counts, chunk counts and cold build times are not measured yet. `cmeval repo-stats` and a
build-time estimate come before a repo is admitted. By their size, kubernetes and rust may take
longer to index than Godot (2 h cold on the M5). These tasks serve the retrieval eval and the
localization tier (§12.1). Graded end-to-end runs on them would need a build container for each
repo, and they are not planned.

**When is open.** This section says "after the paper". Andrew proposes the repo measurements now
and the labelers and the collection from Dec 2, about 2 to 3 working days, so the two languages
can be in the paper's retrieval table.

**Add a second query per task.** Each task also gets its vague rewrite (§9). The headline table
then has two columns per language: the issue text, and the vague request. Tracks B and C tune on
both.

**Add two stronger baselines.** A November 2026 study from Ant Group found that the lead of
embeddings over keyword search shrinks to 0.03 to 0.13 nDCG@10 once the keyword search ranks whole
files, and disappears when a model first adds likely identifiers to the query *(reported)*. Its
reference embedding model was the one codemem uses today. A reviewer will ask the same question,
so the retrieval eval gains:
- **keyword search over whole files**, next to today's function-level grep baselines;
- **grep with guessed identifiers:** a model reads the prompt, proposes names that might appear
  in the code, and those are added to the search. This is what a strong agent does on its own.

**Keep it short in the paper:** one table, three languages, two query kinds.

---

## 13. Metrics and statistics

**Primary measures**, fixed before any test-split run:

| # | Measure | Compared how |
|---|---|---|
| 1 | processed tokens per task (§5.4) | the ratio between setups, on the same task |
| 2 | wall time per task (§5.5) | the ratio between setups, on the same task |
| 3 | completion | the difference between setups, on the same task; and a check that codemem is not worse by more than 5 points |

**Secondary:** processed tokens per completed task; tokens read, by tool; tokens, seconds and
turns before the first edit; share of runs that called codemem; how failed runs ended.

**How differences are tested:**
- **The unit is the task.** Every comparison pairs two setups on the same task. Repetitions of a
  task are averaged first, or modelled as repeated measures.
- **Intervals** are 95% bootstrap intervals that resample whole tasks, and whole repos as a check.
- **The model.** One regression with setup, model tier, repo size and vagueness, and their
  interactions with setup, with a random effect per task and per repo. The interactions are the
  paper's main figure: where does the setup matter?
- **Several tests, one correction.** The three primary measures are corrected together (Holm), as
  `cmeval` already does.
- **Two views of tokens and time:** over all runs, and over tasks that both setups completed. The
  first can flatter a setup that gives up early; the second can hide one that completes more. Both
  are reported.

**What we take from others' practice** *(reported)*:
- **Four classes of tokens, never one total.** Cache reads are the largest class in agent runs.
- **No convention exists for "work before the first edit".** One 2026 study counts turns and
  characters before the first edit. We count turns, tokens and seconds, and say so.
- **Repetitions matter.** A study of randomness in agent evals found single runs of the same setup
  differ by 2.2 to 6.0 points of completion. Three repetitions is the floor.
- **The closest prior study** needed 80 tasks and 3 repetitions to show a 7.9-point difference in
  completion with a paired signed-rank test.

**How many tasks.** Planning numbers, to be replaced by the first runs':

| To detect | Assumption | Paired tasks needed |
|---|---|---|
| a 15% change in tokens or time | the log of the ratio varies with a standard deviation of 0.5 | about 75 |
| a 10% change in tokens or time | the same | about 180 |
| a 10-point change in completion | 20% of tasks are completed by only one of the two setups | about 150 |
| a 5-point change in completion | 15% of tasks are completed by only one of the two setups | about 470 |

**What fits before the paper** is near the first row: 75 to 100 test tasks. Under the same
assumptions they can show a saving of 13 to 15% in tokens or time, and a change in completion of
12 to 15 points, not less. So a frontier model's completion is likely to come out as "no
detectable difference", and the claim for frontier models rests on tokens and time. The exact
number of test tasks follows from how many runs our seats allow, which the first batch measures.

---

## 14. Work packages, in order

The pipeline comes first, on tasks that already exist. The vague prompts and the small models are
added to a pipeline that already works. Sizes are rough working days for one
person.

| # | Work | Deliverable | Done when | Days |
|---|---|---|---|---|
| A1 | **The pipeline skeleton,** end to end on the pilot of §2.2 (10 to 12 tasks from two or three repos): plan, run in a container, record, grade, score. Claude Code only, setups `grep` and `tool`, a cheap model | `cmeval e2e plan / run / grade / score` | the pilot's checklist (§2.2) passes, and one command produces a table of completion, tokens and time for the pilot tasks × 2 setups × 3 repetitions | 6 |
| A2 | **Measurement** (§5): the recording proxy, the cross-check, the six token numbers, the four clocks, the file watcher | the run record of §6 | on the runs of A1, proxy and agent summary agree within 1% on every run, and the proxy adds no measurable delay to the first byte | 4 |
| A3 | **Selection and plans** (§3): the flags, plan files, the run matrix, the iteration plan for tracks B and C | `plans/main.toml`, `plans/iterate.toml` | a plan can be previewed with `--dry-run`, stopped, and resumed without rerunning anything | 3 |
| A4 | **Robustness** (§7): integrity checks, failure classes, the canary, the spending cap, the dashboard view | `cmeval e2e check`; a canary plan | a deliberately broken setup (MCP server missing, wrong context size) is detected and its runs discarded | 3 |
| A5 | **Reports and statistics** (§13) | `cmeval e2e report` | a report can be rebuilt byte for byte from the run records | 3 |
| A6 | **The other setups and the second harness:** `upfront`, `placebo`, `tool-strong`; mini-SWE-agent in text mode with codemem as a command; the localization tier | every setup of §4.1; `--harness mini-swe-agent`; `--tier locate` | the pilot tasks run in every setup and both harnesses; the small-model floor is measured (30 easy tasks, 9B and 14B, `grep` only) | 6 |
| A7 | **Labels** (§10), first on public tasks | every label in the task file | a hand check of 50 tasks agrees with the difficulty and kind labels at least 85% of the time | 3 |
| A8 | **Vague prompts** (§9): the rewriter and its three checks | L1 and L2 for every task, and for the retrieval eval's dev tasks | check 2 passes on at least 80% of rewrites; the human agreement is reported | 4 |
| A9 | **Our own tasks** (§8): the RepoLaunch trial; then the generator for Python and TypeScript, then Go, Java, Rust and C++ | `cmeval generate <repo link>`; validated fresh tasks | 30 validated dev tasks per language | 10 |
| A10 | **Retrieval eval additions** (§12.2): labelers for Go, Java and Rust; the vague column; the two baselines | the six-language retrieval table | labels hand-checked on 15 tasks per language, as for C++ | 6 |
| A11 | **The small-model study** (§11) | the gap-closed table and the failure endings | the 9B and 14B models, on easy and medium tasks, 3 repetitions; the hard probe; a local repeat of a subset on a Mac | 6 |
| A12 | **The matrix on the test split** (§3.3) | the paper's main tables and figure | every primary measure reported with its interval | 5 |
| A13 | **Release:** tasks, images, the task-layer tool, a datasheet | a public dataset and repo | a stranger can add vague prompts and labels to a new set of tasks by following the README | 4 |

**When** (the dates are in [overview.md](overview.md) §8):

| By | Packages | What it gives the team |
|---|---|---|
| **Nov 25** | A1, A2 | the pipeline's first version: a task runs end to end in both setups, with tokens counted two ways that agree. Tracks B and C can start using it |
| **Dec 1:** the solution and the results | A3, a first A5, the computed labels of A7, a first subset of A8, and from A6 the second harness with the localization tier. From A11, the first small-model runs | the run matrix on the dev tasks: baseline and final on all of them, today's codemem on the medium ones, the vague subset, small models on easy and medium with the hard probe |
| **Dec 8:** the paper | A4, the full A5, the rest of A6, A7 and A8 on the test tasks, A11 at its planned size, A12, the vague column and the two baselines of A10, and the part of A13 that goes with a paper | the matrix run once on the test split with the frozen configuration, three repetitions and every integrity check; the `upfront` and `placebo` setups and the vague prompts on subsets; the code, the task list and the run records released with the paper |
| **Later, no date** | A9 beyond a trial; the three new languages of A10; the rest of A13 | our own fresh tasks in six languages, the six-language retrieval table, a dataset release with its datasheet |

A1 to A3 are what the other tracks wait for, so they go first and stay small. The December 1 row
is more than one person can do in nine days. Three parts stand on their own, so someone else can
take them: A2 (the proxy and the cross-check), the mini-SWE-agent part of A6 with the small
models, and the vague rewrites of A8. A9 is the least certain piece of the plan, which is why
nothing in the paper depends on it.

---

## 15. What track A needs from, and gives to, the others

| With | A needs | A gives |
|---|---|---|
| **Track B** | `codemem-today` frozen now, the final configuration on Nov 28 and again on Dec 3; a timing log from codemem for each search (§5.5); no change to tool names or card layout without notice; a note in the work log each time a new piece of retrieval can run | the iteration plan (§3.4); vague rewrites of the dev tasks, a first subset by Nov 27; end-to-end comparisons of card formats |
| **Track C** | a note in the work log as soon as the compact store works on one repo; before the first runs that embed through an API, a codemem install that works in a container without PyTorch; the compact configuration frozen; memory, disk and build-time numbers per repo | the same iteration plan and vague rewrites |

**The eval stays independent of codemem.** `cmeval` never imports codemem except in its one
adapter file, and the labelers stay separate implementations. The end-to-end runner treats codemem
as a black box: an MCP server, a command, and an index folder.

---

## 16. Risks and open questions

| Risk or question | Why it matters | What we do |
|---|---|---|
| Agents don't call codemem | no call, no effect; one vendor saw 1 call in 143 sessions *(reported)* | tools loaded up front; adoption measured in the first runs; `upfront` and `tool-strong` as separate setups |
| The token numbers are wrong and nobody notices | every claim rests on them | two independent counts that must agree (§5.3); the canary |
| Building environments is slow and fragile | published yields range from 9% to 50% of candidates, and the builder needs keys of its own | this phase's results use public tasks that already have images; the generator gets a trial at most |
| Public benchmarks we borrow are flawed | OpenAI estimated that about 30% of SWE-bench Pro's public tasks were broken and stopped recommending it; it had already dropped SWE-bench Verified *(reported)* | tasks are spot-checked by hand before they enter the test split, and a task whose gold patch fails its own tests in our container is dropped |
| Vague prompts become unsolvable | failures would then say nothing about search | check 2 in §9 |
| Usage limits slow everything down | three seats, each with a session and a weekly limit, are all the Claude time we have, and we code on the same seats | the run matrix spends large tasks only on the baseline and the final configuration; the baseline is reused; `--dry-run` sizes a plan first; the first batch tells us how many runs fit in a window |
| The public tasks are older than the models | a model may remember a fix | the same model runs in both setups, so it cannot favour one side; every table says how many tasks are fresh; the closed-book probe below tags tasks a model answers from memory |
| The harness changes under us | Claude Code updates often | pin the version; record it in every run; the canary after any upgrade |
| Small models complete almost nothing | given the gold files, small models repaired 2 tasks of 100 in one study *(reported)*; a base rate that low cannot show a change | the floor is measured first (A6); localization is the primary measure for small models; easy and medium tasks only, plus a small probe |
| The answer leaks | a fresh fix is public on GitHub | no network, no web tools, history cut at the task's commit; a closed-book probe that asks the model for the gold files from the prompt alone, and tags tasks it answers |
| Two harnesses, two sets of numbers | results may not line up | nothing is compared across harnesses: the model gap is measured inside mini-SWE-agent, and the Claude results inside Claude Code |

---

## Sources

Items marked *(reported)* in this file were read by research passes on Nov 22, 2026. Re-read a
page before citing it in the paper.

**Claude Code and other agents**
- Claude Code documentation: headless mode, https://code.claude.com/docs/en/headless · command
  line, https://code.claude.com/docs/en/cli-reference · MCP, https://code.claude.com/docs/en/mcp ·
  authentication, https://code.claude.com/docs/en/authentication · cost tracking,
  https://code.claude.com/docs/en/agent-sdk/cost-tracking · monitoring,
  https://code.claude.com/docs/en/monitoring-usage · gateways,
  https://code.claude.com/docs/en/llm-gateway
- mini-SWE-agent, version 2, https://mini-swe-agent.com/latest/advanced/v2_migration/
- Ollama, context length, https://docs.ollama.com/context-length
- Harbor, task configuration, https://docs.harborframework.com/tasks/configuration
- Our own request traces from the CS146S week 1 assignment (a mitmproxy capture; not in this repo)

**Studies of search tools in agents**
- Bellam, https://arxiv.org/abs/2610.33958 · Code Isn't Memory, https://arxiv.org/abs/2606.22417
- CodeNib, https://arxiv.org/abs/2607.25431 · CodeGrep, https://arxiv.org/abs/2608.05886 ·
  Physical Cost of Context, https://arxiv.org/abs/2610.34763
- Embeddings vs. Grep, https://arxiv.org/abs/2611.20455
- Does a language server save tokens for coding agents?, https://arxiv.org/abs/2608.13568
- Sourcegraph, CodeScaleBench,
  https://sourcegraph.com/blog/codescalebench-testing-coding-agents-on-large-codebases-and-multi-repo-software-engineering-tasks
- JetBrains, IDE-native search tools (corrected July 2026),
  https://blog.jetbrains.com/ai/2026/05/what-happens-when-you-give-agents-ide-native-seach-tools/
- A study of 1,100 failed agent runs across harnesses, https://arxiv.org/abs/2610.32131

**Task pipelines and benchmarks**
- SWE-bench-Live and RepoLaunch, https://arxiv.org/abs/2603.05026 and
  https://github.com/microsoft/SWE-bench-Live · its task sets,
  https://huggingface.co/datasets/SWE-bench-Live/SWE-bench-Live and
  https://huggingface.co/datasets/SWE-bench-Live/MultiLang · RepoLaunch,
  https://github.com/microsoft/RepoLaunch
- SWE-rebench V2, https://arxiv.org/abs/2602.23866 and
  https://github.com/SWE-rebench/SWE-rebench-V2
- SWE-Factory, https://arxiv.org/abs/2506.10954 · SWE-smith, https://arxiv.org/abs/2504.21798 ·
  SWE-bench, https://arxiv.org/abs/2310.06770
- Multi-Docker-Eval, https://arxiv.org/abs/2512.06915
- SWE-bench Pro, https://arxiv.org/abs/2509.16941 and https://github.com/scaleapi/SWE-bench_Pro-os
- OpenAI on SWE-bench Pro and Verified,
  https://openai.com/index/separating-signal-from-noise-coding-evaluations and
  https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified
- SWE-bench on ARM, https://github.com/SWE-bench/SWE-bench/issues/520 · Modal's prices,
  https://modal.com/pricing

**Vague prompts and labels**
- Saving SWE-Bench, https://arxiv.org/abs/2510.08996 · Ask or Assume?,
  https://arxiv.org/abs/2603.26233 · FeatBench, https://arxiv.org/abs/2509.22237
- SWE-bench-Live's first paper (change size and repo size), https://arxiv.org/abs/2505.23419
- What SWE-bench Lite issues name, https://github.com/hammasbuilds/swebench-localization

**Measurement and statistics**
- How Do AI Agents Spend Your Money?, https://arxiv.org/abs/2604.22750
- On Randomness in Agentic Evals, https://arxiv.org/abs/2602.07150
- Work before the first edit, https://arxiv.org/abs/2605.20049
- Miller, Adding Error Bars to Evals, https://arxiv.org/abs/2411.00640

**Small models**
- SWE-rebench, https://swe-rebench.com · the SWE-bench board, https://swebench.com
- Qwen3.5-9B, https://huggingface.co/Qwen/Qwen3.5-9B · Qwen3.8-27B,
  https://huggingface.co/Qwen/Qwen3.8-27B
- Speed and memory on Apple silicon, https://machinelearning.apple.com/research/exploring-llms-mlx-m5
  and https://github.com/ggml-org/llama.cpp/discussions/4167

**Ours**
- The collection funnel and the labels: `eval/tasks/*.meta.json` and
  [eval/README.md](../../eval/README.md).
