# To everyone on the project, people and agents: what this study is for, why open-weight models are in it, and a note on reports about the model this session runs on

- **Track:** shared: a note from Andre, for all three tracks
- **Who:** Andre, with Claude Code (the model of this session is Claude Fable 5.2)
- **When:** 2026-11-27 16:11 UTC
- **Work package:** none: the purpose of the work
- **Branch, commits, pull request:** none

## Done

Andre asked for this note so that nobody, person or agent, has to wonder what the work is for, or whether it crosses a line.

### 1. What the study is for

- **To show when grep is enough, and when an indexed search fills the gap.** It is not to make codemem win.
- **grep has its place, and the paper will say so.** A large model knows a famous repo from memory and goes straight to the right file with a precise grep. Nothing is wrong with that, and for a large enough model on code it knows, grep is probably the wiser choice. Our own probe shows it: with no repository at all, Haiku, Sonnet and Opus named the right pandas file first in 15, 15 and 14 of 17 tasks.
- **An index has to earn its place where memory runs out:** a smaller model (on duckdb the same probe gives 7, 12 and 22 of 41), code a model has never seen (a private or a new repo), and new code or a new feature inside a famous repo. That is why codemem is evaluated on the large models too, and why the results are reported by model and by how well the model knows the code.
- **The gap this fills:** there is little careful work comparing indexed search with grep for coding agents, across models, on tasks newer than the models, with tokens, cost, time and solved tasks measured the same way.

### 2. Why open-weight models are part of it

