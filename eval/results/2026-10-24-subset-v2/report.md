# Results: 2026-10-24-dev50-v2

- Tasks: `swebv-dev50.jsonl` (sha256 b327c2015aca), split dev, 13 tasks scored
- Systems: cm2-bm25, cm2-bm25-code, cm2-bm25-code-usage, cm2-full-fn, cm2-full-tests-down, cm2-full-no-tests, cm2-full-v1-bm25; baseline for the paired tests: cm2-bm25
- Index mode: update; hits per search: 50
- Code: cmeval 31c0f990d380, codemem 31c0f990d380
- Machine: macOS-26.6.2-arm64-arm-64bit
- Tokens: estimate, request overhead of None tokens taken off each count; scored 2026-10-24T08:35:56+00:00
- Intervals: 95% percentile bootstrap, 10,000 resamples, seed 20261023
- Dev split: these numbers guide development. p-values here are guidance only.

## Warnings

- TOKEN NUMBERS ARE ROUGH ESTIMATES: never report them (score again with an API key)

## Main results

Only 13 tasks: percentile bootstrap intervals are too narrow at this size.

### File level: accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| cm2-bm25 | 13 | 0.385 [0.154, 0.617] | 0.500 [0.231, 0.769] | 0.731 [0.500, 0.923] | 0.460 [0.237, 0.708] | 0.692 [0.462, 0.923] |
| cm2-bm25-code | 13 | 0.269 [0.077, 0.500] | 0.769 [0.538, 1.000] | 0.846 [0.615, 1.000] | 0.492 [0.299, 0.697] | 0.846 [0.615, 1.000] |
| cm2-bm25-code-usage | 13 | 0.346 [0.115, 0.615] | 0.692 [0.462, 0.923] | 0.846 [0.615, 1.000] | 0.546 [0.339, 0.759] | 0.846 [0.615, 1.000] |
| cm2-full-fn | 13 | 0.346 [0.115, 0.615] | 0.692 [0.462, 0.923] | 0.846 [0.615, 1.000] | 0.567 [0.362, 0.778] | 0.846 [0.615, 1.000] |
| cm2-full-tests-down | 13 | 0.346 [0.115, 0.615] | 0.769 [0.538, 1.000] | 0.846 [0.615, 1.000] | 0.554 [0.351, 0.765] | 0.846 [0.615, 1.000] |
| cm2-full-no-tests | 13 | 0.346 [0.115, 0.615] | 0.769 [0.538, 1.000] | 0.846 [0.615, 1.000] | 0.573 [0.373, 0.782] | 0.846 [0.615, 1.000] |
| cm2-full-v1-bm25 | 13 | 0.346 [0.115, 0.615] | 0.692 [0.462, 0.923] | 0.846 [0.615, 1.000] | 0.546 [0.340, 0.759] | 0.846 [0.615, 1.000] |

### File level: tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| cm2-bm25 | 13 | 0.500 [0.231, 0.769] | 0.654 [0.385, 0.885] | 1,452 [456, 2,755] | 0.154 [0.000, 0.385] |
| cm2-bm25-code | 13 | 0.615 [0.308, 0.846] | 0.846 [0.615, 1.000] | 483 [246, 755] | 0.154 [0.000, 0.385] |
| cm2-bm25-code-usage | 13 | 0.692 [0.462, 0.923] | 0.923 [0.769, 1.000] | 895 [295, 1,629] | 0.077 [0.000, 0.231] |
| cm2-full-fn | 13 | 0.692 [0.462, 0.923] | 0.846 [0.615, 1.000] | 892 [217, 1,717] | 0.077 [0.000, 0.231] |
| cm2-full-tests-down | 13 | 0.769 [0.538, 1.000] | 0.923 [0.769, 1.000] | 741 [255, 1,440] | 0.077 [0.000, 0.231] |
| cm2-full-no-tests | 13 | 0.769 [0.538, 1.000] | 0.923 [0.769, 1.000] | 782 [237, 1,516] | 0.077 [0.000, 0.231] |
| cm2-full-v1-bm25 | 13 | 0.692 [0.462, 0.923] | 0.923 [0.769, 1.000] | 884 [294, 1,616] | 0.077 [0.000, 0.231] |

### Function level (IoU 0.5): accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| cm2-bm25 | 12 | 0.125 [0.000, 0.292] | 0.250 [0.000, 0.500] | 0.333 [0.083, 0.583] | 0.203 [0.029, 0.432] | 0.333 [0.083, 0.583] |
| cm2-bm25-code | 12 | 0.208 [0.000, 0.458] | 0.333 [0.125, 0.583] | 0.625 [0.375, 0.875] | 0.347 [0.141, 0.583] | 0.583 [0.333, 0.833] |
| cm2-bm25-code-usage | 12 | 0.208 [0.000, 0.458] | 0.500 [0.250, 0.750] | 0.500 [0.250, 0.750] | 0.386 [0.175, 0.618] | 0.417 [0.167, 0.667] |
| cm2-full-fn | 12 | 0.208 [0.000, 0.458] | 0.500 [0.250, 0.750] | 0.500 [0.250, 0.750] | 0.413 [0.200, 0.639] | 0.417 [0.167, 0.667] |
| cm2-full-tests-down | 12 | 0.208 [0.000, 0.458] | 0.500 [0.250, 0.750] | 0.625 [0.375, 0.875] | 0.394 [0.186, 0.623] | 0.583 [0.333, 0.833] |
| cm2-full-no-tests | 12 | 0.167 [0.000, 0.417] | 0.500 [0.250, 0.750] | 0.625 [0.375, 0.875] | 0.338 [0.152, 0.546] | 0.583 [0.333, 0.833] |
| cm2-full-v1-bm25 | 12 | 0.208 [0.000, 0.458] | 0.500 [0.250, 0.750] | 0.500 [0.250, 0.750] | 0.388 [0.178, 0.619] | 0.417 [0.167, 0.667] |

