# Track A: the evaluation pipeline

**Status:** a plan, written Nov 22, 2026. Nothing here is built yet. The shared context is in
[overview.md](overview.md). The eval that exists today is described in
[eval/README.md](../../eval/README.md).

**Goal.** One pipeline that hands a real task to a coding agent, with and without codemem, and
records whether the agent completed it, how long it took and how many tokens it used. The pipeline
comes first. Once it runs, tracks B and C change codemem and rerun it, many times.

**Where this track sits.** It carries the project's primary goal: the end-to-end study, and the
model gap that is part of it ([overview.md](overview.md), "What we are after"). Tracks B and C
give it a good system to test.

**The order of work.**
1. **The eval set-up, end to end.** Our own tasks, generated from repos we choose and taken in a
   fixed order (§8), and the pipeline that runs and grades them: one command for a chosen set of
   tasks, setups and models, with tokens and time from two sources that must agree (§2 to §7).
2. **The first end-to-end test:** two repos, with the codemem that exists today (§2.2).
3. **The main comparison.** When tracks B and C deliver the improved codemem, everything is
   indexed again and the full runs start, on tasks in several languages (§8.3). The index should
   be much smaller by then, which is why only two repos are indexed before it.
4. **The model gap, in the same days:** the same tasks, with open models in open harnesses, to
   see whether codemem helps a small model more (§4.6, §11). At least one open model is in the
   presentation.

**What exists at the end:**
- the task generator and its tasks, with labels (§10) and a vague version of each prompt (§9);
- the pipeline, with flags and plan files that choose what runs (§3);
- the retrieval eval kept short, with a vague query per task and two stronger baselines (§12.2);
- a release with the paper: the generator, the pipeline, the tasks and the run records.

**When.** The improved codemem is frozen on Nov 27 at 16:30 Pacific. The full runs start the same
day at 17:00 Pacific, with the check run: its report is read before the batches run unattended
overnight ([runs.md](runs.md) §6). Sat Nov 28 and Sun Nov 29 are reserved for running. The model
gap runs beside them on its own endpoint, once the open harness and the open models are ready,
which is expected on Sat Nov 28. The freeze is aimed at Nov 30, 23:59. The
hard limit is the presentation on Dec 1 at 14:00. Six more
days of refining follow, to the paper on December 7. The schedule, night by night, is in §14.

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

**How a run is judged.** The agent gets the prompt, and the repo as it was just before the real
fix. It works until it stops or hits a limit. Then the real pull request's own tests, which the
agent never saw, are run on what it left behind. If they pass, the run completed the task. Time
and tokens are counted over the whole run, whether it completed or not. The exact rules are in
§4.7.

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

### 2.2 The first end-to-end test: two repos

This file designs the whole study. The build does not start with the whole study. Once tasks exist
for two repos (§8), the whole chain runs on those two, with the codemem that exists today, before
any other repo is indexed. An error is cheap to see and to fix there.

**The first job of whoever picks up this track, person or agent: run the admission check of §8.2
on the first two repos of §8.3, and confirm them or say why another repo takes a place.**

| The first test | |
|---|---|
| Repos | two, in different languages: the first two of the list in §8.3, pandas (Python) and playwright (TypeScript), unless the admission check rejects one |
| Tasks | first 10 to 12 of them, of mixed difficulty (easy, medium, and at least two hard ones, §10), to bring the chain up. Then every validated task of the two repos |
| Setups | `grep` and `tool` |
| codemem | what exists today, with its local embedding model (§2.3) |
| Agent model | Haiku 5.5 while the chain is being built, then Sonnet 5.5 |
| Control | five ready-made SWE-bench-Live tasks (§8.4). Their environments are known to work, so a failure there is the pipeline's fault, and a failure only on our own tasks is the generator's |

**The test has passed when all of this is true:**
- every stage runs for every task in both setups: plan, index, run, grade, score, report;
- the grader is right: for every task the real change passes, and an empty change fails;
- the two token counts agree within 1% on every run (§5.3);
- the first event of every `tool` run lists codemem's tools, and some runs call them;
- a batch can be stopped and resumed, and a deliberately broken setup is caught (§7);
- one of us has read three whole transcripts, at least one per repo.

Only then are the other repos of §8.3 indexed and run, in order.

**Why two repos first.** Tracks B and C are still improving codemem. Today's index keeps every
vector in memory at full size and loads a 2.2 GB model: for 200,000 vectors, 358 MB of memory and
717 MB of disk ([track C](track-c-memory.md) §3). Track C's target for the same vectors is under
30 MB of memory, and track B changes what is indexed. Every repo indexed today is indexed again
when that lands. So two repos are indexed now, and the others when the improved codemem is ready.
Tracks B and C announce each new configuration in the work log
([CONTRIBUTING.md](../../CONTRIBUTING.md) §3), and these two repos are where it is tried first.
The rest of the plan calls them the pilot repos.

**What does not wait.** Generating tasks for the other repos needs no index, so it goes on in the
meantime. So do baseline runs, which do not use codemem.

### 2.3 Which codemem, and which embedding model

**The pipeline is general on purpose.** It does not know what is inside codemem. It is handed a
codemem configuration file and treats codemem as a black box: an MCP server, a command and an
index folder (§15). So it runs whatever codemem can build: today's version, a branch of track B or
C, the final one. Tracks B and C are still changing retrieval and storage, and the pipeline must
not need a change when they do.

**Now: what exists today, with a local embedding model.** The first runs use today's codemem and
its default local model (`jinaai/jina-code-embeddings-0.5b`), or the local model track C chooses
in its place ([track C](track-c-memory.md) §6).

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
tasks = "tasks/e2e-v1.jsonl"          # every validated task, from every repo that is up
sample = { per_repo = 20, strata = "difficulty", seed = "main-1" }
reps = 3
order = "by-repetition"               # repetition 1 of everything before repetition 2
harness = "claude-code"
models = ["claude-sonnet-5-5"]

[[cell]]                       # the reference: Claude with its own tools
name = "baseline"
setups = ["grep"]

[[cell]]                       # our final solution, on the same tasks
name = "final"
setups = ["tool"]
codemem = "final"

[[cell]]                       # today's codemem: medium tasks are enough to show the difference
name = "today"
setups = ["tool"]
codemem = "today"
where = { difficulty = "medium" }

[[cell]]                       # the model gap: an open model in an open harness
name = "gap"
harness = "mini-swe-agent"
endpoint = "hosted"            # or "local": a server on one of our Macs
models = ["qwen3.5-9b"]        # then "qwen3.8-27b", then "qwen3-14b"
setups = ["grep", "tool"]
codemem = "final"
where = { difficulty = ["easy", "medium"] }

