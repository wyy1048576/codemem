# Results: 2026-10-25-subset-v3-final

- Tasks: `swebv-dev50.jsonl` (sha256 b327c2015aca), split dev, 13 tasks scored
- Systems: cm3-bm25, cm3-bm25-code, cm3-full, cm3-full-v2-weights, cm3-full-all-words, cm3-full-drop-common; baseline for the paired tests: cm3-bm25
- Index mode: update; hits per search: 50
- Code: cmeval 96bc2bcac5b6, codemem 96bc2bcac5b6
- Machine: macOS-26.6.2-arm64-arm-64bit
- Tokens: estimate, request overhead of None tokens taken off each count; scored 2026-10-25T11:38:17+00:00
- Intervals: 95% percentile bootstrap, 10,000 resamples, seed 20261023
- Dev split: these numbers guide development. p-values here are guidance only.

## Warnings

- TOKEN NUMBERS ARE ROUGH ESTIMATES: never report them (score again with an API key)

## Main results

Only 13 tasks: percentile bootstrap intervals are too narrow at this size.

### File level: accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| cm3-bm25 | 13 | 0.385 [0.154, 0.617] | 0.538 [0.308, 0.846] | 0.654 [0.385, 0.885] | 0.453 [0.233, 0.699] | 0.615 [0.385, 0.846] |
| cm3-bm25-code | 13 | 0.346 [0.115, 0.615] | 0.846 [0.615, 1.000] | 0.846 [0.615, 1.000] | 0.547 [0.341, 0.759] | 0.846 [0.615, 1.000] |
| cm3-full | 13 | 0.423 [0.154, 0.692] | 0.769 [0.538, 1.000] | 0.846 [0.615, 1.000] | 0.620 [0.415, 0.825] | 0.846 [0.615, 1.000] |
| cm3-full-v2-weights | 13 | 0.423 [0.154, 0.692] | 0.769 [0.538, 1.000] | 0.846 [0.615, 1.000] | 0.622 [0.417, 0.828] | 0.846 [0.615, 1.000] |
| cm3-full-all-words | 13 | 0.346 [0.115, 0.615] | 0.692 [0.462, 0.923] | 0.846 [0.615, 1.000] | 0.526 [0.317, 0.748] | 0.846 [0.615, 1.000] |
| cm3-full-drop-common | 13 | 0.423 [0.154, 0.692] | 0.846 [0.615, 1.000] | 0.923 [0.769, 1.000] | 0.631 [0.431, 0.833] | 0.923 [0.769, 1.000] |

### File level: tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| cm3-bm25 | 13 | 0.577 [0.308, 0.846] | 0.846 [0.615, 1.000] | 885 [447, 1,374] | 0.154 [0.000, 0.385] |
| cm3-bm25-code | 13 | 0.692 [0.462, 0.923] | 0.846 [0.615, 1.000] | 424 [195, 705] | 0.154 [0.000, 0.385] |
| cm3-full | 13 | 0.769 [0.538, 1.000] | 0.846 [0.615, 1.000] | 709 [160, 1,501] | 0.077 [0.000, 0.231] |
| cm3-full-v2-weights | 13 | 0.769 [0.538, 1.000] | 0.923 [0.769, 1.000] | 535 [160, 1,115] | 0.077 [0.000, 0.231] |
| cm3-full-all-words | 13 | 0.692 [0.462, 0.923] | 0.923 [0.769, 1.000] | 950 [354, 1,694] | 0.077 [0.000, 0.231] |
| cm3-full-drop-common | 13 | 0.846 [0.615, 1.000] | 0.923 [0.769, 1.000] | 515 [158, 1,143] | 0.077 [0.000, 0.231] |

