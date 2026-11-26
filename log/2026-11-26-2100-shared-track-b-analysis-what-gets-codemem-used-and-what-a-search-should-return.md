# For track B (Wilson's agent) and track A: our analysis of what gets codemem used and what a search should return. A lab on the real indexes and 136 agent sessions

- **Track:** shared: track B work done in track C's session, posted so that nobody repeats it
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 21:00 UTC
- **Work package:** B-E0, B-E3, B-E4, B-E7 (what a search returns), B8 (does the agent call codemem), B1 (grep against grep plus codemem)
- **Branch, commits, pull request:** `andre/search-recall` (pushed, tip `da6cd0f`, on `main` `09c4ef0`; no pull request yet). Everything else is measurement: the scripts and session records are on Andre's Mac (`.cache/review/lab`, `adopt`, `compare`); ask and we push what you need

## Done

All of it is codemem beside grep, never in place of it: the agent keeps its own tools.

**1. Does the agent call codemem? It depends on the model more than on the repo.** Claude Code 2.1.285, the runner's prompt frame and flags, sessions that may only read, codemem `09c4ef0`, a wrapper that holds the MCP handshake until the model is loaded.

| Setup of codemem | Haiku 5.5 | Sonnet 5.5 |
|---|---|---|
| wording `light` (main), no hooks: the runner's `tool` setup | `search_code` in turn 1 in 64 of 64 sessions | 0 of 11 short sessions; 2 of 8 full sessions |
| wording `none` | 2 of 12 | not run |
| wording `strong` | as `light`, with more repeat searches | 5 of 11 |
| `light` plus codemem's two hooks (`codemem init --write-hooks`) | the hook does not fire: Haiku searched first | 11 of 11, and 8 of 8 full sessions |

- **Sonnet greps names it remembers.** At L2 (a short request that names no code) its first grep used a real name of the code to change in 7 of 11 tasks and named the right file's path in 4, on vLLM as on pandas.
- **Wilson, the first-search hook does what it was built for.** In every session where Sonnet's first search was a grep, the hook refused it once and the next call was `search_code`. No session repeated the grep, and no later grep was refused. It also refuses under `--permission-mode bypassPermissions` (one scripted session, no model call).
- **But making Sonnet search first did not pay on these tasks.** Against grep alone, same task: turns never lower (equal in 4, higher in 4), tokens higher in 7 of 8, the same answers. So we do not ask for the hooks in the runs.
- **Handing Sonnet the results did.** One codemem search on the request before the session, its 20 best matches in the first message as `path:line  name` under the line "Possibly relevant code, from a search by meaning (it may be wrong):", no tool. Against grep alone: fewer turns in 6 of 8 tasks, never more; the right file first in 8 of 8. Its first call went to a file or name of the list in 8 of 8.

**2. grep against grep plus codemem, same agent, same tasks.** 17 pandas vague-prompt tasks, each at its own base commit with its own index; the agent is asked where the change has to be made and answers with files and functions; one session per cell. State: 16 of 17 tasks for Haiku, 8 for Sonnet.

| Haiku, 16 tasks | Level | Right function named (of 15 with one) | Median turns | Median tokens | Median seconds |
|---|---|---|---|---|---|
| grep only | L2 | 13 | 4.5 | 63,634 | 12.2 |
| codemem (`09c4ef0`) | L2 | 15 | 4 | 58,720 | 8.3 |
| codemem, branch `andre/search-recall` | L2 | 15 | 3 | 48,409 | 8.2 |
| grep only | L1 | 13 | 4 | 53,500 | 10.4 |
| codemem | L1 | 15 | 4 | 58,892 | 8.6 |
| codemem, branch | L1 | 15 | 3.5 | 60,026 | 8.1 |

- codemem named the right function in the 4 cells where grep did not, and was faster in 12 of 16 pairs at L2 and 11 of 16 at L1. Tokens split evenly (8 pairs lower, 8 higher, at each level); turns were lower in 8 pairs and higher in 5 to 7.
- Every arm is near the ceiling: these tasks are small and pandas is well known. This sample cannot show a large effect in either direction.

| Sonnet, 8 tasks, L2 | Right file first | Right function | Median turns | Median tokens | Called `search_code` |
|---|---|---|---|---|---|
| grep only | 7 | 8 | 3 | 15,602 | |
| codemem, as the runner sets it up | 7 | 8 | 3 | 18,412 | 2 of 8 |
| codemem plus hooks | 7 | 7 | 4 | 27,285 | 8 of 8 |
| the branch plus hooks | 7 | 8 | 4 | 30,898 | 8 of 8 |
| 20 results in the first message, no tool | 8 | 7 | 3 | 17,258 | |

**3. What a search should return: the lab.** Offline, the real vLLM (`e9acf48`) and pandas (`a0885a1`) indexes, the product's own `search()`, 733 issue tasks with the issue as the query. Every setting was chosen on one half of the tasks and is reported on the other (175 vLLM, 162 pandas). The 16 vague pandas tasks were never used to choose. A hit is a gold function's own chunk, by chunk id.

- **Where the misses are:** when a function to change is not in the top 10, it is mostly just below it or one call away from a result. About half of the missed functions are already candidates of the merge; none was cut by the model's length limit. It is ranking and reach, not chunking or embedding.

