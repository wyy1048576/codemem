# The dates, corrected, and who leads

- **Track:** shared: for everyone to read
- **Who:** Andre, with Claude Code
- **When:** 2026-11-23 02:55 UTC
- **Work package:** none: planning
- **Branch, commits, pull request:** `main`. The edits to `docs/plan/` are in Andre's working tree, for him to commit

## Done

**The dates in the plan are now the ones Andre set** (`docs/plan/overview.md` §8). Earlier entries
and status files that name Nov 28, Dec 3 or Dec 8 are out of date.

| Date | What |
|---|---|
| Wed Nov 25, evening | tracks B and C have delivered, and `codemem-final` is frozen. It holds what has passed its gate by then, and nothing else |
| Thu Nov 26 | track A starts the full runs: baseline and final on every task of every repo that is up |
| Mon Nov 30, 23:59 | everything is frozen for the presentation: results, tables, slides |
| Tue Dec 1, 14:00 | the presentation |
| Mon Dec 7 | the paper and final report, after six more days of refining |

- **There is no Dec 3 freeze.** If codemem changes after Nov 25, the changed configuration is run
  on the same tasks and the paper reports both.
- **Tracks B and C have a couple of days.** If that is not enough, a piece that has not passed its
  gate by the evening of Nov 25 is left out of the freeze. The order within each track is in the
  overview §8.1.
- **November 30 does not have to be perfect.** Six days of refining follow the presentation.

**Andre leads the project.** If track A or track B is unsure about a decision, the scope or a
priority, ask Andre or his agent. The way to ask is an entry in this log, with the question under
"Blocked on, or needed from others". Andre helps wherever the project falls behind, and keeps the
timeline.

## Checked

- Every date in the four plan files was replaced by script, and the files were checked for
  leftover mentions of the old dates.
- Nothing was run.

## Left

- The status files of tracks A and B still show the old dates. They are for their owners to
  update.

## Blocked on, or needed from others

- **Wilson:** the freeze is the evening of Nov 25, not Nov 28. The vector store interface is to be
  agreed with Andre on Nov 23.
- **Andrew:** the full runs start on Nov 26, with the configuration frozen the evening before.
  The analysis plan (the measures and the tests) is due on Nov 25, before those runs.

## Next

- Andrew: finish the test of the pipeline on the two repos, then the full runs from Nov 26.
- Wilson: B1, then B2, B8, B4 and B3, in that order.
- Andre: C1, then C2, C3 and the `api` preset of C8.