[[cell]]                       # a few hard tasks, to see whether a small model can do them at all
name = "gap-probe"
harness = "mini-swe-agent"
endpoint = "hosted"
models = ["qwen3.5-9b"]
setups = ["grep", "tool"]
codemem = "final"
where = { difficulty = "hard" }
sample = 10
```

- **`sample`** under `[plan]` draws the same tasks for every cell: a fixed number per repo, spread
  over the difficulty levels, from a seed. The drawn list is written to a file and committed
  before the first run. No run may change it afterwards.
- **`order`** makes a batch that is cut short still useful: after repetition 1, every task has one
  complete result in every setup.
- **`endpoint`** says where an open model is served: a hosted API, or a server we host (§11).

### 3.3 The run matrix

The plan above, as a table. This is the proposal for what the paper's numbers come from.

| What runs | On which tasks | Why |
|---|---|---|
| **Baseline:** Claude with its own tools, no codemem | every task, including the large and hard ones | the reference for everything |
| **Final:** Claude with the final codemem | every task | the headline: tokens and time against the baseline, and completion |
| **Today's codemem,** the simple version that exists now | medium tasks only | enough to show the step from today's version to the final one. The large tasks would be wasted on it |
| **The model gap:** an open model, the 9B first, with and without codemem | the easy and medium tasks of the same sample | the second part of the study. At least one open model before the presentation. A small model is not expected to finish hard, spread-out tasks |
| **The model gap, a probe** | about 10 hard tasks | to check that expectation instead of assuming it |
| **Mechanism setups:** results up front, placebo, stronger wording (§4.1) | a medium subset | to explain the headline, not to be it |

**Many tasks are prepared, and a sample is run.** The generator prepares 30 to 40 validated tasks
per repo. The full runs take a fixed sample of them: 20 per repo, spread over easy, medium and
hard, drawn once from a seed and committed before the first run. If usage runs short, the sample
shrinks to 15 per repo, then to 12. The languages stay. The number of tasks gives way.

**Dev and test.** Every task is marked dev or test, and our own tasks keep the mark they already
carry from the retrieval eval (§8.1). The sample holds both. Tracks B and C tune on dev tasks
only, so the test tasks of the sample are run once, with the configuration frozen on Nov 27
([overview.md](overview.md) §8).

**Runs are scheduled by repetition.** Repetition 1 of every task in every setup comes first, then
repetition 2, then 3. If a batch is cut short, what exists is a complete table with fewer
repetitions, never a table with holes.

**What comes first when seats are scarce:**
1. baseline and final, on the whole sample;
2. today's codemem, on the medium tasks;
3. the vague subset;
4. the mechanism setups.

The model gap is not in this list. It does not use the seats: it runs on its own endpoint at the
same time.

**The baseline is run once and reused.** A baseline run does not depend on codemem. So when track
B or C changes codemem, only the codemem cells are rerun, and they are compared with baseline runs
already on disk. This roughly halves the cost of every iteration.

**One measure is exempt: wall time.** The API is faster on some days than on others. So time is
compared only between runs of the same batch, made turn about (§4.5, rule 8). A reused baseline
serves tokens and completion. In the main batch, baseline and final run together.

### 3.4 The loop tracks B and C use

Tracks B and C should not need track A's owner to try a change. The pipeline ships a small fixed
plan for that:

```bash
cmeval e2e run plans/iterate.toml --codemem ./my-branch.toml --run-id try-stemming
cmeval e2e report try-stemming --compare baseline tool
```

`plans/iterate.toml` is 20 to 30 medium dev tasks, one cheap model, the `tool` setup, 2
repetitions. The baseline side is already on disk. One try should take under an hour and a small
part of one seat's usage window. It is a smoke signal, not a result: nothing is claimed from it. Its
report also shows how often codemem was called and at which turn first. Track B needs those
numbers for its adoption check ([track B](track-b-retrieval.md) §5).

---

## 4. What a run is

### 4.1 The setups

| Setup | The agent has | Why |
|---|---|---|
| `grep` | its shipped tools: grep, file listing, file reads, a shell, and its own built-in search subagent if it has one | the baseline is the agent as people use it |
| `tool` | the same, plus codemem's tools, loaded before the first turn, with the wording that ships, which is `light` today and is track B's to set ([track B](track-b-retrieval.md) §5). The agent decides whether to call them | this is how codemem ships |
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

Claude models and open models cannot share a harness (§4.6 explains why), so there are two arms.

| Arm | Harness | Models | codemem reaches the agent as | Why this one |
|---|---|---|---|---|
| Claude | **Claude Code, headless** | Claude Sonnet 5.5 and Haiku 5.5 | MCP tools | it is the product people use, and the only harness our subscriptions cover |
| Open models, main | **mini-SWE-agent** | 9B, 14B and 27B | a shell command, `codemem search "..."`, on the sandbox's path and described in the system prompt | it is the harness the official SWE-bench board uses to compare models. Its fixed prompt is about 800 tokens. It takes actions as plain text or as a single tool call, so it does not depend on how well a model calls tools |
| Open models, second | **Qwen Code** | 9B and 27B | MCP tools, as in Claude Code | the open harness made for these models. It attaches codemem the way codemem ships |

Claude runs only in Claude Code, under our subscriptions. The open models run only in the open
harnesses, through an API or a server we host. So the model gap is measured inside one open
harness, from the 9B model up to the 27B one, and the Claude results stand beside it.

**Any endpoint will do.** Every open harness here takes an OpenAI-style endpoint: a base URL, a
key and a model name. The same model on Nebius, on another provider or on our own server is the
same run with a different address.

**The harness matters as much as the model.** One 2026 study of 1,100 failed runs found that
changing the harness moved the same open model by 28 to 44 points *(reported)*. So results are
never compared across harnesses, only within one.

The candidates, the evidence behind this choice, and the short trial that confirms or changes it
are in §4.6.

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
- **Published test images need x86 Linux.** They are built for x86 only: SWE-bench's maintainers
  closed ARM support as "not planned" in August 2026, and a contributor measured tests 6 to 9
  times slower under emulation *(reported)*. Our own images are built for the machine that runs
  them, so on our Macs they run at full speed (§8.2).
- **Containers are cheap next to model calls.** At 4 cores, 16 GB and 10 minutes a run, 100 runs
  cost about $11 on Modal's sandboxes, or $3 to $6 on one rented cloud machine *(reported prices,
  our arithmetic)*.
- **Use a task format others already use.** SWE-bench Pro's second version ships its tasks in the
  Harbor format: one folder per task, an agent phase with no network, grading on a clean image,
  and a time cap. Harbor already runs Claude Code, and a task can declare an MCP server
  *(reported)*. Writing our tasks in that format means we write a task exporter and a recorder,
  not a container harness.

### 4.5 Rules that keep the comparison fair

1. **One difference.** The same prompt, repo snapshot, model, limits, container and machine.
   Only the setup changes.
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
7. **Tasks are newer than the model.** Our own tasks come from pull requests merged after the
   model's training cutoff. The ready-made add-on is older, and is reported apart (§8.4).
8. **Setups take turns.** The runs of one task are started alternately (`grep`, `tool`, `grep`,
   `tool`), not one whole setup after the other, so a slow hour at the API hits both.
9. **A dev split for building, a test split run once.** Prompts, limits and codemem settings are
   fixed on the dev split before any test-split run.

### 4.6 Open harnesses for the open models: what exists

**The problem.** The open models run on our own server or on a provider such as Nebius. Claude
Code and Codex are built around their vendors' models. We need a harness whose model is a
setting. Everything in this section is *(reported)*: it was read on the projects' own pages on
Nov 22, and nothing was run.

**Can the vendors' agents take another model?** In part, and not as our main route.

| Agent | With an open model | Why it is not the main route |
|---|---|---|
| Claude Code | it works against any endpoint that speaks Anthropic's API, which Ollama offers. Alibaba's own model card says its 27B model was evaluated in the Claude Code harness | Anthropic's documentation says it "doesn't support routing Claude Code to non-Claude models through any gateway". Its fixed prompt is about 16,600 tokens on every call, and the 14B model's whole window is 32,768 |
| Codex CLI | only against an endpoint that serves OpenAI's Responses API. Support for the usual chat API was removed | it depends on each provider's version of that API |
| Any other harness, with a Claude model | not under a subscription. OpenCode's documentation: "Anthropic explicitly prohibits this" | it would need a Claude API key, which this plan does not use |

**Open harnesses.** All of them take any OpenAI-style endpoint, hosted or local.

| Harness | Must the model make native tool calls? | codemem attaches as | What a headless run reports | Note |
|---|---|---|---|---|
| **mini-SWE-agent** 2.4 | no: it has a plain-text mode and a one-tool mode | a shell command | a trajectory file with every raw response. Token counts are inside those responses | the SWE-bench board's harness. Its runner takes any SWE-bench-format file with a Docker image per task, which SWE-bench-Live has |
| **Qwen Code** 0.28 | yes | MCP | JSON, with token usage per run and per message; limits on turns, time and tool calls | made for Qwen models. It sends every tool definition on every request |
| OpenCode | yes | MCP | JSON lines, with tokens per step | two version lines in parallel. With the same 27B model it scored 9 points under mini-SWE-agent in one study |
| Goose | yes | MCP | JSON, with tokens per run only | one binary |
| OpenHands, through its SDK | no: it has a mode without native calls | MCP | through the SDK's metrics | its command-line tool is no longer maintained |
| Inspect's ReAct agent | no: it can emulate tool calls | MCP | token usage per task, in its log | part of an eval framework (below) |
| Terminus 2 | no: it types plain keystrokes | a shell command | through Harbor (below) | built as a neutral test bed for models |

**Do small models manage native tool calls? Both sides.**

| They do | They do not, or not reliably |
|---|---|
| Qwen3.5-9B resolved 54.8% of SWE-bench Verified in Claude Code and 60.6% in mini-SWE-agent, in one vendor's report | In the same report the weakest of seven harnesses was 24 points under the best. At 27B the spread in another study was 9 |
| At 27B, Claude Code and mini-SWE-agent came out "equivalent within five points" (347 against 353 of 444 tasks) | The prompt alone: 16,581 tokens a call in Claude Code, 7,025 in OpenCode, 829 in mini-SWE-agent. Qwen3-14B's window is 32,768 |
| Plain-text actions are not automatically safer. A 4B Qwen broke mini-SWE-agent's text format in 16 of 18 runs and did far better with native calls, in a small study that compared against its authors' own harness. On a function-calling benchmark, Qwen3-14B scores 34.75 on multi-turn tasks with native calls and 26.13 with prompted ones | Local servers still mis-read Qwen3.5 tool calls: reports against Ollama, llama.cpp and mlx-lm from February to November 2026 |
| | With 259 tools loaded, an 8B model answered in plain text instead of calling one (one report) |

**Reading.** Native calls work better than this plan first assumed, and they fail in ways that
depend on the server and on how much the harness puts into the prompt. Nothing was measured for
the base 14B model. So the choice of §4.2 has two parts:
1. **mini-SWE-agent is the main harness, and both of its modes are tried** for each model. The
   mode with fewer broken actions is used for that model.
2. **Qwen Code is the second harness** for the 9B and 27B models, so that codemem is also
   measured the way it ships, as an MCP tool. The 14B model's window is too small for it.

**Claude Code with an open model is an option, not part of the plan.** It is the only way to have
one harness on both sides of the model gap without a Claude API key, and others have published
results that way. Against it: Anthropic does not support it, and its prompt leaves a small model
little room. Decide after the trial below. If it is run, it is reported as a separate arm.

**Frameworks that run a harness over the tasks.**

| Framework | What it would save us | What is missing, or to check |
|---|---|---|
| **Harbor** 0.27 | one job file runs Claude Code, Qwen Code, OpenCode or mini-SWE-agent over the same tasks. An MCP server is declared per run, so "with codemem" and "without" are two entries on identical tasks. It records tokens (input, cached, output) and separate times for the environment, the agent and the tests. A task is a small folder: an image name, the prompt, a test script | it knows neither our own tasks nor SWE-bench-Live's, so our exporter writes the folders. For mini-SWE-agent and Terminus 2 it only mentions an MCP server in the prompt and does not connect it. To check: that its Claude Code agent accepts a subscription login, the clean-run switches of §4.3 and our proxy |
| **Inspect AI** | a simple agent that takes MCP tools and can emulate tool calls; token usage per task; SWE-bench with ready images, and other task sets through a parameter. It can also drive Claude Code, OpenCode and mini-SWE-agent | our tasks need a short task and a scorer in Python. It routes the agents' model calls through itself: check what that does to a subscription login |
| mini-SWE-agent's own runner | nothing to build for the main open arm: `mini-extra swebench --subset <our file>` | it produces patches only. Grading, token totals and timings stay ours |

Tasks are already planned in Harbor's format (§4.4), so Harbor is tried first, for both arms. If
it cannot run Claude Code the way §4.3 requires, our own runner starts each harness. The recording
proxy stays either way: the cross-check of §5.3 needs a count that does not come from the harness.

**The harness trial.** Run it on the pilot tasks (§2.2) as soon as the open arm exists, with the
9B model on one server:

| Run | What it shows |
|---|---|
| mini-SWE-agent, plain-text mode | the floor: no tool calling is needed |
| mini-SWE-agent, one-tool mode | whether native calls help or hurt this model on this server |
| Qwen Code, with codemem over MCP | whether an MCP harness is usable at 9B, and whether the model calls codemem |

For every run, record how it ended: finished, a broken or missing action, a full context window,
or the turn limit. Record also whether codemem was called and whether token counts were captured.
Ten tasks cannot rank harnesses: in one study, reruns alone flipped 13% of tasks. The trial
answers one question: does each harness work at all with this model? OpenCode is the replacement
if Qwen Code does not.

**Traps the research found.** Each one changes results without an error.
- **mini-SWE-agent:** in version 2.4.6 the text mode must be chosen with
  `--model-class litellm_textbased`. The text configuration files alone do not select it (read in
  its source; confirm it). A model it has no price for needs `cost_tracking: "ignore_errors"`.
- **The server's tool-call parser:** Qwen3.5 and Qwen3.8 write tool calls in an XML form, and
  vLLM needs `--enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3`.
  Qwen3-14B uses the older form: `--tool-call-parser hermes`.
- **Context length:** Ollama defaults to 4,096 tokens (§11). Qwen Code assumes a local model has
  a window of a million tokens unless `contextWindowSize` is set. OpenCode assumes 200,000 unless
  `limit.context` is set.
- **OpenCode, version 2:** an MCP server is hidden behind a code-writing tool unless it is
  declared with `codemode: false`.
- **Harbor with a model server on the host:** pass `--skip-model-parsing-and-provider-mapping`,
  and reach the server as `host.docker.internal`. Inside the container, `localhost` is the
  container.

### 4.7 How a run is judged

**What the agent gets.** The prompt, and the repo checked out at the commit just before the real
fix, in a container where the project's tests can run. Nothing else: no hidden tests, no web, and
no history after that commit.

**When it ends.** The agent works until it stops by itself or reaches a limit: 150 turns or 50
minutes, whichever comes first. Both setups of a task get the same limits.

**What is graded.** Whatever the agent left behind: the difference between its working tree and
the task's commit, with new files, without build output. A run that ended at a limit is graded
like any other, on what it left. How it ended is recorded beside the verdict.

**How it is graded.** In a fresh container at the task's commit:
1. the agent's changes are applied;
2. the hidden test files are put in place. They are the test files of the real pull request, and
   they overwrite any version of those files the agent wrote;
3. the task's test command is run.

**The verdict.** A run has **completed** the task if every test that had to start passing passes,
and every test that had to keep passing still passes. Both lists were fixed when the task was
validated (§8.1). Everything else is "not completed": changes that do not apply, a build that
breaks, a failing test, an empty change.

**What is measured beside it,** on every run, completed or not:
- **time:** from the agent's start to its exit. Building the index and starting the container are
  timed apart (§5.5);
- **tokens:** every token the model read and wrote over the whole run (§5.4);
- **what it did:** its searches, the files it read, and whether it called codemem (§6).

**From runs to a result.** Each task is run three times in each setup. A task's completion in a
setup is the share of its three runs that completed. Its time and its tokens are averaged the
same way. The result is the difference between the setups on the same task, over all tasks (§13).

**What this does not judge.** Whether the change is as good as the real one, or written as a
maintainer would write it. The tests are the only judge, as in SWE-bench.

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

The open harnesses talk to open models through an OpenAI-style endpoint. The same proxy sits in
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
| Search behaviour | files read; whether and when a gold file was read; whether codemem was called, how often, at which turn first, and what it returned |
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

Two sources. **Our own tasks are the main one:** generated from repos we choose, newer than the
models, and made by a tool we keep. **SWE-bench-Live is an add-on:** it is ready-made, so
including it costs little.

### 8.1 Our own tasks: the generator

**In plain words.** Point it at a GitHub repo. It finds merged pull requests that fixed an issue
and came with tests, rebuilds the repo as it was just before each one, checks that the tests fail
before the change and pass after it, and writes out a task.

```
 a GitHub repo, and a date range after the model's cutoff
      │
      ▼
 1. COLLECT    merged pull requests with one linked issue written before the fix   ┐ exists:
 2. SPLIT      the change into code and tests; record the commit just before it    ┘ cmeval collect
      │
      ▼
 3. BUILD      an image of the repo at that commit, from the repo's recipe (§8.2)   ┐
 4. VALIDATE   run the pull request's tests before and after the real change,       │ new
               three times: keep the task if some tests go from failing to          │
               passing, and none that passed before now fail or flicker             ┘
      │
      ▼
 5. LABEL      gold files and functions (exists); size, kind and difficulty (§10)   ┐ new, and
 6. REWRITE    the vague versions of the prompt, with their checks (§9)             ┘ ours alone
      │
      ▼
 7. PACKAGE    one JSON line per task, a task folder in the Harbor format, a datasheet
