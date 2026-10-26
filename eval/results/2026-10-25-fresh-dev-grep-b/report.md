# Results: 2026-10-25-fresh-dev-grep-b

- Filter: gold_all_python=true: 364 of 399 scored tasks (35 left out; see 'Tasks left out by the filter')
- Tasks: `fresh-v1.jsonl` (sha256 9c2ca4591305), split dev, 364 tasks scored
- Systems: grep, grep-fn, grep-fn-plus; baseline for the paired tests: grep-fn-plus
- Index mode: update; hits per search: 50
- Code: cmeval 3743a306394c
- Machine: macOS-26.5-arm64-arm-64bit
- Tokens: anthropic:claude-opus-5-5, request overhead of 8 tokens taken off each count; scored 2026-10-25T08:36:52+00:00
- Intervals: 95% percentile bootstrap, 10,000 resamples, seed 20261023
- Dev split: these numbers guide development. p-values here are guidance only.

## Main results

### File level: accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | 364 | 0.012 [0.003, 0.023] | 0.054 [0.033, 0.077] | 0.103 [0.074, 0.134] | 0.045 [0.032, 0.061] | 0.093 [0.066, 0.124] |
| grep-fn | 364 | 0.021 [0.008, 0.036] | 0.108 [0.079, 0.140] | 0.157 [0.123, 0.194] | 0.070 [0.052, 0.090] | 0.137 [0.104, 0.173] |
| grep-fn-plus | 364 | 0.308 [0.264, 0.355] | 0.532 [0.485, 0.580] | 0.599 [0.552, 0.646] | 0.476 [0.432, 0.521] | 0.530 [0.478, 0.582] |

### File level: tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | 364 | 0.023 [0.010, 0.038] | 0.085 [0.059, 0.114] | 9,275 [7,683, 10,954] | 0.739 [0.692, 0.783] |
| grep-fn | 364 | 0.033 [0.017, 0.051] | 0.129 [0.098, 0.162] | 5,000 [4,021, 6,050] | 0.753 [0.706, 0.797] |
| grep-fn-plus | 364 | 0.399 [0.352, 0.446] | 0.585 [0.538, 0.633] | 1,586 [1,293, 1,902] | 0.264 [0.220, 0.310] |

### Function level (IoU 0.5): accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a | n/a |
| grep-fn | 330 | 0.010 [0.001, 0.022] | 0.040 [0.021, 0.061] | 0.072 [0.047, 0.099] | 0.034 [0.022, 0.049] | 0.058 [0.033, 0.082] |
| grep-fn-plus | 330 | 0.223 [0.183, 0.266] | 0.387 [0.340, 0.435] | 0.460 [0.411, 0.509] | 0.403 [0.358, 0.450] | 0.373 [0.321, 0.424] |

### Function level (IoU 0.5): tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a |
| grep-fn | 330 | 0.017 [0.006, 0.033] | 0.064 [0.041, 0.090] | 6,697 [5,367, 8,098] | 0.818 [0.776, 0.858] |
| grep-fn-plus | 330 | 0.309 [0.263, 0.356] | 0.478 [0.429, 0.527] | 1,915 [1,509, 2,357] | 0.327 [0.276, 0.379] |

### Class level (IoU 0.5): accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a | n/a |
| grep-fn | 255 | 0.021 [0.005, 0.039] | 0.082 [0.052, 0.116] | 0.113 [0.078, 0.152] | 0.057 [0.037, 0.079] | 0.098 [0.063, 0.137] |
| grep-fn-plus | 255 | 0.211 [0.164, 0.258] | 0.404 [0.347, 0.460] | 0.472 [0.415, 0.528] | 0.360 [0.309, 0.411] | 0.400 [0.341, 0.459] |

### Class level (IoU 0.5): tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a |
| grep-fn | 255 | 0.029 [0.012, 0.050] | 0.107 [0.072, 0.144] | 6,077 [4,684, 7,553] | 0.761 [0.710, 0.812] |
| grep-fn-plus | 255 | 0.297 [0.245, 0.350] | 0.476 [0.418, 0.534] | 2,229 [1,752, 2,752] | 0.341 [0.282, 0.400] |

tokens_to_first is the mean over the tasks where the system found the right item, so each system's mean is over its own set of tasks. not_found_share shows how many it missed.

## Paired comparison with grep-fn-plus

