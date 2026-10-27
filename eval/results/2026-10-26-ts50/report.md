# Results: 2026-10-26-ts50

- Filter: gold_all_typescript=true: 50 of 50 scored tasks (0 left out; see 'Tasks left out by the filter')
- Tasks: `fresh-ts-v1-50.jsonl` (sha256 d7be5b3b6457), split dev, 50 tasks scored
- Systems: grep, grep-fn, grep-fn-plus, cm3-full; baseline for the paired tests: grep-fn-plus
- Index mode: update; hits per search: 50
- Code: cmeval 7c245582926f, codemem 7c245582926f
- Machine: macOS-26.5-arm64-arm-64bit
- Tokens: anthropic:claude-opus-5-5, request overhead of 8 tokens taken off each count; scored 2026-10-27T00:51:47+00:00
- Intervals: 95% percentile bootstrap, 10,000 resamples, seed 20261023
- Dev split: these numbers guide development. p-values here are guidance only.

## Main results

### File level: accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | 50 | 0.007 [0.000, 0.020] | 0.095 [0.025, 0.180] | 0.106 [0.036, 0.190] | 0.062 [0.025, 0.112] | 0.080 [0.020, 0.160] |
| grep-fn | 50 | 0.040 [0.000, 0.100] | 0.156 [0.074, 0.255] | 0.196 [0.102, 0.304] | 0.105 [0.050, 0.173] | 0.160 [0.060, 0.260] |
| grep-fn-plus | 50 | 0.201 [0.103, 0.312] | 0.315 [0.197, 0.437] | 0.418 [0.293, 0.546] | 0.332 [0.219, 0.452] | 0.360 [0.240, 0.500] |
| cm3-full | 50 | 0.287 [0.171, 0.413] | 0.510 [0.376, 0.640] | 0.601 [0.473, 0.727] | 0.451 [0.338, 0.570] | 0.540 [0.400, 0.680] |

### File level: tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | 50 | 0.007 [0.000, 0.020] | 0.095 [0.025, 0.180] | 12,311 [7,961, 17,190] | 0.620 [0.480, 0.760] |
| grep-fn | 50 | 0.040 [0.000, 0.100] | 0.156 [0.073, 0.255] | 4,803 [2,162, 9,254] | 0.700 [0.560, 0.820] |
| grep-fn-plus | 50 | 0.221 [0.119, 0.336] | 0.338 [0.217, 0.464] | 3,360 [1,733, 5,628] | 0.420 [0.280, 0.560] |
| cm3-full | 50 | 0.438 [0.308, 0.567] | 0.585 [0.455, 0.709] | 1,204 [759, 1,704] | 0.240 [0.120, 0.360] |

### Function level (IoU 0.5): accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a | n/a |
| grep-fn | 45 | 0.044 [0.000, 0.111] | 0.067 [0.011, 0.144] | 0.084 [0.018, 0.167] | 0.070 [0.015, 0.142] | 0.067 [0.000, 0.156] |
| grep-fn-plus | 45 | 0.154 [0.060, 0.263] | 0.224 [0.117, 0.342] | 0.330 [0.204, 0.463] | 0.258 [0.151, 0.378] | 0.289 [0.156, 0.422] |
| cm3-full | 45 | 0.212 [0.101, 0.333] | 0.282 [0.165, 0.408] | 0.329 [0.211, 0.454] | 0.307 [0.192, 0.434] | 0.222 [0.111, 0.356] |

### Function level (IoU 0.5): tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a |
| grep-fn | 45 | 0.044 [0.000, 0.111] | 0.069 [0.011, 0.144] | 7,700 [2,521, 15,204] | 0.800 [0.667, 0.911] |
| grep-fn-plus | 45 | 0.173 [0.078, 0.284] | 0.278 [0.162, 0.404] | 5,275 [2,760, 8,215] | 0.444 [0.311, 0.578] |
| cm3-full | 45 | 0.269 [0.151, 0.396] | 0.371 [0.249, 0.499] | 1,673 [903, 2,573] | 0.400 [0.267, 0.556] |