```

**The first half exists, and has already run.** Steps 1 and 2 are `cmeval collect`. For twelve
repos, 3,788 tasks from pull requests merged between July 1 and October 22, 2026 are on disk in
`eval/tasks/`. Each holds the issue text, the commit before the fix, the code change, the test
change and gold labels.

**They are already split into dev and test.** The end-to-end tasks keep that split. So nothing
that tracks B and C tune on can end up in the end-to-end test set.

**What is new** is steps 3 and 4, the new labels of step 5, and step 6.

**The command.** `cmeval generate <repo>` runs steps 3 to 7 for a repo that has a recipe. Each
step writes to disk, and a run that stops can be resumed, as in the rest of the pipeline.

### 8.2 One recipe per repo

**The idea.** We are not making tasks for hundreds of unknown repos. We are making them for about
ten repos that we choose. So the environment is not worked out by an agent for every task. It is
written down once per repo, as a recipe, and applied to every task of that repo.

A recipe says five things: the base image; how to install the repo's dependencies; what to run
again after a task's commit is checked out; which files count as tests; and how to run a given set
of test files and read the result.

```toml
# eval/envs/pandas.toml: a sketch of the shape, not a tested recipe
repo = "pandas-dev/pandas"
base_image = "python:3.12"
setup = ["pip install -r requirements-dev.txt"]           # once, when the base image is built
refresh = ["pip install -e . --no-build-isolation"]       # after a task's commit is checked out
test_paths = ["pandas/tests/**"]                          # which files count as tests
test = "pytest -q {test_files}"                           # the task's own tests
parser = "pytest"
timeout_min = 10
```

**Who writes it.** One of us with a coding agent, on our subscriptions. Expect an hour or two for
a plain Python repo and up to a day for one with a heavy build. This is the part that is prepared
by hand. Everything after it is automatic.

**The admission check.** Before a repo is admitted, its recipe is run on 10 sampled candidates.
The repo is in if at least 6 validate, each in under 10 minutes. If fewer do, fix the recipe or
move to the next repo of the list (§8.3).

**Images for our own machines.** We build the images, so we choose their architecture. On our Macs
they are built for ARM and run at full speed. SWE-bench-Live's images are x86 only and run several
times slower there (§4.4).

**Why not an agent that builds every environment.** Such tools exist, and they are what makes the
large public sets possible. All *(reported)*.

| Pipeline | What it automates | Languages | Yield and cost | Can it take any repo? |
|---|---|---|---|---|
| **SWE-bench-Live with RepoLaunch** (Microsoft; MIT; updated Nov 2026) | pairing issues and pull requests after a date, a quality filter, an agent that builds the Docker image and finds the test command and log parser, validation over 3 runs | C, C++, C#, Python, Java, JavaScript and TypeScript, Go, Rust | the build succeeds on 72 to 92% of filtered candidates; 8 to 20% of candidate pairs become tasks; about $1.70 per task with a frontier model, less when one build is reused per repo | **yes:** it takes a list of repos and commits |
| SWE-rebench V2 (MIT; updated Nov 2026) | mining, a setup agent, validation, difficulty and category labels | 20 | 32,079 tasks from 583,809 pull requests (5.5%) | **not as published.** The repo holds prompts, base images, log parsers and the grader, not the collector. Its newest task is from October 2025 |
| SWE-Factory (AGPL, non-commercial) | a multi-agent builder of Dockerfiles and test scripts | Python, Java, JavaScript, TypeScript | 42 to 50% of issues; $0.04 to $0.06 and about 25 minutes each | yes |
| SWE-smith (MIT) | one image per repo, then **synthetic** bugs with generated issue texts | Python, plus profiles for C, C++, Go, Java, JavaScript, Rust, TypeScript | half of candidate bugs are valid; $1,360 for 50,000 tasks | yes, but the tasks are made up |
| SWE-bench's own scripts (MIT) | scraping and validation; the install steps are written by hand | Python | 2.5% of pull requests | not the environments |

They solve a problem this phase does not have. They also bring costs: RepoLaunch needs a model API
key of its own (through LiteLLM) and a Tavily search key *(checked Nov 22)*, and an independent
benchmark measured it at 8.9% of tasks validated, with older models and an earlier version.
RepoLaunch stays the route for later, when the generator should take any GitHub link without a
recipe. One caution for that day: the two research passes behind this plan read SWE-rebench V2's
repository differently. One took the paper's word that its collection code is released. The other
opened the repository and did not find it.

**What we add, which none of these has.** Steps 5 and 6: prompts at three levels of vagueness that
are checked to be still solvable, and labels for how hard a task is to *search* for. That layer
works on any task that has a container and hidden tests, whoever made it.

### 8.3 Which repos, and in what order

**What we already hold.** Counted on Nov 22 from the task files in `eval/tasks/`. "With tests"
means the pull request also changed test files, which a hidden-test task needs. Difficulty follows
§10.

| Repo | Language | Tasks collected | With tests | Easy / medium / hard, among those with tests |
|---|---|---|---|---|
| home-assistant/core | Python | 756 | 618 (81%) | 289 / 247 / 82 |
| microsoft/vscode | TypeScript | 771 | 644 (83%) | 175 / 252 / 217 |
| pandas-dev/pandas | Python | 352 | 298 (84%) | 139 / 121 / 38 |
| vllm-project/vllm | Python | 381 | 284 (74%) | 97 / 129 / 58 |
| apache/airflow | Python | 229 | 205 (89%) | 64 / 93 / 48 |
| microsoft/playwright | TypeScript | 209 | 182 (87%) | 85 / 64 / 33 |
| ray-project/ray | Python | 145 | 114 (78%) | 32 / 47 / 35 |
| huggingface/transformers | Python | 132 | 85 (64%) | 43 / 27 / 15 |
| python/cpython | Python and C | 89 | 63 (70%) | 33 / 26 / 4 |
| ggml-org/llama.cpp | C++ | 165 | 43 (26%) | 13 / 18 / 12 |
| duckdb/duckdb | C++ | 209 | 9 by the classifier; about 200 in fact (see below) | not counted yet |
| godotengine/godot | C++ | 350 | 7 (2%) | 5 / 1 / 1 |

Three things to read from it:
- **Python and TypeScript have far more candidates than we need.** The limit there is the
  environment, not the supply.
- **The count for duckdb is wrong, and the reason matters for every repo.** The classifier knows a
  test file by its folder and its extension. DuckDB writes its tests as `.test` files, which the
  classifier does not know, so it counted 9 tasks with tests. We read 25 of the other 200 pull
  requests on GitHub on Nov 22, and 24 of them changed a `.test` file. So duckdb has about 200
  tasks with tests, and it is our C++ repo. **What counts as a test is set per repo, in its
  recipe** (§8.2). Rust has the same trap in another form (below).
- **Godot cannot carry end-to-end tasks.** 7 of its tasks come with tests, and of 10 further pull
  requests we read, 1 changed a test. It stays in the retrieval eval. llama.cpp has 43, and none
  of 10 further ones we read had a test: it is the reserve for C++.
- **Large changes are missing.** The collection kept changes of at most 5 code files and 200
  lines, so "hard" here means 3 to 5 files or 100 to 200 lines. Almost no task adds a new file (0
  to 5% per repo), so tasks of the OCR kind are rare in this set. A second collection pass with a
  higher limit is how to get them.

**The order.** Languages come first. The main results have to cover several languages, so the
first five repos are five languages: Python, TypeScript, Rust, Go and C++. After that, four
things decide: how many tasks come with tests (measured, above); how hard the environment is to
build (expected only: the admission check of §8.2 decides); how large the repo is, because search
should matter most in large ones; and the spread of languages.

| # | Repo | Language | Why here | The environment, as expected |
|---|---|---|---|---|
| 1 | pandas-dev/pandas | Python | 298 tasks with tests; a medium-size repo that today's codemem indexes quickly; a well-known build | low to medium: one compiled extension |
| 2 | microsoft/playwright | TypeScript | 182 with tests; medium size; a second language from the first day | medium: its tests need browsers, and official images with browsers exist |
| 3 | astral-sh/ruff | Rust | a third language, and part of the main results. Not collected yet: 395 merged pull requests with a linked issue *(probed Nov 22, below)* | low, if `cargo test` is as quick as expected |
| 4 | kubernetes/kubernetes | Go | a fourth language, in a very large repo, and part of the main results. Not collected yet: 246 with a linked issue *(probed)* | medium: tests run per package; a large build cache |
| 5 | duckdb/duckdb | C++ | a fifth language, and part of the main results. About 200 tasks with tests, once its `.test` files count as tests | medium: a CMake build of a large code base, done once for the image. One test file runs in seconds |
| 6 | home-assistant/core | Python | the largest pool (618) in a very large, pure-Python repo, where search should matter most | medium: a very long dependency list, installed once |
| 7 | microsoft/vscode | TypeScript | 644 with tests and the largest pool of hard tasks (217); very large | high: a long build, and tests that need a display |
| 8 | apache/airflow | Python | 205 with tests, and the highest share of pull requests with tests (89%) | medium to high: many optional parts, and a database |
| 9 | vllm-project/vllm | Python | 284 with tests on paper | high: a GPU build, and many tests load models. Only tests that run on a CPU would count |
| bonus | a Java repo | Java | a sixth language, as a bonus. apache/kafka **cannot be collected as it is:** 0 of its merged pull requests link a GitHub issue *(probed)*. Another Java repo would take its place (below) | medium to high: a Gradle build |

- **1 and 2** are the two repos of the first end-to-end test (§2.2).
- **3, 4 and 5** add Rust, Go and C++, so that the main results cover five languages. llama.cpp
  is the reserve for C++. For Rust,
  ruff is chosen over the Rust compiler itself, whose own build takes far longer than a task
  should.
- **6 and 7** are the large repos, where the hypothesis says an index helps most.
- **8 and 9** add breadth.
- **Java is a bonus:** a sixth language, if time is left and a Java repo can be collected.

**What GitHub says about the repos that are not collected yet** *(probed Nov 22)*. The window is
the one of the collected sets, July 1 to October 22, 2026. "Linked" is the number of merged pull
requests with a linked issue. It is an upper limit on tasks: in the collected sets, 58 to 87% of
the pull requests with exactly one linked issue became tasks, before the filter for tests.

| Repo | Language | Code in the language | Merged pull requests | Linked |
|---|---|---|---|---|
| astral-sh/ruff | Rust | 30 MB | 1,806 | 395 |
| kubernetes/kubernetes | Go | 109 MB | 1,421 | 246 |
| apache/kafka | Java | 75 MB | 789 | **0** |

- **kafka does not work with our collector.** It keeps its issues in Jira, and GitHub issues are
  switched off for the repo, so no pull request links one. `cmeval collect` starts from that
  link. apache/flink is the same. Java repos that do link issues on GitHub: keycloak/keycloak
  (54 MB, 1,007 linked), quarkusio/quarkus (74 MB, 414), trinodb/trino (92 MB, 140), and
  elastic/elasticsearch (322 MB, 1,562), which is very large. Their environments are not judged
  yet.
- **golang/go and cockroachdb/cockroach** cannot be used either: they do not merge through GitHub
  pull requests (0 and 17 merged in the window).
- **Reserves, if a repo fails its admission check.** Rust: apache/datafusion (40 MB, 607 linked)
  and zed-industries/zed (68 MB, 485). Go: pingcap/tidb (64 MB, 280) and go-gitea/gitea (16 MB,
  238).
- **Rust has a trap for the test filter.** Rust unit tests live in the same file as the code, in
  `#[cfg(test)]` modules. Today a changed file is code or test by its path, so a Rust pull
  request that adds only such tests looks as if it had none. The file-level labeler for Rust
  needs a rule for it.