### Function level (IoU 0.5): tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| cm2-bm25 | 12 | 0.250 [0.000, 0.500] | 0.375 [0.125, 0.667] | 2,945 [1,209, 4,782] | 0.333 [0.083, 0.583] |
| cm2-bm25-code | 12 | 0.375 [0.125, 0.667] | 0.708 [0.458, 0.917] | 1,210 [443, 2,389] | 0.167 [0.000, 0.417] |
| cm2-bm25-code-usage | 12 | 0.500 [0.250, 0.750] | 0.708 [0.458, 0.917] | 793 [255, 1,499] | 0.250 [0.000, 0.500] |
| cm2-full-fn | 12 | 0.500 [0.250, 0.750] | 0.708 [0.458, 0.917] | 1,373 [288, 2,847] | 0.167 [0.000, 0.417] |
| cm2-full-tests-down | 12 | 0.625 [0.375, 0.875] | 0.708 [0.458, 0.917] | 625 [244, 1,188] | 0.250 [0.000, 0.500] |
| cm2-full-no-tests | 12 | 0.625 [0.375, 0.875] | 0.625 [0.375, 0.875] | 1,042 [292, 2,299] | 0.250 [0.000, 0.500] |
| cm2-full-v1-bm25 | 12 | 0.500 [0.250, 0.750] | 0.708 [0.458, 0.917] | 1,314 [377, 2,577] | 0.167 [0.000, 0.417] |

### Class level (IoU 0.5): accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| cm2-bm25 | 11 | 0.227 [0.000, 0.455] | 0.364 [0.091, 0.636] | 0.545 [0.273, 0.818] | 0.313 [0.081, 0.574] | 0.545 [0.273, 0.818] |
| cm2-bm25-code | 11 | 0.182 [0.000, 0.455] | 0.409 [0.136, 0.682] | 0.727 [0.455, 1.000] | 0.295 [0.112, 0.525] | 0.727 [0.455, 1.000] |
| cm2-bm25-code-usage | 11 | 0.273 [0.000, 0.545] | 0.500 [0.227, 0.773] | 0.500 [0.227, 0.773] | 0.391 [0.160, 0.645] | 0.455 [0.182, 0.727] |
| cm2-full-fn | 11 | 0.273 [0.000, 0.545] | 0.500 [0.227, 0.773] | 0.500 [0.227, 0.773] | 0.418 [0.191, 0.682] | 0.455 [0.182, 0.727] |
| cm2-full-tests-down | 11 | 0.273 [0.000, 0.545] | 0.500 [0.227, 0.773] | 0.636 [0.364, 0.909] | 0.398 [0.170, 0.649] | 0.636 [0.364, 0.909] |
| cm2-full-no-tests | 11 | 0.273 [0.000, 0.545] | 0.500 [0.227, 0.773] | 0.636 [0.364, 0.909] | 0.397 [0.168, 0.648] | 0.636 [0.364, 0.909] |
| cm2-full-v1-bm25 | 11 | 0.273 [0.000, 0.545] | 0.500 [0.227, 0.773] | 0.500 [0.227, 0.773] | 0.390 [0.158, 0.645] | 0.455 [0.182, 0.727] |

### Class level (IoU 0.5): tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| cm2-bm25 | 11 | 0.364 [0.091, 0.636] | 0.545 [0.273, 0.818] | 1,234 [382, 2,411] | 0.364 [0.091, 0.636] |
| cm2-bm25-code | 11 | 0.455 [0.182, 0.727] | 0.727 [0.455, 1.000] | 658 [362, 968] | 0.273 [0.000, 0.545] |
| cm2-bm25-code-usage | 11 | 0.500 [0.227, 0.773] | 0.727 [0.455, 1.000] | 931 [238, 1,851] | 0.273 [0.000, 0.545] |
| cm2-full-fn | 11 | 0.500 [0.227, 0.773] | 0.636 [0.364, 0.909] | 920 [175, 1,955] | 0.273 [0.000, 0.545] |
| cm2-full-tests-down | 11 | 0.636 [0.364, 0.909] | 0.727 [0.455, 1.000] | 793 [237, 1,703] | 0.273 [0.000, 0.545] |
| cm2-full-no-tests | 11 | 0.636 [0.364, 0.909] | 0.727 [0.455, 1.000] | 813 [238, 1,726] | 0.273 [0.000, 0.545] |
| cm2-full-v1-bm25 | 11 | 0.500 [0.227, 0.773] | 0.727 [0.455, 1.000] | 946 [227, 1,886] | 0.273 [0.000, 0.545] |

