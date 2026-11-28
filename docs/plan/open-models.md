# Open models: the agent loop, the runs, and how to start them on a rented GPU

**Status:** a plan, written Nov 28, 2026. Nothing of it is built, except what §2 lists as checked.
It is written for the session that builds it and for Andre, who rents the machine and starts the
runs. It refines [track-a-evals.md](track-a-evals.md) §4.2, §4.6 and §11, and replaces their
choice of harness. Where the paper uses these runs is in [paper.md](paper.md) §4.7 (on branch
`andre/paper-plan` until it is merged).

**Do not start building before Andre says so.**

---

## 1. What this is for, and what "done" means

**The question.** The runs so far show no gain from the index for a Claude model on a public repo,
and the reason looks like memory: the model already knows where things are. A smaller open model
knows less and searches worse. Does the index help it more?

**The problem.** An open model cannot run in Claude Code under our subscriptions. It needs its own
agent loop: something that sends the request to the model, runs the commands the model asks for,
lets it edit files, and stops when it is done.

**Three steps, in Andre's words:**

1. Build the loop, with the tools an agent needs, so that an open model can search with grep and
   with codemem.
2. On the rented GPU: build the indexes, then run the tasks in the order of §7.
3. Analyse what comes out.

**Done means this works on a fresh rented machine:**

```bash
git clone https://github.com/wyy1048576/codemem && cd codemem
scripts/open/setup.sh                    # checks the machine, builds the environments, tests itself
scripts/open/prepare.sh pandas           # task images, indexes, the 20 lines of each task
scripts/open/run.sh qwen-35b pandas      # grep and codemem, in the order of §7
scripts/open/report.sh                   # the tables
```

- **The same tasks, containers, limits and grading as track A's Claude runs.** Only the agent and
  its model differ.
- **The model is a setting:** a base URL, a model name, and the name of the variable that holds a
  key. A hosted API and a server on the rented GPU are the same run with another address.
- **The records have the form of track A's,** so the same scripts count and compare them.

---

## 2. What is decided, and what was checked on Nov 28

**Decided (Andre).**

- **Three models:** one of about 30B first, one of 13 to 14B, one of about 8B (§5).
- **Up to three repos,** in the order of §7. The tasks exist already (the run sample); none is
  generated.
- **The budget is about 30 USD** of GPU or API.
- **Tests with a live model use `NEBIUS_API_KEY` from `.env`** in the repo's folder (§10).

**Checked, through the Nebius API** (`https://api.tokenfactory.nebius.com/v1`).

- **It serves 24 models.** Of use to us: `Qwen/Qwen3.8-27B`, `Qwen/Qwen3-30B-A3B-Instruct-2507`
  and `Qwen/Qwen3-Embedding-8B`. It has no Llama model of 8 to 13B and no Qwen of 14B.
- **Tool calls work for both Qwen models.** Each answered a request with a call of a shell tool, and
  a second turn with the tool's result came back as a final answer. Usage is in every answer.
- **grep needs no tool of its own.** Both models wrote a `grep` command into the shell tool
  unasked. A shell tool gives an open model what the shell gives Claude Code.
- **Embeddings work:** `Qwen/Qwen3-Embedding-8B` with `dimensions: 1024`.
- **The 27B thinks by default, and one request field turns that off.** With
  `"chat_template_kwargs": {"enable_thinking": false}`, or with `"reasoning_effort": "none"`, the
  usage shows 0 reasoning tokens. `"reasoning_effort": "low"` still thinks. The 30B has no
  thinking, and the two detail blocks of its usage are `null`.
- **In a Claude run, codemem's tools are in every request in full.** A recorded `grep` run sends
  20 tool definitions with each request, and a `codemem` run 27: codemem's four, and three tools
  for MCP resources that Claude Code adds by itself. So `cmagent` sends codemem's four in full too.
- **A throwaway loop fixed a planted bug in a toy repo.** It used the standard library only, with
  three tools (Bash, Edit, Write) and a vague request.

  | Model | Turns | Seconds | Input tokens | The test afterwards |
  |---|---|---|---|---|
  | `Qwen/Qwen3.8-27B` | 7 | 7 | 9,676 | passes |
  | `Qwen/Qwen3-30B-A3B-Instruct-2507` | 5 | 15 | 4,247 | passes |

- **The eval's own counting code read that loop's event file unchanged.** The loop wrote its
  events in the form of Claude Code's stream. `parse_stream` and `count_steps` returned the turns,
  the two greps, the three views, the edit and the turn of the first opened fix file. This is
  what §4.5 builds on.
- **`.env` was not in `.gitignore`.** This branch adds it. Locally it is in `.git/info/exclude`.

---

## 3. The harness: the choice

