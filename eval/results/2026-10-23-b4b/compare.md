# Update vs. rebuild check (F3 B4, Decision 5)

- A: `2026-10-23-b4b-update` (index mode update, codemem 93f7db1413ec, cmeval 93f7db1413ec)
- B: `2026-10-23-b4b-rebuild` (index mode rebuild, codemem 93f7db1413ec, cmeval 93f7db1413ec)
- The check covers the codemem code named above. Results from other codemem code need their own check.
- Rules: for each system, at least 95% of tasks have the same set of top-10 hits (by location); every metric's mean differs by less than 0.01; token counts by less than 1%.

## Result: PASS

| system | tasks | same top 10 | largest metric difference | largest token difference | result |
|---|---|---|---|---|---|
| grep | 12 | 12 (100%) | 0.0000 | 0.00% | pass |
| grep-fn | 12 | 12 (100%) | 0.0000 | 0.00% | pass |
| grep-fn-plus | 12 | 12 (100%) | 0.0000 | 0.00% | pass |
| cm-bm25 | 12 | 12 (100%) | 0.0000 | 0.36% | pass |
| cm-bm25-code | 12 | 12 (100%) | 0.0000 | 0.12% | pass |
| cm-bm25-code-usage | 12 | 12 (100%) | 0.0000 | 0.22% | pass |