Difference = system - grep-fn-plus on the same tasks. A confidence interval and a p-value can disagree: the interval is about the mean, the Wilcoxon test is about signed ranks.

### Primary metrics

No primary systems in this run (it has no codemem system): every comparison is exploratory.

### Exploratory (raw p, no correction)

#### File level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep | recall@1 | 364 | -0.297 [-0.344, -0.250] | <0.001 |
| grep | recall@5 | 364 | -0.478 [-0.527, -0.430] | <0.001 |
| grep | recall@10 | 364 | -0.496 [-0.544, -0.448] | <0.001 |
| grep | mrr | 364 | -0.430 [-0.475, -0.387] | <0.001 |
| grep | success@10 | 364 | -0.437 [-0.489, -0.385] | <0.001 |
| grep | recall@budget1000 | 364 | -0.376 [-0.424, -0.329] | <0.001 |
| grep | recall@budget4000 | 364 | -0.500 [-0.550, -0.451] | <0.001 |
| grep | tokens_to_first (lower is better) | 92 | +7,861 [+6,193, +9,522] | <0.001 |
| grep | not_found_share (lower is better) | 364 | +0.475 [+0.423, +0.527] | <0.001 |
| grep-fn | recall@1 | 364 | -0.287 [-0.334, -0.241] | <0.001 |
| grep-fn | recall@5 | 364 | -0.424 [-0.473, -0.377] | <0.001 |
| grep-fn | recall@10 | 364 | -0.442 [-0.491, -0.395] | <0.001 |
| grep-fn | mrr | 364 | -0.405 [-0.450, -0.362] | <0.001 |
| grep-fn | success@10 | 364 | -0.393 [-0.442, -0.343] | <0.001 |
| grep-fn | recall@budget1000 | 364 | -0.366 [-0.414, -0.320] | <0.001 |
| grep-fn | recall@budget4000 | 364 | -0.456 [-0.504, -0.408] | <0.001 |
| grep-fn | tokens_to_first (lower is better) | 87 | +3,522 [+2,610, +4,486] | <0.001 |
| grep-fn | not_found_share (lower is better) | 364 | +0.489 [+0.437, +0.541] | <0.001 |

#### Function level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep-fn | recall@1 | 330 | -0.213 [-0.257, -0.172] | <0.001 |
| grep-fn | recall@5 | 330 | -0.347 [-0.395, -0.299] | <0.001 |
| grep-fn | recall@10 | 330 | -0.388 [-0.436, -0.340] | <0.001 |
| grep-fn | mrr | 330 | -0.369 [-0.414, -0.324] | <0.001 |
| grep-fn | success@10 | 330 | -0.315 [-0.367, -0.264] | <0.001 |
| grep-fn | recall@budget1000 | 330 | -0.291 [-0.338, -0.247] | <0.001 |
| grep-fn | recall@budget4000 | 330 | -0.414 [-0.464, -0.365] | <0.001 |
| grep-fn | tokens_to_first (lower is better) | 58 | +5,330 [+3,897, +6,821] | <0.001 |
| grep-fn | not_found_share (lower is better) | 330 | +0.491 [+0.436, +0.545] | <0.001 |

#### Class level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep-fn | recall@1 | 255 | -0.190 [-0.236, -0.143] | <0.001 |
| grep-fn | recall@5 | 255 | -0.322 [-0.377, -0.267] | <0.001 |
| grep-fn | recall@10 | 255 | -0.359 [-0.414, -0.303] | <0.001 |
| grep-fn | mrr | 255 | -0.303 [-0.350, -0.256] | <0.001 |
| grep-fn | success@10 | 255 | -0.302 [-0.357, -0.247] | <0.001 |
| grep-fn | recall@budget1000 | 255 | -0.267 [-0.320, -0.217] | <0.001 |
| grep-fn | recall@budget4000 | 255 | -0.369 [-0.426, -0.312] | <0.001 |
| grep-fn | tokens_to_first (lower is better) | 57 | +4,151 [+2,913, +5,484] | <0.001 |
| grep-fn | not_found_share (lower is better) | 255 | +0.420 [+0.353, +0.482] | <0.001 |

## Groups (means and task counts, no intervals)

### By identifier in query

