# Results: 2026-10-26-py100

- Tasks: `fresh-v1-py100.jsonl` (sha256 753a062e6379), split dev, 100 tasks scored
- Systems: grep, grep-fn, grep-fn-plus, cm3-full; baseline for the paired tests: grep-fn-plus
- Index mode: update; hits per search: 50
- Code: cmeval aed438dea133, codemem aed438dea133
- Machine: macOS-26.5-arm64-arm-64bit
- Tokens: anthropic:claude-opus-5-5, request overhead of 8 tokens taken off each count; scored 2026-10-26T12:07:57+00:00
- Intervals: 95% percentile bootstrap, 10,000 resamples, seed 20261023
- Dev split: these numbers guide development. p-values here are guidance only.

## Main results

### File level: accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | 100 | 0.010 [0.000, 0.030] | 0.072 [0.028, 0.125] | 0.158 [0.090, 0.230] | 0.055 [0.030, 0.086] | 0.150 [0.080, 0.220] |
| grep-fn | 100 | 0.033 [0.005, 0.068] | 0.117 [0.061, 0.180] | 0.200 [0.131, 0.278] | 0.095 [0.055, 0.144] | 0.170 [0.100, 0.250] |
| grep-fn-plus | 100 | 0.402 [0.314, 0.491] | 0.608 [0.521, 0.693] | 0.676 [0.591, 0.758] | 0.570 [0.485, 0.655] | 0.590 [0.490, 0.680] |
| cm3-full | 100 | 0.421 [0.332, 0.509] | 0.703 [0.623, 0.779] | 0.753 [0.675, 0.826] | 0.634 [0.554, 0.712] | 0.680 [0.590, 0.770] |

### File level: tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | 100 | 0.037 [0.007, 0.077] | 0.122 [0.065, 0.188] | 8,206 [5,398, 11,341] | 0.700 [0.610, 0.790] |
| grep-fn | 100 | 0.033 [0.005, 0.068] | 0.185 [0.115, 0.260] | 4,284 [2,848, 5,953] | 0.700 [0.610, 0.790] |
| grep-fn-plus | 100 | 0.454 [0.365, 0.545] | 0.623 [0.537, 0.708] | 1,469 [1,007, 2,024] | 0.200 [0.120, 0.280] |
| cm3-full | 100 | 0.616 [0.530, 0.698] | 0.748 [0.669, 0.822] | 873 [597, 1,183] | 0.120 [0.060, 0.190] |

### Function level (IoU 0.5): accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a | n/a |
| grep-fn | 93 | 0.013 [0.000, 0.038] | 0.028 [0.003, 0.064] | 0.088 [0.039, 0.147] | 0.044 [0.017, 0.080] | 0.065 [0.022, 0.118] |
| grep-fn-plus | 93 | 0.279 [0.196, 0.366] | 0.443 [0.351, 0.535] | 0.484 [0.391, 0.578] | 0.461 [0.368, 0.553] | 0.398 [0.301, 0.495] |
| cm3-full | 93 | 0.218 [0.142, 0.303] | 0.420 [0.332, 0.513] | 0.515 [0.424, 0.606] | 0.378 [0.301, 0.459] | 0.419 [0.323, 0.516] |

### Function level (IoU 0.5): tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a |
| grep-fn | 93 | 0.013 [0.000, 0.038] | 0.083 [0.035, 0.142] | 5,810 [3,689, 8,290] | 0.796 [0.710, 0.871] |
| grep-fn-plus | 93 | 0.346 [0.258, 0.436] | 0.475 [0.383, 0.569] | 1,842 [1,131, 2,726] | 0.323 [0.226, 0.419] |
| cm3-full | 93 | 0.351 [0.263, 0.442] | 0.561 [0.469, 0.653] | 1,641 [1,193, 2,159] | 0.194 [0.118, 0.269] |

### Class level (IoU 0.5): accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a | n/a |
| grep-fn | 68 | 0.020 [0.000, 0.054] | 0.086 [0.029, 0.154] | 0.141 [0.064, 0.225] | 0.058 [0.021, 0.107] | 0.132 [0.059, 0.221] |
| grep-fn-plus | 68 | 0.244 [0.152, 0.344] | 0.404 [0.295, 0.516] | 0.521 [0.411, 0.630] | 0.390 [0.288, 0.497] | 0.441 [0.324, 0.559] |
| cm3-full | 68 | 0.308 [0.206, 0.413] | 0.519 [0.411, 0.626] | 0.644 [0.539, 0.746] | 0.480 [0.381, 0.580] | 0.529 [0.412, 0.647] |

