# No result paid for twice in one session (`search_dedup`): E0 and E1

The work package of the work log entry of 2026-11-27 12:25 UTC (track B, item 2). The code is
`src/codemem/dedup.py` and the switch `search_dedup` (`off` by default; `shorten`, `refill`).

## Input

Andre's session records, `log/2026-11-27-1225-shared-data/sessions-with-codemem-searches.jsonl` on the
`worklog` branch (commit `c09edb7`): 210 Claude Code 2.1.285 sessions on 17 pandas tasks, one line each.
E0 and E1 call no model.

```
python e0_e1.py <path to sessions-with-codemem-searches.jsonl>     # output: e0_e1.out.txt
```

## E0. The counts of the 12:25 table, reproduced

Haiku, arms `tool`, `tool-v0`, `tool-q` (`tool+`, the 20 names in the first message, left out as in the table).

| What was counted | 12:25 table | This script |
|---|---:|---:|
| Sessions | 102 | 102 |
| Searches per session: one / two / three / four or five | 59 / 27 / 9 / 7 | 59 / 27 / 9 / 7 |
| Sessions with more than one search | 43 | 43 |
| Results returned by those later searches | 536 | 536 |
| Of them, already sent earlier in the same session | 156 (29%) | 156 (29%) |
| Sessions where a later search had a function of the fix that the first search had not (`gold_function_among_cards`) | 13 of 43 | 13 of 43 |

Sonnet: 34 sessions with the tool, none searched twice.

## E1. `shorten`, replayed

Each session's searches in order. A result already sent in the session becomes its head line plus one
mark line, about 110 characters; a card's size is its call's `result_chars` divided by its cards. The
text a result adds is read again from the cache on every later turn of the session. Tokens = characters / 4.

| Forget a result after this many tool calls | Search text, all 102 sessions | Text saved | Sessions that save | New-text tokens saved | Cache-read tokens saved |
|---|---:|---:|---:|---:|---:|
| never | 777,507 chars | 62,436 chars (8%) | 39 | 15,609 | 56,028 |
| 10 (the default) | 777,507 chars | 62,436 chars (8%) | 39 | 15,609 | 56,028 |
| 3 | 777,507 chars | 52,379 chars (7%) | 36 | 13,095 | 47,089 |

Against the whole bill of the 43 sessions that searched more than once (469,357 new-text tokens, 3,945,485
cache-read tokens): shorten saves about 3% of their new text and 1.4% of their cache reads. Over all 102
sessions: about 1.7% and 0.8%.

What E1 cannot show: what `refill` brings. The records hold the 10 cards each search returned, not the
ranking below them, so the results a refill would add are not known. That needs E3 (sessions in Claude Code).

## Not done

- E3 (sessions, `off` / `shorten` / `refill`, Haiku then Sonnet, two runs per cell), E4 (scripted
  stale-view sessions), E5 (compaction and subagents), E6 (graded fix runs).
