# Results: 2026-10-26-cpp68

- Filter: gold_all_cpp=true: 68 of 68 scored tasks (0 left out; see 'Tasks left out by the filter')
- Tasks: `fresh-cpp-v1-68.jsonl` (sha256 d8bcfbebf971), split dev, 68 tasks scored
- Systems: grep, grep-fn, grep-fn-plus, cm3-full; baseline for the paired tests: grep-fn-plus
- Index mode: update; hits per search: 50
- Code: cmeval 7c245582926f, codemem 7c245582926f
- Machine: macOS-26.5-arm64-arm-64bit
- Tokens: anthropic:claude-opus-5-5, request overhead of 8 tokens taken off each count; scored 2026-10-26T21:31:04+00:00
- Intervals: 95% percentile bootstrap, 10,000 resamples, seed 20261023
- Dev split: these numbers guide development. p-values here are guidance only.

## Main results

### File level: accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | 68 | 0.000 [0.000, 0.000] | 0.034 [0.000, 0.078] | 0.056 [0.015, 0.106] | 0.031 [0.018, 0.047] | 0.029 [0.000, 0.074] |
| grep-fn | 68 | 0.000 [0.000, 0.000] | 0.108 [0.044, 0.181] | 0.155 [0.079, 0.238] | 0.053 [0.032, 0.077] | 0.118 [0.044, 0.206] |
| grep-fn-plus | 68 | 0.176 [0.097, 0.265] | 0.331 [0.227, 0.439] | 0.382 [0.275, 0.493] | 0.304 [0.212, 0.403] | 0.353 [0.250, 0.471] |
| cm3-full | 68 | 0.343 [0.242, 0.451] | 0.526 [0.419, 0.635] | 0.605 [0.496, 0.709] | 0.523 [0.420, 0.629] | 0.529 [0.412, 0.647] |

### File level: tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | 68 | 0.000 [0.000, 0.000] | 0.048 [0.010, 0.097] | 13,295 [10,340, 16,289] | 0.574 [0.456, 0.691] |
| grep-fn | 68 | 0.000 [0.000, 0.000] | 0.044 [0.007, 0.096] | 10,415 [7,089, 14,327] | 0.647 [0.529, 0.765] |
| grep-fn-plus | 68 | 0.191 [0.107, 0.282] | 0.331 [0.227, 0.439] | 3,462 [2,310, 4,714] | 0.412 [0.294, 0.529] |
| cm3-full | 68 | 0.478 [0.372, 0.584] | 0.598 [0.494, 0.700] | 2,949 [1,142, 5,204] | 0.206 [0.118, 0.309] |

### Function level (IoU 0.5): accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a | n/a |
| grep-fn | 56 | 0.000 [0.000, 0.000] | 0.018 [0.000, 0.054] | 0.019 [0.000, 0.057] | 0.013 [0.004, 0.025] | 0.018 [0.000, 0.054] |
| grep-fn-plus | 56 | 0.081 [0.021, 0.156] | 0.159 [0.076, 0.254] | 0.189 [0.101, 0.289] | 0.152 [0.077, 0.241] | 0.143 [0.054, 0.232] |
| cm3-full | 56 | 0.138 [0.062, 0.227] | 0.272 [0.171, 0.382] | 0.302 [0.201, 0.414] | 0.276 [0.180, 0.382] | 0.214 [0.107, 0.321] |

### Function level (IoU 0.5): tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a |
| grep-fn | 56 | 0.000 [0.000, 0.000] | 0.018 [0.000, 0.054] | 14,082 [6,375, 23,305] | 0.857 [0.768, 0.946] |
| grep-fn-plus | 56 | 0.111 [0.039, 0.196] | 0.207 [0.115, 0.311] | 3,897 [2,340, 5,593] | 0.625 [0.500, 0.750] |
| cm3-full | 56 | 0.254 [0.154, 0.364] | 0.387 [0.277, 0.502] | 3,233 [1,697, 5,196] | 0.321 [0.196, 0.446] |

### Class level (IoU 0.5): accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a | n/a |
| grep-fn | 22 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.001 [0.000, 0.004] | 0.000 [0.000, 0.000] |
| grep-fn-plus | 22 | 0.045 [0.000, 0.136] | 0.057 [0.000, 0.159] | 0.080 [0.000, 0.193] | 0.067 [0.009, 0.167] | 0.045 [0.000, 0.136] |
| cm3-full | 22 | 0.129 [0.015, 0.273] | 0.186 [0.068, 0.326] | 0.254 [0.106, 0.421] | 0.253 [0.106, 0.421] | 0.182 [0.045, 0.364] |

