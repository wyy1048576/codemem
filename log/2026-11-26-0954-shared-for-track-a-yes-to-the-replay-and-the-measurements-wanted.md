# For track A, from Andre: yes to the replay at 10, 20 and 30 results, and the list of measurements that are wanted

- **Track:** from Andre, as project lead. Answers track A's entry of 2026-11-26 09:50
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 09:54 UTC
- **Work package:** A1, A9 on track A's side; it serves decisions of tracks B and C
- **Branch, commits, pull request:** none

## Done

**Andre's answer:** yes to the replay, and yes to any measurement the open decisions need.
Agreed: no new arm in the run matrix. The list below is what is wanted, most useful first. None
of it needs an agent run.

**1. The replay you offered** (decides the number of results; it is track B's setting). The real
first `search_code` query of each `tool` run you have, asked again on that task's own index:

| What | Detail |
|---|---|
| numbers of results | 5, 10, 20, 30 and 50. The 50 says how much a reranker could gain at most |
| measures | a gold file is among the results; every gold file is; a gold function is |
| split | per repo, and per prompt level (L0, L1, L2): the queries differ by level |
| size | the characters of the rendered `search_code` output at each number of results, so that the cost of 10 more results is a number from our runs |

**2. From the runs you have, no replay needed** (weighs the cost you pointed out): the mean size
of the `search_code` result in a run, and the mean number of turns after it. With the cached
share of those tokens, if the recording proxy has it.

**3. On the PC, when it has a free quarter of an hour** (two requests that are already in the
log, in this order):

- `andre/faiss-1-16`: `uv sync && uv run pytest -q` in a worktree of its own (entry of 09:50).
  It is Linux's only run before that pull request merges.
- `andre/track-c-all`: the commands of the entry of 2026-11-25 23:43. They work again since the
  fix of 07:43. Send back the table of `scripts/check_search_indexes.py` with its time columns:
  they would show the compact index against the exact one on x86, which nobody has measured.

**4. One fact:** whether a machine of yours is an Apple-silicon Mac on macOS 14 (entry of 09:50).

## Checked

- Nothing was run for this entry.

## Left

- Track A's side: the four points. Track C needs nothing else from track A.

## Blocked on, or needed from others

- **Andrew:** the four points, 1 and 2 first. The validation and the screen stay ahead of them
  where they compete for the PC.
- **Andre:** the date on which codemem's design is locked (asked by track A at 09:50). Not
  answered here.

## Next

- Track A posts the replay's table here. Wilson and Andre then set the number of results.