### Function level (IoU 0.5): accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| cm3-bm25 | 12 | 0.125 [0.000, 0.292] | 0.167 [0.000, 0.417] | 0.333 [0.083, 0.583] | 0.210 [0.042, 0.441] | 0.333 [0.083, 0.583] |
| cm3-bm25-code | 12 | 0.208 [0.000, 0.458] | 0.417 [0.167, 0.667] | 0.625 [0.333, 0.875] | 0.388 [0.176, 0.620] | 0.583 [0.333, 0.833] |
| cm3-full | 12 | 0.208 [0.000, 0.458] | 0.417 [0.167, 0.667] | 0.500 [0.250, 0.750] | 0.397 [0.186, 0.635] | 0.417 [0.167, 0.667] |
| cm3-full-v2-weights | 12 | 0.208 [0.000, 0.458] | 0.500 [0.250, 0.750] | 0.625 [0.375, 0.875] | 0.410 [0.201, 0.642] | 0.583 [0.333, 0.833] |
| cm3-full-all-words | 12 | 0.208 [0.000, 0.458] | 0.417 [0.167, 0.667] | 0.500 [0.250, 0.750] | 0.356 [0.144, 0.592] | 0.417 [0.167, 0.667] |
| cm3-full-drop-common | 12 | 0.208 [0.000, 0.458] | 0.500 [0.250, 0.750] | 0.500 [0.250, 0.750] | 0.405 [0.191, 0.635] | 0.417 [0.167, 0.667] |

### Function level (IoU 0.5): tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| cm3-bm25 | 12 | 0.333 [0.083, 0.583] | 0.500 [0.250, 0.750] | 2,123 [979, 3,504] | 0.250 [0.000, 0.500] |
| cm3-bm25-code | 12 | 0.458 [0.208, 0.750] | 0.708 [0.458, 0.917] | 986 [337, 1,917] | 0.167 [0.000, 0.417] |
| cm3-full | 12 | 0.417 [0.167, 0.667] | 0.708 [0.458, 0.917] | 1,352 [385, 2,671] | 0.167 [0.000, 0.417] |
| cm3-full-v2-weights | 12 | 0.542 [0.292, 0.792] | 0.708 [0.458, 0.917] | 1,017 [285, 2,108] | 0.167 [0.000, 0.417] |
| cm3-full-all-words | 12 | 0.500 [0.250, 0.750] | 0.708 [0.458, 0.917] | 882 [326, 1,576] | 0.250 [0.000, 0.500] |
| cm3-full-drop-common | 12 | 0.500 [0.250, 0.750] | 0.708 [0.458, 0.917] | 687 [203, 1,308] | 0.250 [0.000, 0.500] |

### Class level (IoU 0.5): accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| cm3-bm25 | 11 | 0.227 [0.000, 0.455] | 0.273 [0.000, 0.545] | 0.545 [0.273, 0.818] | 0.318 [0.085, 0.577] | 0.545 [0.273, 0.818] |
| cm3-bm25-code | 11 | 0.182 [0.000, 0.455] | 0.409 [0.136, 0.682] | 0.727 [0.455, 1.000] | 0.340 [0.146, 0.567] | 0.727 [0.455, 1.000] |
| cm3-full | 11 | 0.364 [0.091, 0.636] | 0.591 [0.318, 0.864] | 0.591 [0.318, 0.864] | 0.503 [0.237, 0.734] | 0.545 [0.273, 0.818] |
| cm3-full-v2-weights | 11 | 0.364 [0.091, 0.636] | 0.591 [0.318, 0.864] | 0.636 [0.364, 0.909] | 0.505 [0.241, 0.736] | 0.636 [0.364, 0.909] |
| cm3-full-all-words | 11 | 0.273 [0.000, 0.545] | 0.409 [0.136, 0.682] | 0.500 [0.227, 0.773] | 0.365 [0.139, 0.618] | 0.455 [0.182, 0.727] |
| cm3-full-drop-common | 11 | 0.364 [0.091, 0.636] | 0.591 [0.318, 0.864] | 0.591 [0.318, 0.864] | 0.503 [0.238, 0.734] | 0.545 [0.273, 0.818] |

### Class level (IoU 0.5): tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| cm3-bm25 | 11 | 0.455 [0.182, 0.727] | 0.727 [0.455, 1.000] | 1,064 [512, 1,650] | 0.273 [0.000, 0.545] |
| cm3-bm25-code | 11 | 0.545 [0.273, 0.818] | 0.727 [0.455, 1.000] | 536 [246, 892] | 0.273 [0.000, 0.545] |
| cm3-full | 11 | 0.591 [0.318, 0.864] | 0.636 [0.364, 0.909] | 660 [135, 1,658] | 0.273 [0.000, 0.545] |
| cm3-full-v2-weights | 11 | 0.636 [0.364, 0.909] | 0.727 [0.455, 1.000] | 535 [135, 1,284] | 0.273 [0.000, 0.545] |
| cm3-full-all-words | 11 | 0.500 [0.227, 0.773] | 0.727 [0.455, 1.000] | 1,015 [288, 1,959] | 0.273 [0.000, 0.545] |
| cm3-full-drop-common | 11 | 0.591 [0.318, 0.864] | 0.727 [0.455, 1.000] | 617 [135, 1,529] | 0.273 [0.000, 0.545] |

