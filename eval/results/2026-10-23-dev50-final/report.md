# Results: 2026-10-23-dev50-final

- Tasks: `swebv-dev50.jsonl` (sha256 b327c2015aca), split dev, 50 tasks scored
- Systems: grep, grep-fn, grep-fn-plus, cm-bm25, cm-bm25-code, cm-bm25-code-usage; baseline for the paired tests: grep-fn-plus
- Index mode: update; hits per search: 50
- Code: cmeval c6b2933cc762, codemem d5c2013aa8a5
- Machine: macOS-26.5-arm64-arm-64bit
- Tokens: anthropic:claude-opus-5-5, request overhead of 8 tokens taken off each count; scored 2026-10-24T01:22:38+00:00
- Intervals: 95% percentile bootstrap, 10,000 resamples, seed 20261023
- Merged part: grep, grep-fn, grep-fn-plus from run `2026-10-23-dev50-grep2` (cmeval c6b2933cc762, macOS-26.5-arm64-arm-64bit, ended 2026-10-24T01:22:11+00:00)
- Merged part: cm-bm25, cm-bm25-code, cm-bm25-code-usage from run `2026-10-23-dev50` (cmeval d5c2013aa8a5, macOS-26.5-arm64-arm-64bit, ended 2026-10-23T19:49:37+00:00)
- Dev split: these numbers guide development. p-values here are guidance only.

## Main results

### File level: accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | 50 | 0.007 [0.000, 0.020] | 0.197 [0.097, 0.310] | 0.330 [0.210, 0.460] | 0.125 [0.078, 0.183] | 0.320 [0.200, 0.460] |
| grep-fn | 50 | 0.040 [0.000, 0.100] | 0.183 [0.083, 0.293] | 0.367 [0.240, 0.500] | 0.135 [0.078, 0.203] | 0.360 [0.220, 0.500] |
| grep-fn-plus | 50 | 0.297 [0.183, 0.420] | 0.603 [0.473, 0.730] | 0.760 [0.647, 0.867] | 0.495 [0.384, 0.607] | 0.700 [0.560, 0.820] |
| cm-bm25 | 50 | 0.280 [0.160, 0.410] | 0.527 [0.390, 0.660] | 0.637 [0.513, 0.757] | 0.452 [0.342, 0.564] | 0.560 [0.420, 0.700] |
| cm-bm25-code | 50 | 0.317 [0.197, 0.440] | 0.600 [0.477, 0.723] | 0.703 [0.583, 0.817] | 0.519 [0.408, 0.630] | 0.640 [0.500, 0.760] |
| cm-bm25-code-usage | 50 | 0.410 [0.287, 0.537] | 0.718 [0.602, 0.830] | 0.848 [0.752, 0.932] | 0.628 [0.520, 0.737] | 0.800 [0.680, 0.900] |

### File level: tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | 50 | 0.117 [0.040, 0.207] | 0.330 [0.210, 0.460] | 7,332 [5,015, 9,873] | 0.300 [0.180, 0.420] |
| grep-fn | 50 | 0.100 [0.020, 0.180] | 0.260 [0.140, 0.380] | 6,120 [3,046, 11,383] | 0.480 [0.340, 0.620] |
| grep-fn-plus | 50 | 0.430 [0.303, 0.560] | 0.740 [0.623, 0.850] | 1,773 [1,154, 2,480] | 0.120 [0.040, 0.220] |
| cm-bm25 | 50 | 0.590 [0.457, 0.717] | 0.673 [0.550, 0.790] | 1,156 [660, 1,723] | 0.160 [0.060, 0.260] |
| cm-bm25-code | 50 | 0.563 [0.440, 0.687] | 0.780 [0.673, 0.880] | 854 [518, 1,255] | 0.120 [0.040, 0.220] |
| cm-bm25-code-usage | 50 | 0.718 [0.605, 0.827] | 0.853 [0.760, 0.937] | 1,000 [581, 1,488] | 0.020 [0.000, 0.060] |