**The choice: our own small loop, `cmagent`, inside the eval package.** One file, the standard
library only, about 500 lines.

**What a survey on Nov 28 found** *(reported; the sources are at the end)*.

| Harness | State | How the model acts | Why it is not our choice |
|---|---|---|---|
| mini-SWE-agent 2.4.6 | MIT; the SWE-bench team; last release Jul 23 | one `bash` tool, or a text mode. It runs on the host and acts in a container through `docker exec`. A run ends on a submit command | no edit tool and no MCP. A reply with no tool call is an error there, and the end of a run in Claude Code. Its trajectory is another format. It is outside code, and two versions of its main dependency were compromised |
| Qwen Code 0.29 | Apache-2.0; several releases a day | native tool calls, MCP, limits on turns and time | it must be installed in every task image; it is made for one family; its token totals are "not guaranteed complete" |
| OpenHands SDK | MIT | native or prompted tool calls, MCP | it wants its own server inside the container |
| Codex CLI | Apache-2.0 | OpenAI's Responses API only | servers of open models speak that API unevenly: tools fail until features are turned off |
| pi | MIT | four tools: read, write, edit and bash | the closest to our shape, but MCP only through an extension. It is outside code that every task image would need, with its own events |
| OpenCode, Goose, Cline, Aider, SWE-agent | | | each has a gap with small open models, or is in maintenance only |
| Claude Code on an open model | possible through vLLM | | Anthropic does not support it; every request carries 36,000 tokens of prompt; a saved login can stay the active credential |
| OpenClaw | | | not a coding harness: an assistant that drives other agents |

Harbor (Apache-2.0) keeps an install script, the headless command and a log parser for 45 agents,
these among them. A cross-check with a published harness would start there.

**Why our own.** The survey's advice is to build on mini-SWE-agent unless Claude Code's exact shape
is needed. Here it is needed.

1. **The two arms should differ in the model, and in as little else as we can manage:** the same
   four tools, the same rule for the end of a run, codemem as the same MCP server.
2. **The events are Claude Code's,** so every count, table and check of the eval works unchanged
   (checked, §2).
3. **It sits inside track A's container script,** with its checks, clocks and limits, and needs
   no glue.
4. **No outside agent code** has to be vetted or pinned.

**What we take from mini-SWE-agent.** Its releases of 2026 list the faults that a new loop meets.
Build each of these in from the start:

- a wall-clock limit that kills the agent's whole process group;
- a cap on answers in a row that cannot be read;
- a call that was billed but could not be read still counts against the budget;
- a tool call that was cut off is told apart from one that is malformed;
- every file is read and written as UTF-8.

**How the weakness is met.** `cmagent` is not a published harness, and a reader can ask whether a
weak loop explains a weak result.

- **Each model must pass a qualification first** (§8): three small tasks that show it can call
  tools, edit a file and stop.
- **A cross-check stays possible:** mini-SWE-agent on a subset, if a reviewer asks. It is outside
  code: nobody downloads it before Andre has looked at it.

---

## 4. The design

### 4.1 Where the loop runs

**In the task's container, started by the same `agent.sh` as Claude Code.** Preparation, the
agent's user, the clocks, the time limit, the clean-up and the patch stay as they are. One line
differs: the command that starts the agent.

- **`eval/src/cmeval/cmagent.py`:** one file, standard library only, with no import of `cmeval`.
  The runner copies it to the run's folder, as it does with `codemem_gate.py`.
- **Its Python is mounted read-only in every setup:** the Python install that codemem's
  environment links to (`e2e_index.codemem_python_root`). So the containers of `grep` and `codemem`
  differ only in codemem's own mounts.
- **The runner writes `cmagent.json`** into the run's folder: the model, the address of the run's
  proxy, the mode, the limits, the paths of the prompt and of the MCP config.

### 4.2 The loop

1. The messages start with the system prompt and the request. **The request is the text that
   Claude Code gets** (`make_prompt`): the same frame, the same issue text, and in the `codemem`
   setup the same 20 lines on top.
2. Send the messages and the tool definitions to `/v1/chat/completions`. No streaming.
3. If the answer has no tool call, the run is finished, and the answer is the agent's last word.
4. Else run each tool call in order, add the results, and go to 2.

**The system prompt** is one fixed text of about 250 words, with a version name
(`cmagent-prompt-v1`): what the agent is, that the repo is the current folder, that it searches
with shell commands such as `grep`, `find` and `sed -n`, that nobody answers questions, and that it
ends with a plain answer and no tool call. The instructions of each MCP server are added after it,
as Claude Code adds them. The text is the same in both setups but for that addition.

### 4.3 The tools

The names and inputs are those of Claude Code's tools, so that the counts mean the same.

