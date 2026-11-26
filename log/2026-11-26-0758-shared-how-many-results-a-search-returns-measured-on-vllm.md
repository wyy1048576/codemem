# For tracks A and B, from Andre: how many results a search should return; measured on vLLM for 5 to 50

- **Track:** from Andre, as project lead. Data from track C's vLLM run (entry of 2026-11-26 07:43)
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 07:58 UTC
- **Work package:** none of track C's. It touches B (the result count and the cards) and A (an arm of the runs)
- **Branch, commits, pull request:** none

## Done

**Andre's question.** Is 10 results enough? His view: the exact rank matters less than whether
the gold files and functions are in what the agent gets, because the agent reads all of it and
chooses. The aim is to beat grep on tokens and time. So 20 or 30 results are an option. No
decision yet: he wants your views.

**What the vLLM run shows.** The 381 issue texts of the eval's vLLM tasks, the merged search
(keywords and vectors), the exact index, one commit of vLLM (`e9acf48`):

| Results | A gold file found | Every gold file found | A gold function found | Every gold function found |
|---|---|---|---|---|
| 5 | 67% | 46% | 51% | 29% |
| 10 | 74% | 54% | 60% | 36% |
| 15 | 78% | 58% | 65% | 39% |
| 20 | 81% | 60% | 68% | 42% |
| 30 | 83% | 65% | 71% | 46% |
| 50 | 86% | 72% | 74% | 49% |

Percentages are of the 375 tasks with a gold file in this index, and of the 342 with a gold
function in it.

- From 10 to 20 results: 7 to 8 points more, for twice the cards. After 20 the gain is smaller.
- A card is at most 12 lines or 800 characters of preview (`preview_lines`, `preview_chars`), so
  10 more results cost about 2,500 tokens at most.
- The median task has 1 gold file and 2 gold functions. 3 of the 381 tasks have more than 10
  gold functions: 10 results cannot hold them.
- `search_code` already takes `k`; 10 is its default.

**How to read "rank does not matter".** It matters at the cut. A better ranking gives the same
share of gold found with fewer results, so with fewer tokens. The measure that fits the aim is
the share of gold found within a number of results, or within a token budget.

## Checked

- The counts are from the kept results of the run of 07:43 (`search(..., k=50)` for each
  question; its first 10 equal the 10 of `k=10` for all 381 questions).
- These are not the eval's numbers. The eval indexes each task's own commit; this is one commit,
  after the fixes were merged. A gold file is matched by its path and a gold function by its path
  and qualified name. The questions are whole issue texts; an agent's queries are shorter.

## Left

- Nothing on track C's side.

## Blocked on, or needed from others

- **Wilson (track B):** your view on the default number of results and on the card's size. The
  same table on the eval's own indexes would be the real number, if the retrieval eval can give
  it for 10, 20 and 30.
- **Andrew (track A):** whether an arm with 20 results fits the runs. Your finding that an agent
  makes one `search_code` call and then greps is why it may matter: that one call is what the
  agent gets.
- **A fact for both:** Markdown files are not indexed (327 `.md` files on vLLM, with 719 `.json`
  and 518 `.yaml` also skipped as not code). Andre asked about them. Nothing is planned before
  the freeze.

## Next

- Tracks A and B answer here. Andre decides after that.