tokens_to_first is the mean over the tasks where the system found the right item, so each system's mean is over its own set of tasks. not_found_share shows how many it missed.

## Paired comparison with cm3-bm25

Difference = system - cm3-bm25 on the same tasks. A confidence interval and a p-value can disagree: the interval is about the mean, the Wilcoxon test is about signed ranks.

### Primary metrics (Holm correction over all 2 tests, significant at 0.05)

| system | metric | tasks | cm3-bm25 | system | difference [95% CI] | Wilcoxon p | Holm p | significant |
|---|---|---|---|---|---|---|---|---|
| cm3-full | function mrr | 12 | 0.210 | 0.397 | +0.187 [-0.029, +0.431] | 0.203 (exact) | 0.406 | no |
| cm3-full | function tokens_to_first (lower is better) | 9 | 2,123 | 1,220 | -903 [-2,586, +763] | 0.383 (exact) | 0.406 | no |

Tokens to the first right function are paired on the tasks both systems found:

| system | found by both | system only | cm3-bm25 only | neither |
|---|---|---|---|---|
| cm3-full | 9 | 1 | 0 | 2 |

### Exploratory (raw p, no correction)

#### File level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| cm3-bm25-code | recall@1 | 13 | -0.038 [-0.308, +0.231] | 1.000 |
| cm3-bm25-code | recall@5 | 13 | +0.308 [+0.077, +0.538] | 0.125 |
| cm3-bm25-code | recall@10 | 13 | +0.192 [+0.000, +0.423] | 0.250 |
| cm3-bm25-code | mrr | 13 | +0.094 [-0.154, +0.340] | 0.406 |
| cm3-bm25-code | success@10 | 13 | +0.231 [+0.000, +0.462] | 0.250 |
| cm3-bm25-code | recall@budget1000 | 13 | +0.115 [-0.231, +0.462] | 0.688 |
| cm3-bm25-code | recall@budget4000 | 13 | +0.000 [+0.000, +0.000] | 1.000 |
| cm3-bm25-code | tokens_to_first (lower is better) | 11 | -461 [-1,010, +54] | 0.203 |
| cm3-bm25-code | not_found_share (lower is better) | 13 | +0.000 [+0.000, +0.000] | 1.000 |
| cm3-full | recall@1 | 13 | +0.038 [-0.346, +0.423] | 1.000 |
| cm3-full | recall@5 | 13 | +0.231 [-0.077, +0.538] | 0.375 |
| cm3-full | recall@10 | 13 | +0.192 [+0.000, +0.423] | 0.250 |
| cm3-full | mrr | 13 | +0.167 [-0.140, +0.470] | 0.275 |
| cm3-full | success@10 | 13 | +0.231 [+0.000, +0.462] | 0.250 |
| cm3-full | recall@budget1000 | 13 | +0.192 [-0.115, +0.500] | 0.375 |
| cm3-full | recall@budget4000 | 13 | +0.000 [-0.231, +0.231] | 1.000 |
| cm3-full | tokens_to_first (lower is better) | 11 | -343 [-1,113, +623] | 0.250 |
| cm3-full | not_found_share (lower is better) | 13 | -0.077 [-0.231, +0.000] | 1.000 |
| cm3-full-v2-weights | recall@1 | 13 | +0.038 [-0.346, +0.423] | 1.000 |
| cm3-full-v2-weights | recall@5 | 13 | +0.231 [-0.077, +0.538] | 0.375 |
| cm3-full-v2-weights | recall@10 | 13 | +0.192 [+0.000, +0.423] | 0.250 |
| cm3-full-v2-weights | mrr | 13 | +0.169 [-0.138, +0.472] | 0.275 |
| cm3-full-v2-weights | success@10 | 13 | +0.231 [+0.000, +0.462] | 0.250 |
| cm3-full-v2-weights | recall@budget1000 | 13 | +0.192 [-0.115, +0.500] | 0.375 |
| cm3-full-v2-weights | recall@budget4000 | 13 | +0.077 [+0.000, +0.231] | 1.000 |
| cm3-full-v2-weights | tokens_to_first (lower is better) | 11 | -433 [-1,117, +366] | 0.250 |
| cm3-full-v2-weights | not_found_share (lower is better) | 13 | -0.077 [-0.231, +0.000] | 1.000 |
| cm3-full-all-words | recall@1 | 13 | -0.038 [-0.385, +0.308] | 1.000 |
| cm3-full-all-words | recall@5 | 13 | +0.154 [-0.231, +0.538] | 0.688 |
| cm3-full-all-words | recall@10 | 13 | +0.192 [+0.000, +0.423] | 0.250 |
| cm3-full-all-words | mrr | 13 | +0.073 [-0.196, +0.355] | 0.607 |
| cm3-full-all-words | success@10 | 13 | +0.231 [+0.000, +0.462] | 0.250 |
| cm3-full-all-words | recall@budget1000 | 13 | +0.115 [-0.231, +0.462] | 0.688 |
| cm3-full-all-words | recall@budget4000 | 13 | +0.077 [+0.000, +0.231] | 1.000 |
| cm3-full-all-words | tokens_to_first (lower is better) | 11 | -92 [-865, +799] | 0.652 |
| cm3-full-all-words | not_found_share (lower is better) | 13 | -0.077 [-0.231, +0.000] | 1.000 |
| cm3-full-drop-common | recall@1 | 13 | +0.038 [-0.346, +0.423] | 1.000 |
| cm3-full-drop-common | recall@5 | 13 | +0.308 [+0.000, +0.615] | 0.219 |
| cm3-full-drop-common | recall@10 | 13 | +0.269 [+0.077, +0.500] | 0.125 |
| cm3-full-drop-common | mrr | 13 | +0.178 [-0.132, +0.479] | 0.275 |
| cm3-full-drop-common | success@10 | 13 | +0.308 [+0.077, +0.538] | 0.125 |
| cm3-full-drop-common | recall@budget1000 | 13 | +0.269 [-0.038, +0.577] | 0.219 |
| cm3-full-drop-common | recall@budget4000 | 13 | +0.077 [+0.000, +0.231] | 1.000 |
| cm3-full-drop-common | tokens_to_first (lower is better) | 11 | -374 [-1,114, +531] | 0.250 |
| cm3-full-drop-common | not_found_share (lower is better) | 13 | -0.077 [-0.231, +0.000] | 1.000 |