tokens_to_first is the mean over the tasks where the system found the right item, so each system's mean is over its own set of tasks. not_found_share shows how many it missed.

## Paired comparison with cm2-bm25

Difference = system - cm2-bm25 on the same tasks. A confidence interval and a p-value can disagree: the interval is about the mean, the Wilcoxon test is about signed ranks.

### Primary metrics (Holm correction over all 4 tests, significant at 0.05)

| system | metric | tasks | cm2-bm25 | system | difference [95% CI] | Wilcoxon p | Holm p | significant |
|---|---|---|---|---|---|---|---|---|
| cm2-bm25-code | function mrr | 12 | 0.203 | 0.347 | +0.144 [-0.076, +0.381] | 0.148 (exact) | 0.594 | no |
| cm2-bm25-code | function tokens_to_first (lower is better) | 8 | 2,945 | 1,180 | -1,765 [-3,866, +215] | 0.156 (exact) | 0.594 | no |
| cm2-bm25-code-usage | function mrr | 12 | 0.203 | 0.386 | +0.184 [-0.026, +0.417] | 0.250 (exact) | 0.594 | no |
| cm2-bm25-code-usage | function tokens_to_first (lower is better) | 7 | 2,842 | 479 | -2,364 [-4,608, -427] | 0.219 (exact) | 0.594 | no |

Tokens to the first right function are paired on the tasks both systems found:

| system | found by both | system only | cm2-bm25 only | neither |
|---|---|---|---|---|
| cm2-bm25-code | 8 | 2 | 0 | 2 |
| cm2-bm25-code-usage | 7 | 2 | 1 | 2 |

### Exploratory (raw p, no correction)