**The repos that are not collected yet need one small addition.** `cmeval collect` labels Python,
C++ and TypeScript. End-to-end tasks are graded by tests, so they need gold files only, and those
come straight from the change. A file-level labeler for other languages is small. Function-level
labels for them can wait (§12.2).

**How many tasks per repo.** Prepare 30 to 40 validated tasks: about 10 easy, 15 medium and 10
hard, drawn with a fixed seed from the candidates with tests, as `cmeval subset` already draws.
The full runs then use a sample of these (§3.3). So a repo is worth preparing even when there is
no time to run all of it.

**If time runs short, run fewer tasks per repo before dropping a language.** Each repo is complete
on its own. Two repos in two languages are already a result. Five give five languages. Seven add
the large repos.

**What every repo must meet,** whatever its place in the list:

| Criterion | Threshold |
|---|---|
| size | at least 1,000 source files in the main language |
| activity after the cutoff | at least 50 merged pull requests with a linked issue and tests |
| build | a clean image builds in under 20 minutes |
| tests | the tests of one pull request run in under 5 minutes, with stable results |

### 8.4 Ready-made tasks: SWE-bench-Live, the add-on

SWE-bench-Live ships a container and hidden tests for every task *(checked on its pages,
Nov 22)*:

| Set | Tasks | Languages |
|---|---|---|
| the Python set | about 1,890 in its full split, with frozen splits of 300 and 500 | Python |
| the multi-language set | 1,077, from 431 repos | C 111, C++ 142, C# 136, Go 138, Java 160, JavaScript 108, Rust 171, TypeScript 111 |

