# Repo stats, 2026-07-01 to 2026-10-22

## Size and languages

| Repo | Branch | Packed MB | Code MB (GitHub) | Python | Top languages |
|---|---|---:|---:|---:|---|
| home-assistant/core | dev | 921 | 135.6 | 100% | Python 100%, Shell 0%, Dockerfile 0% |
| vllm-project/vllm | main | 328 | 84.3 | 85% | Python 85%, Rust 6%, Cuda 4% |
| huggingface/transformers | main | 540 | 78.8 | 100% | Python 100%, Dockerfile 0%, Shell 0% |
| pytorch/pytorch | main | 1,685 | 175.5 | 66% | Python 66%, C++ 27%, Cuda 2% |
| apache/airflow | main | 778 | 86.5 | 87% | Python 87%, TypeScript 9%, Go 1% |
| ansible/ansible | devel | 267 | 11.4 | 86% | Python 86%, PowerShell 7%, Shell 3% |
| getsentry/sentry | master | 976 | 121.8 | 56% | Python 56%, TypeScript 42%, MDX 1% |
| odoo/odoo | 20.0 | 18,102 | 118.6 | 52% | Python 52%, JavaScript 43%, Fluent 2% |
| pandas-dev/pandas | main | 421 | 28.4 | 91% | Python 91%, Cython 6%, C 1% |
| ray-project/ray | master | 833 | 64.2 | 78% | Python 78%, C++ 16%, Java 2% |
| python/cpython | main | 898 | 68.0 | 63% | Python 63%, C 35%, M4 0% |
| saltstack/salt | master | 626 | 35.1 | 97% | Python 97%, Shell 2%, PowerShell 1% |
| kubernetes/kubernetes | master | 1,537 | 102.9 | 0% | Go 98%, Shell 2%, PowerShell 0% |
| microsoft/vscode | main | 1,622 | 223.4 | 0% | TypeScript 96%, CSS 1%, Rust 1% |
| backstage/backstage | master | 7,782 | 32.2 | 0% | TypeScript 94%, JavaScript 2%, MDX 2% |
| godotengine/godot | master | 1,902 | 73.6 | 1% | C++ 87%, C# 3%, Java 2% |

## PR funnel

Count of PRs left after each step:

1. merged into the default branch in the date range
2. author is not a bot
3. closes exactly one issue, in the same repo
4. the issue was opened before the merge
5. at most 10 changed files (all kinds)
6. issue body has 100 or more characters (hidden comments removed)

The last column is an upper estimate of the tasks. The collector drops more tasks with checks that need git.

| Repo | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---:|---:|---:|---:|---:|---:|
| home-assistant/core | 7,828 | 7,596 | 1,262 | 1,261 | 1,227 | 1,226 |
| vllm-project/vllm | 5,344 | 5,344 | 513 | 513 | 482 | 482 |
| huggingface/transformers | 1,203 | 1,166 | 183 | 183 | 151 | 151 |
| pytorch/pytorch | 6 | 0 | 0 | 0 | 0 | 0 |
| apache/airflow | 2,978 | 2,768 | 391 | 391 | 339 | 338 |
| ansible/ansible | 104 | 104 | 24 | 24 | 22 | 22 |
| getsentry/sentry | 6,849 | 6,116 | 46 | 46 | 44 | 44 |
| odoo/odoo | 0 | 0 | 0 | 0 | 0 | 0 |
| pandas-dev/pandas | 1,346 | 1,282 | 546 | 546 | 521 | 519 |
| ray-project/ray | 1,343 | 1,343 | 263 | 263 | 230 | 230 |
| python/cpython | 1,780 | 1,773 | 171 | 171 | 165 | 165 |
| saltstack/salt | 61 | 61 | 8 | 8 | 8 | 8 |
| kubernetes/kubernetes | 1,308 | 1,308 | 226 | 226 | 195 | 194 |
| microsoft/vscode | 6,593 | 6,198 | 1,357 | 1,346 | 1,112 | 1,093 |
| backstage/backstage | 881 | 547 | 79 | 79 | 73 | 73 |
| godotengine/godot | 1,360 | 1,360 | 462 | 462 | 447 | 447 |

## Code that codemem indexes (shallow clone of the default branch)

Embedding hours = chunks / 31 per second (backlog estimate for the M5).

| Repo | Commit | Checkout MB | .py files | Lines | Functions | Methods | Chunks | Embed hours |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| home-assistant/core | 3902d4166773 | 218 | 19,953 | 4,051,564 | 90,886 | 47,901 | 158,739 | 1.4 |
| vllm-project/vllm | 49d634bd6a3d | 134 | 5,526 | 2,018,935 | 36,013 | 35,678 | 76,933 | 0.7 |
| huggingface/transformers | 50e35cc0ca18 | 98 | 5,002 | 1,796,450 | 8,875 | 54,381 | 67,687 | 0.6 |
| pytorch/pytorch | 199499c48eb5 | 250 | 5,085 | 3,092,009 | 62,132 | 109,206 | 176,256 | 1.6 |
| apache/airflow | 602e150aace0 | 202 | 8,418 | 1,869,717 | 21,519 | 54,200 | 84,135 | 0.8 |
| ansible/ansible | 4761c59c9639 | 16 | 1,857 | 267,604 | 4,132 | 6,868 | 12,690 | 0.1 |
| getsentry/sentry | 86b1728a40fc | 238 | 8,374 | 1,790,589 | 16,459 | 55,380 | 79,373 | 0.7 |
| odoo/odoo | 5ce200f24cfa | 1,091 | 9,473 | 1,379,744 | 4,177 | 52,779 | 66,386 | 0.6 |
| pandas-dev/pandas | c4d25081f431 | 62 | 1,546 | 744,351 | 13,599 | 21,224 | 36,257 | 0.3 |
| ray-project/ray | 4ab3f8bcdfd4 | 372 | 4,866 | 1,412,426 | 28,306 | 32,960 | 65,840 | 0.6 |
| python/cpython | 7dd8b4736a14 | 138 | 2,360 | 1,185,329 | 15,521 | 63,159 | 80,991 | 0.7 |
| saltstack/salt | 03d8a9816865 | 59 | 3,028 | 1,023,326 | 26,843 | 9,677 | 39,289 | 0.3 |
| kubernetes/kubernetes | Python is 0% of the code (below 30%) | | | | | | | |
| microsoft/vscode | Python is 0% of the code (below 30%) | | | | | | | |
| backstage/backstage | Python is 0% of the code (below 30%) | | | | | | | |
| godotengine/godot | Python is 1% of the code (below 30%) | | | | | | | |