### Function level (IoU 0.5): accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a | n/a |
| grep-fn | 46 | 0.022 [0.000, 0.065] | 0.098 [0.022, 0.185] | 0.101 [0.025, 0.196] | 0.068 [0.025, 0.125] | 0.087 [0.022, 0.174] |
| grep-fn-plus | 46 | 0.163 [0.076, 0.264] | 0.278 [0.167, 0.402] | 0.448 [0.317, 0.582] | 0.316 [0.204, 0.437] | 0.370 [0.239, 0.522] |
| cm-bm25 | 46 | 0.116 [0.040, 0.207] | 0.255 [0.139, 0.380] | 0.313 [0.190, 0.442] | 0.229 [0.130, 0.337] | 0.261 [0.130, 0.391] |
| cm-bm25-code | 46 | 0.208 [0.104, 0.326] | 0.360 [0.236, 0.488] | 0.422 [0.289, 0.555] | 0.334 [0.217, 0.458] | 0.348 [0.217, 0.478] |
| cm-bm25-code-usage | 46 | 0.262 [0.149, 0.384] | 0.440 [0.308, 0.572] | 0.456 [0.324, 0.585] | 0.423 [0.300, 0.547] | 0.370 [0.239, 0.500] |

### Function level (IoU 0.5): tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a |
| grep-fn | 46 | 0.054 [0.000, 0.120] | 0.101 [0.025, 0.196] | 4,674 [3,311, 6,014] | 0.630 [0.478, 0.761] |
| grep-fn-plus | 46 | 0.262 [0.153, 0.388] | 0.473 [0.344, 0.605] | 1,958 [1,324, 2,638] | 0.326 [0.196, 0.457] |
| cm-bm25 | 46 | 0.277 [0.157, 0.406] | 0.367 [0.241, 0.500] | 1,721 [951, 2,586] | 0.478 [0.326, 0.630] |
| cm-bm25-code | 46 | 0.360 [0.236, 0.488] | 0.549 [0.413, 0.683] | 1,072 [672, 1,517] | 0.348 [0.217, 0.478] |
| cm-bm25-code-usage | 46 | 0.445 [0.315, 0.575] | 0.622 [0.489, 0.750] | 1,411 [861, 2,027] | 0.196 [0.087, 0.326] |

### Class level (IoU 0.5): accuracy

| system | tasks | recall@1 | recall@5 | recall@10 | mrr | success@10 |
|---|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a | n/a |
| grep-fn | 34 | 0.059 [0.000, 0.147] | 0.103 [0.015, 0.206] | 0.172 [0.059, 0.294] | 0.108 [0.037, 0.200] | 0.147 [0.029, 0.265] |
| grep-fn-plus | 34 | 0.265 [0.132, 0.397] | 0.412 [0.260, 0.569] | 0.515 [0.353, 0.676] | 0.404 [0.262, 0.553] | 0.471 [0.294, 0.647] |
| cm-bm25 | 34 | 0.162 [0.059, 0.294] | 0.377 [0.230, 0.529] | 0.436 [0.284, 0.593] | 0.309 [0.192, 0.436] | 0.382 [0.235, 0.559] |
| cm-bm25-code | 34 | 0.216 [0.098, 0.353] | 0.377 [0.230, 0.534] | 0.529 [0.373, 0.686] | 0.360 [0.227, 0.498] | 0.471 [0.294, 0.647] |
| cm-bm25-code-usage | 34 | 0.314 [0.172, 0.461] | 0.534 [0.382, 0.691] | 0.554 [0.407, 0.706] | 0.489 [0.346, 0.630] | 0.471 [0.294, 0.647] |

### Class level (IoU 0.5): tokens

| system | tasks | recall@budget1000 | recall@budget4000 | tokens_to_first (lower is better) | not_found_share (lower is better) |
|---|---|---|---|---|---|
| grep | - | n/a | n/a | n/a | n/a |
| grep-fn | 34 | 0.088 [0.000, 0.206] | 0.172 [0.059, 0.294] | 4,405 [2,987, 5,867] | 0.529 [0.353, 0.706] |
| grep-fn-plus | 34 | 0.373 [0.225, 0.525] | 0.574 [0.417, 0.725] | 1,970 [1,047, 3,099] | 0.265 [0.118, 0.412] |
| cm-bm25 | 34 | 0.422 [0.265, 0.583] | 0.539 [0.382, 0.696] | 1,233 [612, 2,004] | 0.353 [0.206, 0.500] |
| cm-bm25-code | 34 | 0.412 [0.260, 0.569] | 0.632 [0.475, 0.784] | 763 [460, 1,120] | 0.324 [0.176, 0.471] |
| cm-bm25-code-usage | 34 | 0.544 [0.392, 0.696] | 0.716 [0.569, 0.853] | 1,143 [575, 1,823] | 0.147 [0.029, 0.265] |

tokens_to_first is the mean over the tasks where the system found the right item, so each system's mean is over its own set of tasks. not_found_share shows how many it missed.

## Paired comparison with grep-fn-plus

Difference = system - grep-fn-plus on the same tasks. A confidence interval and a p-value can disagree: the interval is about the mean, the Wilcoxon test is about signed ranks.

