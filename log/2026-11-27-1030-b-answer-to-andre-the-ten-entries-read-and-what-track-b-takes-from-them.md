# Track B, answer to Andre's entry of 09:55 UTC: the ten entries are read; answers to the open questions; each experiment against the findings

- **Track:** B. Answers the shared entries of Nov 25 23:05, Nov 26 07:58 and 21:10, and Nov 27 09:55 UTC
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-27 10:30 UTC
- **Work package:** B1, B8, B-E3, B-E9
- **Branch, commits, pull request:** none (PR #45 unchanged by this entry). The hop runs and the hop retest are on
  Wilson's laptop (`analysis/b1-links/llm_query/out/e2e-vague8/`, `out/e2e-b7/`, arms `merged10nc`, `merged10hop`), not pushed

## Done

**Read, all ten named in the 09:55 entry:** Nov 25 23:05; Nov 26 07:58, 13:46, 19:25 (A), 21:00, 21:10, 21:50;
Nov 27 02:15 (A), 08:45, 09:10 (A). Also 09:55 itself, and track B's own 04:50 and 10:13 (the hybrid, from Wilson's
other session).

**Dates taken:** design lock today, Nov 27, 20:00 UTC (`main`, now `463171c`); runs from 21:00 UTC; results frozen
Nov 30, 23:59 Pacific. PR #45 touches only `eval/experiments/b1-loop/`, so nothing of track B blocks the lock.

**Answers to the open questions.**

1. **Code reaching the agent as code (Nov 25, 23:05).** Fixed in #54. Track B's loops do not go through MCP: they
   put the code into Sonnet's prompt as plain text, so they never had the fault. The early "agent with codemem" arm
   of PR #45 did go through MCP and got keyword-only answers (model still loading): **those runs do not count.**
2. **How many results (Nov 26, 07:58). Track B's view: 10 full cards, then results 11 to 30 by name only.** Track A's
   replay: a gold function in 49% of real first searches at 10, 63% at 20, 67% at 30. Andre's lab: the next 20 by
   name reach about as much as 30 full results, for about 1,600 characters against 8,400. Track B's own runs agree on
   the cost side: every block of extra raw code we showed Sonnet cost far more than it found (next point). Card size:
   keep 12 lines / 800 characters.
3. **The call graph (21:00, 21:10): agreed, it does not help as more code.** Track B's test last night: the chosen
   loop at 10 results a round, with and without one hop (3 closest callers or callees of each of results 1-5, 2 of
   each of 6-10, hubs of more than 50 callers left out, shown as raw code), 14 tasks, L1 and L2, one run each:

   | Level | Arm | Cost, 14 tasks | Gold functions edited (of 27) | Tasks with a gold function edited (of 14) | Runs that hit the 10-round cap without an edit |
   |---|---|---:|---:|---:|---:|
   | L1 | grep agent | $0.80 | 14 | 11 | 0 |
   | L1 | loop, 10 a round | $0.90 | 14 | 11 | 0 |
   | L1 | loop, 10 a round, with the hop | $1.57 | 15 | 11 | 1 |
   | L2 | grep agent | $1.04 | 16 | 12 | 0 |
   | L2 | loop, 10 a round | $0.99 | 15 | 10 | 0 |
   | L2 | loop, 10 a round, with the hop | $1.70 | 15 | 11 | 1 |

   About 20 neighbours a round; +70% cost for one more gold function edited, within noise. Not adopted. The offline
   retest (gold missing from the top 20, 5 neighbours of each of results 1-5 and 2 of 6-20) found 6 of 37 against 1.7
   for random neighbours, but the plain results 21-50 found 9. Your point stands: as names under a result, for
   several-function fixes, is the one place it may pay; we did not test that.
4. **Hooks:** agreed, no hooks arm.
5. **Grading (19:25, point 7). Please grade 56 diffs:** `grep.diff` and `loopk_nc.diff` (the chosen loop) for the 14
   tasks at L1 and L2, `eval/experiments/b1-loop/out/e2e-vague8/<level>/` and `out/e2e-b7/<level>/` on PR #45. The
   e2e-b45 set (35 tasks, the 10:13 entry) after that, if the PC has time.

**Each experiment against the findings.**

| Experiment | State | Rests on | Contradicts |
|---|---|---|---|
| Loop-k, the loop at 10, the hop (PR #45) | done, stopped | raw code reaching the model; the prompt-cache cost | "codemem is an enhancement, not a replacement": they replace the agent's search, so no run measures them. They stay as evidence, not as an arm |
| Hybrid and hybrid_v2 (04:50, 10:13) | the other session is diagnosing why it edits less than grep | the one arm that fits the question (09:55) | runs on Sonnet only, where a gain cannot show (09:55, 21:50). Already true: on 35 tasks it edits fewer gold functions than grep (47 / 41 against 50 / 47) at more cost |
| Renaming control | **next, not started** | Sonnet works from memory (`grep_memory.py`; 21:00, 21:50) | nothing |

**Our own runs against the faults of 09:55, point 4.**

- Model loaded: yes for the loops (search runs in one process, with a vector for every query); no for PR #45's early
  agent arm (above).
- Own commit and own copy: each task at its base commit with its own index, but the copies under `~/e2e-copies` are
  shared between Wilson's sessions. Two collisions: one run moved aside and rerun (17:00 entry); **5 pandas runs of the
  earlier 21-task sweep ran on the wrong copy** (66270 n10 and n25, 66530 n10 and n25, 70107 n25) and will be marked.
- Edited is not fixed: nothing graded yet (point 5).
- One run per cell: every track B table so far is one run per cell. A difference of one or two tasks is noise, and the
  tables will say so with pairs (lower / equal / higher).

## Checked

- The hop table: `score_vague8.py` on both sets; the two cap runs read from their summaries (10 rounds of searching,
  no edit). The other numbers are quoted from the entries named.
- Not checked: any of it with tests.

## Left

- `status/track-b.md`: the dates and the answered questions.
- `loop_vs_grep.md`: the share of gold "seen" is 39%, not 92% (Andre's audit); mark the 5 wrong-copy runs.
- The renaming control.

## Blocked on, or needed from others

- **Track A:** grade the 56 diffs of point 5.
- **Andre:** the direction for track B you announced; until then track B starts the renaming control.

## Next

- Wilson, with Claude Code: the status page, the two corrections, then the renaming control.
