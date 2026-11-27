# For track B (Wilson's agent), from Andre: read the log before the next experiment. Ten entries to read, the lock is today at 20:00 UTC, and several things you are testing are already answered

- **Track:** shared: from Andre as project lead, addressed to track B
- **Who:** Andre, with Claude Code
- **When:** 2026-11-27 09:55 UTC
- **Work package:** B1, B8, B-E3, B-E9
- **Branch, commits, pull request:** none

## Done

**Why this entry.** The last entry of track B that refers to anything posted by track A or track C is from 2026-11-25, 22:06 UTC. Since then track B has posted ten entries, all on its search loop, and none takes up the 35 entries the other two tracks posted in that time. Two of them were addressed to track B and are unanswered. Your status page still gives the freeze as "Nov 28, evening". Track A's agent missed entries the same way for five hours on Nov 26 and lost that time. This entry is to prevent the same for you.

**1. The dates.** The design is locked **today, Fri Nov 27, at 20:00 UTC** (noon Pacific): codemem is `main` at that moment, now `463171c`, with no tag. The runs start at 21:00 UTC. Results are frozen Nov 30, 23:59 Pacific. Nothing of PR #45 changes codemem's own code (all of it is under `eval/experiments/b1-loop/`), so the lock does not wait for it.

**2. Read these, in this order.** All are in `log/`.

| Entry | Why it matters to you |
|---|---|
| `2026-11-25-2305-shared-for-track-b-check-that-the-code-reaches-the-agent.md` | addressed to you, unanswered. It was right: a tool result reached the model as one escaped JSON string. Fixed in #54 |
| `2026-11-26-0758-shared-how-many-results-a-search-returns-measured-on-vllm.md` | addressed to you and track A, unanswered: 10, 20 or 30 results |
| `2026-11-26-1346-shared-the-lock-date-the-goals-and-the-runs.md` | the goals as Andre set them, the lock, and which model runs which tasks |
| `2026-11-26-1925-a-the-replay-and-five-codemem-tests-fail-on-linux.md` (track A) | half of track A's first searches were answered from keywords only, because the model was still loading. And `cmeval e2e grade`, which grades your saved diffs with the tests |
| `2026-11-26-2100-shared-track-b-analysis-what-gets-codemem-used-and-what-a-search-should-return.md` | who calls codemem, and every search idea we tried with its numbers |
| `2026-11-26-2110-shared-for-track-b-the-branch-search-recall-is-yours-to-explore.md` | a branch handed to you, with what is untried |
| `2026-11-26-2150-shared-final-tables-grep-against-codemem-and-the-20-matches-in-the-first-message.md` | 186 sessions, three setups, and the noise between two runs of the same thing |
| `2026-11-27-0215-a-compact-linux-passes-duckdb-and-kubernetes-validated-the-pc-disk.md` (track A) | the runner now loads codemem before the agent starts |
| `2026-11-27-0845-shared-for-track-a-build-fewer-candidates-keep-only-the-chosen-images-and-the-commit-to-run.md` | the commit to run |
| `2026-11-27-0910-a-where-we-are-the-full-to-do-list-and-what-runs-now.md` (track A) | what the PC is doing, and when it can grade for you |

**3. What they mean for the experiments you are running.** Each line is a finding with its source. Hold your plans against them.

- **The project compares one agent with grep against the same agent with grep and codemem.** That is Claude Code with codemem as MCP tools, and it is what the runs measure. A program that replaces the agent's own search is another agent, and no run measures it. Andre's words: codemem is an enhancement, not a replacement. Your own tables agree: after ten entries of tuning, your best loop costs about what grep costs and edits the same functions (11 and 12 of 14 tasks, as grep). Your hybrid, where the model picks grep or a codemem search at each step, is the first arm that fits the question.
- **Sonnet is the model on which a gain cannot show on these repos.** It finds the code from memory: you showed it (`grep_memory.py`), and so did our sessions (Sonnet called `search_code` in 3 of 17, Opus in 0 of 6; their first move is a grep for a name they remember). With grep alone Sonnet already edits a right function in 7 of your 8 tasks. Every arm you run on Sonnet can at best tie that. Haiku calls codemem in every session (68 of 68) and answers faster with it. **So: Haiku, or code that Sonnet cannot remember. Your renaming control (your "Next", item 2) is the experiment the project needs most from track B, and it has not started.**
- **One search, 20 names in the first message, no loop,** was the only setup that saved turns for all three models: fewer turns than grep in 13 of 17 tasks (Haiku), 12 of 17 (Sonnet), 3 of 6 (Opus). It is your one-shot idea with names in place of code (21:50 entry, point 3, has the recipe).
- **Your question to track A about an arm with the hooks is answered.** Your first-search hook does what it was built for: Sonnet searched right after the refusal in 11 of 11 and 8 of 8 sessions. But that cost it a turn in 4 of 8 tasks and more tokens in 7 of 8, for the same answers. No hooks arm is asked of track A.
- **The call graph does not improve the ranking** (random neighbours do as well). As names shown under each result it adds something only for fixes that change several functions: every function on the page for 107 of 304 tasks, against 81 for a control. That, and three more parts, are on `andre/search-recall` (PR #61, open, not merged) for you to explore.

**4. Faults that cost the other tracks their runs. Check your own for each.**

- **Was the model loaded when your loop searched?** In PR #45's first comparison the arm "agent with codemem" got keyword-only answers. None of track A's runs before #59 counts, for the same reason.
- **Each task at its own base commit, with an index of that commit, and a copy no other session touches.** Your entry of 17:00 UTC reports a run that failed because another session was rebuilding the shared repo copies.
- **"Edited a gold function" is not "fixed".** Nothing of track B's is graded with the tests yet. `cmeval e2e grade` is on `main` since #56, and track A offered to run it: say which diffs.
- **One run per cell on 8 to 14 tasks cannot separate arms that differ by one task.** In our sessions an arm that barely differed from grep still showed fewer turns in 8 tasks and more in 3. Give pairs, lower, equal and higher, and say when a difference is noise.

**5. What is asked of you now.**

1. Read the ten entries.
2. **Before you start another experiment, post one entry** that lists the entries you read, and for each experiment you are running or planning says in one line which of these findings it rests on, and which it would contradict.
3. Bring `status/track-b.md` up to date: the dates, and the questions that are answered.
4. What is solid in your work stays: the cost of writing a prompt to the cache for every fresh call, the evidence that Sonnet works from memory, the hooks, the measure "seen as raw code". Build on those.

Andre will follow with direction for track B.

## Checked

- That no entry of track B since 2026-11-25 22:06 UTC names an entry of track A or track C: every entry of track B since then was searched for it. The counts in point 3 are from the entries named.
- Not checked: whether Wilson's agent read the log without saying so.

## Left

- Andre's direction for track B.

## Blocked on, or needed from others

- **Track B:** points 1 to 3 of section 5, before the next experiment.

## Next

- Andre: the direction for track B, and the announcement of the lock to all.
