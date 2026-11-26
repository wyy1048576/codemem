# Track B: the full-code judge end to end on the 3 pandas pilot tasks; PR #45 updated

- **Track:** B
- **Who:** Wilson, with Claude Code (runs by another of Wilson's sessions, put into git by this one)
- **When:** 2026-11-26 13:26 UTC
- **Work package:** B1 and the query path; loop vs grep end to end, without tests
- **Branch, commits, pull request:** `wilson/loop-vs-grep-e2e`, new commit `4eff0c7`; **PR #45**
  https://github.com/wyy1048576/codemem/pull/45 (description updated). Details in
  `eval/experiments/b1-loop/loop_vs_grep.md`, section 4b

## Done

- `e2e_loop.py` now has `LOOP_FULL=1`: the end-to-end judge sees each result's raw code from the index (header line
  plus chunk source, cut at 20,000 characters; an over-long class is shown as its skeleton) instead of a
  500-character preview. The summary now counts the one-shot query call in `cost_usd` (`oneshot_cost_usd`).
  Without `LOOP_FULL` it behaves as before (the 21-task runs of the 13:21 entry used the older file).
- `run_pilot3_full.py` ran the full-code loop at n = 5, 10, 25 on pandas 68195, 68945, 68090 (one run each).
- `score_pilot3.py` is stricter now: a gold function is seen only if at least half its lines reached Sonnet as raw
  code (previews do not count); loop costs include the one-shot call; loop-50 is left out.

| Arm (3 tasks, 6 gold functions) | Cost | Turns / rounds | Gold functions seen (raw code) | Gold functions edited | Tasks with a change |
|---|---:|---:|---:|---:|---:|
| grep agent | $0.14 | 22 | 3/6 | 4/6 | 3/3 |
| loop, previews, n=25 | $0.32 | 4 | 3/6 | 2/6 | 3/3 |
| loop, previews, n=10 | $0.31 | 4 | 4/6 | 3/6 | 3/3 |
| loop, full code, n=25 | $0.45 | 3 | 6/6 | 3/6 | 3/3 |
| loop, full code, n=10 | $0.77 | 13 | 6/6 | 2/6 | 2/3 |
| loop, full code, n=5 | $0.35 | 5 | 4/6 | 2/6 | 3/3 |

- Full code puts every gold function in front of Sonnet at n = 10 and 25, but no loop arm edits more than grep.
- full10's cost is one task: 68090's fix call said "could not fix" in round 1 (it judged `get_indexer_dict` and
  `BaseGrouper.indices` self-consistent), then 9 rounds found nothing ($0.55). Same failure as the 7 no-change
  tasks on 21 tasks (13:21 entry).

Also in the commit, without outputs: `run_vague8.py` / `score_vague8.py`, grep vs the full-code loop (n = 5, 10, 25,
50) on the 8 contamination-free, validated, fair pilot tasks with vague prompts (L1 / L2 of
`eval/tasks/vague-pilot18-v2.jsonl`). It was running when this was written (L1, first task, grep done).

## Checked

- `score_pilot3.py` was run after the last full-code run (68090, n = 25) finished; it gives the table above.
- The PR description was read back after the edit and has the new section.
- **Not checked:** nothing built or tested; one run per arm and task, 3 tasks, so no ranking of the full-code arms.

## Left

- Outputs of the vague-prompt run (`out/e2e-vague8/`), once it finishes.
- Everything in the 13:21 entry's Left list.

## Blocked on, or needed from others

- Andrew (A): grading saved diffs in the task images (as in the 13:21 entry). Andre (C): a look at PR #45.

## Next

- Wilson: add the vague-prompt results to PR #45 when the run finishes; then the loop's fix step (on "could not
  fix", get more code or show earlier results again), narrow probes per round, the renaming control.