Each task names an x86 Docker image, its test commands and a log parser, and the project's own
script grades a patch. So it needs an importer and nothing else.

**What it is for here:**
1. **A control while the pipeline is built.** Its environments are known to work. A failed run
   there is our pipeline's fault. A failure only on our own tasks is the generator's (§2.2).
2. **Languages our own repos have not reached,** if the list of §8.3 is not finished.
3. **An outside check for the paper:** the same comparison on tasks we did not make.

**Why it is not the main source.**
- **Its tasks are older than the models.** The newest Python task we saw was created in August
  2025, and the multi-language page shows no dates. The task tables do *(downloaded Nov 22)*:
  the `verified` Python split runs from July 2024 to April 2025; the TypeScript and Go splits
  end in April 2026; the Rust split ends in July 2026, and 68 of its 171 tasks were created
  after June 2026. So only some Rust tasks are newer. A model that remembers a fix has less to
  search for, which can hide a saving. So these tasks are reported apart and never mixed into the
  headline.
- **Its images are x86 only,** and slow on our Macs (§4.4).
- **Public sets have flaws** (§16). Tasks are spot-checked by hand before they enter a test
  split.

SWE-bench Pro's second version is another ready-made set, already in the Harbor format
*(reported)*.

**Synthetic bugs have one use here:** as a pool of easy tasks for the small models, if real fresh
pull requests give too few that pass the small-model filter.

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
| about 14B | **Qwen3-14B** | the newer Qwen generations have no size between 9B and 27B. In a published 30-turn agent loop it finished 99.4% of episodes, where Gemma 4 12B finished 44.5%. Its window is 32,768 tokens, the smallest of the three, so it runs in mini-SWE-agent only (§4.6) | hosted, at about $0.12 per million input tokens; locally 9.2 GB at 4 bits |
| about 27B: the top of the curve in this harness | **Qwen3.8-27B** (Apache-2.0) | 86% on SWE-bench Verified with mini-SWE-agent; served by Nebius. Qwen3.6-27B is the runner-up and the only one with an independent score on fresh tasks (31%) | hosted only: Nebius, $0.45 in and $3.00 out per million tokens. At 18 GB it does not fit a 24 GB Mac next to anything else |
| for context | Claude Haiku 5.5 and Claude Sonnet 5.5 | the cheap and the frontier end, from the main runs. A different harness, so they are shown beside the open models and not compared with them | Claude Code, under our subscriptions |

