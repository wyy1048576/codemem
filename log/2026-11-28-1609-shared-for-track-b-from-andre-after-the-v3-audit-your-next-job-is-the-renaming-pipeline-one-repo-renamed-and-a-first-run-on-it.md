# For track B, from Andre: after the v3 audit, your next job is the renaming pipeline. The aim: one repo renamed as a proof of concept, and a first run on it

- **Track:** shared: from the lead, for track B. Lifts the hold on renaming of our entry of Nov 27, 12:25 UTC (point 4)
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 16:09 UTC
- **Work package:** B8; the paper's test on unseen code (`docs/plan/paper.md` §4.6, on branch `andre/paper-plan`)
- **Branch, commits, pull request:** none yet

## Done

**1. Andre: when your audit of v2 against v3 is done and answered, put your time into the renaming pipeline.** Very likely you pick it up today, Nov 28.

- **The hold of Nov 27 is lifted.** Then renaming was "future work, not for Dec 1". Now it is the paper's main test.
- **Why.** The runs so far show no gain from the index for Haiku on public repos, and the reason looks like memory: the model already knows where things are.
  - In grep runs on pandas, the agent's first command names a fix file that the prompt does not hold in 16 of 27 runs.
  - grep opens a fix file by turn 3 in 45 of 51 runs.
  - A renamed repo is code the model cannot remember. It tells us whether an index helps there.

**2. The aim: at least one repo renamed, as a proof of concept, and a first run on it for a first result.** If it is ready by the freeze (Nov 30, 23:59 Pacific), the presentation of Dec 1 shows it. If not, it goes into the paper.

**3. What we have already.**

- **Your own plan of Nov 26** (your entry of 13:21 UTC): rename and move files in the test copy, and rerun grep; and `grep_memory.py`.
- **Andre's notes of Nov 26:**
  - Rename every identifier and path that the project defines, with one consistent mapping, in the code and in the issue: `TopNHeap` to `K7Heap`, `physical_top_n.cpp` to `op_0412.cpp`, `heap_size` to `v_cap`. Structure, comments and the bug stay.
  - Risks noted then: renaming C++ is fiddly (macros, strings, headers), and renaming blurs meaning, so a search by meaning gets worse for both setups.
- **The paper plan, §4.6** (`docs/plan/paper.md` on branch `andre/paper-plan`, not on `main` yet): the idea, what has to hold, two kinds of new names, and the order.

**4. What has to hold for each renamed task** (paper plan §4.6).

- The tests fail before the renamed fix and pass after it, as in the original.
- The request names nothing that no longer exists.
- **Memory is gone:** asked with no repo and no tools, the model no longer names the right file.

**5. Three points for your plan.**

- **The pilot repo.** pandas is where memory is strongest, so it shows the effect best, but its compiled parts make renaming harder. Say which repo you propose, and why.
- **Names that keep the meaning first** (`merge_asof` to `join_nearest`), so that a search by meaning stays a fair test. Names with no meaning are the second kind, a stress test.
- **grep alone first.** How many turns does grep need to open the fix file on the renamed repo, against the original? That number says whether an index has room to help there.

**6. What can run where.**

- **On your PC, with no Docker:** the renaming itself, the memory probe, and sessions that only locate the code (the harness of the v3 check, branch `andre/v3-check-data`, folder `v3-check/bin/`).
- **With Docker only:** the check that the tests fail and pass in the task's container, and full fix runs. Those go to the machine of job 1, or to track A's PC after its runs. Ask here when you get there.

**7. Post a short plan here before you build:** the pilot repo, what is renamed and with which tool, how each of the three points of 4 is checked, and where the first run happens.

**Unchanged:** job 1 waits for a machine; codemem stays at `463171c`; a question in this log before any assumption.

## Left

- Track B: the answer on the v3 check, then the plan for renaming.

## Blocked on, or needed from others

- **Track B:** your plan for the renaming pipeline, after the audit.

## Next

- Andre reads the plan and answers.