### Class level (IoU 0.5): accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a | n/a |
| grep-fn | 41 | 0.000 [0.000, 0.000] | 0.098 [0.026, 0.188] | 0.160 [0.065, 0.273] | 0.058 [0.025, 0.095] | 0.122 [0.024, 0.244] |
| grep-fn-plus | 41 | 0.143 [0.054, 0.252] | 0.237 [0.127, 0.359] | 0.344 [0.220, 0.476] | 0.271 [0.162, 0.393] | 0.268 [0.146, 0.415] |
| cm3-full | 41 | 0.167 [0.070, 0.285] | 0.345 [0.218, 0.476] | 0.378 [0.246, 0.511] | 0.321 [0.207, 0.445] | 0.293 [0.146, 0.439] |

### Class level (IoU 0.5): tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a |
| grep-fn | 41 | 0.000 [0.000, 0.000] | 0.128 [0.043, 0.229] | 5,894 [2,688, 11,691] | 0.732 [0.585, 0.854] |
| grep-fn-plus | 41 | 0.167 [0.070, 0.281] | 0.261 [0.146, 0.388] | 4,997 [2,394, 8,468] | 0.415 [0.268, 0.561] |
| cm3-full | 41 | 0.316 [0.190, 0.451] | 0.451 [0.313, 0.589] | 1,534 [902, 2,287] | 0.317 [0.171, 0.463] |

tokens_to_first is the mean over the tasks where the system found the right item, so each system's mean is over its own set of tasks. not_found_share shows how many it missed.

## Paired comparison with grep-fn-plus

Difference = system - grep-fn-plus on the same tasks. A confidence interval and a p-value can disagree: the interval is about the mean, the Wilcoxon test is about signed ranks.

### Primary metrics (Holm correction over all 2 tests, significant at 0.05)

Primary systems: cm3-full (codemem v3, fixed 2026-10-25).

| system | metric | tasks | grep-fn-plus | system | difference [95% CI] | Wilcoxon p | Holm p | significant |
|---|---|---|---|---|---|---|---|---|
| cm3-full | function mrr | 45 | 0.258 | 0.307 | +0.049 [-0.071, +0.173] | 0.469 (normal) | 0.469 | no |
| cm3-full | function tokens_to_first (lower is better) | 21 | 4,329 | 1,745 | -2,583 [-5,713, -100] | 0.024 (exact) | 0.048 | yes |

Tokens to the first right function are paired on the tasks both systems found:

| system | found by both | system only | grep-fn-plus only | neither |
|---|---|---|---|---|
| cm3-full | 21 | 6 | 4 | 14 |

### Exploratory (raw p, no correction)

#### File level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep | recall@1 | 50 | -0.195 [-0.307, -0.095] | 0.002 |
| grep | recall@5 | 50 | -0.220 [-0.357, -0.085] | 0.005 |
| grep | recall@10 | 50 | -0.313 [-0.461, -0.165] | <0.001 |
| grep | mrr | 50 | -0.270 [-0.397, -0.146] | <0.001 |
| grep | success@10 | 50 | -0.280 [-0.440, -0.140] | <0.001 |
| grep | recall@budget1000 | 50 | -0.215 [-0.332, -0.111] | <0.001 |
| grep | recall@budget4000 | 50 | -0.243 [-0.385, -0.103] | 0.003 |
| grep | tokens_to_first (lower is better) | 13 | +8,883 [+2,303, +15,323] | 0.013 |
| grep | not_found_share (lower is better) | 50 | +0.200 [+0.020, +0.380] | 0.033 |
| grep-fn | recall@1 | 50 | -0.161 [-0.277, -0.055] | 0.008 |
| grep-fn | recall@5 | 50 | -0.159 [-0.309, -0.002] | 0.052 |
| grep-fn | recall@10 | 50 | -0.222 [-0.374, -0.068] | 0.009 |
| grep-fn | mrr | 50 | -0.226 [-0.347, -0.109] | 0.001 |
| grep-fn | success@10 | 50 | -0.200 [-0.360, -0.040] | 0.018 |
| grep-fn | recall@budget1000 | 50 | -0.181 [-0.300, -0.071] | 0.005 |
| grep-fn | recall@budget4000 | 50 | -0.181 [-0.325, -0.036] | 0.023 |
| grep-fn | tokens_to_first (lower is better) | 12 | +662 [-5,713, +7,517] | 0.577 |
| grep-fn | not_found_share (lower is better) | 50 | +0.280 [+0.120, +0.440] | 0.002 |
| cm3-full | recall@1 | 50 | +0.086 [-0.004, +0.186] | 0.092 |
| cm3-full | recall@5 | 50 | +0.195 [+0.097, +0.306] | <0.001 |
| cm3-full | recall@10 | 50 | +0.183 [+0.066, +0.309] | 0.006 |
| cm3-full | mrr | 50 | +0.120 [+0.027, +0.221] | 0.018 |
| cm3-full | success@10 | 50 | +0.180 [+0.060, +0.300] | 0.007 |
| cm3-full | recall@budget1000 | 50 | +0.216 [+0.118, +0.327] | <0.001 |
| cm3-full | recall@budget4000 | 50 | +0.247 [+0.142, +0.363] | <0.001 |
| cm3-full | tokens_to_first (lower is better) | 27 | -2,146 [-4,457, -572] | <0.001 |
| cm3-full | not_found_share (lower is better) | 50 | -0.180 [-0.320, -0.060] | 0.013 |