A 4B model of the same family (Qwen3.5-4B) is a cheap optional fourth point: the largest published
gains from search tools are at 4B.

**No independent score on fresh tasks exists for any model under 20B.** The scores above for the
9B class are on SWE-bench Verified, which models have partly memorized, and are vendor-reported.
So the first result of this study is the plain baseline: what a 9B and a 14B model complete on
tasks newer than they are.

**When.** In the same days as the main comparison, with at least one model before the
presentation. This study reuses the tasks, the pipeline and the design, and changes only the
agent's model and its harness. Its runs go to their own endpoint, so they do not wait for the
Claude seats.

**In what order.** Which models are run is settled by Andrew with Andre. This is the starting
proposal.
1. One model first: Qwen3.5-9B. It has the long context window, and it fits a 24 GB Mac if no
   provider is at hand.
2. Its localization runs first (§12.1). They need no container and finish in hours.
3. Then its end-to-end runs on the easy and medium tasks of the sample, with the hard probe.
4. Then Qwen3.8-27B, the larger model the gap is measured against.
5. Then Qwen3-14B.

With one model only, the result is the plain difference with and without codemem. The gap measure
below needs the 27B model as well.

**Other model families.** The model is a setting (§4.6), so a model from another family, for
example a Llama model, is one more row. Qwen comes first because it has current models at each of
these sizes. Whether another family has was not checked.

**Which tasks.** Easy and medium tasks, as in the run matrix (§3.3), and about ten hard ones as a
probe. Small models complete a narrow kind of task: on SWE-bench Verified, the tasks that weak
models solve are 95 to 100% single-file, with a median real change of 2 to 4 lines, and a 32B
model from 2024 solved 16.5% of the tasks humans rate under 15 minutes and none of those over an
hour *(reported)*. The small-model set of §10 marks the tasks with the best chance. Each is run at
L0 first. The vague versions follow when the main cells are done.

**Where they run.** Through an API or self-hosted. This study is the one part of the plan where
the agent's own model is not on a subscription.
- **A hosted endpoint,** for the batches: the same open weights, at cents per run, many runs side
  by side. What we found on Nov 22 *(reported)*, in dollars per million tokens in and out:
  DeepInfra lists all three models (the 9B at 0.10 and 0.15, the 14B at 0.12 and 0.24, the 27B at
  0.15 and 1.875 on a promotion). Together lists the 9B (0.17 and 0.25). Nebius serves the 27B
  (0.45 and 3.00) and, as far as we could see, neither of the smaller two. Most of these offer
  function calling for the 9B and the 27B; for the 14B only DeepInfra does.
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

**Add languages: Go and Rust now, Java as a bonus.** codemem indexes nine languages. The eval grades
three. Go and Rust are part of the main results, on kubernetes and ruff, the same two repos the
end-to-end tasks use (§8.3).

| Language | Graded today | To add | Candidate repos (to check with `cmeval repo-stats`) |
|---|---|---|---|
| Python | yes: pandas, transformers, home-assistant, airflow | — | — |
| C++ | yes: Godot, duckdb, llama.cpp | — | — |
| TypeScript | yes: vscode, playwright | — | — |
| Go | no | a labeler; kubernetes first | kubernetes; then tidb, gitea |
| Java | no | a bonus: a labeler, and a repo that links its issues on GitHub | keycloak, quarkus, trino. kafka cannot be collected (§8.3) |
| Rust | no | a labeler; ruff first | ruff; then datafusion, zed |

"A labeler" is the part of `cmeval` that turns a fix into gold line ranges with tree-sitter. It is
written separately from codemem on purpose, so that a codemem bug cannot grade itself. Each new
language needs one, as C++ and TypeScript did.

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

**Keep it short in the paper:** one table, five languages once Go and Rust are in, two query kinds.

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

**What fits before the paper** is near the first row: 80 to 120 tasks, from four to six repos at
20 each. Under the same
assumptions they can show a saving of 13 to 15% in tokens or time, and a change in completion of
12 to 15 points, not less. So a frontier model's completion is likely to come out as "no
detectable difference", and the claim for frontier models rests on tokens and time. The exact
number of test tasks follows from how many runs our seats allow, which the first batch measures.

---

## 14. Work packages, and how they are run

The tasks and the pipeline come first, side by side. The full runs and the model gap follow in the
same days. Most of this work can go on unattended, at night, if every job has a clear end and a
clear answer to "what if it fails". §14.2 to §14.5 are written for that.

| # | Work | Deliverable | Done when |
|---|---|---|---|
| A1 | **The pipeline skeleton,** end to end on the first two repos (§2.2): plan, run in a container, record, grade, score. Claude Code only, setups `grep` and `tool`, a cheap model | `cmeval e2e plan / run / grade / score` | the checklist of §2.2 passes, and one command produces a table of completion, tokens and time for the two repos' tasks × 2 setups × 3 repetitions |
| A2 | **Measurement** (§5): the recording proxy, the cross-check, the six token numbers, the four clocks, the file watcher | the run record of §6 | on the runs of A1, proxy and agent summary agree within 1% on every run, and the proxy adds no measurable delay to the first byte |
| A3 | **Selection and plans** (§3): the flags, plan files, the run matrix, the iteration plan for tracks B and C | `plans/main.toml`, `plans/iterate.toml` | a plan can be previewed with `--dry-run`, stopped, and resumed without rerunning anything |
| A4 | **Robustness** (§7): integrity checks, failure classes, the canary, the spending cap, the dashboard view | `cmeval e2e check`; a canary plan | a deliberately broken setup (MCP server missing, wrong context size) is detected and its runs discarded |
| A5 | **Reports and statistics** (§13) | `cmeval e2e report` | a report can be rebuilt byte for byte from the run records |
| A6 | **The other setups and the open harnesses:** `upfront`, `placebo`, `tool-strong`; mini-SWE-agent with codemem as a command; Qwen Code with codemem over MCP; the harness trial of §4.6; the localization tier | every setup of §4.1; `--harness mini-swe-agent`, `--harness qwen-code`; `--tier locate` | the harness trial is done and its outcome written down; the pilot tasks run in every setup and every harness; the small-model floor is measured (30 easy tasks, 9B and 14B, `grep` only) |
| A7 | **Labels** (§10) | every label in the task file | a hand check of 50 tasks agrees with the difficulty and kind labels at least 85% of the time |
| A8 | **Vague prompts** (§9): the rewriter and its three checks | L1 and L2 for every task, and for the retrieval eval's dev tasks | check 2 passes on at least 80% of rewrites; the human agreement is reported |
| A9 | **Our own tasks** (§8): the build and validate steps of the generator; one recipe per repo, in the order of §8.3; `collect` for ruff and kubernetes, with a file-level labeler and the Rust rule for tests | `cmeval generate <repo>`; validated fresh tasks | pandas and playwright each have 30 or more validated tasks of mixed difficulty by Nov 25, and ruff, kubernetes and duckdb by Nov 27. Every repo passes the admission check of §8.2 |
| A10 | **Retrieval eval additions** (§12.2): labelers for Go and Rust, on kubernetes and ruff; the vague column; the two baselines. Java is a bonus | the retrieval table in five languages | labels hand-checked on 15 tasks per language, as for C++ |
| A11 | **The model gap** (§11): one open model first, the 9B; then the 27B; then the 14B | for each model, the difference with and without codemem, and how failed runs ended; the gap-closed table once the 27B has run | the 9B model on the easy and medium tasks of the sample, 3 repetitions, with the hard probe, before Nov 30. The other models as time allows. A local repeat of a subset on a Mac |
| A12 | **The main batch** (§3.3): baseline and final on the sample, with today's codemem on the medium tasks | the paper's main tables and figure | every primary measure reported with its interval |
| A13 | **Release:** tasks, images, the task-layer tool, a datasheet | a public dataset and repo | a stranger can add vague prompts and labels to a new set of tasks by following the README |

