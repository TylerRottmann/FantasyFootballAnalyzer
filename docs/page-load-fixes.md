# Market and waiver load fixes — November 18, 2026

The weekly market page was retrieving and scoring all remaining-season
projections and ADP even though its template only displays weekly projections.
It now skips those queries on normal weekly requests. Explicit legacy season
or ADP sorting still loads the data required for that sort. The long-term page
retains its totals, completeness checks, ranking and buy/sell logic.

Saved market projections now retrieve only fields used for scoring, without
joining player/team rows that the view already loaded. Player position is
passed from those loaded rows into the scoring helper. This also avoids
transferring duplicate player metadata across every remaining week.

Waiver lineup evaluation now computes eligible slot bits once per player
instead of once per player per lineup state. This applies to both known-score
lineups and unknown-player reservations, preserving all possibilities and
existing suggestion logic. No candidate limits or scoring thresholds changed.

## Before/after checks

`scripts/benchmark_page_fixes.py` compares the pre-fix market/waiver modules in
commit `d51dad3` with the working tree. Live market reads run inside a read-only
transaction, using an existing 2026 league and week 11. Each route was measured
twice in before/after order; this is a small sample, not a production load test.
The first before run includes connection/cache warmup effects.

| Workload | Before | After |
| --- | --- | --- |
| Weekly market view data preparation | 9.71 s / 5.09 s | 0.80 s / 0.82 s |
| Weekly data queries | 9 | 5 |
| Long-term market view data preparation | 5.11 s / 6.06 s | 4.32 s / 3.86 s |
| Synthetic waiver horizon + suggestion evaluation | 6.62 s | 1.61 s |

Compared all displayed player rankings and values for each market route, not
just the first page. Outputs matched. Fields not displayed on the weekly page
(ADP and remaining-season totals/signals) are intentionally not computed there.
The synthetic waiver workload used 14 owned players, 4 available players, eight
starter slots (including FLEX and SUPER_FLEX), and eight forecast weeks. Tags
and suggestion cards matched exactly before/after. This is a CPU benchmark,
not a measurement of the live waiver endpoint.

These timings exclude HTML rendering, authentication/league selector work,
network download and browser rendering. Real page loads will take longer.
No permanent database schema or data was modified for these fixes or tests.
Raw results are in `page-fix-benchmark.json`.

Validation: four market database regression tests, two exhaustive lineup tests,
and eight timing instrumentation tests. The existing waiver suite previously
had five failures and three errors; those were reproduced against committed
pre-fix code and remain outside these changes.

Restart the application with the updated code; no migration is needed for
these page-load fixes. Existing Server-Timing instrumentation remains available
to measure the page stages in development or for authorized staff.