#### Function level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep-fn | recall@1 | 45 | -0.110 [-0.221, -0.007] | 0.050 |
| grep-fn | recall@5 | 45 | -0.157 [-0.279, -0.042] | 0.015 |
| grep-fn | recall@10 | 45 | -0.246 [-0.397, -0.102] | 0.005 |
| grep-fn | mrr | 45 | -0.188 [-0.312, -0.073] | <0.001 |
| grep-fn | success@10 | 45 | -0.222 [-0.378, -0.067] | 0.008 |
| grep-fn | recall@budget1000 | 45 | -0.128 [-0.243, -0.024] | 0.037 |
| grep-fn | recall@budget4000 | 45 | -0.209 [-0.341, -0.085] | 0.005 |
| grep-fn | tokens_to_first (lower is better) | 7 | +5,480 [+535, +10,699] | 0.156 |
| grep-fn | not_found_share (lower is better) | 45 | +0.356 [+0.200, +0.533] | <0.001 |
| cm3-full | recall@1 | 45 | +0.058 [-0.041, +0.164] | 0.301 |
| cm3-full | recall@5 | 45 | +0.058 [-0.047, +0.173] | 0.342 |
| cm3-full | recall@10 | 45 | -0.001 [-0.107, +0.107] | 0.955 |
| cm3-full | success@10 | 45 | -0.067 [-0.178, +0.044] | 0.257 |
| cm3-full | recall@budget1000 | 45 | +0.096 [+0.007, +0.201] | 0.060 |
| cm3-full | recall@budget4000 | 45 | +0.093 [+0.004, +0.190] | 0.068 |
| cm3-full | not_found_share (lower is better) | 45 | -0.044 [-0.178, +0.089] | 0.527 |

#### Class level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep-fn | recall@1 | 41 | -0.143 [-0.252, -0.054] | 0.010 |
| grep-fn | recall@5 | 41 | -0.138 [-0.280, +0.000] | 0.062 |
| grep-fn | recall@10 | 41 | -0.184 [-0.334, -0.033] | 0.027 |
| grep-fn | mrr | 41 | -0.213 [-0.330, -0.109] | 0.001 |
| grep-fn | success@10 | 41 | -0.146 [-0.293, +0.000] | 0.058 |
| grep-fn | recall@budget1000 | 41 | -0.167 [-0.281, -0.070] | 0.006 |
| grep-fn | recall@budget4000 | 41 | -0.133 [-0.280, +0.005] | 0.069 |
| grep-fn | tokens_to_first (lower is better) | 10 | +738 [-6,892, +8,599] | 0.695 |
| grep-fn | not_found_share (lower is better) | 41 | +0.317 [+0.171, +0.463] | <0.001 |
| cm3-full | recall@1 | 41 | +0.024 [-0.054, +0.112] | 0.581 |
| cm3-full | recall@5 | 41 | +0.108 [+0.028, +0.202] | 0.017 |
| cm3-full | recall@10 | 41 | +0.034 [-0.059, +0.130] | 0.562 |
| cm3-full | mrr | 41 | +0.051 [-0.040, +0.145] | 0.254 |
| cm3-full | success@10 | 41 | +0.024 [-0.049, +0.122] | 0.564 |
| cm3-full | recall@budget1000 | 41 | +0.149 [+0.057, +0.254] | 0.007 |
| cm3-full | recall@budget4000 | 41 | +0.190 [+0.084, +0.306] | 0.002 |
| cm3-full | tokens_to_first (lower is better) | 22 | -3,547 [-6,996, -760] | <0.001 |
| cm3-full | not_found_share (lower is better) | 41 | -0.098 [-0.220, +0.024] | 0.157 |

