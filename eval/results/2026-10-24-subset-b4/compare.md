# Update vs. rebuild check (F3 B4, Decision 5)

- A: `2026-10-24-dev50-v2` (index mode update, codemem 31c0f990d380, cmeval 31c0f990d380)
- B: `2026-10-24-subset-rebuild` (index mode rebuild, codemem 18d3b77ac96b, cmeval 18d3b77ac96b)
- The check covers the codemem code named above. Results from other codemem code need their own check.
- Rules: for each system, at least 95% of tasks have the same set of top-10 hits (by location); every metric's mean differs by less than 0.01; token counts by less than 1%.

- Warning: the runs use different codemem code: 31c0f990d38054b5ed041d881516af59c03db247 vs. 18d3b77ac96b5c0ff7db650668f1503415eb63e1

## Result: PASS

| system | tasks | same top 10 | largest metric difference | largest token difference | result |
|---|---|---|---|---|---|
| cm2-bm25 | 13 | 13 (100%) | 0.0000 | 0.13% | pass |
| cm2-bm25-code | 13 | 13 (100%) | 0.0000 | 0.08% | pass |
| cm2-bm25-code-usage | 13 | 13 (100%) | 0.0000 | 0.14% | pass |
| cm2-full-fn | 13 | 13 (100%) | 0.0000 | 0.12% | pass |
| cm2-full-tests-down | 13 | 13 (100%) | 0.0000 | 0.11% | pass |
| cm2-full-no-tests | 13 | 13 (100%) | 0.0000 | 0.11% | pass |
| cm2-full-v1-bm25 | 13 | 13 (100%) | 0.0000 | 0.19% | pass |