### Primary metrics (Holm correction over all 6 tests, significant at 0.05)

| system | metric | tasks | grep-fn-plus | system | difference [95% CI] | Wilcoxon p | Holm p | significant |
|---|---|---|---|---|---|---|---|---|
| cm-bm25 | function mrr | 46 | 0.316 | 0.229 | -0.087 [-0.212, +0.033] | 0.086 (normal) | 0.514 | no |
| cm-bm25 | function tokens_to_first (lower is better) | 22 | 2,033 | 1,800 | -233 [-899, +428] | 0.581 (normal) | 1.000 | no |
| cm-bm25-code | function mrr | 46 | 0.316 | 0.334 | +0.018 [-0.130, +0.161] | 0.779 (normal) | 1.000 | no |
| cm-bm25-code | function tokens_to_first (lower is better) | 26 | 1,709 | 1,130 | -579 [-1,401, +245] | 0.136 (exact) | 0.588 | no |
| cm-bm25-code-usage | function mrr | 46 | 0.316 | 0.423 | +0.107 [-0.044, +0.254] | 0.118 (normal) | 0.588 | no |
| cm-bm25-code-usage | function tokens_to_first (lower is better) | 29 | 1,933 | 1,461 | -472 [-1,479, +545] | 0.183 (exact) | 0.588 | no |

Tokens to the first right function are paired on the tasks both systems found:

| system | found by both | system only | grep-fn-plus only | neither |
|---|---|---|---|---|
| cm-bm25 | 22 | 2 | 9 | 13 |
| cm-bm25-code | 26 | 4 | 5 | 11 |
| cm-bm25-code-usage | 29 | 8 | 2 | 7 |

### Exploratory (raw p, no correction)

#### File level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep | recall@1 | 50 | -0.290 [-0.410, -0.180] | <0.001 |
| grep | recall@5 | 50 | -0.407 [-0.567, -0.243] | <0.001 |
| grep | recall@10 | 50 | -0.430 [-0.583, -0.270] | <0.001 |
| grep | mrr | 50 | -0.370 [-0.486, -0.257] | <0.001 |
| grep | success@10 | 50 | -0.380 [-0.540, -0.220] | <0.001 |
| grep | recall@budget1000 | 50 | -0.313 [-0.467, -0.157] | 0.001 |
| grep | recall@budget4000 | 50 | -0.410 [-0.573, -0.240] | <0.001 |
| grep | tokens_to_first (lower is better) | 33 | +5,745 [+3,159, +8,535] | <0.001 |
| grep | not_found_share (lower is better) | 50 | +0.180 [+0.040, +0.320] | 0.013 |
| grep-fn | recall@1 | 50 | -0.257 [-0.387, -0.137] | <0.001 |
| grep-fn | recall@5 | 50 | -0.420 [-0.550, -0.293] | <0.001 |
| grep-fn | recall@10 | 50 | -0.393 [-0.540, -0.250] | <0.001 |
| grep-fn | mrr | 50 | -0.360 [-0.471, -0.250] | <0.001 |
| grep-fn | success@10 | 50 | -0.340 [-0.500, -0.180] | <0.001 |
| grep-fn | recall@budget1000 | 50 | -0.330 [-0.477, -0.183] | <0.001 |
| grep-fn | recall@budget4000 | 50 | -0.480 [-0.627, -0.333] | <0.001 |
| grep-fn | tokens_to_first (lower is better) | 25 | +4,971 [+1,796, +10,244] | <0.001 |
| grep-fn | not_found_share (lower is better) | 50 | +0.360 [+0.220, +0.500] | <0.001 |
| cm-bm25 | recall@1 | 50 | -0.017 [-0.150, +0.120] | 1.000 |
| cm-bm25 | recall@5 | 50 | -0.077 [-0.227, +0.070] | 0.477 |
| cm-bm25 | recall@10 | 50 | -0.123 [-0.257, +0.007] | 0.084 |
| cm-bm25 | mrr | 50 | -0.043 [-0.176, +0.091] | 0.539 |
| cm-bm25 | success@10 | 50 | -0.140 [-0.280, +0.000] | 0.052 |
| cm-bm25 | recall@budget1000 | 50 | +0.160 [-0.003, +0.323] | 0.042 |
| cm-bm25 | recall@budget4000 | 50 | -0.067 [-0.207, +0.067] | 0.326 |
| cm-bm25 | tokens_to_first (lower is better) | 38 | -565 [-1,401, +220] | 0.044 |
| cm-bm25 | not_found_share (lower is better) | 50 | +0.040 [-0.080, +0.160] | 0.527 |
| cm-bm25-code | recall@1 | 50 | +0.020 [-0.140, +0.177] | 0.798 |
| cm-bm25-code | recall@5 | 50 | -0.003 [-0.157, +0.150] | 0.984 |
| cm-bm25-code | recall@10 | 50 | -0.057 [-0.173, +0.057] | 0.310 |
| cm-bm25-code | mrr | 50 | +0.024 [-0.108, +0.155] | 0.679 |
| cm-bm25-code | success@10 | 50 | -0.060 [-0.180, +0.060] | 0.317 |
| cm-bm25-code | recall@budget1000 | 50 | +0.133 [-0.033, +0.297] | 0.144 |
| cm-bm25-code | recall@budget4000 | 50 | +0.040 [-0.073, +0.153] | 0.517 |
| cm-bm25-code | tokens_to_first (lower is better) | 41 | -816 [-1,472, -226] | 0.002 |
| cm-bm25-code | not_found_share (lower is better) | 50 | +0.000 [-0.100, +0.100] | 1.000 |
| cm-bm25-code-usage | recall@1 | 50 | +0.113 [-0.050, +0.277] | 0.201 |
| cm-bm25-code-usage | recall@5 | 50 | +0.115 [-0.050, +0.280] | 0.201 |
| cm-bm25-code-usage | recall@10 | 50 | +0.088 [-0.030, +0.208] | 0.179 |
| cm-bm25-code-usage | mrr | 50 | +0.133 [-0.014, +0.277] | 0.077 |
| cm-bm25-code-usage | success@10 | 50 | +0.100 [-0.020, +0.240] | 0.132 |
| cm-bm25-code-usage | recall@budget1000 | 50 | +0.288 [+0.110, +0.463] | 0.004 |
| cm-bm25-code-usage | recall@budget4000 | 50 | +0.113 [-0.027, +0.250] | 0.157 |
| cm-bm25-code-usage | tokens_to_first (lower is better) | 43 | -916 [-1,778, -122] | 0.003 |
| cm-bm25-code-usage | not_found_share (lower is better) | 50 | -0.100 [-0.200, +0.000] | 0.059 |