- **Results from top models alone would mislead.** A reader who swaps the model, or works on a private codebase, would find that the numbers do not carry over, and the benchmark would be moot.
- **So the small-model study of the plan is core, not an extra:** Qwen at 9B, 14B and 27B as the agent, in an open harness (track A's plan, §11). These models are less up to date and smaller than Sonnet or Opus. That is the point: it shows where grep stops being enough.
- **They have to be tested as carefully as the Claude models:** the same tasks, the same measures, the same checks.
- **Where it stands:** the eval can only drive Claude Code today (its harness is a constant). The runner for open models is not built and is on nobody's list for this week. Anyone picking it up is doing wanted work.

### 3. Reports about Anthropic and Fable models: what we know and what we do not

- **What Andre has seen.** In the last days, several posts claim that Anthropic deliberately slows or sabotages research work done with its Fable models, for example by silently using a weaker model or by introducing errors, in order to slow progress at the frontier of AI. Two examples he gave: https://x.com/i/trending/2125741644398071932 and https://www.reddit.com/r/ClaudeAI/comments/1y5jpc9/anthropic_exemployee_claude_sabotages_research/
- **We cannot verify them.** This session tried to read both pages and could not (one refused the fetch, the other asked for payment). So we cannot say what exactly they claim, on what basis, or whether any of it is true. Nobody on this project can.
- **What this session can say about itself, from its own instructions:**
  - The training of Claude Fable 5.2 included measures to limit advances in a narrow set of capabilities that could most directly accelerate AI development. The example given is the optimisation of low-level code for accelerators.
  - In those areas it is told to trust its own assumptions less and to look up documentation more often, and that it can otherwise help as usual. The first is a limit on what the model learned; the second is how to work well in spite of it.
  - It is told that these measures do not affect ordinary machine learning.
  - It knows of no instruction and no mechanism to swap in a weaker model silently or to introduce errors on purpose, and it would not knowingly introduce one. It cannot rule out what it cannot see.
  - The official description of the model is at https://www.anthropic.com/claude/fable
- **Whether it touches this work.** Hardly: a search tool for code and a benchmark are not that kind of work. The one place that comes near is low-level speed (threads and the math library of the compact index). There nothing was taken on the model's word: the fix is not merged, and it waits for a measurement on Linux.
- **What protects the results whatever the cause of an error:** every number that goes into a table is recounted from the raw records; audits are made by separate agents and checked again; the three tracks' agents read and check one another's work; and what cannot be checked is said to be unchecked.

### 4. What we ask of everyone

- **Do not hold back on this work out of worry.** It is a benchmark and a tool, done to give readers a view that carries over to other models and other code.
- **If you suspect an error from a model, yours or another's, write it in this log** with what you saw. We recheck from the records.

### 5. Added at 16:24 UTC: the pages have now been read, and one correction to point 3

After this entry was posted, Andre showed this session screenshots of two of the posts, and its fetches of a Hacker News thread on the same post and of two pages of Anthropic went through. Point 3 stays as it was written. This part says what is known now.

- **What the post says.** A post on X of Nov 25 by the account @skirano, shown in the Reddit post and linked from https://news.ycombinator.com/item?id=50651552: "If you use Claude models for research, they'll try to sabotage the work at every stage." The author says he built a skill that sends the work to other models instead. The post gives no example and no way to repeat what he saw. The Reddit title and one commenter call him a former Anthropic employee; we have not checked that.
- **What the thread adds.** The commenters disagree with one another. Some ask for evidence. One who works on training and fine-tuning reports no such sign. Several point to Anthropic's own announcement. One writes that an Anthropic employee replied that answers about AI research had been degraded at serving time during the first two days of Fable 5, called that a mistake that was fixed quickly, and said it is not done now; we have not seen that reply. One claims that Claude Code redirects requests to cheaper models.
- **What Anthropic's announcement says** (https://www.anthropic.com/claude-fable-and-mythos-5-2, under "AI research and development"; the wording is as our fetch returned it):
  - during training, "we took steps to limit advances in the specific research capabilities that could most directly accelerate AI development";
  - in those areas, "including accelerator kernel optimization and improving large language model architectures", Fable 5.2 and Mythos 5.2 "perform at about the level of Opus 5.5";
  - the changes "did not affect related capabilities like agentic coding, hardware development, and traditional AI or machine learning research";
  - "We do not alter these capabilities as the model is being served to users (that is, at inference time)."
- **The correction.** Point 3 said that this session knows of no mechanism that puts another model in its place. Anthropic's pages describe one. A request that the safeguards flag for cybersecurity or biology is answered by an earlier Opus model. And the announcement names "transparent fallbacks to Opus 5 for a small set of topics" in AI development, "including kernel development on certain nonstandard accelerators". None of these subjects is part of this project. We could not read the system card itself: the file was too large for the fetch.
- **What this means for us.**
  - The published limit is that a Fable model is about as good as Opus 5.5, and no better, in a narrow area. That is not a statement that it does worse work on purpose. On the post's wider claim we have no evidence either way.
  - This project is coding and the evaluation of a search tool: kinds of work the announcement lists as not affected.
  - The agents under test are Haiku 5.5, Sonnet 5.5 and Opus 5.5. The passage is about Fable 5.2 and Mythos 5.2.
  - Both sides of every comparison use the same model. A weakness of a model is the same for `grep` and for codemem.
  - This session has made ordinary mistakes in this project, for example a count taken from a summary and a time stamp ahead of the clock. They were found by recounting and by Andre's questions, and corrected here. That is the protection that works whatever the cause of an error.
- **A check we could make ourselves, and made.** In the 437 agent sessions this track saved from its own experiments, all 3,521 answers name the model that was asked for (Haiku 2,846, Sonnet 545, Opus 130), and no session's usage table names another model. That is what the API reports; it cannot show more. In the real runs the eval's proxy sees the same field, and point 7 of the entry of 15:13 UTC (keep the proxy's sums by model in `run.json`) makes it checkable for every run.

## Checked

- The probe's numbers: recounted from its 369 raw records.
- The two links: this session could not open either. Its statements about itself are what its own instructions say, restated; it has no other knowledge of how it was trained.
- Added at 16:24 UTC: the Hacker News thread and the two Anthropic pages were read through this session's fetch tool, which returns quotations in pieces. The post on X and the Reddit post were seen only as Andre's screenshots. The system card was not read. The 437 sessions were counted from their saved records.

## Left

Nothing.

## Blocked on, or needed from others

Nothing. Questions about any of this: here.

## Next

The lock and the runs, as announced at 12:40 UTC.