### Class level (IoU 0.5): tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a |
| grep-fn | 68 | 0.020 [0.000, 0.054] | 0.130 [0.059, 0.211] | 5,684 [2,843, 9,058] | 0.779 [0.676, 0.868] |
| grep-fn-plus | 68 | 0.303 [0.201, 0.410] | 0.454 [0.344, 0.566] | 3,181 [2,052, 4,441] | 0.265 [0.162, 0.368] |
| cm3-full | 68 | 0.484 [0.375, 0.592] | 0.691 [0.588, 0.792] | 1,255 [820, 1,748] | 0.162 [0.074, 0.250] |

tokens_to_first is the mean over the tasks where the system found the right item, so each system's mean is over its own set of tasks. not_found_share shows how many it missed.

## Paired comparison with grep-fn-plus

Difference = system - grep-fn-plus on the same tasks. A confidence interval and a p-value can disagree: the interval is about the mean, the Wilcoxon test is about signed ranks.

### Primary metrics (Holm correction over all 2 tests, significant at 0.05)

Primary systems: cm3-full (codemem v3, fixed 2026-10-25).

| system | metric | tasks | grep-fn-plus | system | difference [95% CI] | Wilcoxon p | Holm p | significant |
|---|---|---|---|---|---|---|---|---|
| cm3-full | function mrr | 93 | 0.461 | 0.378 | -0.083 [-0.178, +0.011] | 0.119 (normal) | 0.238 | no |
| cm3-full | function tokens_to_first (lower is better) | 58 | 1,871 | 1,284 | -586 [-1,588, +270] | 0.397 (normal) | 0.397 | no |

Tokens to the first right function are paired on the tasks both systems found:

| system | found by both | system only | grep-fn-plus only | neither |
|---|---|---|---|---|
| cm3-full | 58 | 17 | 5 | 13 |

### Exploratory (raw p, no correction)

#### File level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep | recall@1 | 100 | -0.392 [-0.484, -0.299] | <0.001 |
| grep | recall@5 | 100 | -0.536 [-0.626, -0.445] | <0.001 |
| grep | recall@10 | 100 | -0.518 [-0.610, -0.425] | <0.001 |
| grep | mrr | 100 | -0.515 [-0.599, -0.430] | <0.001 |
| grep | success@10 | 100 | -0.440 [-0.540, -0.340] | <0.001 |
| grep | recall@budget1000 | 100 | -0.417 [-0.512, -0.322] | <0.001 |
| grep | recall@budget4000 | 100 | -0.501 [-0.592, -0.407] | <0.001 |
| grep | tokens_to_first (lower is better) | 30 | +7,275 [+4,448, +10,390] | <0.001 |
| grep | not_found_share (lower is better) | 100 | +0.500 [+0.400, +0.600] | <0.001 |
| grep-fn | recall@1 | 100 | -0.369 [-0.461, -0.280] | <0.001 |
| grep-fn | recall@5 | 100 | -0.491 [-0.583, -0.400] | <0.001 |
| grep-fn | recall@10 | 100 | -0.476 [-0.565, -0.385] | <0.001 |
| grep-fn | mrr | 100 | -0.475 [-0.561, -0.388] | <0.001 |
| grep-fn | success@10 | 100 | -0.420 [-0.520, -0.320] | <0.001 |
| grep-fn | recall@budget1000 | 100 | -0.422 [-0.514, -0.330] | <0.001 |
| grep-fn | recall@budget4000 | 100 | -0.438 [-0.528, -0.346] | <0.001 |
| grep-fn | tokens_to_first (lower is better) | 30 | +3,353 [+1,837, +5,086] | <0.001 |
| grep-fn | not_found_share (lower is better) | 100 | +0.500 [+0.400, +0.600] | <0.001 |
| cm3-full | recall@1 | 100 | +0.019 [-0.073, +0.109] | 0.743 |
| cm3-full | recall@5 | 100 | +0.095 [+0.017, +0.176] | 0.030 |
| cm3-full | recall@10 | 100 | +0.077 [+0.004, +0.150] | 0.040 |
| cm3-full | mrr | 100 | +0.064 [-0.021, +0.145] | 0.156 |
| cm3-full | success@10 | 100 | +0.090 [+0.010, +0.170] | 0.039 |
| cm3-full | recall@budget1000 | 100 | +0.162 [+0.073, +0.249] | 0.001 |
| cm3-full | recall@budget4000 | 100 | +0.124 [+0.048, +0.201] | 0.004 |
| cm3-full | tokens_to_first (lower is better) | 76 | -713 [-1,267, -246] | <0.001 |
| cm3-full | not_found_share (lower is better) | 100 | -0.080 [-0.160, -0.010] | 0.046 |