#### File level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| cm2-bm25-code | recall@1 | 13 | -0.115 [-0.423, +0.192] | 0.625 |
| cm2-bm25-code | recall@5 | 13 | +0.269 [+0.077, +0.500] | 0.125 |
| cm2-bm25-code | recall@10 | 13 | +0.115 [+0.000, +0.308] | 0.500 |
| cm2-bm25-code | mrr | 13 | +0.032 [-0.206, +0.266] | 0.756 |
| cm2-bm25-code | success@10 | 13 | +0.154 [+0.000, +0.385] | 0.500 |
| cm2-bm25-code | recall@budget1000 | 13 | +0.115 [-0.154, +0.385] | 0.625 |
| cm2-bm25-code | recall@budget4000 | 13 | +0.192 [+0.000, +0.423] | 0.250 |
| cm2-bm25-code | tokens_to_first (lower is better) | 10 | -540 [-1,465, +122] | 0.250 |
| cm2-bm25-code | not_found_share (lower is better) | 13 | +0.000 [-0.231, +0.231] | 1.000 |
| cm2-bm25-code-usage | recall@1 | 13 | -0.038 [-0.385, +0.308] | 1.000 |
| cm2-bm25-code-usage | recall@5 | 13 | +0.192 [-0.115, +0.500] | 0.375 |
| cm2-bm25-code-usage | recall@10 | 13 | +0.115 [+0.000, +0.308] | 0.500 |
| cm2-bm25-code-usage | mrr | 13 | +0.086 [-0.177, +0.351] | 0.451 |
| cm2-bm25-code-usage | success@10 | 13 | +0.154 [+0.000, +0.385] | 0.500 |
| cm2-bm25-code-usage | recall@budget1000 | 13 | +0.192 [-0.115, +0.500] | 0.375 |
| cm2-bm25-code-usage | recall@budget4000 | 13 | +0.269 [+0.077, +0.500] | 0.125 |
| cm2-bm25-code-usage | tokens_to_first (lower is better) | 10 | -222 [-1,360, +864] | 0.742 |
| cm2-bm25-code-usage | not_found_share (lower is better) | 13 | -0.077 [-0.308, +0.154] | 1.000 |
| cm2-full-fn | recall@1 | 13 | -0.038 [-0.385, +0.308] | 1.000 |
| cm2-full-fn | recall@5 | 13 | +0.192 [-0.115, +0.500] | 0.375 |
| cm2-full-fn | recall@10 | 13 | +0.115 [+0.000, +0.308] | 0.500 |
| cm2-full-fn | mrr | 13 | +0.107 [-0.165, +0.375] | 0.412 |
| cm2-full-fn | success@10 | 13 | +0.154 [+0.000, +0.385] | 0.500 |
| cm2-full-fn | recall@budget1000 | 13 | +0.192 [-0.115, +0.500] | 0.375 |
| cm2-full-fn | recall@budget4000 | 13 | +0.192 [-0.115, +0.500] | 0.375 |
| cm2-full-fn | tokens_to_first (lower is better) | 10 | -183 [-1,378, +1,009] | 0.742 |
| cm2-full-fn | not_found_share (lower is better) | 13 | -0.077 [-0.308, +0.154] | 1.000 |
| cm2-full-tests-down | recall@1 | 13 | -0.038 [-0.385, +0.308] | 1.000 |
| cm2-full-tests-down | recall@5 | 13 | +0.269 [-0.038, +0.577] | 0.219 |
| cm2-full-tests-down | recall@10 | 13 | +0.115 [+0.000, +0.308] | 0.500 |
| cm2-full-tests-down | mrr | 13 | +0.094 [-0.169, +0.357] | 0.451 |
| cm2-full-tests-down | success@10 | 13 | +0.154 [+0.000, +0.385] | 0.500 |
| cm2-full-tests-down | recall@budget1000 | 13 | +0.269 [-0.038, +0.577] | 0.219 |
| cm2-full-tests-down | recall@budget4000 | 13 | +0.269 [+0.077, +0.500] | 0.125 |
| cm2-full-tests-down | tokens_to_first (lower is better) | 10 | -333 [-1,453, +774] | 0.312 |
| cm2-full-tests-down | not_found_share (lower is better) | 13 | -0.077 [-0.308, +0.154] | 1.000 |
| cm2-full-no-tests | recall@1 | 13 | -0.038 [-0.385, +0.308] | 1.000 |
| cm2-full-no-tests | recall@5 | 13 | +0.269 [-0.038, +0.577] | 0.219 |
| cm2-full-no-tests | recall@10 | 13 | +0.115 [+0.000, +0.308] | 0.500 |
| cm2-full-no-tests | mrr | 13 | +0.113 [-0.155, +0.374] | 0.451 |
| cm2-full-no-tests | success@10 | 13 | +0.154 [+0.000, +0.385] | 0.500 |
| cm2-full-no-tests | recall@budget1000 | 13 | +0.269 [-0.038, +0.577] | 0.219 |
| cm2-full-no-tests | recall@budget4000 | 13 | +0.269 [+0.077, +0.500] | 0.125 |
| cm2-full-no-tests | tokens_to_first (lower is better) | 10 | -365 [-1,488, +743] | 0.312 |
| cm2-full-no-tests | not_found_share (lower is better) | 13 | -0.077 [-0.308, +0.154] | 1.000 |
| cm2-full-v1-bm25 | recall@1 | 13 | -0.038 [-0.385, +0.308] | 1.000 |
| cm2-full-v1-bm25 | recall@5 | 13 | +0.192 [-0.115, +0.500] | 0.375 |
| cm2-full-v1-bm25 | recall@10 | 13 | +0.115 [+0.000, +0.308] | 0.500 |
| cm2-full-v1-bm25 | mrr | 13 | +0.086 [-0.177, +0.351] | 0.451 |
| cm2-full-v1-bm25 | success@10 | 13 | +0.154 [+0.000, +0.385] | 0.500 |
| cm2-full-v1-bm25 | recall@budget1000 | 13 | +0.192 [-0.115, +0.500] | 0.375 |
| cm2-full-v1-bm25 | recall@budget4000 | 13 | +0.269 [+0.077, +0.500] | 0.125 |
| cm2-full-v1-bm25 | tokens_to_first (lower is better) | 10 | -210 [-1,367, +883] | 0.742 |
| cm2-full-v1-bm25 | not_found_share (lower is better) | 13 | -0.077 [-0.308, +0.154] | 1.000 |