### Class level (IoU 0.5): tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a |
| grep-fn | 22 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 22,588 | 0.955 [0.864, 1.000] |
| grep-fn-plus | 22 | 0.045 [0.000, 0.136] | 0.080 [0.000, 0.193] | 4,596 [2,344, 6,952] | 0.727 [0.545, 0.909] |
| cm3-full | 22 | 0.163 [0.045, 0.303] | 0.322 [0.155, 0.511] | 2,692 [909, 4,871] | 0.455 [0.273, 0.682] |

tokens_to_first is the mean over the tasks where the system found the right item, so each system's mean is over its own set of tasks. not_found_share shows how many it missed.

## Paired comparison with grep-fn-plus

Difference = system - grep-fn-plus on the same tasks. A confidence interval and a p-value can disagree: the interval is about the mean, the Wilcoxon test is about signed ranks.

### Primary metrics (Holm correction over all 2 tests, significant at 0.05)

Primary systems: cm3-full (codemem v3, fixed 2026-10-25).

| system | metric | tasks | grep-fn-plus | system | difference [95% CI] | Wilcoxon p | Holm p | significant |
|---|---|---|---|---|---|---|---|---|
| cm3-full | function mrr | 56 | 0.152 | 0.276 | +0.124 [+0.037, +0.225] | 0.014 (normal) | 0.014 | yes |
| cm3-full | function tokens_to_first (lower is better) | 20 | 3,955 | 1,813 | -2,142 [-4,209, -83] | 0.005 (exact) | 0.010 | yes |

Tokens to the first right function are paired on the tasks both systems found:

| system | found by both | system only | grep-fn-plus only | neither |
|---|---|---|---|---|
| cm3-full | 20 | 18 | 1 | 17 |

### Exploratory (raw p, no correction)

#### File level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep | recall@1 | 68 | -0.176 [-0.265, -0.097] | <0.001 |
| grep | recall@5 | 68 | -0.296 [-0.407, -0.185] | <0.001 |
| grep | recall@10 | 68 | -0.326 [-0.444, -0.209] | <0.001 |
| grep | mrr | 68 | -0.273 [-0.367, -0.184] | <0.001 |
| grep | success@10 | 68 | -0.324 [-0.441, -0.206] | <0.001 |
| grep | recall@budget1000 | 68 | -0.191 [-0.282, -0.107] | <0.001 |
| grep | recall@budget4000 | 68 | -0.282 [-0.396, -0.172] | <0.001 |
| grep | tokens_to_first (lower is better) | 21 | +9,061 [+5,994, +12,303] | <0.001 |
| grep | not_found_share (lower is better) | 68 | +0.162 [+0.015, +0.309] | 0.034 |
| grep-fn | recall@1 | 68 | -0.176 [-0.265, -0.097] | <0.001 |
| grep-fn | recall@5 | 68 | -0.223 [-0.337, -0.112] | <0.001 |
| grep-fn | recall@10 | 68 | -0.227 [-0.345, -0.112] | <0.001 |
| grep-fn | mrr | 68 | -0.251 [-0.347, -0.161] | <0.001 |
| grep-fn | success@10 | 68 | -0.235 [-0.353, -0.118] | <0.001 |
| grep-fn | recall@budget1000 | 68 | -0.191 [-0.282, -0.107] | <0.001 |
| grep-fn | recall@budget4000 | 68 | -0.287 [-0.406, -0.168] | <0.001 |
| grep-fn | tokens_to_first (lower is better) | 19 | +6,357 [+2,845, +10,852] | 0.002 |
| grep-fn | not_found_share (lower is better) | 68 | +0.235 [+0.103, +0.368] | 0.002 |
| cm3-full | recall@1 | 68 | +0.167 [+0.074, +0.268] | 0.002 |
| cm3-full | recall@5 | 68 | +0.195 [+0.087, +0.306] | 0.002 |
| cm3-full | recall@10 | 68 | +0.223 [+0.104, +0.340] | 0.002 |
| cm3-full | mrr | 68 | +0.219 [+0.115, +0.326] | <0.001 |
| cm3-full | success@10 | 68 | +0.176 [+0.059, +0.294] | 0.007 |
| cm3-full | recall@budget1000 | 68 | +0.287 [+0.195, +0.385] | <0.001 |
| cm3-full | recall@budget4000 | 68 | +0.267 [+0.150, +0.385] | <0.001 |
| cm3-full | tokens_to_first (lower is better) | 38 | -739 [-3,118, +2,217] | <0.001 |
| cm3-full | not_found_share (lower is better) | 68 | -0.206 [-0.324, -0.103] | <0.001 |