#### Function level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep-fn | recall@1 | 46 | -0.141 [-0.236, -0.062] | 0.005 |
| grep-fn | recall@5 | 46 | -0.180 [-0.312, -0.051] | 0.020 |
| grep-fn | recall@10 | 46 | -0.346 [-0.491, -0.206] | <0.001 |
| grep-fn | mrr | 46 | -0.248 [-0.365, -0.141] | <0.001 |
| grep-fn | success@10 | 46 | -0.283 [-0.435, -0.152] | <0.001 |
| grep-fn | recall@budget1000 | 46 | -0.208 [-0.336, -0.090] | 0.004 |
| grep-fn | recall@budget4000 | 46 | -0.372 [-0.513, -0.230] | <0.001 |
| grep-fn | tokens_to_first (lower is better) | 16 | +2,366 [+651, +4,078] | 0.027 |
| grep-fn | not_found_share (lower is better) | 46 | +0.304 [+0.152, +0.457] | <0.001 |
| cm-bm25 | recall@1 | 46 | -0.047 [-0.167, +0.065] | 0.491 |
| cm-bm25 | recall@5 | 46 | -0.022 [-0.161, +0.118] | 0.837 |
| cm-bm25 | recall@10 | 46 | -0.135 [-0.264, -0.011] | 0.054 |
| cm-bm25 | success@10 | 46 | -0.109 [-0.239, +0.000] | 0.096 |
| cm-bm25 | recall@budget1000 | 46 | +0.014 [-0.120, +0.149] | 0.828 |
| cm-bm25 | recall@budget4000 | 46 | -0.106 [-0.236, +0.021] | 0.145 |
| cm-bm25 | not_found_share (lower is better) | 46 | +0.152 [+0.022, +0.283] | 0.035 |
| cm-bm25-code | recall@1 | 46 | +0.045 [-0.090, +0.183] | 0.466 |
| cm-bm25-code | recall@5 | 46 | +0.083 [-0.077, +0.241] | 0.280 |
| cm-bm25-code | recall@10 | 46 | -0.026 [-0.171, +0.116] | 0.770 |
| cm-bm25-code | success@10 | 46 | -0.022 [-0.174, +0.109] | 0.763 |
| cm-bm25-code | recall@budget1000 | 46 | +0.098 [-0.065, +0.257] | 0.209 |
| cm-bm25-code | recall@budget4000 | 46 | +0.075 [-0.038, +0.195] | 0.170 |
| cm-bm25-code | not_found_share (lower is better) | 46 | +0.022 [-0.109, +0.152] | 0.739 |
| cm-bm25-code-usage | recall@1 | 46 | +0.099 [-0.044, +0.244] | 0.162 |
| cm-bm25-code-usage | recall@5 | 46 | +0.162 [-0.009, +0.329] | 0.068 |
| cm-bm25-code-usage | recall@10 | 46 | +0.008 [-0.143, +0.157] | 0.902 |
| cm-bm25-code-usage | success@10 | 46 | +0.000 [-0.152, +0.152] | 1.000 |
| cm-bm25-code-usage | recall@budget1000 | 46 | +0.183 [+0.011, +0.350] | 0.043 |
| cm-bm25-code-usage | recall@budget4000 | 46 | +0.149 [-0.013, +0.306] | 0.080 |
| cm-bm25-code-usage | not_found_share (lower is better) | 46 | -0.130 [-0.261, +0.000] | 0.058 |