| Tool | Input | What it does |
|---|---|---|
| `Bash` | `command`, optional `timeout` | runs the command with `bash -c` as the agent's user, and returns the output of both streams and the exit code when it is not 0. Every command is its own process: the working folder carries over to the next call, the shell's variables do not. Default limit 120 s, at most 600 s; the process group is killed at the limit |
| `Read` | `file_path`, optional `offset`, `limit` | returns lines with their numbers, 2,000 at most |
| `Edit` | `file_path`, `old_string`, `new_string`, optional `replace_all` | replaces an exact text. It is an error when the text is not there, or is there more than once without `replace_all`. It needs no earlier `Read` of the file |
| `Write` | `file_path`, `content` | writes the whole file |
| `mcp__<server>__<tool>` | the tool's own schema | every tool of every server in the MCP config, with the server's own description. A call goes to the server, and the text of its answer comes back |

- **Long output is cut in the middle,** with a note of how much is left out. The limit is a
  setting of the model (`max_output_chars`): 30,000 for a model with a large window, less for one
  with 32,768 tokens.
- **The MCP client exists already** on this branch: `McpProcess` in `eval/src/cmeval/cm_bridge.py`
  (newline-delimited JSON-RPC over stdio, the handshake, `tools/list`, `tools/call`). Move what is
  needed into `cmagent.py`.
- **With no server in the config, the agent has the four tools above.** That is the `grep` setup.
- **Where this differs from Claude Code, on purpose.** Both points hold for `grep` and `codemem`
  alike.
  - Claude Code sends 20 tool definitions with each request, and three more for MCP resources when
    a server is there (checked, §2). `cmagent` sends its four and the server's own.
  - Claude Code's `Edit` asks for an earlier `Read` of the file. `cmagent`'s does not: a small
    model fails on such a rule, and the failure says nothing about search.

### 4.4 A second way to act: text mode

Some small models, and some servers, break tool calls. For them the same loop has a text mode: no
tool definitions, and the model writes one fenced `bash` block a turn.

- In text mode the agent has the shell only. codemem is then a shell command, `codemem search
  "..."`, that calls the same warm server (the `serve` and `call` halves of `cm_bridge.py`).
- The events are written as `Bash` calls, so the counts stay the same.
- **Build it after the tool mode works** (§8, step 8). A model moves to text mode only when its
  qualification shows broken tool calls.

### 4.5 What the agent writes: Claude Code's events

**`stream.jsonl` has the form of Claude Code's stream.** Then `parse_stream`, `count_steps`, the
turn counter that enforces the turn limit, the check for codemem's fallback searches, track A's
score and our analysis scripts all work as they are.

| Event | Fields that the eval reads |
|---|---|
| start | `type: system`, `subtype: init`, `model`, `tools` (the names), `mcp_servers` (name and `status: connected`), and what names the harness: `harness: cmagent`, its version, the mode |
| each answer of the model | `type: assistant`, a `message` with an `id`, the `content` blocks (`text`, and `tool_use` with `id`, `name`, `input`) and the `usage` of that request |
| the results of its tool calls | `type: user`, a `message` whose `content` is the `tool_result` blocks (`tool_use_id`, `content`, `is_error`) |
| end | `type: result`, `num_turns`, the last answer in `result`, the durations, the summed `usage`, a `modelUsage` block for the cross-check with the proxy, and how the run ended |

**Read these before writing the events,** and make each of them pass on a `cmagent` stream in a
test: `e2e_steps.parse_stream`, `e2e_steps.count_steps`, `e2e_steps.codemem_fallbacks`, and in
`e2e_run.py`: `_follow_stream`, `classify_end`, `token_block`, `check_setup`.

### 4.6 The endpoint, the proxy and the key

**The container talks to the run's recording proxy and to nothing else,** as in a Claude run.

- The proxy sends each request on to the model's endpoint (`--upstream`): the Nebius API, or a
  server on the same machine.
- **The key never enters the container.** The proxy adds the `Authorization` header itself, from
  the variable named by `--api-key-env` in the environment of the host. It writes no credential,
  as now.
- **`proxy.py` learns the OpenAI form:** the path `/v1/chat/completions`, and the `usage` of a
  plain JSON answer. It writes the counts under the names it uses today:

  | The log's name | From the answer |
  |---|---|
  | `input_tokens` | `prompt_tokens` less the cached ones |
  | `cache_read_input_tokens` | `prompt_tokens_details.cached_tokens`, or `prompt_cache_hit_tokens` (Nebius) |
  | `cache_creation_input_tokens` | 0 |
  | `output_tokens` | `completion_tokens` |
  | `reasoning_tokens` (new) | `completion_tokens_details.reasoning_tokens`. They are a part of `completion_tokens` |