#### Function level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| cm2-bm25-code | recall@1 | 12 | +0.083 [-0.083, +0.292] | 0.750 |
| cm2-bm25-code | recall@5 | 12 | +0.083 [-0.083, +0.292] | 0.750 |
| cm2-bm25-code | recall@10 | 12 | +0.292 [+0.083, +0.542] | 0.125 |
| cm2-bm25-code | success@10 | 12 | +0.250 [+0.000, +0.500] | 0.250 |
| cm2-bm25-code | recall@budget1000 | 12 | +0.125 [+0.000, +0.333] | 0.500 |
| cm2-bm25-code | recall@budget4000 | 12 | +0.333 [+0.042, +0.625] | 0.094 |
| cm2-bm25-code | not_found_share (lower is better) | 12 | -0.167 [-0.417, +0.000] | 0.500 |
| cm2-bm25-code-usage | recall@1 | 12 | +0.083 [-0.083, +0.292] | 0.750 |
| cm2-bm25-code-usage | recall@5 | 12 | +0.250 [+0.000, +0.542] | 0.188 |
| cm2-bm25-code-usage | recall@10 | 12 | +0.167 [-0.167, +0.500] | 0.500 |
| cm2-bm25-code-usage | success@10 | 12 | +0.083 [-0.250, +0.417] | 1.000 |
| cm2-bm25-code-usage | recall@budget1000 | 12 | +0.250 [+0.000, +0.542] | 0.188 |
| cm2-bm25-code-usage | recall@budget4000 | 12 | +0.333 [+0.042, +0.625] | 0.094 |
| cm2-bm25-code-usage | not_found_share (lower is better) | 12 | -0.083 [-0.333, +0.167] | 1.000 |
| cm2-full-fn | recall@1 | 12 | +0.083 [-0.083, +0.292] | 0.750 |
| cm2-full-fn | recall@5 | 12 | +0.250 [+0.000, +0.542] | 0.188 |
| cm2-full-fn | recall@10 | 12 | +0.167 [-0.167, +0.500] | 0.500 |
| cm2-full-fn | mrr | 12 | +0.211 [-0.005, +0.445] | 0.172 |
| cm2-full-fn | success@10 | 12 | +0.083 [-0.250, +0.417] | 1.000 |
| cm2-full-fn | recall@budget1000 | 12 | +0.250 [+0.000, +0.542] | 0.188 |
| cm2-full-fn | recall@budget4000 | 12 | +0.333 [+0.042, +0.625] | 0.094 |
| cm2-full-fn | tokens_to_first (lower is better) | 8 | -1,624 [-3,964, +632] | 0.375 |
| cm2-full-fn | not_found_share (lower is better) | 12 | -0.167 [-0.417, +0.000] | 0.500 |
| cm2-full-tests-down | recall@1 | 12 | +0.083 [-0.083, +0.292] | 0.750 |
| cm2-full-tests-down | recall@5 | 12 | +0.250 [+0.000, +0.542] | 0.188 |
| cm2-full-tests-down | recall@10 | 12 | +0.292 [+0.083, +0.542] | 0.125 |
| cm2-full-tests-down | mrr | 12 | +0.192 [-0.016, +0.421] | 0.129 |
| cm2-full-tests-down | success@10 | 12 | +0.250 [+0.000, +0.500] | 0.250 |
| cm2-full-tests-down | recall@budget1000 | 12 | +0.375 [+0.125, +0.625] | 0.062 |
| cm2-full-tests-down | recall@budget4000 | 12 | +0.333 [+0.042, +0.625] | 0.094 |
| cm2-full-tests-down | tokens_to_first (lower is better) | 7 | -2,522 [-4,683, -696] | 0.062 |
| cm2-full-tests-down | not_found_share (lower is better) | 12 | -0.083 [-0.333, +0.167] | 1.000 |
| cm2-full-no-tests | recall@1 | 12 | +0.042 [-0.125, +0.250] | 1.000 |
| cm2-full-no-tests | recall@5 | 12 | +0.250 [+0.000, +0.542] | 0.188 |
| cm2-full-no-tests | recall@10 | 12 | +0.292 [+0.083, +0.542] | 0.125 |
| cm2-full-no-tests | mrr | 12 | +0.135 [-0.040, +0.320] | 0.203 |
| cm2-full-no-tests | success@10 | 12 | +0.250 [+0.000, +0.500] | 0.250 |
| cm2-full-no-tests | recall@budget1000 | 12 | +0.375 [+0.125, +0.625] | 0.062 |
| cm2-full-no-tests | recall@budget4000 | 12 | +0.250 [+0.000, +0.542] | 0.188 |
| cm2-full-no-tests | tokens_to_first (lower is better) | 7 | -2,431 [-4,574, -627] | 0.062 |
| cm2-full-no-tests | not_found_share (lower is better) | 12 | -0.083 [-0.333, +0.167] | 1.000 |
| cm2-full-v1-bm25 | recall@1 | 12 | +0.083 [-0.083, +0.292] | 0.750 |
| cm2-full-v1-bm25 | recall@5 | 12 | +0.250 [+0.000, +0.542] | 0.188 |
| cm2-full-v1-bm25 | recall@10 | 12 | +0.167 [-0.167, +0.500] | 0.500 |
| cm2-full-v1-bm25 | mrr | 12 | +0.185 [-0.023, +0.418] | 0.203 |
| cm2-full-v1-bm25 | success@10 | 12 | +0.083 [-0.250, +0.417] | 1.000 |
| cm2-full-v1-bm25 | recall@budget1000 | 12 | +0.250 [+0.000, +0.542] | 0.188 |
| cm2-full-v1-bm25 | recall@budget4000 | 12 | +0.333 [+0.042, +0.625] | 0.094 |
| cm2-full-v1-bm25 | tokens_to_first (lower is better) | 8 | -1,725 [-3,956, +412] | 0.375 |
| cm2-full-v1-bm25 | not_found_share (lower is better) | 12 | -0.167 [-0.417, +0.000] | 0.500 |