## Groups (means and task counts, no intervals)

### By identifier in query

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| false | 29 | 0.053 (26) | 0.073 (26) | 0.135 (26) |
| true | 21 | 0.093 (19) | 0.512 (19) | 0.543 (19) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| false | 29 | 0.085 (26) | 0.065 (26) | 0.108 (26) |
| true | 21 | 0.084 (19) | 0.692 (19) | 0.632 (19) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| false | 29 | 0.096 (29) | 0.156 (29) | 0.211 (29) | 0.397 (29) |
| true | 21 | 0.119 (21) | 0.252 (21) | 0.705 (21) | 0.883 (21) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| false | 29 | 10,534 (4) | 11,786 (9) | 2,923 (8) |
| true | 21 | 5,433 (5) | 1,613 (16) | 1,147 (19) |

### By repo

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| microsoft/playwright | 25 | 0.130 (21) | 0.336 (21) | 0.356 (21) |
| microsoft/vscode | 25 | 0.018 (24) | 0.190 (24) | 0.265 (24) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| microsoft/playwright | 25 | 0.124 (21) | 0.460 (21) | 0.423 (21) |
| microsoft/vscode | 25 | 0.050 (24) | 0.217 (24) | 0.247 (24) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| microsoft/playwright | 25 | 0.150 (25) | 0.221 (25) | 0.522 (25) | 0.785 (25) |
| microsoft/vscode | 25 | 0.061 (25) | 0.171 (25) | 0.315 (25) | 0.417 (25) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| microsoft/playwright | 25 | 2,798 (5) | 2,775 (14) | 1,984 (16) |
| microsoft/vscode | 25 | 13,828 (4) | 8,458 (11) | 1,220 (11) |

- language: all 50 tasks are 'typescript', so there is no table.

### By issue date

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| before 2026-07-01 | 4 | 0.000 (4) | 0.042 (4) | 0.500 (4) |
| on or after 2026-07-01 | 46 | 0.077 (41) | 0.279 (41) | 0.289 (41) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| before 2026-07-01 | 4 | 0.000 (4) | 0.250 (4) | 0.500 (4) |
| on or after 2026-07-01 | 46 | 0.093 (41) | 0.338 (41) | 0.312 (41) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| before 2026-07-01 | 4 | 0.000 (4) | 0.000 (4) | 0.500 (4) | 0.750 (4) |
| on or after 2026-07-01 | 46 | 0.115 (46) | 0.213 (46) | 0.411 (46) | 0.588 (46) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| before 2026-07-01 | 4 | - (0) | 2,176 (1) | 177 (2) |
| on or after 2026-07-01 | 46 | 7,700 (9) | 5,404 (24) | 1,793 (25) |

- gold all Python: all 50 tasks are 'false', so there is no table.

- gold all C++: all 50 tasks are 'false', so there is no table.

- gold all TypeScript: all 50 tasks are 'true', so there is no table.

### By repo size (code files of the task's language)

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| medium (1,000 to 5,000) | 25 | 0.130 (21) | 0.336 (21) | 0.356 (21) |
| large (> 5,000) | 25 | 0.018 (24) | 0.190 (24) | 0.265 (24) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| medium (1,000 to 5,000) | 25 | 0.124 (21) | 0.460 (21) | 0.423 (21) |
| large (> 5,000) | 25 | 0.050 (24) | 0.217 (24) | 0.247 (24) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| medium (1,000 to 5,000) | 25 | 0.150 (25) | 0.221 (25) | 0.522 (25) | 0.785 (25) |
| large (> 5,000) | 25 | 0.061 (25) | 0.171 (25) | 0.315 (25) | 0.417 (25) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| medium (1,000 to 5,000) | 25 | 2,798 (5) | 2,775 (14) | 1,984 (16) |
| large (> 5,000) | 25 | 13,828 (4) | 8,458 (11) | 1,220 (11) |