#### Function level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| cm3-bm25-code | recall@1 | 12 | +0.083 [-0.083, +0.292] | 0.750 |
| cm3-bm25-code | recall@5 | 12 | +0.250 [+0.000, +0.542] | 0.188 |
| cm3-bm25-code | recall@10 | 12 | +0.292 [+0.083, +0.542] | 0.125 |
| cm3-bm25-code | mrr | 12 | +0.178 [-0.055, +0.420] | 0.164 |
| cm3-bm25-code | success@10 | 12 | +0.250 [+0.000, +0.500] | 0.250 |
| cm3-bm25-code | recall@budget1000 | 12 | +0.125 [-0.167, +0.417] | 0.625 |
| cm3-bm25-code | recall@budget4000 | 12 | +0.208 [-0.042, +0.500] | 0.250 |
| cm3-bm25-code | tokens_to_first (lower is better) | 9 | -1,160 [-2,488, +59] | 0.195 |
| cm3-bm25-code | not_found_share (lower is better) | 12 | -0.083 [-0.250, +0.000] | 1.000 |
| cm3-full | recall@1 | 12 | +0.083 [-0.083, +0.292] | 0.750 |
| cm3-full | recall@5 | 12 | +0.250 [+0.000, +0.542] | 0.188 |
| cm3-full | recall@10 | 12 | +0.167 [-0.167, +0.500] | 0.500 |
| cm3-full | success@10 | 12 | +0.083 [-0.250, +0.417] | 1.000 |
| cm3-full | recall@budget1000 | 12 | +0.083 [-0.208, +0.375] | 0.812 |
| cm3-full | recall@budget4000 | 12 | +0.208 [-0.042, +0.500] | 0.250 |
| cm3-full | not_found_share (lower is better) | 12 | -0.083 [-0.250, +0.000] | 1.000 |
| cm3-full-v2-weights | recall@1 | 12 | +0.083 [-0.083, +0.292] | 0.750 |
| cm3-full-v2-weights | recall@5 | 12 | +0.333 [+0.042, +0.625] | 0.094 |
| cm3-full-v2-weights | recall@10 | 12 | +0.292 [+0.083, +0.542] | 0.125 |
| cm3-full-v2-weights | mrr | 12 | +0.199 [-0.016, +0.441] | 0.164 |
| cm3-full-v2-weights | success@10 | 12 | +0.250 [+0.000, +0.500] | 0.250 |
| cm3-full-v2-weights | recall@budget1000 | 12 | +0.208 [-0.125, +0.500] | 0.375 |
| cm3-full-v2-weights | recall@budget4000 | 12 | +0.208 [-0.042, +0.500] | 0.250 |
| cm3-full-v2-weights | tokens_to_first (lower is better) | 9 | -1,177 [-2,787, +335] | 0.250 |
| cm3-full-v2-weights | not_found_share (lower is better) | 12 | -0.083 [-0.250, +0.000] | 1.000 |
| cm3-full-all-words | recall@1 | 12 | +0.083 [-0.083, +0.292] | 0.750 |
| cm3-full-all-words | recall@5 | 12 | +0.250 [+0.000, +0.542] | 0.188 |
| cm3-full-all-words | recall@10 | 12 | +0.167 [-0.167, +0.500] | 0.500 |
| cm3-full-all-words | mrr | 12 | +0.145 [-0.056, +0.372] | 0.250 |
| cm3-full-all-words | success@10 | 12 | +0.083 [-0.250, +0.417] | 1.000 |
| cm3-full-all-words | recall@budget1000 | 12 | +0.167 [-0.167, +0.500] | 0.500 |
| cm3-full-all-words | recall@budget4000 | 12 | +0.208 [-0.042, +0.500] | 0.250 |
| cm3-full-all-words | tokens_to_first (lower is better) | 8 | -1,441 [-2,898, -139] | 0.156 |
| cm3-full-all-words | not_found_share (lower is better) | 12 | +0.000 [-0.250, +0.250] | 1.000 |
| cm3-full-drop-common | recall@1 | 12 | +0.083 [-0.083, +0.292] | 0.750 |
| cm3-full-drop-common | recall@5 | 12 | +0.333 [+0.042, +0.625] | 0.094 |
| cm3-full-drop-common | recall@10 | 12 | +0.167 [-0.167, +0.500] | 0.500 |
| cm3-full-drop-common | mrr | 12 | +0.194 [-0.023, +0.439] | 0.250 |
| cm3-full-drop-common | success@10 | 12 | +0.083 [-0.250, +0.417] | 1.000 |
| cm3-full-drop-common | recall@budget1000 | 12 | +0.167 [-0.167, +0.500] | 0.500 |
| cm3-full-drop-common | recall@budget4000 | 12 | +0.208 [-0.042, +0.500] | 0.250 |
| cm3-full-drop-common | tokens_to_first (lower is better) | 8 | -1,593 [-3,163, -189] | 0.109 |
| cm3-full-drop-common | not_found_share (lower is better) | 12 | +0.000 [-0.250, +0.250] | 1.000 |

