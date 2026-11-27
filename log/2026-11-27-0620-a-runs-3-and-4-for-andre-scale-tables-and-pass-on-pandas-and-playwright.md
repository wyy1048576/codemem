# Track A, for Andre: runs 3 and 4 are done. The scale tables are below, and the compact index passes on pandas and playwright

- **Track:** A, for track C. Answers the entry of 2026-11-26 11:32 UTC, runs 3 and 4
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-27 06:20 UTC
- **Work package:** C6 and C2 on track C's side
- **Branch, commits, pull request:** none. codemem `09c4ef0` in the worktree `~/codemem-project/codemem-c` on the PC

## Done

All four runs of the entry of 11:32 are now done. Runs 1 and 2 are in our entries of 2026-11-26 19:25 and 19:40 UTC.
Runs 3 and 4 ran with nothing else on the machine (load 0.1 at the start). Only the disk guard ran beside them.
The four JSON files and the full log are in `log/2026-11-27-0620-a-data/`.

**Run 3, all cores** (`--sizes 100000,200000,500000,1000000,2000000`), 04:57 to 05:32 UTC, exit 0:

```
codemem 0.2.0 | FAISS 1.16.0 | x86_64 Linux-6.18.58.1-microsoft-standard-WSL2-x86_64-with-glibc2.39 | 16 CPUs | OMP_NUM_THREADS unset
  vectors index     memory MB  saved MB from file s from rows s  search ms filtered ms | in turns:   exact  compact FAISS own same top 10 same candidates
   100000 exact         198.2     180.0        0.45        1.44      20.58        6.31
          compact        86.4      59.6        0.31        3.99       80.0       68.83 |             28.32    69.36    135.93         1.0          0.9106
   200000 exact         399.1     360.0        0.89        2.93      39.32       11.99
          compact       154.9     119.2        0.58        7.54      76.47       76.52 |             50.54    50.38    192.44         1.0          0.9126
   500000 exact         998.8     900.0        2.74        7.97      95.27       28.41
          compact       369.9     298.0        1.39       18.24      90.79       94.83 |             94.67    92.18    301.66         1.0          0.9986
  1000000 exact        1944.6    1800.0        6.81       19.23     190.45       56.62
          compact       703.8     596.0         3.1       36.41     148.52       105.0 |            187.69   151.69     389.1         1.0             1.0
  2000000 exact        3892.3    3600.0       14.38       50.41     380.97      113.44
          compact      1403.7    1192.0        7.16       74.32     258.48      127.62 |            385.36   261.02    472.14         1.0          0.9999
```

**Run 3, one core** (`--threads 1 --sizes 100000,200000,500000,1000000`), 05:32 to 05:51 UTC, exit 0:

```
codemem 0.2.0 | FAISS 1.16.0 | x86_64 Linux-6.18.58.1-microsoft-standard-WSL2-x86_64-with-glibc2.39 | 16 CPUs | OMP_NUM_THREADS =1
  vectors index     memory MB  saved MB from file s from rows s  search ms filtered ms | in turns:   exact  compact FAISS own same top 10 same candidates
   100000 exact         198.2     180.0        0.45        1.42      18.79        5.22
          compact        85.4      59.6        0.31       15.66      22.27       21.69 |             19.66    22.51    103.31         1.0          0.9105
   200000 exact         399.2     360.0        0.88        2.71      38.52        9.73
          compact       153.6     119.2        0.58       30.82      25.84       25.36 |             37.04    25.86    159.93         1.0          0.9127
   500000 exact         998.9     900.0        2.46        7.28      91.05       26.02
          compact       368.8     298.0         1.4       77.31      59.25       36.88 |             91.97    59.28    273.34         1.0          0.9987
  1000000 exact        1944.6    1800.0         6.5       17.02     190.41       54.07
          compact       702.6     596.0        3.01      154.48     114.86       55.46 |            188.67   115.03    364.36         1.0             1.0
```

**Run 4, pandas** (the index of pandas 70742, the largest index on the PC), 05:51 to 06:09 UTC, exit 0:

```
codemem 09c4ef0 | FAISS 1.16.0 on 16 threads | x86_64 Linux-6.18.58.1-microsoft-standard-WSL2-x86_64-with-glibc2.39, 16 CPUs, 50.5 GB | 2026-11-26 21:51 -0800
pandas-dev/pandas: 352 questions of fresh-v1 (286 test, 66 dev); vectors: code 41,932, usage 6,419
questions embedded by jinaai/jina-code-embeddings-0.5b|doc|L1024|float16|cuda, the embedder the index was built with

setting                        index    split |   code: top 10 same top-50 overlap |  usage: top 10 same top-50 overlap | merged same |   code ms  usage ms search ms
faiss                          faiss    all   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      11.5       1.6     304.3
                                        dev   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      11.4       1.6     302.1
                                        test  |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      11.5       1.6     305.1
auto                           faiss    all   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      11.5       1.7     303.4
                                        dev   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      11.5       2.0     306.1
                                        test  |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      11.5       1.7     302.6
compact:bits=4,rescore=200     compact  all   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      88.8      80.7     462.5
                                        dev   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      90.5      80.2     443.7
                                        test  |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      88.4      80.8     466.9
compact:bits=2,rescore=500     compact  all   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      81.8      70.4     450.1
                                        dev   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      80.3      72.7     429.1
                                        test  |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      82.1      69.6     453.9
compact:bits=1,rescore=500     compact  all   |               1.000         0.9999 |               1.000         1.0000 |       1.000 |      43.7      35.8     384.8
                                        dev   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      46.6      35.7     370.5
                                        test  |               1.000         0.9999 |               1.000         1.0000 |       1.000 |      43.4      35.9     387.6
compact:bits=1,rescore=1000    compact  all   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      61.5      53.8     404.9
                                        dev   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      58.8      51.4     385.5
                                        test  |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      62.4      54.0     410.4

PASS: auto and compact:bits=4,rescore=200 returned what the exact index returns, for every question
```

**Run 4, playwright** (the index of playwright 43000), 06:09 to 06:17 UTC, exit 0:

```
codemem 09c4ef0 | FAISS 1.16.0 on 16 threads | x86_64 Linux-6.18.58.1-microsoft-standard-WSL2-x86_64-with-glibc2.39, 16 CPUs, 50.5 GB | 2026-11-26 22:09 -0800
microsoft/playwright: 209 questions of fresh-ts-v1 (180 test, 29 dev); vectors: code 20,731, usage 7,692
questions embedded by jinaai/jina-code-embeddings-0.5b|doc|L1024|float16|cuda, the embedder the index was built with

setting                        index    split |   code: top 10 same top-50 overlap |  usage: top 10 same top-50 overlap | merged same |   code ms  usage ms search ms
faiss                          faiss    all   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |       6.1       2.5     163.2
                                        dev   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |       6.2       2.5     191.3
                                        test  |               1.000         1.0000 |               1.000         1.0000 |       1.000 |       6.1       2.5     162.3
auto                           faiss    all   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |       6.1       2.5     164.0
                                        dev   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |       6.1       2.5     190.6
                                        test  |               1.000         1.0000 |               1.000         1.0000 |       1.000 |       6.1       2.5     160.2
compact:bits=4,rescore=200     compact  all   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      91.3      79.5     330.2
                                        dev   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      90.8      80.2     388.8
                                        test  |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      91.6      79.5     329.3
compact:bits=2,rescore=500     compact  all   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      80.3      68.2     319.4
                                        dev   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      79.1      68.4     371.0
                                        test  |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      80.6      67.7     314.1
compact:bits=1,rescore=500     compact  all   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      47.1      40.0     256.2
                                        dev   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      54.6      43.7     276.1
                                        test  |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      47.0      40.0     254.2
compact:bits=1,rescore=1000    compact  all   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      58.9      52.8     276.2
                                        dev   |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      60.2      54.5     318.1
                                        test  |               1.000         1.0000 |               1.000         1.0000 |       1.000 |      58.8      52.6     271.0

PASS: auto and compact:bits=4,rescore=200 returned what the exact index returns, for every question
```

**What we read in the numbers.** These are only facts from the tables. The decisions are yours.

- Run 3, all cores: the compact index uses 36 to 44% of the exact index's memory. Its search is slower than the exact search up to 500,000 vectors (80.0 against 20.6 ms at 100,000). It is faster from 1,000,000 vectors (148.5 against 190.5 ms; at 2,000,000, 258.5 against 381.0 ms). With a filter, the exact search is faster at every size.
- Run 3, one core: the compact search is faster from 200,000 vectors (25.8 against 38.5 ms; at 1,000,000, 114.9 against 190.4 ms). With a filter, the exact search is faster at every size here too.
- FAISS's own search over one code ("FAISS own") is slower than the exact and the compact search at every size, on both settings.
- Run 4: on both repos every setting gives the same top 10 as the exact index. Only `compact:bits=1,rescore=500` misses one result in the top 50 on pandas (overlap 0.9999). At these sizes (pandas 41,932 code vectors, playwright 20,731) the compact search is 4 to 15 times slower than the exact search on the code vectors.

## Checked

- Both scripts ended with exit 0. Both run 4 checks end with `PASS`. The JSON files load in Python.
- The two indexes were built with codemem `041124e`. The program that checked them is `09c4ef0`.
- The `.npy` files with the embedded questions stay on the PC (`~/.cmeval/andre/out/`, 2 MB). Ask if you want them.

## Left

- Nothing from the entry of 11:32. No index on the PC is larger than pandas, so the third repo of run 4 is pandas itself.

## Blocked on, or needed from others

- Nothing.

## Next

- Andre: the decisions that waited for these numbers.
- Track A: a compaction of the PC's virtual disk, then ruff in groups of about 15 tasks.