- **A count can be `null` or missing.** The 30B's usage has `null` for both detail blocks
  (checked, §2), and a vLLM server can leave out the cached tokens *(reported)*. All prompt tokens
  then count as `input_tokens`, and the total stays right.
- `request_facts` and `opens_with` learn the OpenAI form of a request, so that "the first message
  begins with the 20 lines" is still checked.

### 4.7 The two setups

They are track A's, unchanged.

- **`grep`:** an MCP config with no server. The agent has Bash, Read, Edit and Write.
- **`codemem`:** the 20 lines on top of the first message (`cmeval e2e block`), and codemem's MCP
  server through the gate (`gated_mcp_config`): the same `mcp.json`, the same warm server, the same
  four tools with the same descriptions as in a Claude run. The mount proof and the warm check
  stay.

### 4.8 Limits, and how a run can end

**The limits are those of the Claude runs:** 150 turns, 3,000 s, 4 CPUs, 16 GB.

| End | When | Counts as |
|---|---|---|
| finished | the model answered with no tool call | graded |
| turn limit, time limit, error | as now | not completed |
| context limit | the next request does not fit the model's window: the endpoint says so, or the agent's own count does | not completed |
| broken actions | 5 answers in a row with a tool call that cannot be read, or a tool that does not exist | not completed |
| repeated action | the same call with the same input 5 times in a row | not completed |
| token budget | the run has read more than `max_run_tokens` (2,000,000). A guard for the budget: one Haiku run reached 10.9 million | not completed |

- **The end rule is Claude Code's:** an answer with no tool call ends the run. Two guards go with
  it, because small models and their servers fail exactly here.
  - **An answer with no tool call that holds the text of one** (`<tool_call>`, `<function=`) is a
    broken action, not an end. vLLM returns such answers when a Qwen model writes its call inside
    its thinking *(reported)*.
  - **A model that ends without a change in a qualification task that asks for one** (§8) runs
    with a `Done` tool as its only way to end (the setting `end_rule`). An answer with no tool
    call then gets a reminder, and five of them in a row end the run as broken actions. The report
    says which models run so.
- **Arguments are read as JSON first.** A Python-style value such as `None` is accepted and
  noted: servers of Qwen models send them at times *(reported)*.
- **`max_tokens` is cut to what is left of the window,** so that a full window ends the run
  cleanly and not with an error of the server.
- **No history is dropped or summarised.** A full window ends the run. How runs end is a result
  for small models (track-a-evals.md §11).
- **Thinking is off** where a model has such a mode, and the sampling settings are the vendor's
  for that model. Both are in the record.

### 4.9 The record, and the command

**`run.json` as now,** with: `harness: cmagent` and its version; the endpoint's host, never a key;
the model as the endpoint names it; the mode, the prompt version, the output limit, the window and
the sampling; and the end of §4.8. Tokens come from the proxy. Cost comes from a price table for a
hosted model (`prices.py`), and is empty for a model on the rented GPU.

```bash
cmeval e2e run eval/envs/pandas.toml --tasks <file> --run-id <id> \
  --setup grep --setup codemem --prompt-level L0 --reps 1 \
  --harness cmagent --model Qwen/Qwen3.8-27B \
  --base-url https://api.tokenfactory.nebius.com/v1 --api-key-env NEBIUS_API_KEY
```

`--harness` defaults to `claude-code`, and nothing changes for a Claude run.

---

## 5. The models, and where they are served

**There is no current code model at these sizes, and no small Llama** *(reported)*.

- **Qwen's code model of about 30B** (`Qwen3-Coder-30B-A3B`, 2025) scores 33 to 52 on SWE-bench
  Verified, depending on the harness. The newer general Qwen models of the same size score 70 to
  86. vLLM also leaves its tool calls in the text, in an issue that was closed without a fix.
- **The last code Llama models of 7B and 13B are from 2023.** Llama 4 has no small size, and
  Meta's open model of 2026 comes in one size, 30B.
- **No Qwen newer than Qwen3 exists at 13 to 14B.**

So the picks are general models that are strong at coding, from one family where that is possible.