#### Function level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep-fn | recall@1 | 93 | -0.265 [-0.357, -0.177] | <0.001 |
| grep-fn | recall@5 | 93 | -0.416 [-0.511, -0.319] | <0.001 |
| grep-fn | recall@10 | 93 | -0.395 [-0.491, -0.303] | <0.001 |
| grep-fn | mrr | 93 | -0.417 [-0.509, -0.324] | <0.001 |
| grep-fn | success@10 | 93 | -0.333 [-0.430, -0.237] | <0.001 |
| grep-fn | recall@budget1000 | 93 | -0.333 [-0.426, -0.240] | <0.001 |
| grep-fn | recall@budget4000 | 93 | -0.392 [-0.487, -0.299] | <0.001 |
| grep-fn | tokens_to_first (lower is better) | 18 | +5,411 [+3,311, +7,854] | <0.001 |
| grep-fn | not_found_share (lower is better) | 93 | +0.473 [+0.366, +0.581] | <0.001 |
| cm3-full | recall@1 | 93 | -0.061 [-0.152, +0.032] | 0.187 |
| cm3-full | recall@5 | 93 | -0.024 [-0.106, +0.058] | 0.527 |
| cm3-full | recall@10 | 93 | +0.031 [-0.061, +0.122] | 0.526 |
| cm3-full | success@10 | 93 | +0.022 [-0.065, +0.108] | 0.637 |
| cm3-full | recall@budget1000 | 93 | +0.005 [-0.078, +0.087] | 0.868 |
| cm3-full | recall@budget4000 | 93 | +0.086 [-0.008, +0.179] | 0.073 |
| cm3-full | not_found_share (lower is better) | 93 | -0.129 [-0.226, -0.032] | 0.011 |

#### Class level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep-fn | recall@1 | 68 | -0.225 [-0.322, -0.135] | <0.001 |
| grep-fn | recall@5 | 68 | -0.318 [-0.425, -0.219] | <0.001 |
| grep-fn | recall@10 | 68 | -0.380 [-0.488, -0.277] | <0.001 |
| grep-fn | mrr | 68 | -0.332 [-0.427, -0.241] | <0.001 |
| grep-fn | success@10 | 68 | -0.309 [-0.426, -0.206] | <0.001 |
| grep-fn | recall@budget1000 | 68 | -0.284 [-0.388, -0.184] | <0.001 |
| grep-fn | recall@budget4000 | 68 | -0.324 [-0.428, -0.224] | <0.001 |
| grep-fn | tokens_to_first (lower is better) | 15 | +4,657 [+2,159, +7,573] | 0.001 |
| grep-fn | not_found_share (lower is better) | 68 | +0.515 [+0.397, +0.632] | <0.001 |
| cm3-full | recall@1 | 68 | +0.063 [-0.037, +0.169] | 0.223 |
| cm3-full | recall@5 | 68 | +0.114 [+0.018, +0.211] | 0.025 |
| cm3-full | recall@10 | 68 | +0.123 [+0.041, +0.211] | 0.015 |
| cm3-full | mrr | 68 | +0.089 [-0.008, +0.189] | 0.047 |
| cm3-full | success@10 | 68 | +0.088 [+0.000, +0.176] | 0.058 |
| cm3-full | recall@budget1000 | 68 | +0.181 [+0.074, +0.287] | 0.003 |
| cm3-full | recall@budget4000 | 68 | +0.237 [+0.144, +0.336] | <0.001 |
| cm3-full | tokens_to_first (lower is better) | 48 | -1,847 [-3,048, -815] | <0.001 |
| cm3-full | not_found_share (lower is better) | 68 | -0.103 [-0.191, -0.015] | 0.035 |

## Groups (means and task counts, no intervals)