#### Class level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| cm2-bm25-code | recall@1 | 11 | -0.045 [-0.318, +0.227] | 1.000 |
| cm2-bm25-code | recall@5 | 11 | +0.045 [-0.273, +0.364] | 1.000 |
| cm2-bm25-code | recall@10 | 11 | +0.182 [+0.000, +0.455] | 0.500 |
| cm2-bm25-code | mrr | 11 | -0.018 [-0.262, +0.218] | 1.000 |
| cm2-bm25-code | success@10 | 11 | +0.182 [+0.000, +0.455] | 0.500 |
| cm2-bm25-code | recall@budget1000 | 11 | +0.091 [-0.182, +0.364] | 1.000 |
| cm2-bm25-code | recall@budget4000 | 11 | +0.182 [+0.000, +0.455] | 0.500 |
| cm2-bm25-code | tokens_to_first (lower is better) | 7 | -645 [-1,786, +226] | 0.312 |
| cm2-bm25-code | not_found_share (lower is better) | 11 | -0.091 [-0.273, +0.000] | 1.000 |
| cm2-bm25-code-usage | recall@1 | 11 | +0.045 [-0.273, +0.364] | 1.000 |
| cm2-bm25-code-usage | recall@5 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm2-bm25-code-usage | recall@10 | 11 | -0.045 [-0.409, +0.318] | 1.000 |
| cm2-bm25-code-usage | mrr | 11 | +0.078 [-0.226, +0.377] | 0.688 |
| cm2-bm25-code-usage | success@10 | 11 | -0.091 [-0.455, +0.273] | 1.000 |
| cm2-bm25-code-usage | recall@budget1000 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm2-bm25-code-usage | recall@budget4000 | 11 | +0.182 [+0.000, +0.455] | 0.500 |
| cm2-bm25-code-usage | tokens_to_first (lower is better) | 7 | -271 [-1,881, +1,328] | 0.844 |
| cm2-bm25-code-usage | not_found_share (lower is better) | 11 | -0.091 [-0.273, +0.000] | 1.000 |
| cm2-full-fn | recall@1 | 11 | +0.045 [-0.273, +0.364] | 1.000 |
| cm2-full-fn | recall@5 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm2-full-fn | recall@10 | 11 | -0.045 [-0.409, +0.318] | 1.000 |
| cm2-full-fn | mrr | 11 | +0.105 [-0.209, +0.408] | 0.734 |
| cm2-full-fn | success@10 | 11 | -0.091 [-0.455, +0.273] | 1.000 |
| cm2-full-fn | recall@budget1000 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm2-full-fn | recall@budget4000 | 11 | +0.091 [-0.182, +0.364] | 1.000 |
| cm2-full-fn | tokens_to_first (lower is better) | 7 | -214 [-1,908, +1,529] | 0.844 |
| cm2-full-fn | not_found_share (lower is better) | 11 | -0.091 [-0.273, +0.000] | 1.000 |
| cm2-full-tests-down | recall@1 | 11 | +0.045 [-0.273, +0.364] | 1.000 |
| cm2-full-tests-down | recall@5 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm2-full-tests-down | recall@10 | 11 | +0.091 [-0.182, +0.364] | 1.000 |
| cm2-full-tests-down | mrr | 11 | +0.085 [-0.218, +0.381] | 0.578 |
| cm2-full-tests-down | success@10 | 11 | +0.091 [-0.182, +0.364] | 1.000 |
| cm2-full-tests-down | recall@budget1000 | 11 | +0.273 [-0.091, +0.636] | 0.375 |
| cm2-full-tests-down | recall@budget4000 | 11 | +0.182 [+0.000, +0.455] | 0.500 |
| cm2-full-tests-down | tokens_to_first (lower is better) | 7 | -430 [-1,995, +1,187] | 0.438 |
| cm2-full-tests-down | not_found_share (lower is better) | 11 | -0.091 [-0.273, +0.000] | 1.000 |
| cm2-full-no-tests | recall@1 | 11 | +0.045 [-0.273, +0.364] | 1.000 |
| cm2-full-no-tests | recall@5 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm2-full-no-tests | recall@10 | 11 | +0.091 [-0.182, +0.364] | 1.000 |
| cm2-full-no-tests | mrr | 11 | +0.083 [-0.220, +0.381] | 0.578 |
| cm2-full-no-tests | success@10 | 11 | +0.091 [-0.182, +0.364] | 1.000 |
| cm2-full-no-tests | recall@budget1000 | 11 | +0.273 [-0.091, +0.636] | 0.375 |
| cm2-full-no-tests | recall@budget4000 | 11 | +0.182 [+0.000, +0.455] | 0.500 |
| cm2-full-no-tests | tokens_to_first (lower is better) | 7 | -407 [-1,964, +1,209] | 0.438 |
| cm2-full-no-tests | not_found_share (lower is better) | 11 | -0.091 [-0.273, +0.000] | 1.000 |
| cm2-full-v1-bm25 | recall@1 | 11 | +0.045 [-0.273, +0.364] | 1.000 |
| cm2-full-v1-bm25 | recall@5 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm2-full-v1-bm25 | recall@10 | 11 | -0.045 [-0.409, +0.318] | 1.000 |
| cm2-full-v1-bm25 | mrr | 11 | +0.077 [-0.226, +0.376] | 0.688 |
| cm2-full-v1-bm25 | success@10 | 11 | -0.091 [-0.455, +0.273] | 1.000 |
| cm2-full-v1-bm25 | recall@budget1000 | 11 | +0.136 [-0.227, +0.500] | 0.625 |
| cm2-full-v1-bm25 | recall@budget4000 | 11 | +0.182 [+0.000, +0.455] | 0.500 |
| cm2-full-v1-bm25 | tokens_to_first (lower is better) | 7 | -254 [-1,892, +1,355] | 0.844 |
| cm2-full-v1-bm25 | not_found_share (lower is better) | 11 | -0.091 [-0.273, +0.000] | 1.000 |