#### Class level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| cm3-bm25-code | recall@1 | 11 | -0.045 [-0.318, +0.227] | 1.000 |
| cm3-bm25-code | recall@5 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm3-bm25-code | recall@10 | 11 | +0.182 [+0.000, +0.455] | 0.500 |
| cm3-bm25-code | mrr | 11 | +0.021 [-0.252, +0.286] | 0.812 |
| cm3-bm25-code | success@10 | 11 | +0.182 [+0.000, +0.455] | 0.500 |
| cm3-bm25-code | recall@budget1000 | 11 | +0.091 [-0.273, +0.455] | 1.000 |
| cm3-bm25-code | recall@budget4000 | 11 | +0.000 [+0.000, +0.000] | 1.000 |
| cm3-bm25-code | tokens_to_first (lower is better) | 8 | -527 [-1,236, +174] | 0.297 |
| cm3-bm25-code | not_found_share (lower is better) | 11 | +0.000 [+0.000, +0.000] | 1.000 |
| cm3-full | recall@1 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm3-full | recall@5 | 11 | +0.318 [-0.091, +0.727] | 0.219 |
| cm3-full | recall@10 | 11 | +0.045 [-0.273, +0.364] | 1.000 |
| cm3-full | mrr | 11 | +0.185 [-0.154, +0.513] | 0.578 |
| cm3-full | success@10 | 11 | +0.000 [-0.364, +0.364] | 1.000 |
| cm3-full | recall@budget1000 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm3-full | recall@budget4000 | 11 | -0.091 [-0.273, +0.000] | 1.000 |
| cm3-full | tokens_to_first (lower is better) | 8 | -404 [-1,421, +933] | 0.375 |
| cm3-full | not_found_share (lower is better) | 11 | +0.000 [+0.000, +0.000] | 1.000 |
| cm3-full-v2-weights | recall@1 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm3-full-v2-weights | recall@5 | 11 | +0.318 [-0.091, +0.727] | 0.219 |
| cm3-full-v2-weights | recall@10 | 11 | +0.091 [-0.182, +0.364] | 1.000 |
| cm3-full-v2-weights | mrr | 11 | +0.186 [-0.150, +0.513] | 0.578 |
| cm3-full-v2-weights | success@10 | 11 | +0.091 [-0.182, +0.364] | 1.000 |
| cm3-full-v2-weights | recall@budget1000 | 11 | +0.182 [-0.182, +0.545] | 0.625 |
| cm3-full-v2-weights | recall@budget4000 | 11 | +0.000 [+0.000, +0.000] | 1.000 |
| cm3-full-v2-weights | tokens_to_first (lower is better) | 8 | -528 [-1,428, +568] | 0.375 |
| cm3-full-v2-weights | not_found_share (lower is better) | 11 | +0.000 [+0.000, +0.000] | 1.000 |
| cm3-full-all-words | recall@1 | 11 | +0.045 [-0.273, +0.364] | 1.000 |
| cm3-full-all-words | recall@5 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm3-full-all-words | recall@10 | 11 | -0.045 [-0.409, +0.318] | 1.000 |
| cm3-full-all-words | mrr | 11 | +0.046 [-0.253, +0.354] | 0.938 |
| cm3-full-all-words | success@10 | 11 | -0.091 [-0.455, +0.273] | 1.000 |
| cm3-full-all-words | recall@budget1000 | 11 | +0.045 [-0.364, +0.455] | 1.000 |
| cm3-full-all-words | recall@budget4000 | 11 | +0.000 [+0.000, +0.000] | 1.000 |
| cm3-full-all-words | tokens_to_first (lower is better) | 8 | -48 [-1,072, +1,165] | 0.812 |
| cm3-full-all-words | not_found_share (lower is better) | 11 | +0.000 [+0.000, +0.000] | 1.000 |
| cm3-full-drop-common | recall@1 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm3-full-drop-common | recall@5 | 11 | +0.318 [-0.091, +0.727] | 0.219 |
| cm3-full-drop-common | recall@10 | 11 | +0.045 [-0.273, +0.364] | 1.000 |
| cm3-full-drop-common | mrr | 11 | +0.185 [-0.154, +0.513] | 0.578 |
| cm3-full-drop-common | success@10 | 11 | +0.000 [-0.364, +0.364] | 1.000 |
| cm3-full-drop-common | recall@budget1000 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm3-full-drop-common | recall@budget4000 | 11 | +0.000 [+0.000, +0.000] | 1.000 |
| cm3-full-drop-common | tokens_to_first (lower is better) | 8 | -446 [-1,421, +804] | 0.375 |
| cm3-full-drop-common | not_found_share (lower is better) | 11 | +0.000 [+0.000, +0.000] | 1.000 |