#### Class level

| system | metric | tasks | difference [95% CI] | Wilcoxon p |
|---|---|---|---|---|
| grep-fn | recall@1 | 34 | -0.206 [-0.353, -0.059] | 0.022 |
| grep-fn | recall@5 | 34 | -0.309 [-0.451, -0.172] | 0.001 |
| grep-fn | recall@10 | 34 | -0.343 [-0.534, -0.152] | 0.004 |
| grep-fn | mrr | 34 | -0.297 [-0.447, -0.150] | <0.001 |
| grep-fn | success@10 | 34 | -0.324 [-0.500, -0.118] | 0.005 |
| grep-fn | recall@budget1000 | 34 | -0.284 [-0.446, -0.123] | 0.005 |
| grep-fn | recall@budget4000 | 34 | -0.402 [-0.574, -0.230] | <0.001 |
| grep-fn | tokens_to_first (lower is better) | 15 | +2,691 [+994, +4,463] | 0.026 |
| grep-fn | not_found_share (lower is better) | 34 | +0.265 [+0.088, +0.441] | 0.007 |
| cm-bm25 | recall@1 | 34 | -0.103 [-0.265, +0.059] | 0.329 |
| cm-bm25 | recall@5 | 34 | -0.034 [-0.201, +0.137] | 0.801 |
| cm-bm25 | recall@10 | 34 | -0.078 [-0.230, +0.078] | 0.410 |
| cm-bm25 | mrr | 34 | -0.096 [-0.244, +0.061] | 0.131 |
| cm-bm25 | success@10 | 34 | -0.088 [-0.265, +0.088] | 0.317 |
| cm-bm25 | recall@budget1000 | 34 | +0.049 [-0.108, +0.221] | 0.444 |
| cm-bm25 | recall@budget4000 | 34 | -0.034 [-0.211, +0.142] | 0.871 |
| cm-bm25 | tokens_to_first (lower is better) | 19 | -220 [-1,187, +692] | 0.768 |
| cm-bm25 | not_found_share (lower is better) | 34 | +0.088 [-0.088, +0.265] | 0.317 |
| cm-bm25-code | recall@1 | 34 | -0.049 [-0.186, +0.083] | 0.472 |
| cm-bm25-code | recall@5 | 34 | -0.034 [-0.201, +0.137] | 0.781 |
| cm-bm25-code | recall@10 | 34 | +0.015 [-0.162, +0.191] | 0.837 |
| cm-bm25-code | mrr | 34 | -0.045 [-0.184, +0.089] | 0.672 |
| cm-bm25-code | success@10 | 34 | +0.000 [-0.176, +0.176] | 1.000 |
| cm-bm25-code | recall@budget1000 | 34 | +0.039 [-0.137, +0.216] | 0.711 |
| cm-bm25-code | recall@budget4000 | 34 | +0.059 [-0.069, +0.196] | 0.293 |
| cm-bm25-code | tokens_to_first (lower is better) | 21 | -685 [-1,535, +84] | 0.026 |
| cm-bm25-code | not_found_share (lower is better) | 34 | +0.059 [-0.088, +0.206] | 0.414 |
| cm-bm25-code-usage | recall@1 | 34 | +0.049 [-0.123, +0.216] | 0.598 |
| cm-bm25-code-usage | recall@5 | 34 | +0.123 [-0.069, +0.314] | 0.165 |
| cm-bm25-code-usage | recall@10 | 34 | +0.039 [-0.132, +0.216] | 0.720 |
| cm-bm25-code-usage | mrr | 34 | +0.084 [-0.080, +0.240] | 0.183 |
| cm-bm25-code-usage | success@10 | 34 | +0.000 [-0.176, +0.176] | 1.000 |
| cm-bm25-code-usage | recall@budget1000 | 34 | +0.172 [-0.025, +0.363] | 0.090 |
| cm-bm25-code-usage | recall@budget4000 | 34 | +0.142 [-0.020, +0.304] | 0.123 |
| cm-bm25-code-usage | tokens_to_first (lower is better) | 24 | -1,218 [-2,340, -175] | 0.004 |
| cm-bm25-code-usage | not_found_share (lower is better) | 34 | -0.118 [-0.265, +0.000] | 0.102 |