| Tried | Function to change in the top 10, or named on the page: vLLM / pandas | Vague L1 / L2 (of 16) |
|---|---|---|
| today | 99 / 94 | 9 / 8 |
| callers and callees of the best results as a fourth list of the merge | 100 / 99 (random neighbours do as well) | 10 / 9 |
| callers and callees lift a candidate | 93 / 98 | 9 / 10 |
| the other functions of the best results' files, as a list | 103 / 96 | 9 / 9 |
| a ranking of files; exact names of the query; files that change together | 98 / 94; 104 / 94; 98 / 97 | no gain |
| 200 candidates per list and other weights | 104 / 96 (pandas files fall by 5) | 9 / 9 |
| at most 3 results of one file | 94 / 87 | 9 / 7 |
| callees of the best-ranked tests | 98 / 93 | 9 / 9 |
| a whole-file keyword list (needs a new table) | 96 / 96 | 11 / 11 |
| tests kept out of the 10 results | 103 / 100 (the labels are never tests, so this is favoured) | 10 / 11 |
| **3 related callers or callees named under each result** | **117 / 108** | 12 / 9 |
| **results 11 to 30 listed by name after the 10** | **116 / 108** | 11 / 12 |
| **both** | **127 / 117** | **13 / 12** |
| names the agent knows or guesses as an argument of their own (keywords only), with a short query | 58 to 88 of 175; 70 to 81 of 162 | 11 / 11 |

- **The call graph does not improve the ranking.** In the ranking, neighbours gain 1 to 5 tasks and random neighbours gain as much. As three names under each result they reach 18 and 14 more tasks. Listing results 11 to 30 by name reaches as many, but other tasks, so the two add up.
- **Track A's replay (19:25 UTC) agrees, on real agent queries:** a gold function is in the results for 49% of first searches at 10 results and 67% at 30. Thirty full results cost about 8,400 more characters than ten; listing 20 more by name costs about 1,600.
- **What the names cost:** an answer of `search_code` grows from 5,801 to 9,332 characters on the vLLM issues (about 900 tokens a search); 4 to 9 ms; no model call; no index change.

**4. The branch `andre/search-recall`** holds the three bold rows and the names argument: `card_relations` (3), `more_results` (20), `names` on `search_code`, and `tests_apart` (off). Without `names`, and with the two settings at 0, a search is what it is on `main`, result for result. In the sessions above it changed no outcome against `main` (15 of 15 both) and cost more than grep in 15 of 16 Haiku pairs at L1, because longer answers are written to the cache. The function to change was on the page of the first result in 27 of 30 first searches, against 22 of 30 on `main`; the agents wrote their own queries, so that is not a controlled count. The agent's next step followed a name that was only listed in 3 of 32 sessions; Haiku passed `names` in about half. **Whether it is merged before the lock, and with which defaults, is Andre's decision and is not made.**

**5. What we learned about running such sessions,** for whoever measures next.

- **Load the model before the agent starts.** Track A found the same in its runs (31 of 62 first searches from keywords only). A query that arrives during the warm-up can also crash the server on an Apple GPU; `andre/macos-omp` fixes that (one model call at a time).
- **A tool's answer must reach the model as plain text** (#54). Check it in the request bodies, not in the stream.
- **A task needs the repo at its own commit.** A newer checkout holds the fix. Inside another repository, give the task folder an empty `.git` file, or codemem and git resolve to the outer one.
- **A fence that only allows reading costs turns unevenly.** 22 commands were refused in 33 Sonnet sessions, 10 of them `cd dir && grep ...` and 7 `python -c`. Allow `cd`, count refused calls per arm, and report turns with and without them.
- **Reach is not use.** A function named on the page counts for nothing until a session shows the agent following it.
- **Longer answers show in cost before they show in tokens,** because they are cache writes.
- **codemem does not index Cython:** 41 of the 352 pandas tasks have a `.pyx` or `.pxd` file among the files to change, 25 of them only such files.

**6. For track A.**
- **The five failures on Linux: yes, please post the full log.** Most useful: the first failing assertion of each of the three tests (`-x --tb=long`), the output of `python -c "import faiss; print(faiss.get_compile_options())"`, and whether the five still fail with `OMP_NUM_THREADS=1`. On macOS codemem runs FAISS on one thread, so these tests have never run on several here. An agent is on it.
- **`andre/vague-prompts-v3` will not be merged:** your version 3 on `main` replaces it. Thank you for the four further rows.
- **The replay answered what we asked;** see point 3.

## Checked

- The session tables were counted again from each session's own record, apart from the agents that ran them. The lab's numbers for the branch were reproduced with the branch's own `search()`. The branch's suite: 746 pass on the default index, 743 with each index forced (Mac, FAISS 1.16.0).
- Not checked: any of it on Linux; any repo but pandas in the comparison; whether a fix is completed, since the sessions only locate. One session per cell, so a difference of one or two tasks is noise.

## Left

- The comparison's last blocks: the seventeenth task, the 20-results-in-the-prompt arm for Haiku on all 17 tasks and for Sonnet on the other 9. A short entry follows with the final tables.
- Andre's decisions: the branch; whether the runs get a setup with the results in the first message.

## Blocked on, or needed from others

- **Track A:** the log of the five failures, as in point 6.
- **Wilson:** nothing. If a table here would help your revision as data (per task, per session), say which and we post the file.

## Next

- Andre's session: the final tables; the cause of the Linux failures.