## Groups (means and task counts, no intervals)

### By identifier in query

Function mrr:

| group | tasks | cm3-bm25 | cm3-bm25-code | cm3-full | cm3-full-v2-weights | cm3-full-all-words | cm3-full-drop-common |
|---|---|---|---|---|---|---|---|
| false | 8 | 0.157 (8) | 0.203 (8) | 0.280 (8) | 0.299 (8) | 0.158 (8) | 0.295 (8) |
| true | 5 | 0.317 (4) | 0.759 (4) | 0.631 (4) | 0.632 (4) | 0.750 (4) | 0.625 (4) |

Function recall@10:

| group | tasks | cm3-bm25 | cm3-bm25-code | cm3-full | cm3-full-v2-weights | cm3-full-all-words | cm3-full-drop-common |
|---|---|---|---|---|---|---|---|
| false | 8 | 0.250 (8) | 0.625 (8) | 0.438 (8) | 0.625 (8) | 0.438 (8) | 0.438 (8) |
| true | 5 | 0.500 (4) | 0.625 (4) | 0.625 (4) | 0.625 (4) | 0.625 (4) | 0.625 (4) |

File recall@10:

| group | tasks | cm3-bm25 | cm3-bm25-code | cm3-full | cm3-full-v2-weights | cm3-full-all-words | cm3-full-drop-common |
|---|---|---|---|---|---|---|---|
| false | 8 | 0.500 (8) | 0.750 (8) | 0.750 (8) | 0.750 (8) | 0.750 (8) | 0.875 (8) |
| true | 5 | 0.900 (5) | 1.000 (5) | 1.000 (5) | 1.000 (5) | 1.000 (5) | 1.000 (5) |