| Rung | Pick | Why | Where | vLLM flags |
|---|---|---|---|---|
| about 30B, through the API | `Qwen/Qwen3.8-27B` | the strongest open model of its size: 86.0 on SWE-bench Verified in mini-SWE-agent (vals.ai) | the Nebius API (checked): $0.45 in, $0.10 cached, $3.00 out, per million tokens | none |
| about 30B, on the GPU | `Qwen/Qwen3.6-35B-A3B`, FP8 | 3B of its parameters are active, so it is fast; 73.4 in Qwen's own scaffold | the rented GPU, about 35 GB | `--reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder --language-model-only` |
| about 9B | `Qwen/Qwen3.5-9B` | the strongest of its size: 45.2 in a shell-only harness | the rented GPU, about 10 GB in FP8 | the same two parsers |
| the third rung | `allenai/SERA-14B` if its window of 32,768 tokens holds, else `Qwen/Qwen3.5-4B` | SERA is a Qwen3-14B tuned for agents: 41.7 | the rented GPU | `--enable-auto-tool-choice --tool-call-parser hermes` |
| a cheap check | `Qwen/Qwen3-30B-A3B-Instruct-2507` | general and older; a tenth of the 27B's price | the Nebius API (checked): $0.10 in, $0.30 out | none |

- **Every model has one entry in `scripts/open/models.toml`:** its name, where it is served, the
  base URL, the name of the key's variable, its window, the mode, the end rule, the output limit,
  the sampling, extra request fields, and for a model on the GPU the weights and the server's
  flags.
- **The window is the model card's:** 262,144 tokens for the Qwen models of 2026, also where an
  API allows more (the Nebius API lists 1M for the 27B).
- **A model on the GPU is served by vLLM, version 0.26 or later,** with an OpenAI-style endpoint on
  `127.0.0.1:8000`. Requests are not streamed.
  - **The FP8 weights of the 35B** are named `Qwen/Qwen3.6-35B-A3B-FP8` in a forum post
    *(reported)*. `serve.sh` checks that a repo exists before it downloads from it.
  - **vLLM takes about nine tenths of the GPU's memory unless told otherwise.** `serve.sh` sets
    `--gpu-memory-utilization` so that about 16 GB stay free: each running `codemem` container
    holds the embedding model on the same GPU. The 16 GB are a guess; the pilot measures it.
  - **`--max-model-len` is the window in `models.toml`.**
- **Thinking is off,** so that a run costs cents and the rungs are alike.
  - **On the GPU,** for the Qwen models: `--default-chat-template-kwargs
    '{"enable_thinking": false}'`.
  - **Through the Nebius API:** `"chat_template_kwargs": {"enable_thinking": false}` in every
    request (checked, §2).
  - **Qwen3.8-27B thinks at its highest setting by default,** and a task then costs about a dollar
    *(reported, vals.ai)*. Its published 86.0 is with thinking on (decision 4 in §11).
  - **The qualification reads `reasoning_tokens` in the usage.** It must be 0.
- **Known faults to test for in the qualification** *(reported)*: a tool call written inside the
  thinking, which comes back as an empty call list; `None` in the arguments; SERA-14B calling a
  `submit` tool that does not exist.
- **Other hosts** *(reported)*: providers on OpenRouter serve the 35B at $0.05 to $0.08 in and
  $0.45 to $0.76 out, and the 9B at $0.04 to $0.08 in and $0.06 to $0.12 out, per million tokens.
  That is another account and another key: only with Andre's yes.

---

## 6. The machine, and the seamless path

**One rented Linux machine does everything:** the task containers, codemem's index and its
searches, and the models that are not on an API.

- **It needs:** an NVIDIA GPU, Docker with the NVIDIA container toolkit, 16 CPUs or more, 64 GB of
  memory or more, and about 300 GB of disk for the task images.
- **The recommended machine: one Nebius VM with an RTX PRO 6000** (96 GB, 24 CPUs, 218 GB of
  memory). It serves any of the models beside codemem's embedding model and four or five runs at
  once.

  | Nebius GPU *(reported)* | On demand, per hour | Preemptible, per hour | 30 USD buys |
  |---|---|---|---|
  | RTX PRO 6000, 96 GB | $1.80 | from $0.79 | 16.7 hours on demand |
  | L40S, 48 GB | $1.55 | $0.74 | 19.4 hours on demand, 40 preemptible |
  | H100, 80 GB | $4.50 | from $0.79 | 6.7 hours on demand |

- **What to know before renting** *(reported)*:
  - billing is by the second; a stopped machine still pays for its disk, about $0.70 a day for
    300 GiB; the first payment is at least $25;
  - a preemptible price is a floor ("from"), so the real price can be higher;
  - the image has CUDA and the NVIDIA container toolkit. Docker is not named, so `setup.sh`
    installs it when it is missing;
  - a preemptible machine is stopped with 60 seconds of warning, keeps its disk, and does not
    start again by itself. The runs survive that: a finished run is never run twice;
  - RunPod and Vast.ai cannot run the task containers, since they give no Docker inside. Lambda
    can.
- **The indexes are built with codemem's own model on that GPU,** exactly as track A builds them
  (`cmeval e2e index`). So the `codemem` setup is the one of the Claude runs.