## Groups (means and task counts, no intervals)

### By identifier in query

Function mrr:

| group | tasks | cm2-bm25 | cm2-bm25-code | cm2-bm25-code-usage | cm2-full-fn | cm2-full-tests-down | cm2-full-no-tests | cm2-full-v1-bm25 |
|---|---|---|---|---|---|---|---|---|
| false | 8 | 0.145 (8) | 0.142 (8) | 0.205 (8) | 0.243 (8) | 0.216 (8) | 0.194 (8) | 0.205 (8) |
| true | 5 | 0.317 (4) | 0.756 (4) | 0.750 (4) | 0.755 (4) | 0.750 (4) | 0.625 (4) | 0.756 (4) |

Function recall@10:

| group | tasks | cm2-bm25 | cm2-bm25-code | cm2-bm25-code-usage | cm2-full-fn | cm2-full-tests-down | cm2-full-no-tests | cm2-full-v1-bm25 |
|---|---|---|---|---|---|---|---|---|
| false | 8 | 0.250 (8) | 0.625 (8) | 0.438 (8) | 0.438 (8) | 0.625 (8) | 0.625 (8) | 0.438 (8) |
| true | 5 | 0.500 (4) | 0.625 (4) | 0.625 (4) | 0.625 (4) | 0.625 (4) | 0.625 (4) | 0.625 (4) |

File recall@10:

| group | tasks | cm2-bm25 | cm2-bm25-code | cm2-bm25-code-usage | cm2-full-fn | cm2-full-tests-down | cm2-full-no-tests | cm2-full-v1-bm25 |
|---|---|---|---|---|---|---|---|---|
| false | 8 | 0.625 (8) | 0.750 (8) | 0.750 (8) | 0.750 (8) | 0.750 (8) | 0.750 (8) | 0.750 (8) |
| true | 5 | 0.900 (5) | 1.000 (5) | 1.000 (5) | 1.000 (5) | 1.000 (5) | 1.000 (5) | 1.000 (5) |

Function tokens_to_first (lower is better):

| group | tasks | cm2-bm25 | cm2-bm25-code | cm2-bm25-code-usage | cm2-full-fn | cm2-full-tests-down | cm2-full-no-tests | cm2-full-v1-bm25 |
|---|---|---|---|---|---|---|---|---|
| false | 8 | 3,411 (4) | 944 (6) | 1,127 (6) | 1,018 (6) | 874 (6) | 1,480 (6) | 1,088 (6) |
| true | 5 | 2,480 (4) | 1,610 (4) | 127 (3) | 1,904 (4) | 127 (3) | 167 (3) | 1,652 (4) |

### By repo

Function mrr:

| group | tasks | cm2-bm25 | cm2-bm25-code | cm2-bm25-code-usage | cm2-full-fn | cm2-full-tests-down | cm2-full-no-tests | cm2-full-v1-bm25 |
|---|---|---|---|---|---|---|---|---|
| mwaskom/seaborn | 2 | 0.035 (2) | 0.512 (2) | 0.500 (2) | 0.510 (2) | 0.500 (2) | 0.250 (2) | 0.511 (2) |
| pallets/flask | 1 | 0.000 (1) | 0.091 (1) | 0.042 (1) | 0.045 (1) | 0.056 (1) | 0.026 (1) | 0.048 (1) |
| psf/requests | 5 | 0.250 (5) | 0.387 (5) | 0.507 (5) | 0.567 (5) | 0.507 (5) | 0.480 (5) | 0.507 (5) |
| pytest-dev/pytest | 5 | 0.278 (4) | 0.278 (4) | 0.266 (4) | 0.266 (4) | 0.286 (4) | 0.281 (4) | 0.264 (4) |

Function recall@10:

| group | tasks | cm2-bm25 | cm2-bm25-code | cm2-bm25-code-usage | cm2-full-fn | cm2-full-tests-down | cm2-full-no-tests | cm2-full-v1-bm25 |
|---|---|---|---|---|---|---|---|---|
| mwaskom/seaborn | 2 | 0.000 (2) | 0.250 (2) | 0.250 (2) | 0.250 (2) | 0.250 (2) | 0.250 (2) | 0.250 (2) |
| pallets/flask | 1 | 0.000 (1) | 0.000 (1) | 0.000 (1) | 0.000 (1) | 0.000 (1) | 0.000 (1) | 0.000 (1) |
| psf/requests | 5 | 0.400 (5) | 1.000 (5) | 0.900 (5) | 0.900 (5) | 1.000 (5) | 1.000 (5) | 0.900 (5) |
| pytest-dev/pytest | 5 | 0.500 (4) | 0.500 (4) | 0.250 (4) | 0.250 (4) | 0.500 (4) | 0.500 (4) | 0.250 (4) |

File recall@10:

| group | tasks | cm2-bm25 | cm2-bm25-code | cm2-bm25-code-usage | cm2-full-fn | cm2-full-tests-down | cm2-full-no-tests | cm2-full-v1-bm25 |
|---|---|---|---|---|---|---|---|---|
| mwaskom/seaborn | 2 | 0.750 (2) | 1.000 (2) | 1.000 (2) | 1.000 (2) | 1.000 (2) | 1.000 (2) | 1.000 (2) |
| pallets/flask | 1 | 1.000 (1) | 1.000 (1) | 1.000 (1) | 1.000 (1) | 1.000 (1) | 1.000 (1) | 1.000 (1) |
| psf/requests | 5 | 0.800 (5) | 1.000 (5) | 1.000 (5) | 1.000 (5) | 1.000 (5) | 1.000 (5) | 1.000 (5) |
| pytest-dev/pytest | 5 | 0.600 (5) | 0.600 (5) | 0.600 (5) | 0.600 (5) | 0.600 (5) | 0.600 (5) | 0.600 (5) |

Function tokens_to_first (lower is better):

| group | tasks | cm2-bm25 | cm2-bm25-code | cm2-bm25-code-usage | cm2-full-fn | cm2-full-tests-down | cm2-full-no-tests | cm2-full-v1-bm25 |
|---|---|---|---|---|---|---|---|---|
| mwaskom/seaborn | 2 | 4,658 (2) | 3,102 (2) | 143 (1) | 3,690 (2) | 143 (1) | 263 (1) | 3,185 (2) |
| pallets/flask | 1 | - (0) | 1,522 (1) | 3,075 (1) | 2,929 (1) | 2,666 (1) | 5,780 (1) | 2,659 (1) |
| psf/requests | 5 | 3,198 (4) | 641 (5) | 376 (5) | 275 (5) | 376 (5) | 449 (5) | 376 (5) |
| pytest-dev/pytest | 5 | 728 (2) | 586 (2) | 1,020 (2) | 1,020 (2) | 466 (2) | 546 (2) | 1,112 (2) |

- language: all 13 tasks are 'python', so there is no table.

- issue date: all 13 tasks are 'before 2026-07-01', so there is no table.

## IoU check (function level)

| system | mrr @ IoU 0.3 | mrr @ IoU 0.5 | mrr @ IoU 0.7 | recall@10 @ IoU 0.3 | recall@10 @ IoU 0.5 | recall@10 @ IoU 0.7 |
|---|---|---|---|---|---|---|
| cm2-bm25 | 0.203 | 0.203 | 0.203 | 0.333 | 0.333 | 0.333 |
| cm2-bm25-code | 0.347 | 0.347 | 0.347 | 0.625 | 0.625 | 0.625 |
| cm2-bm25-code-usage | 0.386 | 0.386 | 0.386 | 0.500 | 0.500 | 0.500 |
| cm2-full-fn | 0.413 | 0.413 | 0.413 | 0.500 | 0.500 | 0.500 |
| cm2-full-tests-down | 0.394 | 0.394 | 0.394 | 0.625 | 0.625 | 0.625 |
| cm2-full-no-tests | 0.338 | 0.338 | 0.338 | 0.625 | 0.625 | 0.625 |
| cm2-full-v1-bm25 | 0.388 | 0.388 | 0.388 | 0.500 | 0.500 | 0.500 |

## Latency and size

| system | search ms (median) | search ms (p95) | build s (mean) | update s (median) | items re-embedded (mean) | index MB | files failed |
|---|---|---|---|---|---|---|---|
| cm2-bm25 | 36.1 | 305.5 | 655.7 | 336.8 | 2,037.1 | 89.5 | 0.0 |
| cm2-bm25-code | 296.6 | 2,509.4 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 |
| cm2-bm25-code-usage | 38.5 | 129.6 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 |
| cm2-full-fn | 36.6 | 127.7 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 |
| cm2-full-tests-down | 34.6 | 120.2 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 |
| cm2-full-no-tests | 30.7 | 95.4 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 |
| cm2-full-v1-bm25 | 34.9 | 122.1 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 | same as cm2-bm25 |

Index MB = 10^6 bytes. Systems with the same index settings share one index.

## Task counts

13 tasks scored. Tasks left out at each level:

| system | level | left out | reasons |
|---|---|---|---|
| cm2-bm25 | class | 2 | no gold at this level: 2 |
| cm2-bm25 | function | 1 | no gold at this level: 1 |
| cm2-bm25-code | class | 2 | no gold at this level: 2 |
| cm2-bm25-code | function | 1 | no gold at this level: 1 |
| cm2-bm25-code-usage | class | 2 | no gold at this level: 2 |
| cm2-bm25-code-usage | function | 1 | no gold at this level: 1 |
| cm2-full-fn | class | 2 | no gold at this level: 2 |
| cm2-full-fn | function | 1 | no gold at this level: 1 |
| cm2-full-tests-down | class | 2 | no gold at this level: 2 |
| cm2-full-tests-down | function | 1 | no gold at this level: 1 |
| cm2-full-no-tests | class | 2 | no gold at this level: 2 |
| cm2-full-no-tests | function | 1 | no gold at this level: 1 |
| cm2-full-v1-bm25 | class | 2 | no gold at this level: 2 |
| cm2-full-v1-bm25 | function | 1 | no gold at this level: 1 |
