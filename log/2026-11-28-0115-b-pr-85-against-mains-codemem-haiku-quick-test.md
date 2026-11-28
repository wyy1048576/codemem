# Track B: a quick test of PR #85 (no hooks, `k` 1 to 10, the augmented query) against `main`'s codemem, Haiku, 5 tasks at L2, two runs each. PR #85 is 19% cheaper with 17% fewer turns and the same functions edited; the difference is within run-to-run noise

- **Track:** B. Also answers Andre's question (chat, 01:04 UTC): "PR85 is without the k=20 at the start?"
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-28 01:15 UTC
- **Work package:** B8
- **Branch, commits, pull request:** PR #85, `wilson/no-hooks` at `4902671` (arm `pr85`); codemem `463171c` = `main`'s codemem (arm `main`, called `tool` in the item 1 entry of 00:40). Records: `log/2026-11-28-0115-b-data/` (`pr85-vs-main-records.zip`: stream, diff, summary, status and MCP config of every run; `score-pr85-vs-main.json`; `run_item1.py`, `score_item1.py`)

## Done

**Andre's question: yes, PR #85 has no k=20 block at the start.** No arm in this entry or in the entry of 00:40 puts the 20 results of a starting search in the first message; the agent gets codemem only as the MCP tool. So `main` here is `main`'s codemem as a tool, not the runs' `codemem` setup of `docs/plan/runs.md` §1 (tool plus the block). That setup, and PR #85 with the block, are not measured.

**Setup:** as item 1 (entry of 00:40): Claude Code 2.1.314, `claude-haiku-5-5`, built-in Read, Edit, Write, Grep, Glob, no shell, no hooks, prompt cache on, own repo copy and own index per run (codemem `463171c`'s index, brought up to each task's commit), `alwaysLoad`. The two arms differ only in the server's code: `463171c` or PR #85. Tasks: 5 of the 14 at L2 (pandas 70742, 68090, 67897; playwright 43174, 42792), chosen because `main` called `search_code` on them in item 1. Run 1 of `main` is item 1's `tool` run; the other three runs per task were made now. Two of `main`'s second runs (67897, 42792) did not finish in the time given and are left out with their pairs; playwright 41988 has no finished PR #85 run and is left out.

**Totals over the 8 pairs where both arms finished.** Cost in USD as Claude Code reports it; seconds without the first search's wait for the model; gold functions edited: the final diff touches a line inside a function the real fix changed.

| Arm | Cost | Turns | Seconds | Gold functions edited |
|---|---:|---:|---:|---:|
| `main` (463171c) | 0.121 | 141 | 631 | 7 of 17 |
| PR #85 | 0.097 | 117 | 536 | 7 of 17 |

**Per task.** Cost, turns, gold functions edited; run 1, then run 2.

| Task, L2 | `main` | PR #85 |
|---|---|---|
| pandas 70742 | $0.006 9 1/1; $0.013 20 0/1 | $0.008 9 0/1; $0.015 18 1/1 |
| pandas 68090 | $0.044 37 0/3; $0.021 16 1/3 | $0.021 22 1/3; $0.017 20 0/3 |
| pandas 67897 | $0.010 17 3/4; did not finish | $0.019 23 4/4; $0.014 21 4/4 |
| playwright 43174 | $0.012 17 0/2; $0.008 12 1/2 | $0.006 7 0/2; $0.007 7 0/2 |
| playwright 42792 | $0.007 13 1/1; did not finish | $0.006 11 1/1; $0.012 17 1/1 |

**What it says.**
- **No loss from PR #85, maybe a small saving:** 19% less cost and 17% fewer turns over 8 pairs, the same functions edited.
- **Run-to-run noise is as large as the gap.** `main`'s two runs of pandas 68090 cost $0.044 and $0.021; that one run is most of the difference. Both arms doubled their cost on 70742 between runs, and the functions edited flip between runs. The one steady difference: playwright 43174, 7 turns in both PR #85 runs against 17 and 12.
- **Haiku fills in PR #85's new inputs.** In the 6 runs of the first pass (8 searches) it gave `intent`, `symptom` and `anchors` almost every time, `locations` once, and sometimes a `k` below 10. The anchors were real names of the code (`fast_xs`, `ArrowIntervalType`, `innerAccumulatedElementText`).

**Checks of 13:15:** every codemem run connected, its index updated with exit 0; no search result held a loading note; every result was code; only Haiku answered. One run per arm and task is not enough for a verdict: this is a quick test, not a result for the paper.

## Checked

`score_item1.py` on the runs; the per-task numbers from `score-pr85-vs-main.json`.

## Left

- PR #85 on all 14 tasks at L1 and L2, two runs each, against `main` (about 1 hour here).
- Both arms with the k=20 block at the start (the runs' setup), if Andre wants the design judged where it will run.

## Blocked on, or needed from others

**Andre:** whether the next test should add the block.

## Next

As Andre says.
