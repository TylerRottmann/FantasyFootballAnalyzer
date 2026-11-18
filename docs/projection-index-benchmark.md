# Saved projection index benchmark — November 18, 2026

The proposed `(season, model_version, week)` index improves broad saved-projection
retrieval in this experiment. It offers little benefit to the tested league
power-ranking query. No permanent tables, indexes, or application behavior were
changed, and no migration was applied.

## Method

Executed real Django ORM query shapes from waiver forecasts, power rankings and
market rankings with `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`. Used the latest
saved season (2026), model `v2_stat`, 3,211 fantasy-position player IDs and 421
distinct player IDs from the league with the most roster entries. Week 11 is a
fixed representative midseason case; weeks 1 and 18 test broad/narrow ranges.
The market test uses the initial unfiltered player pool.

Collected a live baseline inside a read-only transaction. Copied all 119,817
projection rows to a PostgreSQL temporary table with all existing indexes and
analyzed the copy. Ran the same queries before and after adding the candidate
index, then dropped the candidate and repeated the baseline. Each case has one
warmup and five measured executions. The temporary work was in a single
transaction with `ON COMMIT DROP`, compatible with transaction pooling. The
connection was closed after testing.

The copy retained the primary key, player FK index, player/season/week index,
season/week index, and player/season/week/model unique index. Player joins used
the existing public player table. No query plans were forced.

## Results

Median server execution times in milliseconds:

| Query | Live existing indexes | Copy existing indexes | Copy plus candidate | Copy reduction |
| --- | ---: | ---: | ---: | ---: |
| Waivers, weeks 11–18 | 17.536 | 23.186 | 15.841 | 32% |
| Market, week 11 | 12.001 | 14.017 | 5.965 | 57% |
| Market, weeks 11–18 | 33.082 | 37.825 | 30.325 | 20% |
| Power rankings, weeks 11–18 | 7.392 | 13.307 | 13.118 | 1% |
| Waivers, week 18 | 9.312 | 12.863 | 1.441 | 89% |
| Waivers, weeks 1–18 | 69.220 | 85.176 | 36.303 | 57%* |

*Full-season baseline was unstable when repeated after dropping the index:
92–1,181 ms versus the initial 85 ms median. Do not treat its percentage as a
reliable improvement estimate. Other repeat baseline medians stayed close to
their initial values: 23.403, 14.116, 37.506, 13.145 and 12.269 ms respectively.

The candidate was selected for all tested broad-pool queries. For the weeks
11–18 waiver query, the old season/week scan returned 25,612 rows and discarded
24,726 rows of other model versions; the new index returned those 25,612 rows
without filtering out other model versions. Power rankings retained its existing
player/season/week/model index, matching the negligible timing difference.

## Interpretation and limits

The evidence supports considering this index for waiver and market retrieval.
Typical midseason gains here were about 7–8 ms per affected database query, so
these results do not imply a dramatic page-load improvement. Power rankings
already has a suitable access path.

Temporary PostgreSQL tables use local buffers, while public tables use shared
buffers. The recorded buffer counts show local reads in several copy tests;
this differs from production caching and can magnify the candidate's benefit.
Use the copy-before/copy-after numbers for the experiment, not live-before versus
copy-after as a production speedup claim. This was one session on one database
snapshot, not a controlled cold-cache benchmark or a permanent staging clone.

`EXPLAIN ANALYZE` measures server execution under instrumentation, not result
transfer, Django object construction, scoring, cache hits or page rendering.
Rows and JSON payloads still have to be returned and processed. Defense queries,
write/import overhead and index storage size were not measured. If deployed,
recheck actual production timings and index use before deciding whether an
overlapping existing index can be retired.

Raw timings and summarized plans: `projection-index-benchmark.json`.
Reproduce with `.venv\Scripts\python.exe scripts/benchmark_projection_index.py`.
The script needs network/database access and permission to create temporary
tables; it creates no permanent schema objects.