### By identifier in query

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| false | 37 | 0.007 (34) | 0.178 (34) | 0.115 (34) |
| true | 63 | 0.065 (59) | 0.624 (59) | 0.530 (59) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| false | 37 | 0.029 (34) | 0.189 (34) | 0.208 (34) |
| true | 63 | 0.122 (59) | 0.654 (59) | 0.692 (59) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| false | 37 | 0.081 (37) | 0.128 (37) | 0.412 (37) | 0.482 (37) |
| true | 63 | 0.202 (63) | 0.243 (63) | 0.831 (63) | 0.912 (63) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| false | 37 | 5,332 (3) | 1,196 (10) | 3,253 (20) |
| true | 63 | 5,899 (16) | 1,963 (53) | 1,055 (55) |

### By repo

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| apache/airflow | 25 | 0.072 (25) | 0.571 (25) | 0.321 (25) |
| home-assistant/core | 25 | 0.002 (24) | 0.357 (24) | 0.331 (24) |
| huggingface/transformers | 25 | 0.021 (21) | 0.468 (21) | 0.545 (21) |
| pandas-dev/pandas | 25 | 0.078 (23) | 0.441 (23) | 0.335 (23) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| apache/airflow | 25 | 0.132 (25) | 0.506 (25) | 0.439 (25) |
| home-assistant/core | 25 | 0.000 (24) | 0.330 (24) | 0.462 (24) |
| huggingface/transformers | 25 | 0.071 (21) | 0.667 (21) | 0.794 (21) |
| pandas-dev/pandas | 25 | 0.149 (23) | 0.453 (23) | 0.399 (23) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| apache/airflow | 25 | 0.100 (25) | 0.191 (25) | 0.714 (25) | 0.771 (25) |
| home-assistant/core | 25 | 0.040 (25) | 0.040 (25) | 0.520 (25) | 0.690 (25) |
| huggingface/transformers | 25 | 0.280 (25) | 0.200 (25) | 0.880 (25) | 1.000 (25) |
| pandas-dev/pandas | 25 | 0.210 (25) | 0.370 (25) | 0.590 (25) | 0.550 (25) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| apache/airflow | 25 | 2,730 (5) | 1,713 (19) | 1,766 (21) |
| home-assistant/core | 25 | 8,639 (1) | 1,074 (13) | 1,856 (20) |
| huggingface/transformers | 25 | 9,906 (5) | 3,131 (18) | 1,256 (20) |
| pandas-dev/pandas | 25 | 4,821 (8) | 1,012 (13) | 1,698 (14) |

- language: all 100 tasks are 'python', so there is no table.

### By issue date

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| before 2026-07-01 | 31 | 0.021 (30) | 0.314 (30) | 0.309 (30) |
| on or after 2026-07-01 | 69 | 0.055 (63) | 0.530 (63) | 0.411 (63) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| before 2026-07-01 | 31 | 0.077 (30) | 0.295 (30) | 0.285 (30) |
| on or after 2026-07-01 | 69 | 0.094 (63) | 0.574 (63) | 0.625 (63) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| before 2026-07-01 | 31 | 0.097 (31) | 0.176 (31) | 0.431 (31) | 0.595 (31) |
| on or after 2026-07-01 | 69 | 0.185 (69) | 0.211 (69) | 0.786 (69) | 0.824 (69) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| before 2026-07-01 | 31 | 5,089 (5) | 856 (12) | 2,291 (23) |
| on or after 2026-07-01 | 69 | 6,067 (14) | 2,073 (51) | 1,354 (52) |

- gold all Python: all 100 tasks are 'true', so there is no table.

### By repo size (Python files)

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| medium (1,000 to 5,000) | 49 | 0.051 (43) | 0.459 (43) | 0.445 (43) |
| large (> 5,000) | 51 | 0.038 (50) | 0.462 (50) | 0.320 (50) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| medium (1,000 to 5,000) | 49 | 0.114 (43) | 0.545 (43) | 0.601 (43) |
| large (> 5,000) | 51 | 0.066 (50) | 0.432 (50) | 0.441 (50) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| medium (1,000 to 5,000) | 49 | 0.230 (49) | 0.270 (49) | 0.730 (49) | 0.770 (49) |
| large (> 5,000) | 51 | 0.088 (51) | 0.133 (51) | 0.625 (51) | 0.736 (51) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| medium (1,000 to 5,000) | 49 | 6,620 (12) | 2,255 (30) | 1,278 (33) |
| large (> 5,000) | 51 | 4,421 (7) | 1,465 (33) | 1,926 (42) |