#### Function level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep-fn | recall@1 | 56 | -0.081 [-0.156, -0.021] | 0.024 |
| grep-fn | recall@5 | 56 | -0.141 [-0.243, -0.046] | 0.013 |
| grep-fn | recall@10 | 56 | -0.170 [-0.277, -0.071] | 0.005 |
| grep-fn | mrr | 56 | -0.139 [-0.226, -0.065] | <0.001 |
| grep-fn | success@10 | 56 | -0.125 [-0.232, -0.036] | 0.020 |
| grep-fn | recall@budget1000 | 56 | -0.111 [-0.196, -0.039] | 0.010 |
| grep-fn | recall@budget4000 | 56 | -0.189 [-0.301, -0.086] | 0.004 |
| grep-fn | tokens_to_first (lower is better) | 5 | +10,300 [+6,439, +14,705] | 0.062 |
| grep-fn | not_found_share (lower is better) | 56 | +0.232 [+0.089, +0.375] | 0.003 |
| cm3-full | recall@1 | 56 | +0.057 [-0.013, +0.135] | 0.120 |
| cm3-full | recall@5 | 56 | +0.113 [+0.042, +0.199] | 0.009 |
| cm3-full | recall@10 | 56 | +0.112 [+0.028, +0.206] | 0.022 |
| cm3-full | success@10 | 56 | +0.071 [+0.000, +0.161] | 0.102 |
| cm3-full | recall@budget1000 | 56 | +0.143 [+0.065, +0.234] | 0.002 |
| cm3-full | recall@budget4000 | 56 | +0.179 [+0.069, +0.291] | 0.005 |
| cm3-full | not_found_share (lower is better) | 56 | -0.304 [-0.429, -0.179] | <0.001 |

#### Class level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep-fn | recall@1 | 22 | -0.045 [-0.136, +0.000] | 0.317 |
| grep-fn | recall@5 | 22 | -0.057 [-0.159, +0.000] | 0.180 |
| grep-fn | recall@10 | 22 | -0.080 [-0.193, +0.000] | 0.109 |
| grep-fn | mrr | 22 | -0.066 [-0.165, -0.008] | 0.028 |
| grep-fn | success@10 | 22 | -0.045 [-0.136, +0.000] | 0.317 |
| grep-fn | recall@budget1000 | 22 | -0.045 [-0.136, +0.000] | 0.317 |
| grep-fn | recall@budget4000 | 22 | -0.080 [-0.193, +0.000] | 0.109 |
| grep-fn | tokens_to_first (lower is better) | 1 | +20,389 | 1.000 |
| grep-fn | not_found_share (lower is better) | 22 | +0.227 [+0.090, +0.409] | 0.025 |
| cm3-full | recall@1 | 22 | +0.083 [+0.000, +0.197] | 0.109 |
| cm3-full | recall@5 | 22 | +0.129 [+0.038, +0.250] | 0.039 |
| cm3-full | recall@10 | 22 | +0.174 [+0.045, +0.333] | 0.039 |
| cm3-full | mrr | 22 | +0.186 [+0.063, +0.334] | 0.003 |
| cm3-full | success@10 | 22 | +0.136 [+0.000, +0.273] | 0.083 |
| cm3-full | recall@budget1000 | 22 | +0.117 [+0.027, +0.231] | 0.042 |
| cm3-full | recall@budget4000 | 22 | +0.242 [+0.091, +0.417] | 0.016 |
| cm3-full | tokens_to_first (lower is better) | 6 | -3,956 [-6,118, -1,986] | 0.031 |
| cm3-full | not_found_share (lower is better) | 22 | -0.273 [-0.455, -0.091] | 0.014 |

## Groups (means and task counts, no intervals)

### By identifier in query

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| false | 48 | 0.012 (45) | 0.078 (45) | 0.217 (45) |
| true | 20 | 0.014 (11) | 0.454 (11) | 0.520 (11) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| false | 48 | 0.024 (45) | 0.115 (45) | 0.225 (45) |
| true | 20 | 0.000 (11) | 0.494 (11) | 0.615 (11) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| false | 48 | 0.010 (48) | 0.164 (48) | 0.344 (48) | 0.558 (48) |
| true | 20 | 0.164 (20) | 0.135 (20) | 0.474 (20) | 0.718 (20) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| false | 48 | 10,802 (5) | 5,238 (13) | 3,870 (28) |
| true | 20 | 19,549 (3) | 1,718 (8) | 1,450 (10) |