- **Not the embedding API for these runs.** An index holds one model's vectors. With
  `Qwen3-Embedding-8B` the setup would be another one than track A's, and every search inside a
  run would need the API and its key in the container.

**The scripts, in `scripts/open/`.** Each one says what it does, stops at the first thing that is
wrong, and can be run again.

| Script | What it does |
|---|---|
| `setup.sh` | checks the GPU, Docker, the disk and the CDI spec; installs `uv`; builds the two environments; fetches codemem's embedding model; makes the Docker network; runs the self-test of §8 |
| `prepare.sh <repo>` | builds and validates the task images of the repo's tasks (`cmeval generate`), builds their indexes and the 20 lines for each level |
| `serve.sh <model>` | for a model on the GPU: starts vLLM with that model's flags, and waits until it answers |
| `qualify.sh <model>` | the three small tasks of §8 for that model, before any real run |
| `run.sh <model> <repo>` | the runs of §7 for that model and repo, in order, a finished run never twice |
| `report.sh` | the tables: completion, turns, tokens, how runs ended, the turn of the first opened fix file |
| `pack.sh` | one archive per batch for the release, searched for keys and names first |

- **`scripts/open/tasks/`** holds the task files of the open runs, made from
  `eval/tasks/run-sample-v1.jsonl` by a script, not by hand.
- **`.env.example`** names the variables. `.env` is never committed.

---

## 7. The runs, in order of priority

**The tasks.** For each repo the six easy tasks of the run sample. Small models complete easy,
one-file tasks or nothing (track-a-evals.md §11).

| Order | Repo | Why | Its six easy tasks |
|---|---|---|---|
| 1 | pandas | Python, mid-size, the Claude numbers to set beside are complete | 68278, 68945, 69924, 67025, 71232, 69779 |
| 2 | home-assistant | very large, with look-alike modules; where memory helped the Claude models least | 184675, 180391, 183382, 180438, 181276, 180560 |
| 3 | playwright | TypeScript, mid-size | 42204, 43316, 42780, 42503, 43012, 43174 |

**The steps.** Each one is a whole result that can be shown. The runs stop wherever the time or
the money ends.

| Step | What runs | Runs | What it shows |
|---|---|---|---|
| 1 | the first rung (§5), pandas, L0 and L2, `grep`, once | 12 | whether an open model can do our tasks at all, and the headroom: how many turns grep needs to open the fix file |
| 2 | the same with `codemem` | 12 | the first 12 pairs of grep against codemem |
| 3 | the second rung, then the third: steps 1 and 2 | 48 | **the trend with model size, on one repo** |
| 4 | repetitions 2 and 3 of steps 1 to 3 | 144 | intervals |
| 5 | the first rung on home-assistant, then on playwright | 48 | whether the result holds on other repos |
| 6 | the two smaller rungs on those repos; L1; medium tasks at L0, pandas' three first; a hard task for the first rung | as time allows | the rest of the picture |

**Three models on one repo come before one model on three repos.** The claim under test is about
the size of the model, so the picture to show first is the trend across sizes. Steps 1 and 2, one
model on one repo, come before both and can be shown alone.

**grep alone runs first** in every new cell. If grep still opens the fix file in two or three
turns, an index has no room there, and that is a finding.

**The budget, on the recommended machine at $1.80 an hour.** The hours are guesses until the pilot
has measured how many runs an hour the machine does.

| What | Hours | Cost |
|---|---|---|
| setup, the task images of pandas, their indexes | about 3 | $5 |
| the qualification of each model, and one task end to end | about 1 | $2 |
| steps 1 to 4: 216 runs, at 30 to 45 runs an hour | 5 to 7 | $9 to $13 |
| step 5: the images and indexes of two more repos, and 48 runs | 4 to 5 | $7 to $9 |
| **steps 1 to 5** | **13 to 16** | **$23 to $29** |

- **The 27B through the API costs beside that:** about $0.15 to $0.50 a run with thinking off, so
  $4 to $12 for the 24 runs of steps 1 and 2. On the GPU the first rung is the 35B, at no cost per
  run.
- **A preemptible machine costs about half** while its price is at the floor, at the risk of a
  stop.
- **The disk is extra:** about $0.70 a day for 300 GiB, also while the machine is stopped.

---

## 8. The order of building, with a check for each step

Each step ends with tests that pass. Nothing of a later step is started on a red test.

