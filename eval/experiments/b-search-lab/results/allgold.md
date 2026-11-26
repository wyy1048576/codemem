# Fixes that change two or more functions: how many of them a search shows

`allgold.py` with the branch `andre/search-recall` (its own `search()`, `card_relations` 3, results 11 to 30 by name).
A task counts when its fix changes two or more functions that the index holds. The control lists, after the next 20,
as many further results as the search named related functions (about 15 to 18).

**pandas, the whole issue as the query, all tasks: 127 tasks, 610 functions to change (4.8 a task)**

| The page shows | Every function | At least two | Share of all the functions |
|---|---|---|---|
| the 10 results | 14 | 40 | 22% |
| and related names | 30 | 62 | 32% |
| and the next 20 by name | 31 | 58 | 33% |
| and both | 43 | 71 | 38% |
| control: the next 20 and as many deeper results as related names | 33 | 61 | 35% |

**pandas, the whole issue as the query, the held-out half: 69 tasks, 356 functions to change (5.2 a task)**

| The page shows | Every function | At least two | Share of all the functions |
|---|---|---|---|
| the 10 results | 5 | 18 | 20% |
| and related names | 14 | 29 | 29% |
| and the next 20 by name | 16 | 29 | 30% |
| and both | 21 | 36 | 34% |
| control: the next 20 and as many deeper results as related names | 17 | 31 | 32% |

**vLLM, the whole issue as the query, all tasks: 177 tasks, 629 functions to change (3.6 a task)**

| The page shows | Every function | At least two | Share of all the functions |
|---|---|---|---|
| the 10 results | 27 | 59 | 30% |
| and related names | 51 | 95 | 44% |
| and the next 20 by name | 44 | 84 | 41% |
| and both | 64 | 105 | 50% |
| control: the next 20 and as many deeper results as related names | 48 | 93 | 46% |

**vLLM, the whole issue as the query, the held-out half: 94 tasks, 354 functions to change (3.8 a task)**

| The page shows | Every function | At least two | Share of all the functions |
|---|---|---|---|
| the 10 results | 15 | 32 | 28% |
| and related names | 26 | 47 | 41% |
| and the next 20 by name | 23 | 41 | 38% |
| and both | 30 | 52 | 47% |
| control: the next 20 and as many deeper results as related names | 25 | 46 | 43% |

**pandas and vLLM together, all tasks: 304 tasks, 1239 functions to change (4.1 a task)**

| The page shows | Every function | At least two | Share of all the functions |
|---|---|---|---|
| the 10 results | 41 | 99 | 26% |
| and related names | 81 | 157 | 38% |
| and the next 20 by name | 75 | 142 | 37% |
| and both | 107 | 176 | 44% |
| control: the next 20 and as many deeper results as related names | 81 | 154 | 41% |

**the vague pandas requests, L1: 7 tasks, 24 functions to change (3.4 a task)**

| The page shows | Every function | At least two | Share of all the functions |
|---|---|---|---|
| the 10 results | 1 | 5 | 46% |
| and related names | 3 | 5 | 67% |
| and the next 20 by name | 4 | 5 | 75% |
| and both | 5 | 5 | 83% |
| control: the next 20 and as many deeper results as related names | 5 | 5 | 83% |

**the vague pandas requests, L2: 7 tasks, 24 functions to change (3.4 a task)**

| The page shows | Every function | At least two | Share of all the functions |
|---|---|---|---|
| the 10 results | 2 | 3 | 46% |
| and related names | 4 | 5 | 67% |
| and the next 20 by name | 2 | 5 | 62% |
| and both | 4 | 5 | 71% |
| control: the next 20 and as many deeper results as related names | 3 | 5 | 67% |
