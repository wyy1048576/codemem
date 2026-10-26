# Update vs. rebuild check (F3 B4, Decision 5)

- A: `2026-10-25-subset-v3-final` (index mode update, codemem 96bc2bcac5b6, cmeval 96bc2bcac5b6)
- B: `2026-10-25-subset-v3-rebuild` (index mode rebuild, codemem 96bc2bcac5b6, cmeval 96bc2bcac5b6)
- The check covers the codemem code named above. Results from other codemem code need their own check.
- Rules: for each system, at least 95% of tasks have the same set of top-10 hits (by location); every metric's mean differs by less than 0.01; token counts by less than 1%.

## Result: PASS

| system | tasks | same top 10 | largest metric difference | largest token difference | result |
|---|---|---|---|---|---|
| cm3-bm25 | 13 | 13 (100%) | 0.0000 | 0.15% | pass |
| cm3-bm25-code | 13 | 13 (100%) | 0.0000 | 0.06% | pass |
| cm3-full | 13 | 13 (100%) | 0.0000 | 0.14% | pass |
| cm3-full-v2-weights | 13 | 13 (100%) | 0.0000 | 0.11% | pass |
| cm3-full-all-words | 13 | 13 (100%) | 0.0000 | 0.12% | pass |
| cm3-full-drop-common | 13 | 13 (100%) | 0.0000 | 0.05% | pass |