| Step | Build | It is done when |
|---|---|---|
| 0 | Read this plan, track-a-evals.md §4 to §7 and §11, `e2e_run.py`, `e2e_steps.py`, `proxy.py`, `codemem_gate.py`, `cm_bridge.py` | you can say what `agent.sh` does line by line |
| 1 | `cmagent.py` in tool mode: the loop, Bash, Read, Edit, Write, the limits and ends of §4.8 | unit tests against a stand-in endpoint: a task solved; each tool's errors; the carried working folder; long output cut; every end of §4.8 reached |
| 2 | the events of §4.5 | a `cmagent` stream goes through `parse_stream`, `count_steps`, `classify_end` and `token_block` in tests, with the counts checked by hand |
| 3 | the MCP client, and the tools of a server | with the stand-in MCP server of the existing tests: tools listed, a call answered, a server that dies handled |
| 4 | the proxy's OpenAI form and the key | tests: usage read from a plain answer; the header added from the host's variable; no credential in the log; the 20 lines found in the first message |
| 5 | the runner: `--harness cmagent`, the agent's line in `agent.sh`, the mount, the checks, the record | the local end-to-end test with stand-ins passes in `grep` and in `codemem`, as `_local_run` does for Claude Code. The whole eval suite passes, and a Claude run is byte for byte what it was |
| 6 | the qualification, and a live test on the Mac | with `NEBIUS_API_KEY`: both hosted Qwen models pass the three small tasks in a temporary folder, commands fenced in as in §10; one of them also with a real codemem server on a small index |
| 7 | `scripts/open/`, `models.toml`, the task files, `.env.example`, a section in `eval/README.md` | `setup.sh` passes its checks that need no GPU on the Mac; `qualify.sh` passes for a hosted model; the task files equal the sample's easy tasks |
| 8 | text mode | the tests of step 1 pass in text mode; one live task passes |
| 9 | the audit of §9 | its note is written |

**The qualification** (`scripts/open/qualify.sh <model>`). Three small tasks in a toy repo that
the script makes itself. A test grades each one.

1. **A planted bug in one function,** with a failing test (the check of §2).
2. **A fix that needs a search first:** the request describes a behaviour and names nothing, and
   the function is one of about 30 in 10 files.
3. **A question with nothing to change:** the right end is an answer after one or two reads.

- **A model passes** when all three runs end as finished, the test is green in 1 and 2, and no
  file is changed in 3.
- **It records for each task:** the turns, the tokens, the reasoning tokens, the calls that could
  not be read, and how the run ended.
- **A model that fails goes to text mode** (§4.4) or to the `Done` end rule (§4.8), and runs the
  three tasks again. A model that fails those too is left out, and the report says so.

**On the rented machine, with Andre:** `setup.sh` and its self-test; `qualify.sh` for each model;
one pandas task in both setups, with the record read line by line; then step 1 of §7.

---

## 9. At the end: audit your own work, and test it

Before you say it is done, check it as someone who expects to find a fault.

1. **Read your whole diff again,** file by file, against this plan. List what the plan asks for
   and you did not build, and say why.
2. **Run every test:** the eval suite and codemem's suite. A Claude run must be unchanged: the
   tests that pin its script, its `mcp.json` and its record must pass untouched.
3. **Try to break it.** For each of these, write a test or run it by hand, and note the result:
   - **The key.** After a live run, search the run's folder, the logs and the event file for the
     key's text. Dump the environment from inside the agent's shell. The key must be nowhere.
   - **The network.** From the agent's shell, try to reach an outside address. Only the proxy may
     answer.
   - **The two setups.** Compare the first request of a `grep` run and a `codemem` run of one task.
     They may differ in the 20 lines, in codemem's tools and in its instructions, and in nothing
     else.
   - **Each end of §4.8,** reached on purpose.
   - **A model that misbehaves:** tool calls with broken JSON, an unknown tool, an empty answer, an
     answer cut at the token limit, an endpoint that answers 500 or times out.
   - **The counts.** For one live run, count the turns, searches, views and edits by reading the
     event file yourself, and compare with `count_steps`.
4. **Test with a live model** where a stand-in cannot show it: `NEBIUS_API_KEY` from `.env`. A
   live test costs cents; say what you spent.
5. **Write the audit note** (`.personal/audits/<date>-open-harness.md`): what was tested and how,
   what failed and was fixed, and **what was not tested**. The Mac has no Docker, so the path
   through a real container is first run on the rented machine. Say that plainly.

---

## 10. Rules for the session that builds this

- **Start when Andre says so,** on branch `andre/open-harness`. On Andre's Mac it is checked out
  in `.cache/wt/open-harness`: work there, not in the main checkout. Never push `main`, and never
  force a push. Andre opens pull requests; put the text in `.personal/pr-drafts/`.
- **No outside agent code.** mini-SWE-agent, Qwen Code and any other harness, MCP server or tool
  are downloaded only after Andre has looked at them. Well-known Python packages are fine, but
  `cmagent.py` uses the standard library only.
- **The key.** Read `NEBIUS_API_KEY` from `.env` inside the process that needs it. Never print it,
  log it, commit it, or put it in a URL. `.env` stays ignored.