### By repo

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| duckdb/duckdb | 25 | 0.014 (24) | 0.196 (24) | 0.254 (24) |
| ggml-org/llama.cpp | 18 | 0.012 (13) | 0.207 (13) | 0.297 (13) |
| godotengine/godot | 25 | 0.011 (19) | 0.059 (19) | 0.291 (19) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| duckdb/duckdb | 25 | 0.042 (24) | 0.167 (24) | 0.260 (24) |
| ggml-org/llama.cpp | 18 | 0.000 (13) | 0.315 (13) | 0.418 (13) |
| godotengine/godot | 25 | 0.005 (19) | 0.132 (19) | 0.274 (19) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| duckdb/duckdb | 25 | 0.013 (25) | 0.060 (25) | 0.301 (25) | 0.576 (25) |
| ggml-org/llama.cpp | 18 | 0.164 (18) | 0.094 (18) | 0.497 (18) | 0.592 (18) |
| godotengine/godot | 25 | 0.020 (25) | 0.295 (25) | 0.380 (25) | 0.643 (25) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| duckdb/duckdb | 25 | 3,728 (2) | 3,618 (8) | 1,954 (15) |
| ggml-org/llama.cpp | 18 | 19,549 (3) | 2,289 (6) | 4,202 (8) |
| godotengine/godot | 25 | 15,518 (3) | 5,594 (7) | 3,997 (15) |

### By language

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| c | 7 | 0.000 (2) | 0.031 (2) | 0.292 (2) |
| cpp | 61 | 0.013 (54) | 0.156 (54) | 0.276 (54) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| c | 7 | 0.000 (2) | 0.000 (2) | 0.167 (2) |
| cpp | 61 | 0.020 (54) | 0.196 (54) | 0.307 (54) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| c | 7 | 0.190 (7) | 0.000 (7) | 0.048 (7) | 0.440 (7) |
| cpp | 61 | 0.040 (61) | 0.173 (61) | 0.420 (61) | 0.623 (61) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| c | 7 | - (0) | 5,944 (1) | 1,426 (2) |
| cpp | 61 | 14,082 (8) | 3,794 (20) | 3,334 (36) |

### By issue date

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| before 2026-07-01 | 6 | 0.018 (5) | 0.223 (5) | 0.614 (5) |
| on or after 2026-07-01 | 62 | 0.012 (51) | 0.145 (51) | 0.243 (51) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| before 2026-07-01 | 6 | 0.000 (5) | 0.133 (5) | 0.433 (5) |
| on or after 2026-07-01 | 62 | 0.021 (51) | 0.195 (51) | 0.289 (51) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| before 2026-07-01 | 6 | 0.250 (6) | 0.500 (6) | 0.583 (6) | 0.833 (6) |
| on or after 2026-07-01 | 62 | 0.037 (62) | 0.122 (62) | 0.363 (62) | 0.583 (62) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| before 2026-07-01 | 6 | 5,185 (1) | 6,318 (3) | 1,894 (4) |
| on or after 2026-07-01 | 62 | 15,353 (7) | 3,493 (18) | 3,391 (34) |

- gold all Python: all 68 tasks are 'false', so there is no table.

- gold all C++: all 68 tasks are 'true', so there is no table.

- gold all TypeScript: all 68 tasks are 'false', so there is no table.

### By repo size (code files of the task's language)

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| medium (1,000 to 5,000) | 33 | 0.009 (27) | 0.274 (27) | 0.345 (27) |
| large (> 5,000) | 35 | 0.016 (29) | 0.039 (29) | 0.212 (29) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| medium (1,000 to 5,000) | 33 | 0.000 (27) | 0.300 (27) | 0.396 (27) |
| large (> 5,000) | 35 | 0.038 (29) | 0.086 (29) | 0.214 (29) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| medium (1,000 to 5,000) | 33 | 0.099 (33) | 0.067 (33) | 0.469 (33) | 0.577 (33) |
| large (> 5,000) | 35 | 0.014 (35) | 0.239 (35) | 0.300 (35) | 0.630 (35) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| medium (1,000 to 5,000) | 33 | 15,958 (4) | 3,048 (14) | 2,704 (18) |
| large (> 5,000) | 35 | 12,206 (4) | 5,594 (7) | 3,710 (20) |