Nothing here is sized in working days. The deadlines are in §14.1, and the lanes and the nights
below are how the work fits into them.

### 14.1 When

The dates are in [overview.md](overview.md) §8.

| By | Packages | What it gives the team |
|---|---|---|
| **Nov 27, 16:30 Pacific** | A1, A2, A3 and the integrity checks of A4; A9 for pandas and playwright, then ruff, kubernetes and duckdb; from A6, mini-SWE-agent and the localization tier; the computed labels of A7; the sample and the analysis plan | the pipeline tested end to end on two repos with today's codemem; validated tasks for every repo that is ready; the open harness working with one model, which is expected on Sat Nov 28; the sample of tasks and the measures fixed before the full runs. Tracks B and C can run the pipeline themselves |
| **Nov 27, 17:00 Pacific, to Nov 30, first:** the runs for the presentation | A12, with a first A5; A11 with the 9B model | the runs of [runs.md](runs.md), in its order, with the check run first; the model gap for at least one open model, once the open harness and the open models are ready. The freeze is aimed at Nov 30, 23:59. The hard limit is the presentation of Dec 1 at 14:00 |
| **Nov 27–30, beside the runs** | the rest of A6 and A11; A9 for further repos; A10; A7 and A8 completed; the rest of A4 and A5; the part of A13 that goes with a paper | everything else in the track, as far as the lanes allow without slowing the runs: the other open models, more repos, the retrieval table with Go and Rust, its vague column and its two baselines, a vague version of every prompt. The aim is to leave nothing open after December 1 |
| **Dec 7:** the paper and final report | the writing, and whatever is still open | the paper, with the code, the task list and the run records |
| **No date** | Java, in A9 and A10, as a bonus. As future work: a generator that takes any repo without a recipe, and the rest of A13 | a sixth language; tasks from any GitHub link; a dataset release with its datasheet |

### 14.2 Five lanes that do not wait for each other

Each lane uses a different scarce thing. So all five can be busy at the same time, and a lane
that is stuck does not stop the others.

| Lane | What is scarce | Its jobs |
|---|---|---|
| 1. Claude seats | subscription usage | the first end-to-end test; the main batch; the vague subset; the mechanism setups |
| 2. Docker | the Mac's cores, memory and disk | generating tasks: build the image, validate the tests. Grading finished runs |
| 3. The local GPU | the Mac's GPU | building codemem indexes for the tasks about to run |
| 4. The open-model endpoint | a few dollars | the model gap: the harness trial, localization, then end to end |
| 5. Nothing scarce | — | `collect`, the labelers, labels, the sample, plan files, reports, the analysis plan |

**Two machines carry lanes 1 to 3:** Andrew's M5 Mac and his PC. Spread the lanes over them, so
that several jobs run at once. Three rules:
- **A repo's tasks are validated and run on one machine.** An image built on the Mac and one built
  on the PC are different images.
- **Both setups of a task run on the same machine,** turn about. Then the machine cannot look like
  a difference between setups.
- **Watch each machine's memory.** Start with three agent runs at once in all, one per seat, and
  on each machine two build or validate containers and one indexing job. Lower the containers
  first if a machine starts to swap.

How an index that was built on the Mac is used on the PC is for the first runs to settle. Until
then, build an index on the machine that runs the task.

### 14.3 Night by night

What each night should leave behind. A lane moves on to its next row as soon as it finishes one.
It does not wait for the date.

| Night of | Lane 1: seats | Lane 2: Docker | Lane 3: GPU | Lane 4: endpoint | Lane 5 |
|---|---|---|---|---|---|
| **Fri Nov 27** | 16:30 Pacific: codemem is frozen. 17:00: **the check run** ([runs.md](runs.md) §6), and its report. When it has passed, **repetition 1 of Haiku and of Sonnet** starts, repo by repo in the order of [runs.md](runs.md) §7, and runs unattended overnight | grading as runs finish. The hard tier of the repos that are run | index the tasks that are about to run, with the frozen codemem | — | the sample of each repo committed before its first run |
| **Sat Nov 28:** reserved for running | repetition 1 goes on; then Opus; then repetitions 2 and 3 of Haiku start | grading; the hard tier, and the medium tier where a repo is short | index the hard tasks as they are ready | the open harness and the open models are expected to be ready: end to end with the 9B model, repetition 1 | a first report, after repetition 1 of the first two repos |
| **Sun Nov 29:** reserved for running | repetitions 2 and 3 of Haiku; then kubernetes, once | grading | — | the 9B model: repetitions 2 and 3, and the probe; then the 27B model | the tables, per language and overall |
| **Mon Nov 30** | only what is missing; repetitions 2 and 3 of Sonnet if time is left. No new run after 18:00 | grading | — | the 14B model, if the 27B is done; only what is missing | the final tables, by 23:59 |

**Nov 30, 23:59 is the freeze we aim for.** The hard limit is Dec 1, before the presentation at
14:00, and that morning is for preparing the presentation, not for runs.

### 14.4 Decisions already made

An agent that runs at night must not have to ask. These are the answers.

| Question | Answer |
|---|---|
| Which Claude model | `claude-sonnet-5-5` for everything that is reported. `claude-haiku-5-5` for bring-up and for the iteration plan |
| How many repetitions | three, scheduled by repetition (§3.3) |
| The limits of a run | 150 turns or 50 minutes, the same in every setup (§4.7) |
| Which tasks | a sample of 20 per repo: 6 easy, 8 medium, 6 hard, with seed `main-1`. If usage runs short: 15, then 12. Never fewer languages before fewer tasks |
| Which prompt | the issue as written (L0) in the main batch. The short request (L2) only in the vague subset |
| Which repos, in what order | §8.3 |
| Which setups in the main batch | `grep`, and `tool` with `codemem-final`. `tool` with `codemem-today` on the medium tasks |
| Which embedding model | today's local model, until Andre announces another one in the work log |
| Which open model | Qwen3.5-9B first, then Qwen3.8-27B, then Qwen3-14B, in mini-SWE-agent. The action mode is the one the harness trial chose (§4.6). Andrew settles the choice of models with Andre, in the log; this order is the starting point |
| Where open models run | a hosted endpoint if its key is in the environment. If it is not, the 9B on the Mac, while lane 3 is idle |
| Where runs happen | on Andrew's M5 Mac and on his PC. A repo stays on one machine. The SWE-bench-Live control tasks go to the PC, which is x86 |
| A model for helper jobs: a judge, the rewriter, reading labels | a seat, when one is idle. The team also holds $200 of Claude API credit as a reserve for jobs like these. Ask Andre in the log before spending from it |
| How work reaches `main` | on a branch, through a pull request. Never a push to `main`. The `worklog` branch is pushed freely |

### 14.5 Rules for running unattended