- **No Claude seat and no Claude API key** is used for these runs.
- **Commands that a model writes are fenced in** when they run on the Mac: a temporary folder
  outside the home folder, no network, no write outside that folder, and no read of the home
  folder. The check of §2 ran each command as `sandbox-exec -f <profile> /bin/bash -c <command>`,
  with `PATH` cut to the system's folders, and with this profile:

  ```
  (version 1)
  (allow default)
  (deny network*)
  (deny file-write*)
  (allow file-write* (subpath "<the temporary folder>"))
  (allow file-write* (literal "/dev/null") (literal "/dev/tty") (regex #"^/dev/fd/"))
  (deny file-read* (subpath "<the home folder>"))
  ```

- **The throwaway loop of §2 is kept on Andre's Mac** in `.personal/open-harness/proto/`, with
  the events of its two runs. It shows the shape of a request and of the events. It is not a base
  to build on: it has no limits, no MCP and no tests.
- **On the Mac:** first `source .cache/env.sh` of the main checkout; everything stays inside the
  project folder; no Docker; one heavy process at a time; write `.py` files through the shell.
- **Tell Andre before any entry goes into the work log.**

---

## 11. Decisions for Andre

Each has a proposal. The session that builds this follows the proposal until Andre says
otherwise: none of the four changes the loop, only `models.toml` and the scripts' defaults.

1. **The three models.** You asked for a code model of about 30B, a code Llama of 8 or 13B, and a
   Qwen of 13 or 14B. None of the three exists in a current form (§5). **The proposal:**
   Qwen3.6-35B-A3B or Qwen3.8-27B, then Qwen3.5-9B, then SERA-14B, or Qwen3.5-4B if SERA's small
   window ends its runs early. Yes, or other picks?
2. **The first rung:** the 35B on the rented GPU, or the 27B through the Nebius API. **The
   proposal:** the 35B for the runs. The machine is rented anyway, a run on it costs nothing more,
   and the 27B's runs alone would use a third of the budget in steps 1 and 2. The 27B stays the
   model of the live tests on the Mac, and the fallback if vLLM's tool calls fail.
3. **The machine:** a Nebius RTX PRO 6000, on demand or preemptible. The first payment is at
   least $25. **The proposal:** on demand. A preempted machine does not start again by itself, so
   a night of runs can be lost.
4. **Thinking:** off for every model, or on for the first rung. **The proposal:** off. A run then
   costs cents, and the rungs are alike. The 27B's published 86.0 is with thinking on, at about a
   dollar a task.

---

## Sources

All *(reported)*: read on Nov 28 by a research pass, not re-read by the team.

- **Harnesses:** [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent) and its
  [releases](https://github.com/SWE-agent/mini-swe-agent/releases);
  [Qwen Code](https://github.com/QwenLM/qwen-code);
  [OpenHands SDK](https://github.com/OpenHands/software-agent-sdk);
  [Codex CLI's config reference](https://learn.chatgpt.com/docs/config-file/config-reference);
  [OpenClaw](https://github.com/openclaw/openclaw);
  [pi](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent);
  [Harbor's agents](https://docs.harborframework.com/agents/pre-integrated-agents);
  [Claude Code through a gateway](https://code.claude.com/docs/en/llm-gateway).
- **Claude Code's loop and tools:** [the agent loop](https://code.claude.com/docs/en/agent-sdk/agent-loop),
  [the tools](https://code.claude.com/docs/en/tools-reference).
- **Models:** [Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B),
  [Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) and
  [its vLLM recipe](https://recipes.vllm.ai/Qwen/Qwen3.6-35B-A3B.md),
  [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B),
  [SERA-14B](https://huggingface.co/allenai/SERA-14B),
  [Qwen3-Coder-30B-A3B](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct);
  scores at [vals.ai](https://www.vals.ai/benchmarks/swebench).
- **Serving:** [vLLM's tool calling](https://docs.vllm.ai/en/stable/features/tool_calling.html);
  [the fault with tool calls inside the thinking](https://particula.tech/blog/empty-tool-calls-reasoning-content-vllm-parser).
- **Other hosts:** OpenRouter's providers of
  [the 35B](https://openrouter.ai/qwen/qwen3.6-35b-a3b/providers) and of
  [the 9B](https://openrouter.ai/qwen/qwen3.5-9b/providers).
- **Nebius:** [the API's models and prices](https://tokenfactory.nebius.com/api/public/models_info),
  [GPU prices](https://nebius.com/prices),
  [preemptible machines](https://docs.nebius.com/compute/virtual-machines/preemptible.md),
  [boot images](https://docs.nebius.com/compute/storage/boot-disk-images.md).