Function mrr:

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| false | 138 | 0.008 (119) | 0.177 (119) |
| true | 226 | 0.049 (211) | 0.531 (211) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| false | 138 | 0.018 (119) | 0.196 (119) |
| true | 226 | 0.102 (211) | 0.608 (211) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus |
|---|---|---|---|---|
| false | 138 | 0.053 (138) | 0.101 (138) | 0.364 (138) |
| true | 226 | 0.134 (226) | 0.191 (226) | 0.743 (226) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| false | 138 | 7,943 (10) | 3,161 (46) |
| true | 226 | 6,447 (50) | 1,590 (176) |

### By repo

Function mrr:

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| apache/airflow | 29 | 0.069 (29) | 0.539 (29) |
| home-assistant/core | 145 | 0.003 (127) | 0.399 (127) |
| huggingface/transformers | 25 | 0.021 (21) | 0.468 (21) |
| pandas-dev/pandas | 56 | 0.081 (51) | 0.378 (51) |
| python/cpython | 7 | 0.055 (6) | 0.450 (6) |
| ray-project/ray | 22 | 0.029 (21) | 0.359 (21) |
| vllm-project/vllm | 80 | 0.046 (75) | 0.364 (75) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| apache/airflow | 29 | 0.149 (29) | 0.482 (29) |
| home-assistant/core | 145 | 0.001 (127) | 0.427 (127) |
| huggingface/transformers | 25 | 0.071 (21) | 0.667 (21) |
| pandas-dev/pandas | 56 | 0.145 (51) | 0.489 (51) |
| python/cpython | 7 | 0.208 (6) | 0.658 (6) |
| ray-project/ray | 22 | 0.143 (21) | 0.416 (21) |
| vllm-project/vllm | 80 | 0.080 (75) | 0.424 (75) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus |
|---|---|---|---|---|
| apache/airflow | 29 | 0.086 (29) | 0.199 (29) | 0.696 (29) |
| home-assistant/core | 145 | 0.009 (145) | 0.020 (145) | 0.540 (145) |
| huggingface/transformers | 25 | 0.280 (25) | 0.200 (25) | 0.880 (25) |
| pandas-dev/pandas | 56 | 0.299 (56) | 0.344 (56) | 0.652 (56) |
| python/cpython | 7 | 0.143 (7) | 0.571 (7) | 0.857 (7) |
| ray-project/ray | 22 | 0.091 (22) | 0.333 (22) | 0.610 (22) |
| vllm-project/vllm | 80 | 0.089 (80) | 0.161 (80) | 0.521 (80) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| apache/airflow | 29 | 2,753 (6) | 2,618 (22) |
| home-assistant/core | 145 | 4,935 (2) | 1,446 (81) |
| huggingface/transformers | 25 | 9,906 (5) | 3,131 (18) |
| pandas-dev/pandas | 56 | 4,795 (17) | 1,581 (30) |
| python/cpython | 7 | 5,146 (3) | 736 (5) |
| ray-project/ray | 22 | 7,310 (5) | 1,491 (13) |
| vllm-project/vllm | 80 | 8,744 (22) | 2,333 (53) |

- language: all 364 tasks are 'python', so there is no table.

### By issue date

Function mrr:

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| before 2026-07-01 | 104 | 0.038 (98) | 0.297 (98) |
| on or after 2026-07-01 | 260 | 0.033 (232) | 0.448 (232) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| before 2026-07-01 | 104 | 0.080 (98) | 0.372 (98) |
| on or after 2026-07-01 | 260 | 0.068 (232) | 0.497 (232) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus |
|---|---|---|---|---|
| before 2026-07-01 | 104 | 0.120 (104) | 0.181 (104) | 0.528 (104) |
| on or after 2026-07-01 | 260 | 0.096 (260) | 0.147 (260) | 0.627 (260) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| before 2026-07-01 | 104 | 5,760 (19) | 2,220 (55) |
| on or after 2026-07-01 | 260 | 7,131 (41) | 1,815 (167) |

- gold all Python: all 364 tasks are 'true', so there is no table.

### By repo size (Python files)

Function mrr:

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| medium (1,000 to 5,000) | 164 | 0.054 (151) | 0.378 (151) |
| large (> 5,000) | 200 | 0.018 (179) | 0.425 (179) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| medium (1,000 to 5,000) | 164 | 0.120 (151) | 0.491 (151) |
| large (> 5,000) | 200 | 0.030 (179) | 0.433 (179) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus |
|---|---|---|---|---|
| medium (1,000 to 5,000) | 164 | 0.190 (164) | 0.270 (164) | 0.649 (164) |
| large (> 5,000) | 200 | 0.033 (200) | 0.064 (200) | 0.558 (200) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| medium (1,000 to 5,000) | 164 | 6,694 (44) | 2,154 (101) |
| large (> 5,000) | 200 | 6,705 (16) | 1,716 (121) |