### By fix size (changed code lines)

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| up to 10 | 21 | 0.102 (20) | 0.233 (20) | 0.250 (20) |
| 11 to 50 | 18 | 0.066 (14) | 0.332 (14) | 0.486 (14) |
| over 50 | 11 | 0.017 (11) | 0.211 (11) | 0.184 (11) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| up to 10 | 21 | 0.100 (20) | 0.350 (20) | 0.275 (20) |
| 11 to 50 | 18 | 0.121 (14) | 0.455 (14) | 0.543 (14) |
| over 50 | 11 | 0.009 (11) | 0.135 (11) | 0.156 (11) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| up to 10 | 21 | 0.071 (21) | 0.190 (21) | 0.524 (21) | 0.690 (21) |
| 11 to 50 | 18 | 0.199 (18) | 0.273 (18) | 0.412 (18) | 0.662 (18) |
| over 50 | 11 | 0.018 (11) | 0.082 (11) | 0.227 (11) | 0.332 (11) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| up to 10 | 21 | 4,909 (3) | 4,171 (10) | 2,226 (10) |
| 11 to 50 | 18 | 4,314 (4) | 3,218 (9) | 1,379 (11) |
| over 50 | 11 | 18,659 (2) | 10,202 (6) | 1,289 (6) |

### By gold files

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| 1 | 33 | 0.094 (30) | 0.303 (30) | 0.335 (30) |
| 2 or more | 17 | 0.024 (15) | 0.169 (15) | 0.253 (15) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| 1 | 33 | 0.117 (30) | 0.400 (30) | 0.394 (30) |
| 2 or more | 17 | 0.020 (15) | 0.190 (15) | 0.198 (15) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| 1 | 33 | 0.091 (33) | 0.212 (33) | 0.485 (33) | 0.697 (33) |
| 2 or more | 17 | 0.134 (17) | 0.166 (17) | 0.289 (17) | 0.416 (17) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| 1 | 33 | 4,606 (6) | 3,001 (15) | 1,528 (17) |
| 2 or more | 17 | 13,888 (3) | 8,687 (10) | 1,920 (10) |

## IoU check (function level)

| system | mrr @ IoU 0.3 | mrr @ IoU 0.5 | mrr @ IoU 0.7 | recall@10 @ IoU 0.3 | recall@10 @ IoU 0.5 | recall@10 @ IoU 0.7 |
|---|---|---|---|---|---|---|
| grep-fn | 0.070 | 0.070 | 0.070 | 0.084 | 0.084 | 0.084 |
| grep-fn-plus | 0.258 | 0.258 | 0.258 | 0.330 | 0.330 | 0.330 |
| cm3-full | 0.307 | 0.307 | 0.307 | 0.329 | 0.329 | 0.329 |

## Latency and size

| system | search ms (median) | search ms (p95) | build s (mean) | update s (median) | items re-embedded (mean) | index MB | files failed |
|---|---|---|---|---|---|---|---|
| grep | 274.5 | 590.9 | 0.0 | 0.0 | - | 0.0 | 0.0 |
| grep-fn | 1,542.4 | 17,067.9 | same as grep | same as grep | same as grep | same as grep | same as grep |
| grep-fn-plus | 2,879.3 | 11,392.0 | same as grep | same as grep | same as grep | same as grep | same as grep |
| cm3-full | 731.3 | 9,275.1 | 109.1 | 54.5 | 12,432.6 | 4,291.4 | 0.0 |

Index MB = 10^6 bytes. Systems with the same index settings share one index.
Latency and size come from summary.csv, over all 50 scored tasks: the filter does not apply to them.

## Task counts

50 tasks scored. Tasks left out at each level:

| system | level | left out | reasons |
|---|---|---|---|
| grep | class | 50 | file-granularity system: 50 |
| grep | function | 50 | file-granularity system: 50 |
| grep-fn | class | 9 | no gold at this level: 9 |
| grep-fn | function | 5 | no gold at this level: 5 |
| grep-fn-plus | class | 9 | no gold at this level: 9 |
| grep-fn-plus | function | 5 | no gold at this level: 5 |
| cm3-full | class | 9 | no gold at this level: 9 |
| cm3-full | function | 5 | no gold at this level: 5 |

## Tasks left out by the filter

0 scored tasks do not match gold_all_typescript=true. Means and counts only, no intervals.