### By fix size (changed code lines)

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| up to 10 | 43 | 0.027 (39) | 0.568 (39) | 0.467 (39) |
| 11 to 50 | 38 | 0.076 (36) | 0.347 (36) | 0.287 (36) |
| over 50 | 19 | 0.019 (18) | 0.456 (18) | 0.368 (18) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| up to 10 | 43 | 0.115 (39) | 0.701 (39) | 0.650 (39) |
| 11 to 50 | 38 | 0.085 (36) | 0.337 (36) | 0.453 (36) |
| over 50 | 19 | 0.037 (18) | 0.307 (18) | 0.346 (18) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| up to 10 | 43 | 0.209 (43) | 0.233 (43) | 0.767 (43) | 0.837 (43) |
| 11 to 50 | 38 | 0.178 (38) | 0.196 (38) | 0.566 (38) | 0.667 (38) |
| over 50 | 19 | 0.000 (19) | 0.136 (19) | 0.689 (19) | 0.732 (19) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| up to 10 | 43 | 7,851 (10) | 1,468 (33) | 1,426 (31) |
| 11 to 50 | 38 | 3,733 (7) | 3,034 (19) | 1,806 (28) |
| over 50 | 19 | 2,874 (2) | 902 (11) | 1,771 (16) |

### By gold files

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| 1 | 66 | 0.031 (62) | 0.523 (62) | 0.421 (62) |
| 2 or more | 34 | 0.070 (31) | 0.335 (31) | 0.292 (31) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| 1 | 66 | 0.110 (62) | 0.594 (62) | 0.619 (62) |
| 2 or more | 34 | 0.045 (31) | 0.263 (31) | 0.306 (31) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| 1 | 66 | 0.212 (66) | 0.258 (66) | 0.742 (66) | 0.803 (66) |
| 2 or more | 34 | 0.051 (34) | 0.089 (34) | 0.547 (34) | 0.655 (34) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| 1 | 66 | 6,217 (15) | 1,702 (47) | 1,505 (51) |
| 2 or more | 34 | 4,284 (4) | 2,252 (16) | 1,932 (24) |

## IoU check (function level)

| system | mrr @ IoU 0.3 | mrr @ IoU 0.5 | mrr @ IoU 0.7 | recall@10 @ IoU 0.3 | recall@10 @ IoU 0.5 | recall@10 @ IoU 0.7 |
|---|---|---|---|---|---|---|
| grep-fn | 0.044 | 0.044 | 0.044 | 0.088 | 0.088 | 0.088 |
| grep-fn-plus | 0.461 | 0.461 | 0.461 | 0.484 | 0.484 | 0.484 |
| cm3-full | 0.386 | 0.378 | 0.369 | 0.515 | 0.515 | 0.513 |

## Latency and size

| system | search ms (median) | search ms (p95) | build s (mean) | update s (median) | items re-embedded (mean) | index MB | files failed |
|---|---|---|---|---|---|---|---|
| grep | 323.4 | 674.8 | 0.0 | 0.0 | - | 0.0 | 0.0 |
| grep-fn | 1,254.7 | 2,102.1 | same as grep | same as grep | same as grep | same as grep | same as grep |
| grep-fn-plus | 2,487.3 | 5,225.4 | same as grep | same as grep | same as grep | same as grep | same as grep |
| cm3-full | 999.7 | 3,680.5 | 2,265.2 | 51.7 | 7,029.7 | 2,777.6 | 0.0 |

Index MB = 10^6 bytes. Systems with the same index settings share one index.

## Task counts

100 tasks scored. Tasks left out at each level:

| system | level | left out | reasons |
|---|---|---|---|
| grep | class | 100 | file-granularity system: 100 |
| grep | function | 100 | file-granularity system: 100 |
| grep-fn | class | 32 | no gold at this level: 32 |
| grep-fn | function | 7 | no gold at this level: 7 |
| grep-fn-plus | class | 32 | no gold at this level: 32 |
| grep-fn-plus | function | 7 | no gold at this level: 7 |
| cm3-full | class | 32 | no gold at this level: 32 |
| cm3-full | function | 7 | no gold at this level: 7 |