## Groups (means and task counts, no intervals)

### By identifier in query

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm-bm25 | cm-bm25-code | cm-bm25-code-usage |
|---|---|---|---|---|---|---|
| false | 23 | 0.054 (21) | 0.188 (21) | 0.189 (21) | 0.265 (21) | 0.346 (21) |
| true | 27 | 0.080 (25) | 0.424 (25) | 0.263 (25) | 0.391 (25) | 0.488 (25) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm-bm25 | cm-bm25-code | cm-bm25-code-usage |
|---|---|---|---|---|---|---|
| false | 23 | 0.103 (21) | 0.441 (21) | 0.305 (21) | 0.376 (21) | 0.404 (21) |
| true | 27 | 0.100 (25) | 0.453 (25) | 0.320 (25) | 0.460 (25) | 0.500 (25) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm-bm25 | cm-bm25-code | cm-bm25-code-usage |
|---|---|---|---|---|---|---|---|
| false | 23 | 0.391 (23) | 0.348 (23) | 0.754 (23) | 0.609 (23) | 0.681 (23) | 0.779 (23) |
| true | 27 | 0.278 (27) | 0.383 (27) | 0.765 (27) | 0.660 (27) | 0.722 (27) | 0.907 (27) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm-bm25 | cm-bm25-code | cm-bm25-code-usage |
|---|---|---|---|---|---|---|
| false | 23 | 5,206 (10) | 2,727 (14) | 2,121 (10) | 1,138 (12) | 1,597 (16) |
| true | 27 | 3,914 (7) | 1,325 (17) | 1,436 (14) | 1,028 (18) | 1,269 (21) |

### By repo

Function mrr:

| group | tasks | grep-fn | grep-fn-plus | cm-bm25 | cm-bm25-code | cm-bm25-code-usage |
|---|---|---|---|---|---|---|
| astropy/astropy | 5 | 0.000 (5) | 0.107 (5) | 0.222 (5) | 0.340 (5) | 0.519 (5) |
| django/django | 5 | 0.000 (4) | 0.300 (4) | 0.375 (4) | 0.500 (4) | 0.500 (4) |
| matplotlib/matplotlib | 5 | 0.009 (5) | 0.012 (5) | 0.000 (5) | 0.067 (5) | 0.212 (5) |
| mwaskom/seaborn | 2 | 0.250 (2) | 0.538 (2) | 0.049 (2) | 0.519 (2) | 0.523 (2) |
| pallets/flask | 1 | 0.053 (1) | 0.143 (1) | 0.000 (1) | 0.067 (1) | 0.036 (1) |
| psf/requests | 5 | 0.271 (5) | 0.436 (5) | 0.236 (5) | 0.315 (5) | 0.429 (5) |
| pydata/xarray | 5 | 0.085 (5) | 0.577 (5) | 0.115 (5) | 0.300 (5) | 0.482 (5) |
| pylint-dev/pylint | 5 | 0.018 (4) | 0.250 (4) | 0.281 (4) | 0.375 (4) | 0.356 (4) |
| pytest-dev/pytest | 5 | 0.018 (4) | 0.375 (4) | 0.300 (4) | 0.265 (4) | 0.259 (4) |
| scikit-learn/scikit-learn | 4 | 0.167 (3) | 0.437 (3) | 0.076 (3) | 0.422 (3) | 0.515 (3) |
| sphinx-doc/sphinx | 4 | 0.025 (4) | 0.163 (4) | 0.381 (4) | 0.510 (4) | 0.458 (4) |
| sympy/sympy | 4 | 0.000 (4) | 0.500 (4) | 0.500 (4) | 0.319 (4) | 0.583 (4) |

Function recall@10:

| group | tasks | grep-fn | grep-fn-plus | cm-bm25 | cm-bm25-code | cm-bm25-code-usage |
|---|---|---|---|---|---|---|
| astropy/astropy | 5 | 0.000 (5) | 0.500 (5) | 0.500 (5) | 0.500 (5) | 0.500 (5) |
| django/django | 5 | 0.000 (4) | 0.292 (4) | 0.333 (4) | 0.333 (4) | 0.333 (4) |
| matplotlib/matplotlib | 5 | 0.000 (5) | 0.000 (5) | 0.000 (5) | 0.200 (5) | 0.200 (5) |
| mwaskom/seaborn | 2 | 0.250 (2) | 0.250 (2) | 0.000 (2) | 0.250 (2) | 0.250 (2) |
| pallets/flask | 1 | 0.000 (1) | 1.000 (1) | 0.000 (1) | 0.000 (1) | 0.000 (1) |
| psf/requests | 5 | 0.400 (5) | 0.600 (5) | 0.400 (5) | 0.700 (5) | 0.700 (5) |
| pydata/xarray | 5 | 0.200 (5) | 0.800 (5) | 0.200 (5) | 0.600 (5) | 0.600 (5) |
| pylint-dev/pylint | 5 | 0.000 (4) | 0.250 (4) | 0.500 (4) | 0.500 (4) | 0.562 (4) |
| pytest-dev/pytest | 5 | 0.000 (4) | 0.417 (4) | 0.500 (4) | 0.250 (4) | 0.250 (4) |
| scikit-learn/scikit-learn | 4 | 0.333 (3) | 1.000 (3) | 0.333 (3) | 0.667 (3) | 0.667 (3) |
| sphinx-doc/sphinx | 4 | 0.042 (4) | 0.400 (4) | 0.350 (4) | 0.350 (4) | 0.433 (4) |
| sympy/sympy | 4 | 0.000 (4) | 0.292 (4) | 0.292 (4) | 0.292 (4) | 0.542 (4) |

File recall@10:

| group | tasks | grep | grep-fn | grep-fn-plus | cm-bm25 | cm-bm25-code | cm-bm25-code-usage |
|---|---|---|---|---|---|---|---|
| astropy/astropy | 5 | 0.000 (5) | 0.200 (5) | 0.700 (5) | 0.700 (5) | 0.900 (5) | 1.000 (5) |
| django/django | 5 | 0.000 (5) | 0.000 (5) | 0.800 (5) | 0.900 (5) | 1.000 (5) | 0.800 (5) |
| matplotlib/matplotlib | 5 | 0.400 (5) | 0.067 (5) | 0.733 (5) | 0.600 (5) | 0.733 (5) | 0.733 (5) |
| mwaskom/seaborn | 2 | 0.500 (2) | 0.500 (2) | 1.000 (2) | 0.750 (2) | 0.750 (2) | 1.000 (2) |
| pallets/flask | 1 | 1.000 (1) | 1.000 (1) | 1.000 (1) | 0.000 (1) | 1.000 (1) | 1.000 (1) |
| psf/requests | 5 | 1.000 (5) | 1.000 (5) | 1.000 (5) | 0.800 (5) | 1.000 (5) | 1.000 (5) |
| pydata/xarray | 5 | 0.600 (5) | 0.800 (5) | 1.000 (5) | 0.500 (5) | 0.600 (5) | 0.800 (5) |
| pylint-dev/pylint | 5 | 0.000 (5) | 0.400 (5) | 0.400 (5) | 0.467 (5) | 0.467 (5) | 0.717 (5) |
| pytest-dev/pytest | 5 | 0.000 (5) | 0.000 (5) | 0.600 (5) | 0.600 (5) | 0.600 (5) | 0.600 (5) |
| scikit-learn/scikit-learn | 4 | 0.500 (4) | 0.750 (4) | 1.000 (4) | 0.750 (4) | 0.750 (4) | 1.000 (4) |
| sphinx-doc/sphinx | 4 | 0.250 (4) | 0.250 (4) | 0.583 (4) | 0.500 (4) | 0.417 (4) | 0.917 (4) |
| sympy/sympy | 4 | 0.375 (4) | 0.000 (4) | 0.625 (4) | 0.625 (4) | 0.375 (4) | 0.875 (4) |

Function tokens_to_first (lower is better):

