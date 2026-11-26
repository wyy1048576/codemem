# Track B: codemem's search loop against a grep agent on the 3 fair pandas pilot tasks; fewer results per round is cheaper

- **Track:** B
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-26 13:07 UTC
- **Work package:** B1 (why searches miss) and the query path; an end-to-end look without tests
- **Branch, commits, pull request:** `wilson/loop-vs-grep-e2e` (`2c2a7b6`), from `main`; no pull request.
  Everything is in `eval/experiments/b1-loop/` (its README has the tables)

## Done

**The B1 loop work is now in git.** The scripts lived only on Wilson's laptop until now:
`eval/experiments/b1-loop/` holds the search loop (`e2e_loop.py`, `aug_retriever.py`, `llm.py` and its prompts),
the grep agent (`e2e_run.py`), the scorers, the retrieval-only arms (one-shot, revise, diagnose, loop, loopfull,
hop) with their result notes, and the raw outputs of the end-to-end runs (`out/e2e-pilot3/`, `out/e2e-all/`).
The LLM answer cache and run logs are not included.

**Four arms on the 3 fair pandas pilot tasks** (68195 easy, 68945 easy, 68090 hard: valid on Andrew's PC and
fair by both screen reads; 70742 left out while its screen is reopened). Sonnet 5.5 everywhere, one run each.
No build and no tests: "edited" means the final diff touches a gold function.

| Arm | Cost (USD) | Turns | Gold functions seen | Gold functions edited | Tasks with a change |
|---|---|---|---|---|---|
| grep agent (Claude Code: Read, Edit, Write, Grep, Glob) | 0.14 | 22 | 3 / 6 | 4 / 6 | 3 / 3 |
| codemem loop, 50 results per round | 0.75 | 13 | 6 / 6 | 2 / 6 | 2 / 3 |
| codemem loop, 25 results per round | 0.28 | 4 | 6 / 6 | 2 / 6 | 3 / 3 |
| codemem loop, 10 results per round | 0.27 | 4 | 5 / 6 | 3 / 6 | 3 / 3 |

Turns: Claude Code's turns (grep), search rounds (loops). Seen: at least half of a gold function's lines were
shown to the model. Edited: the final diff touches a line inside it. The loop's cap is 10 rounds or $3.

**What the logs show.**
- In every loop arm, round 1 already had the right function within its first 10 results. Results 11 to 50
  added nothing on these 3 tasks.
- Most of the 50-result loop's cost is one task (68090, $0.60 of $0.75): the fix call said "could not fix"
  on the same code that the 25-result loop fixed, and since results are never shown twice, the next 9 rounds
  saw only results 51 and later and found nothing. The 10-result loop's first fix also failed, but its round 2
  still had good results left and it applied a fix.
- Grep is cheapest because it reads only the lines it picks (68195: 3 lines of a 36-line function before the
  edit) and its one conversation re-reads earlier turns from the prompt cache; each loop round is a new
  `claude -p` call. The second point is inferred: the loop's cache does not store token counts.

## Checked

- `score_pilot3.py` run from the branch's folder gives the totals above.
- The 3 tasks are identical (base commit, issue text, gold labels) in `main`'s `eval/tasks/fresh-v1.jsonl`
  and the local copy at `7c24558` the runs used.
- One run of the 25-result loop on 68945 failed on a Windows file lock when codemem saved the index
  (`PermissionError` on the rename in `store._atomic_write`). It was run again; the rerun is the one scored.
- **Not checked:** nothing was built or tested, so no arm is known to fix any task. 3 tasks and one run each
  cannot rank the arms: the gaps between the loops come from one task each.

## Left

- 3 to 5 runs per arm and task.
- Grade the saved diffs (`out/e2e-pilot3/<task>/<arm>.diff`) with the hidden tests in the task images.
- The scripts still use absolute Windows paths in places and a local codemem at `7c24558`.

## Blocked on, or needed from others

- **Andrew:** whether the grader can take a saved diff for a task (fresh container of the task's image, apply
  the diff, put the hidden tests in, run them), so these diffs get a real verdict without running the agents
  again. Wilson's laptop has no Docker and no NVIDIA GPU.
- **Andre:** a look at the branch, as asked.

## Next

- Wilson: repeat runs, and a loop that starts with few results per round and widens only when nothing is found.