### By fix size (changed code lines)

Function mrr:

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| up to 10 | 141 | 0.024 (118) | 0.454 (118) |
| 11 to 50 | 158 | 0.047 (150) | 0.353 (150) |
| over 50 | 65 | 0.022 (62) | 0.428 (62) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| up to 10 | 141 | 0.089 (118) | 0.589 (118) |
| 11 to 50 | 158 | 0.079 (150) | 0.435 (150) |
| over 50 | 65 | 0.021 (62) | 0.272 (62) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus |
|---|---|---|---|---|
| up to 10 | 141 | 0.135 (141) | 0.181 (141) | 0.669 (141) |
| 11 to 50 | 158 | 0.107 (158) | 0.173 (158) | 0.577 (158) |
| over 50 | 65 | 0.027 (65) | 0.065 (65) | 0.501 (65) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| up to 10 | 141 | 7,189 (23) | 1,757 (88) |
| 11 to 50 | 158 | 6,115 (29) | 2,192 (96) |
| over 50 | 65 | 7,390 (8) | 1,584 (38) |

### By gold files

Function mrr:

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| 1 | 257 | 0.035 (228) | 0.422 (228) |
| 2 or more | 107 | 0.034 (102) | 0.360 (102) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| 1 | 257 | 0.092 (228) | 0.546 (228) |
| 2 or more | 107 | 0.025 (102) | 0.267 (102) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus |
|---|---|---|---|---|
| 1 | 257 | 0.128 (257) | 0.195 (257) | 0.669 (257) |
| 2 or more | 107 | 0.043 (107) | 0.067 (107) | 0.430 (107) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| 1 | 257 | 6,148 (45) | 1,813 (160) |
| 2 or more | 107 | 8,343 (15) | 2,181 (62) |

## IoU check (function level)

| system | mrr @ IoU 0.3 | mrr @ IoU 0.5 | mrr @ IoU 0.7 | recall@10 @ IoU 0.3 | recall@10 @ IoU 0.5 | recall@10 @ IoU 0.7 |
|---|---|---|---|---|---|---|
| grep-fn | 0.034 | 0.034 | 0.034 | 0.072 | 0.072 | 0.072 |
| grep-fn-plus | 0.403 | 0.403 | 0.401 | 0.460 | 0.460 | 0.457 |

## Latency and size

| system | search ms (median) | search ms (p95) | build s (mean) | update s (median) | items re-embedded (mean) | index MB | files failed |
|---|---|---|---|---|---|---|---|
| grep | 190.5 | 698.6 | 0.0 | 0.0 | - | 0.0 | 0.0 |
| grep-fn | 753.2 | 1,546.7 | same as grep | same as grep | same as grep | same as grep | same as grep |
| grep-fn-plus | 1,583.1 | 4,992.9 | same as grep | same as grep | same as grep | same as grep | same as grep |

Index MB = 10^6 bytes. Systems with the same index settings share one index.
Latency and size come from summary.csv, over all 399 scored tasks: the filter does not apply to them.

## Task counts

364 tasks scored. Tasks left out at each level:

| system | level | left out | reasons |
|---|---|---|---|
| grep | class | 364 | file-granularity system: 364 |
| grep | function | 364 | file-granularity system: 364 |
| grep-fn | class | 109 | no gold at this level: 107, partial labels: 2 |
| grep-fn | function | 34 | no gold at this level: 32, partial labels: 2 |
| grep-fn-plus | class | 109 | no gold at this level: 107, partial labels: 2 |
| grep-fn-plus | function | 34 | no gold at this level: 32, partial labels: 2 |

## Tasks left out by the filter

35 scored tasks do not match gold_all_python=true. Means and counts only, no intervals.

Function mrr:

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| left out | 35 | - (0) | - (0) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| left out | 35 | - (0) | - (0) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus |
|---|---|---|---|---|
| left out | 35 | 0.257 (35) | 0.014 (35) | 0.029 (35) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus |
|---|---|---|---|
| left out | 35 | - (0) | - (0) |

