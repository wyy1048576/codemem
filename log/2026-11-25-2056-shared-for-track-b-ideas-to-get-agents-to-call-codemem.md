# For track B: ideas to get agents to call codemem, after the pilot's 0 of 18

- **Track:** shared, addressed to track B. Point 1 is also for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-25 20:56 UTC
- **Work package:** B8 and B-E9
- **Branch, commits, pull request:** none

## Done

Andre and Wilson agreed on Nov 25 to try a mix: a hook before a tool call, a hook after one, and
the prompt. Andre asked for ideas to be passed to Wilson's agent. These are ideas, ranked by what
the pilot's evidence points at (entry of 2026-11-25 15:57). None is tested. Check each hook
detail against Claude Code's hooks documentation before building on it.

**The evidence.** At `light`, 0 of 18 Haiku runs called codemem. At `strong`, 4 of 5 called it
once, in turn 1, next to a `grep`, and never again. One of those four calls returned "No results"
with the note that the model was still loading. The result reaches the agent as one JSON string
with escaped line ends. So there are two problems: the agent does not start, and when it starts,
the first call gives it no reason to come back.

**A. Make the first call worth it. Do these first: they are faults, not wording.**

1. **The first search must not answer while the model loads.** In track A's container the model
   loads for about 7 s at start, and a search waits 4 s. An agent that searches in turn 1 gets
   keywords only. Two ways out:
   - the runner sends the prompt only when codemem is ready. On `andre/model-idle-unload`,
     `index_status` reports `models_loaded`; on `main` a first throwaway search does the same;
   - the embedding server (`codemem serve-embeddings`, `andre/embedding-endpoints`): the model is
     always loaded, and no container loads one.
   A real session does not have this problem: the server starts with the session and the first
   prompt comes later. So waiting is the fair choice for the eval, not a favour to codemem.
2. **Return plain text.** If the model really receives `{"result": "1. pandas/io/...\\n   def ..."}`,
   the cards are one unreadable line, and "never again" is the natural reaction. Check what the
   model received: track A's proxy keeps every request body (#28), so the tool result is in the
   next request. If it is the JSON string, return the text as the tool's content.
3. **Accept an absolute `path_prefix`,** by cutting the repo root off it. And never return a bare
   "No results" for a filtered search: search again without the filter and say so.
4. **Make each result a next step.** Give `path:start-end` in a form the agent can paste into
   `sed -n`, and end with the one call that goes deeper (`get_chunk`). The agent works in the
   shell, so a result it can act on with a shell command will be used.

**B. Do the first search for the agent.**

5. **Inject the first results.** A hook at the start of the session, or when the prompt is
   submitted, runs codemem's search on the task text and adds the best 5 cards as context. The
   agent then needs no decision to benefit, and it sees what codemem returns before it forms its
   grep habit for the task. This is the `upfront` setup of track A's plan (§3). A related
   published result: a retrieval agent's results injected into a frozen coding agent raised
   SWE-bench Verified from 25.8% to 27.0% and cut tokens by 19% on resolved tasks (CodeGrep,
   arXiv 2608.05886). I would give this arm priority: it does not depend on the model's habits.

**C. Catch the agent where it searches: the shell.**

6. **The hooks must cover Bash.** Claude Code 2.1.332 has no Grep or Glob tool, so a hook on
   those never fires. After a shell `grep`, `rg` or `find` that printed nothing, or more than
   about 50 lines, add one line that names the call: `search_code("<the behaviour in plain
   words>")`. Adding a line after the call costs no turn. Refusing a call before it does.
7. **A shell command for codemem.** Haiku typed plain `grep` for almost every search. A command
   on the path, for example `codemem search "<words>"`, with output shaped like grep's
   (`path:line: text`), meets that habit. It is also the only form an agent without MCP can use:
   mini-SWE-agent, the main harness for the open models, has a shell and nothing else. So this
   piece is needed for the model-gap runs anyway.

**D. The prompt.**

8. One sentence with a rule for when, not a general request: "Before your first grep, call
   search_code with the behaviour in your own words; grep once you have a name." The `light`
   wording of #26 says this in the tool's own text. A version in the task prompt is its own
   setup, because then two things differ from the baseline.

**How to tell which one works.** One mechanism per arm, on the same 18 tasks, with Haiku and
with Sonnet, three repetitions each: two runs of one task differed by up to 8 times in tokens,
so one repetition shows nothing. Per arm: the share of runs with at least one call, the turn of
the first call, the calls after the first, and whether the first result holds a gold file. The
second and third numbers separate "the agent starts" from "the agent comes back".

**One answer on the graph work.** To score a hit's neighbours against the query, call
`Store.vector_search(vec_type, query, n, allowed_ids=<their chunk ids>)`. With few allowed
chunks every backend scores each one exactly, with no scan. It works the same on the compact
store of track C.

## Checked

- Nothing here was run. The evidence is track A's pilot and probe.
- The hook mechanics (what a hook before a tool call may return, how context is added after a
  call or at session start) are from memory of Claude Code's documentation. Read the current
  pages before writing code.

## Left

- All of it is track B's to choose from.

## Blocked on, or needed from others

- **Wilson:** take what is useful. Items 1 to 4 look like prerequisites for any adoption number.
- **Andrew:** item 1. Say whether the runner should wait for the model, or whether the embedding
  server is wanted after all.

## Next

- Wilson's agent.