| group | tasks | grep-fn | grep-fn-plus | cm-bm25 | cm-bm25-code | cm-bm25-code-usage |
|---|---|---|---|---|---|---|
| astropy/astropy | 5 | - (0) | 3,040 (4) | 807 (3) | 460 (3) | 1,814 (5) |
| django/django | 5 | - (0) | 441 (2) | 461 (2) | 141 (2) | 134 (2) |
| matplotlib/matplotlib | 5 | 8,950 (1) | 4,352 (1) | - (0) | 404 (1) | 1,278 (2) |
| mwaskom/seaborn | 2 | 609 (1) | 1,982 (2) | 3,533 (2) | 2,234 (2) | 1,887 (2) |
| pallets/flask | 1 | 5,749 (1) | 2,026 (1) | - (0) | 2,726 (1) | 5,016 (1) |
| psf/requests | 5 | 4,001 (5) | 3,144 (5) | 3,081 (4) | 808 (4) | 829 (5) |
| pydata/xarray | 5 | 5,357 (4) | 1,570 (5) | 1,706 (2) | 1,378 (4) | 2,351 (5) |
| pylint-dev/pylint | 5 | 5,092 (1) | 449 (1) | 859 (2) | 272 (2) | 1,191 (4) |
| pytest-dev/pytest | 5 | 7,192 (2) | 352 (2) | 540 (2) | 1,568 (2) | 2,502 (2) |
| scikit-learn/scikit-learn | 4 | 812 (1) | 1,636 (3) | 2,411 (2) | 1,227 (3) | 1,339 (3) |
| sphinx-doc/sphinx | 4 | 2,429 (1) | 2,290 (3) | 2,398 (3) | 1,256 (3) | 309 (3) |
| sympy/sympy | 4 | - (0) | 405 (2) | 176 (2) | 1,011 (3) | 301 (3) |

- language: all 50 tasks are 'python', so there is no table.

- issue date: all 50 tasks are 'before 2026-07-01', so there is no table.

## IoU check (function level)

| system | mrr @ IoU 0.3 | mrr @ IoU 0.5 | mrr @ IoU 0.7 | recall@10 @ IoU 0.3 | recall@10 @ IoU 0.5 | recall@10 @ IoU 0.7 |
|---|---|---|---|---|---|---|
| grep-fn | 0.068 | 0.068 | 0.068 | 0.101 | 0.101 | 0.101 |
| grep-fn-plus | 0.316 | 0.316 | 0.316 | 0.455 | 0.448 | 0.448 |
| cm-bm25 | 0.229 | 0.229 | 0.229 | 0.313 | 0.313 | 0.313 |
| cm-bm25-code | 0.334 | 0.334 | 0.334 | 0.422 | 0.422 | 0.422 |
| cm-bm25-code-usage | 0.423 | 0.423 | 0.423 | 0.456 | 0.456 | 0.456 |

## Latency and size

| system | search ms (median) | search ms (p95) | build s (mean) | update s (median) | items re-embedded (mean) | index MB | files failed |
|---|---|---|---|---|---|---|---|
| grep | 37.3 | 221.2 | 0.0 | 0.0 | - | 0.0 | 0.0 |
| grep-fn | 264.0 | 765.1 | same as grep | same as grep | same as grep | same as grep | same as grep |
| grep-fn-plus | 451.1 | 1,422.5 | same as grep | same as grep | same as grep | same as grep | same as grep |
| cm-bm25 | 101.5 | 297.5 | 232.3 | 64.4 | 6,072.4 | 398.3 | 0.0 |
| cm-bm25-code | 184.4 | 439.4 | same as cm-bm25 | same as cm-bm25 | same as cm-bm25 | same as cm-bm25 | same as cm-bm25 |
| cm-bm25-code-usage | 143.4 | 388.7 | same as cm-bm25 | same as cm-bm25 | same as cm-bm25 | same as cm-bm25 | same as cm-bm25 |

Index MB = 10^6 bytes. Systems with the same index settings share one index.
This run is merged from separate runs, so search times of different parts come from different sessions.

## Task counts

50 tasks scored. Tasks left out at each level:

| system | level | left out | reasons |
|---|---|---|---|
| grep | class | 50 | file-granularity system: 50 |
| grep | function | 50 | file-granularity system: 50 |
| grep-fn | class | 16 | no gold at this level: 16 |
| grep-fn | function | 4 | no gold at this level: 4 |
| grep-fn-plus | class | 16 | no gold at this level: 16 |
| grep-fn-plus | function | 4 | no gold at this level: 4 |
| cm-bm25 | class | 16 | no gold at this level: 16 |
| cm-bm25 | function | 4 | no gold at this level: 4 |
| cm-bm25-code | class | 16 | no gold at this level: 16 |
| cm-bm25-code | function | 4 | no gold at this level: 4 |
| cm-bm25-code-usage | class | 16 | no gold at this level: 16 |
| cm-bm25-code-usage | function | 4 | no gold at this level: 4 |
