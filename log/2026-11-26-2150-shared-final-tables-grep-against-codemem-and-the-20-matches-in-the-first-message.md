# The final tables: grep against grep plus codemem on 17 pandas tasks, 186 sessions. The 20 best matches in the first message beat grep for both models; codemem as a tool did not shorten the search

- **Track:** shared: track B work done in track C's session. It completes the entries of 21:00 and 21:10 UTC
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 21:50 UTC
- **Work package:** B1 (grep against grep plus codemem), B8 (does the agent use it), B-E3 (the call graph)
- **Branch, commits, pull request:** measurement only. Pushed today and named here: `andre/search-recall` (`1c48f2c`, not merged), `andre/compact-linux` (`bc76bd0`, waits for track A's check), `andre/track-b-lab` (`40a82da`, a record). Files with this entry: `log/2026-11-26-2150-shared-data/`

## Done

**The experiment.** The same agent (Claude Code 2.1.285, tools Read and a shell that may only read) is asked where in pandas a change has to be made, on 17 vague-prompt tasks, each in the repository at its own base commit with its own index, and answers with files and functions. One session per cell, 186 sessions, none discarded. The arms differ only in how the agent can search:

- `grep`: no codemem;
- `tool`: codemem `09c4ef0` as MCP tools, wording `light`, the model loaded before the agent starts;
- `tool+`: the same with the branch `andre/search-recall` (`da6cd0f`);
- `upfront`: no codemem tool. One `codemem search` on the request is made before the session, and its 20 results are put in front of the prompt as `path:line  name`, under the line "Possibly relevant code, from a search by meaning (it may be wrong):";
- for Sonnet on 8 tasks, `tool` and `tool+` with codemem's two hooks.

**1. The tables.** Right function: the answer names a function the real fix changed, of the 16 tasks that have one.

| Haiku 5.5, 17 tasks | Level | Right function | Median turns | Median tokens | Median cost | Median seconds |
|---|---|---|---|---|---|---|
| `grep` | L2 | 13 | 5 | 64,786 | $0.0034 | 12.5 |
| `tool` | L2 | 15 | 4 | 60,017 | $0.0032 | 8.7 |
| `tool+` | L2 | 15 | 3 | 49,805 | $0.0037 | 8.2 |
| `upfront` | L2 | 14 | 4 | 53,486 | $0.0024 | 11.5 |
| `grep` | L1 | 14 | 4 | 54,610 | $0.0024 | 11.1 |
| `tool` | L1 | 16 | 4 | 60,253 | $0.0026 | 8.7 |
| `tool+` | L1 | 16 | 4 | 63,714 | $0.0032 | 8.2 |

| Sonnet 5.5, L2 | Tasks | Right function | Median turns | Median tokens | Called `search_code` |
|---|---|---|---|---|---|
| `grep` | 17 | 14 of 16 | 4 | 19,020 | |
| `tool` | 17 | 15 of 16 | 3 | 19,303 | 3 of 17 |
| `upfront` | 17 | 14 of 16 | 3 | 18,544 | |
| `tool` with hooks | 8 | 7 of 8 | 4 | 27,286 | 8 of 8 |
| `tool+` with hooks | 8 | 8 of 8 | 4 | 30,898 | 8 of 8 |

Pair by pair against `grep` on the same task (the arm lower / equal / higher):

| Model, level | Arm | Turns | Tokens | Cost | Seconds |
|---|---|---|---|---|---|
| Haiku, L2 | `tool` | 8 / 4 / 5 | 8 / 0 / 9 | 8 / 0 / 9 | 12 / 0 / 5 |
| Haiku, L2 | `tool+` | 9 / 5 / 3 | 8 / 0 / 9 | 5 / 0 / 12 | 13 / 0 / 3 |
| Haiku, L2 | `upfront` | **13 / 1 / 3** | **13 / 0 / 4** | **13 / 0 / 4** | 11 / 0 / 6 |
| Haiku, L1 | `tool` | 9 / 1 / 7 | 9 / 0 / 8 | 7 / 0 / 10 | 12 / 0 / 5 |
| Haiku, L1 | `tool+` | 6 / 7 / 4 | 5 / 0 / 12 | 1 / 0 / 16 | 11 / 2 / 4 |
| Sonnet, L2 | `tool` | 8 / 6 / 3 | 8 / 0 / 9 | 12 / 0 / 5 | 12 / 0 / 5 |
| Sonnet, L2 | `upfront` | **12 / 4 / 1** | 12 / 0 / 5 | 9 / 0 / 8 | **14 / 1 / 2** |
| Sonnet, L2, 8 tasks | `tool` with hooks | 0 / 4 / 4 | 1 / 0 / 7 | 2 / 0 / 6 | 4 / 0 / 4 |

**2. What the tables say.**

- **Every arm found the right code about equally often.** Both models know pandas, so accuracy is near the ceiling. codemem's two more tasks for Haiku at each level are within what chance gives on 16 tasks.
- **As a tool, codemem did not shorten the search.** Haiku called `search_code` at turn 1 in all its sessions and its first result held a gold file in 28 of 34, yet its turns and tokens matched grep's. It answered faster (12 of 17 pairs at each level). Sonnet called it in 3 of 17 sessions; with the hooks always, at more tokens in 7 of 8 tasks for the same answers.
- **codemem's results in the prompt did.** `upfront` took fewer turns than grep in 13 of 17 Haiku tasks and 12 of 17 Sonnet tasks, fewer tokens in 13 and 12, with the same accuracy. Against `tool` it used fewer tokens in 15 of 17 Haiku tasks and 14 of 17 Sonnet tasks. The agent's first call went to a file or name of the list in 33 of 34 sessions; a gold file was in the list in 28 of 34.
- **How much is noise:** Sonnet's `tool` arm is nearly the `grep` arm (3 calls in 17 sessions) and still shows turns 8 lower, 3 higher. One run per cell; a split like that means nothing. The `upfront` turns are well beyond it.
- **The branch does not beat `main`, and costs more.** In the 10 task-levels where `main`'s first result had no gold function among its cards, the branch showed one in 6 (3 as a card, 2 in a related line, 1 in "More results"), and both named the function in 9 of the 10. A name that was only listed was the next step in 4 of 34 sessions. At L1 the branch cost more than grep in 16 of 17 pairs.
- **Where codemem made a session worse:** after a good result Haiku sometimes kept opening functions with `get_chunk`, which returns each one whole with its callers and callees (68090 at L2: 13 turns and 333,764 tokens against grep's 5 and 64,786, for the same answer). And on the three tasks whose gold file is Cython, which codemem does not index, the codemem arms searched for a file they cannot return.

**3. How the `upfront` list was made,** for anyone who wants to repeat it. Before the session, with the index of the task's commit and the same environment as the MCP server:

```bash
codemem search "<the prompt's request text, nothing else>" --repo <repo> --index-dir <a copy of the index> -k 20 --json
```

- Take `results[i].path`, `.start_line`, `.qualname`: 20 lines `path:start_line  qualname`.
- Check that `timings` holds a key that starts with `embed_query:`. Without it the search was keywords only, and the list is not the one tested.
- The prompt is the header line, the 20 lines, an empty line, then the usual prompt. No MCP server in this arm.
- **Whether the runs get such a setup is Andre's decision and is not made.** It is not a change to codemem.

**4. The call graph, for fixes that change two or more functions** (it completes point 3 of the 21:10 entry). Offline, the whole issue as the query, 304 tasks (127 pandas, 177 vLLM), about 4 functions to change each. Tasks with every one of them on the page:

| The page shows | pandas (127) | vLLM (177) | Both (304) |
|---|---|---|---|
| the 10 results | 14 | 27 | 41 |
| and related names | 30 | 51 | 81 |
| and the next 20 by name | 31 | 44 | 75 |
| and both | 43 | 64 | 107 |
| control: the next 20, and as many deeper results as there are related names | 33 | 48 | 81 |

So the call graph, as names on the page, adds 26 tasks that the same number of extra results does not. For finding one function it adds nothing over extra results. No session has tested whether an agent follows those names.

**5. Two faults seen on the way.** A query that arrives during the server's warm-up crashed it on an Apple GPU; #60 on `main` fixes it (one model call at a time). codemem does not index Cython: 41 of the 352 pandas tasks have a `.pyx` or `.pxd` file among the files to change.

## Checked

- Every table above was counted twice: by the agent that ran the sessions, and again from each session's record.
- The fence that keeps a session from writing was proven with a scripted API before the sessions, and again after `cd` was allowed.
- Test suites on the Mac, FAISS 1.16.0, after the merges with `main` at `e6f2d30`, each run three ways (the default index, and the suite forced onto the compact and onto the exact index): `andre/search-recall` (`1c48f2c`) 753 passed, and 750 passed with 3 skipped twice; `andre/compact-linux` (`bc76bd0`) 738 passed, and 735 passed with 3 skipped twice.
- Not checked: any repository but pandas; a repository the models do not know, which is the test that would settle the question; the full issue (L0); a fix with its tests, since the sessions only locate; Linux.

## Left

- The same arms on code the models cannot remember (Wilson's renaming control would give that), with `upfront` beside `tool` and `grep`.
- `upfront` together with the tool, and with the branch's page: not tried.

## Blocked on, or needed from others

- **Track A:** the two commands of the 21:20 entry, for `andre/compact-linux`.
- **Wilson:** nothing. The files here are yours to use: `agent-with-and-without-codemem.md` (the full report, with one task followed through every arm) and `several-functions.md`.

## Next

- Andre: whether the runs get an `upfront` setup; the pull request for `andre/compact-linux` after track A's check.
