# Measuring market and waiver pages

Restart Django after updating the code. No migration is needed for profiling.
`SERVER_TIMING_ENABLED` defaults to the value of `DEBUG`. To explicitly enable
it in PowerShell before starting the application:

```powershell
$env:SERVER_TIMING_ENABLED = 'true'
.\.venv\Scripts\python.exe manage.py runserver
```

Alternatively add `SERVER_TIMING_ENABLED=true` to the deployment environment.
With `DEBUG=False`, timing headers require a logged-in staff account
(`is_staff=True`). Regular users do not receive detailed timings. Set the flag
to `false` to disable detailed profiling. Existing slow-request logging remains
active. Profiled responses are marked private/no-store.

In browser DevTools, open Network, clear old entries and reload one page. Select
the market document request or the waiver document / `part=warm` / `part=moves`
request, then open Timing. The Server Timing section shows milliseconds. The
raw `Server-Timing` response header is also available in Headers.

| Metric | Meaning |
| --- | --- |
| total | Elapsed time through the existing request middleware |
| db | Time inside Django's default database SQL execution wrapper |
| db_queries | Query count, stored as a description rather than a duration |
| nfl_week | Current-week lookup when no week was supplied, including any cache/API work |
| market_setup | Initial request/auth/league setup and current-week lookup |
| market_players_filters | Player/team loading, row creation and filtering |
| market_weekly_consensus | Weekly external saved projections: retrieval and scoring |
| market_adp | ADP retrieval and assignment |
| market_weekly_saved | Our saved weekly projections: retrieval and scoring |
| market_ros_consensus | External remaining-season saved projections and scoring |
| market_ros_saved | Our remaining-season saved projections and scoring |
| market_rank_sort | Ranking, sorting, URL construction and pagination |
| market_scoring | Aggregate time in the three scoring helpers across weekly/season stages |
| waiver_pool | Full waiver pool lookup/build, including application cache access |
| waiver_forecasts | Saved forecast loading and availability processing on a pool cache miss |
| waiver_values | Player value computation/loading on a pool cache miss |
| waiver_horizons | Pickup horizon cache lookup/computation |
| waiver_moves | Suggested move computation |
| render | Template rendering, including template context processors and lazy queries |

Metrics overlap: `db` and `market_scoring` occur inside page stages; waiver
forecasts/values occur inside `waiver_pool`; `nfl_week` is part of setup. Do not
sum every displayed number. A missing stage may indicate an early return or an
application cache hit. Query counts help identify repeated per-player queries.

Database execution time includes client/server SQL round trips, but not every
connection setup, result fetch, JSON decoding or Django object creation cost.
It is not the same number as server-only `EXPLAIN ANALYZE`. The gap between
`total` and `db` is not pure Python CPU time: it can include connections,
fetching, cache access, external requests and rendering. Middleware before the
profiler, proxy queueing, network latency and streaming bodies are not timed.

Repeat the same league/week/filter five times, recording the first request
separately from subsequent requests. Disabling browser cache does not clear
Redis or Django's application caches; profiling does not clear them either.
Compare the same environment before and after any optimization. Slow-request
logs include `stages_ms`, total duration, database time and query count; no SQL,
query-string filters, or credentials are recorded by this profiler.