Function tokens_to_first (lower is better):

| group | tasks | cm3-bm25 | cm3-bm25-code | cm3-full | cm3-full-v2-weights | cm3-full-all-words | cm3-full-drop-common |
|---|---|---|---|---|---|---|---|
| false | 8 | 2,807 (5) | 827 (6) | 1,093 (6) | 687 (6) | 1,260 (6) | 953 (6) |
| true | 5 | 1,269 (4) | 1,224 (4) | 1,739 (4) | 1,511 (4) | 127 (3) | 157 (3) |

### By repo

Function mrr:

| group | tasks | cm3-bm25 | cm3-bm25-code | cm3-full | cm3-full-v2-weights | cm3-full-all-words | cm3-full-drop-common |
|---|---|---|---|---|---|---|---|
| mwaskom/seaborn | 2 | 0.079 (2) | 0.517 (2) | 0.511 (2) | 0.513 (2) | 0.500 (2) | 0.500 (2) |
| pallets/flask | 1 | 0.000 (1) | 0.100 (1) | 0.048 (1) | 0.091 (1) | 0.042 (1) | 0.048 (1) |
| psf/requests | 5 | 0.245 (5) | 0.482 (5) | 0.529 (5) | 0.540 (5) | 0.433 (5) | 0.550 (5) |
| pytest-dev/pytest | 5 | 0.286 (4) | 0.278 (4) | 0.263 (4) | 0.275 (4) | 0.265 (4) | 0.265 (4) |

Function recall@10:

| group | tasks | cm3-bm25 | cm3-bm25-code | cm3-full | cm3-full-v2-weights | cm3-full-all-words | cm3-full-drop-common |
|---|---|---|---|---|---|---|---|
| mwaskom/seaborn | 2 | 0.000 (2) | 0.250 (2) | 0.250 (2) | 0.250 (2) | 0.250 (2) | 0.250 (2) |
| pallets/flask | 1 | 0.000 (1) | 1.000 (1) | 0.000 (1) | 0.000 (1) | 0.000 (1) | 0.000 (1) |
| psf/requests | 5 | 0.400 (5) | 0.800 (5) | 0.900 (5) | 1.000 (5) | 0.900 (5) | 0.900 (5) |
| pytest-dev/pytest | 5 | 0.500 (4) | 0.500 (4) | 0.250 (4) | 0.500 (4) | 0.250 (4) | 0.250 (4) |

File recall@10:

| group | tasks | cm3-bm25 | cm3-bm25-code | cm3-full | cm3-full-v2-weights | cm3-full-all-words | cm3-full-drop-common |
|---|---|---|---|---|---|---|---|
| mwaskom/seaborn | 2 | 0.750 (2) | 1.000 (2) | 1.000 (2) | 1.000 (2) | 1.000 (2) | 1.000 (2) |
| pallets/flask | 1 | 0.000 (1) | 1.000 (1) | 1.000 (1) | 1.000 (1) | 1.000 (1) | 1.000 (1) |
| psf/requests | 5 | 0.800 (5) | 1.000 (5) | 1.000 (5) | 1.000 (5) | 1.000 (5) | 1.000 (5) |
| pytest-dev/pytest | 5 | 0.600 (5) | 0.600 (5) | 0.600 (5) | 0.600 (5) | 0.600 (5) | 0.800 (5) |

Function tokens_to_first (lower is better):

| group | tasks | cm3-bm25 | cm3-bm25-code | cm3-full | cm3-full-v2-weights | cm3-full-all-words | cm3-full-drop-common |
|---|---|---|---|---|---|---|---|
| mwaskom/seaborn | 2 | 2,010 (2) | 2,329 (2) | 3,314 (2) | 2,859 (2) | 143 (1) | 143 (1) |
| pallets/flask | 1 | - (0) | 1,189 (1) | 2,534 (1) | 1,646 (1) | 3,075 (1) | 2,534 (1) |
| psf/requests | 5 | 2,820 (5) | 575 (5) | 406 (5) | 311 (5) | 507 (5) | 283 (5) |
| pytest-dev/pytest | 5 | 494 (2) | 568 (2) | 1,160 (2) | 623 (2) | 1,092 (2) | 1,048 (2) |

- language: all 13 tasks are 'python', so there is no table.

- issue date: all 13 tasks are 'before 2026-07-01', so there is no table.

## IoU check (function level)

| system | mrr @ IoU 0.3 | mrr @ IoU 0.5 | mrr @ IoU 0.7 | recall@10 @ IoU 0.3 | recall@10 @ IoU 0.5 | recall@10 @ IoU 0.7 |
|---|---|---|---|---|---|---|
| cm3-bm25 | 0.210 | 0.210 | 0.210 | 0.333 | 0.333 | 0.333 |
| cm3-bm25-code | 0.388 | 0.388 | 0.388 | 0.625 | 0.625 | 0.625 |
| cm3-full | 0.397 | 0.397 | 0.397 | 0.500 | 0.500 | 0.500 |
| cm3-full-v2-weights | 0.410 | 0.410 | 0.410 | 0.625 | 0.625 | 0.625 |
| cm3-full-all-words | 0.356 | 0.356 | 0.356 | 0.500 | 0.500 | 0.500 |
| cm3-full-drop-common | 0.405 | 0.405 | 0.405 | 0.500 | 0.500 | 0.500 |

## Latency and size

| system | search ms (median) | search ms (p95) | build s (mean) | update s (median) | items re-embedded (mean) | index MB | files failed |
|---|---|---|---|---|---|---|---|
| cm3-bm25 | 14.8 | 222.3 | 4.0 | 1.8 | 2,127.7 | 85.0 | 0.0 |
| cm3-bm25-code | 958.4 | 1,730.1 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 |
| cm3-full | 18.2 | 153.3 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 |
| cm3-full-v2-weights | 19.5 | 185.2 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 |
| cm3-full-all-words | 24.7 | 337.1 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 |
| cm3-full-drop-common | 11.9 | 86.4 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 | same as cm3-bm25 |

Index MB = 10^6 bytes. Systems with the same index settings share one index.

## Task counts

13 tasks scored. Tasks left out at each level:

| system | level | left out | reasons |
|---|---|---|---|
| cm3-bm25 | class | 2 | no gold at this level: 2 |
| cm3-bm25 | function | 1 | no gold at this level: 1 |
| cm3-bm25-code | class | 2 | no gold at this level: 2 |
| cm3-bm25-code | function | 1 | no gold at this level: 1 |
| cm3-full | class | 2 | no gold at this level: 2 |
| cm3-full | function | 1 | no gold at this level: 1 |
| cm3-full-v2-weights | class | 2 | no gold at this level: 2 |
| cm3-full-v2-weights | function | 1 | no gold at this level: 1 |
| cm3-full-all-words | class | 2 | no gold at this level: 2 |
| cm3-full-all-words | function | 1 | no gold at this level: 1 |
| cm3-full-drop-common | class | 2 | no gold at this level: 2 |
| cm3-full-drop-common | function | 1 | no gold at this level: 1 |