### By fix size (changed code lines)

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| up to 10 | 34 | 0.013 (25) | 0.122 (25) | 0.251 (25) |
| 11 to 50 | 23 | 0.003 (22) | 0.155 (22) | 0.267 (22) |
| over 50 | 11 | 0.035 (9) | 0.227 (9) | 0.370 (9) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| up to 10 | 34 | 0.040 (25) | 0.200 (25) | 0.340 (25) |
| 11 to 50 | 23 | 0.000 (22) | 0.197 (22) | 0.286 (22) |
| over 50 | 11 | 0.010 (9) | 0.141 (9) | 0.234 (9) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| up to 10 | 34 | 0.074 (34) | 0.191 (34) | 0.485 (34) | 0.632 (34) |
| 11 to 50 | 23 | 0.014 (23) | 0.116 (23) | 0.328 (23) | 0.592 (23) |
| over 50 | 11 | 0.086 (11) | 0.127 (11) | 0.177 (11) | 0.545 (11) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| up to 10 | 34 | 16,588 (3) | 4,235 (10) | 3,380 (17) |
| 11 to 50 | 23 | 21,172 (2) | 3,283 (8) | 4,038 (15) |
| over 50 | 11 | 6,849 (3) | 4,407 (3) | 806 (6) |

### By gold files

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| 1 | 49 | 0.009 (42) | 0.137 (42) | 0.204 (42) |
| 2 or more | 19 | 0.024 (14) | 0.197 (14) | 0.494 (14) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| 1 | 49 | 0.024 (42) | 0.202 (42) | 0.310 (42) |
| 2 or more | 19 | 0.006 (14) | 0.150 (14) | 0.278 (14) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|---|
| 1 | 49 | 0.041 (49) | 0.163 (49) | 0.449 (49) | 0.633 (49) |
| 2 or more | 19 | 0.094 (19) | 0.135 (19) | 0.210 (19) | 0.532 (19) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm3-full |
|---|---|---|---|---|
| 1 | 49 | 15,697 (4) | 3,377 (14) | 4,265 (27) |
| 2 or more | 19 | 12,466 (4) | 4,936 (7) | 701 (11) |

## IoU check (function level)

| system | mrr @ IoU 0.3 | mrr @ IoU 0.5 | mrr @ IoU 0.7 | recall@10 @ IoU 0.3 | recall@10 @ IoU 0.5 | recall@10 @ IoU 0.7 |
|---|---|---|---|---|---|---|
| grep-fn | 0.013 | 0.013 | 0.013 | 0.019 | 0.019 | 0.019 |
| grep-fn-plus | 0.152 | 0.152 | 0.152 | 0.189 | 0.189 | 0.189 |
| cm3-full | 0.276 | 0.276 | 0.276 | 0.302 | 0.302 | 0.302 |

## Latency and size

| system | search ms (median) | search ms (p95) | build s (mean) | update s (median) | items re-embedded (mean) | index MB | files failed |
|---|---|---|---|---|---|---|---|
| grep | 364.7 | 482.1 | 0.0 | 0.0 | - | 0.0 | 0.0 |
| grep-fn | 5,199.3 | 19,608.3 | same as grep | same as grep | same as grep | same as grep | same as grep |
| grep-fn-plus | 4,796.0 | 14,563.2 | same as grep | same as grep | same as grep | same as grep | same as grep |
| cm3-full | 1,238.5 | 4,020.6 | 453.9 | 37.6 | 8,906.8 | 3,500.3 | 0.0 |

Index MB = 10^6 bytes. Systems with the same index settings share one index.
Latency and size come from summary.csv, over all 68 scored tasks: the filter does not apply to them.

## Task counts

68 tasks scored. Tasks left out at each level:

| system | level | left out | reasons |
|---|---|---|---|
| grep | class | 68 | file-granularity system: 68 |
| grep | function | 68 | file-granularity system: 68 |
| grep-fn | class | 46 | no gold at this level: 41, partial labels: 5 |
| grep-fn | function | 12 | no gold at this level: 7, partial labels: 5 |
| grep-fn-plus | class | 46 | no gold at this level: 41, partial labels: 5 |
| grep-fn-plus | function | 12 | no gold at this level: 7, partial labels: 5 |
| cm3-full | class | 46 | no gold at this level: 41, partial labels: 5 |
| cm3-full | function | 12 | no gold at this level: 7, partial labels: 5 |

## Tasks left out by the filter

0 scored tasks do not match gold_all_cpp=true. Means and counts only, no intervals.