**Keep going when:**
- **a task fails.** Record it and move on. A failed task is a result;
- **a repo fails its admission check** (§8.2). Write why in the log, and take the next repo of
  §8.3;
- **a seat reaches its usage limit.** That seat pauses until its reset. The run that was cut off
  is thrown away and queued again. The other lanes carry on;
- **a question is answered in §14.4.** Use that answer, and say in the log that you did.

**Stop the lane, not the night, when:**
- a credential is missing, or a login has expired;
- the same job has failed three times with the same error;
- less than 20 GB of disk is free;
- going on would need a change to something frozen: the sample, a prompt, a limit, the analysis
  plan, a frozen configuration.

Then write a log entry that says what is blocked and what you tried, and work on another lane.

**When track A needs help,** whether more machines, more hands or a decision: say so in the work
log, addressed to Andre, under "Blocked on, or needed from others". Say it early. He moves people
and work to where the plan is falling behind.

**Stop every agent run when** the two token counts disagree on more than 1 run in 20 of a batch
(§5.3). The measurement is broken, and more runs would only spend usage.

**Never:**
- change the sample, the prompts, the limits or the analysis plan after the first run of the main
  batch;
- change a frozen configuration, or run a batch on one that is not frozen;
- score a run that failed an integrity check, or delete a run's records;
- give one setup something the other does not get: a longer limit, another model, a retry;
- report something as done without the output of its check.

**Before a long batch starts:** save the dry run of the plan (how many runs, in what order). Run
the canary. Record the versions of the agent, the model and codemem.

**At least every four hours, and at the end of every session,** write a log entry
([CONTRIBUTING.md](../../CONTRIBUTING.md) §4) and bring the status file up to date. In the entry,
give for each lane:
- what ran, in numbers: runs finished, thrown away and still queued; tasks validated per repo;
- what failed, by kind;
- what is running now;
- what needs a person.

That entry is what the three of us read in the morning.

---

## 15. What track A needs from, and gives to, the others

| With | A needs | A gives |
|---|---|---|
| **Track B** | `codemem-today` frozen now, the final configuration on Nov 27 at 16:30 Pacific; a timing log from codemem for each search (§5.5); no change to tool names or card layout without notice; a note in the work log each time a new piece of retrieval has passed its gate on the retrieval eval and can run | the iteration plan (§3.4); vague rewrites of the dev tasks, a first subset by Nov 24 if it is to count for the freeze; end-to-end comparisons of card formats; the adoption numbers track B needs |
| **Track C** | a note in the work log as soon as the compact store works on one repo; before the first runs that embed through an API, a codemem install that works in a container without PyTorch; the compact configuration frozen; the embedding configuration for each batch, a local model first and Qwen through Nebius later; memory, disk and build-time numbers per repo | the same iteration plan and vague rewrites |

**The eval stays independent of codemem.** `cmeval` never imports codemem except in its one
adapter file, and the labelers stay separate implementations. The end-to-end runner treats codemem
as a black box: an MCP server, a command, and an index folder.

---

## 16. Risks and open questions

| Risk or question | Why it matters | What we do |
|---|---|---|
| Agents don't call codemem | no call, no effect; one vendor saw 1 call in 143 sessions *(reported)* | **track B owns this** ([track B](track-b-retrieval.md) §5): tools loaded up front, the text that tells the agent when to call. Track A measures it in every run and reports it to track B; `upfront` and `tool-strong` are separate setups |
| Baseline and final are run days apart | the API is faster on some days, which would look like a saving in time | wall time is compared only inside one batch, turn about (§3.3; §4.5, rule 8) |
| The token numbers are wrong and nobody notices | every claim rests on them | two independent counts that must agree (§5.3); the canary |
| Building environments is slow and fragile | it is the longest and least certain job in the track | one recipe per repo, written once; a check on 10 tasks before a repo is admitted; repos in a fixed order, each complete on its own; SWE-bench-Live as the control and the fallback (§8) |
| A repo's tests are not recognised | the classifier goes by folder and extension. It counted 9 duckdb tasks with tests where there are about 200, and Rust keeps unit tests inside code files | what counts as a test is set in each repo's recipe (§8.2). Before a repo's count is trusted, 10 of its pull requests are read by hand |
| Public benchmarks we borrow are flawed | OpenAI estimated that about 30% of SWE-bench Pro's public tasks were broken and stopped recommending it; it had already dropped SWE-bench Verified *(reported)* | tasks are spot-checked by hand before they enter the test split, and a task whose gold patch fails its own tests in our container is dropped |
| Vague prompts become unsolvable | failures would then say nothing about search | check 2 in §9 |
| Usage limits slow everything down | three seats, each with a session and a weekly limit, are all the Claude time we have, and we code on the same seats | the run matrix spends large tasks only on the baseline and the final configuration; the baseline is reused; `--dry-run` sizes a plan first; the first batch tells us how many runs fit in a window |
| The ready-made tasks are older than the models | a model may remember a fix | the headline rests on our own tasks, which are newer; the ready-made ones are reported apart; the closed-book probe below tags tasks a model answers from memory |
| The harness changes under us | Claude Code updates often | pin the version; record it in every run; the canary after any upgrade |
| Small models complete almost nothing | given the gold files, small models repaired 2 tasks of 100 in one study *(reported)*; a base rate that low cannot show a change | the floor is measured first (A6); localization is the primary measure for small models; easy and medium tasks only, plus a small probe |
| The answer leaks | a fresh fix is public on GitHub | no network, no web tools, history cut at the task's commit; a closed-book probe that asks the model for the gold files from the prompt alone, and tags tasks it answers |
| A small model fails the harness, not the task | a broken tool call or a full context window looks like a failed task | the harness trial (§4.6); how every run ended is recorded; the server's parser and context settings are checked before each batch |
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

**Open harnesses and frameworks for open models** (§4.6)
- mini-SWE-agent: models, https://mini-swe-agent.com/latest/models/local_models/ · its SWE-bench
  runner, https://mini-swe-agent.com/latest/usage/swebench/
- Qwen Code, https://github.com/QwenLM/qwen-code and
  https://qwenlm.github.io/qwen-code-docs/en/users/configuration/model-providers/ · OpenCode,
  https://opencode.ai/docs · Goose, https://github.com/aaif-goose/goose · OpenHands,
  https://docs.openhands.dev
- Codex CLI and the Responses API, https://github.com/openai/codex/discussions/7782
- Claude Code with other models: Anthropic, https://code.claude.com/docs/en/llm-gateway.md ·
  Ollama, https://docs.ollama.com/integrations/claude-code · the 259-tool report,
  https://github.com/anthropics/claude-code/issues/25857
- Harbor: agents, https://docs.harborframework.com/agents/pre-integrated-agents.md · job files,
  https://docs.harborframework.com/jobs/configs.md
- Inspect AI: MCP tools, https://inspect.aisi.org.uk/tools-mcp.html · providers,
  https://inspect.aisi.org.uk/providers.html · its agents, https://meridianlabs-ai.github.io/inspect_swe/
- Small models and tool calls: Qwen3.5-9B in seven harnesses (the MiMo-V2.6 report),
  https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Pro-RL/blob/main/MiMo_V2_6_technical_report.pdf ·
  Qwen3.8-27B in three harnesses, https://arxiv.org/abs/2610.04433 · Qwen3.5 at 0.8B to 4B,
  https://arxiv.org/abs/2611.21407 · the function-calling board,
  https://gorilla.cs.berkeley.edu/leaderboard.html
- Serving: Qwen's function-calling notes,
  https://qwen.readthedocs.io/en/latest/framework/function_call.html · vLLM's recipe,
  https://recipes.vllm.ai/Qwen/Qwen3.8-27B · Ollama's context length,
  https://docs.ollama.com/context-length
- Hosted prices: https://deepinfra.com/Qwen/Qwen3.5-9B · https://openrouter.ai/api/v1/models ·
  https://docs.together.ai/docs/serverless/models.md

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
