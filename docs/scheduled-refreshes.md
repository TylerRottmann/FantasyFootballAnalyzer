# Production NFL and Sleeper refreshes

Apply Django migrations against the deployed application's PostgreSQL database.
Migration 0013 creates the scheduler table and 0014 seeds its UTC schedules.

```sh
python manage.py migrate
python manage.py run_scheduled_refreshes --list
```

Install [the cron entry](../deploy/fantasy-football-refresh.cron) on the
production host under `/etc/cron.d/fantasy-football-refresh`. Replace the
example service account, checkout and Python paths with the deployed values.
Run under the same environment as the web process, including its
`DJANGO_SETTINGS_MODULE`, production `DB_*` settings and `REDIS_URL`. Django
can load shared configuration from the checkout's `.env`. If the web host
injects environment variables, provide the same values to cron through the
deployment's service configuration or a launcher. Ensure the log destination
is writable by the cron account and covered by log rotation.

Set `FFA_REFRESH_ARTIFACT_DIR` to an existing absolute directory mounted
persistently for the scheduler and web workers. Give the scheduler write
access and workers read access. Both processes read kicker and injury
profiles from this directory when configured. Seed it with the existing
`analyzer/data/injury_duration_profiles.json` and copy an existing
`kicker_weekly.json` if one is available. The scheduled builders publish JSON
by atomic rename. Run the weekly job once during the regular season to
populate the shared files from the configured database and upstream feeds.

| Seeded job | UTC cadence |
| --- | --- |
| `external-cache` | Every five minutes. Refreshes NFL week and Sleeper league playoff metadata. League API work increases with connected league count. |
| `player-metadata` | 12:20 daily during the regular season and preseason. Tuesday offseason. |
| `injuries` | Every three hours at :35 Thursday through Monday during the regular season. Tuesday and Wednesday at 15:35. |
| `adp` | 12:50 Tuesday during the regular season. Daily in preseason and the July–September draft window outside the regular season. |
| `market` | 14:10 daily during the regular season. Refreshes the current week through Week 18. |
| `weekly` | Tuesday at 16:00. Wednesday at 16:00 retries an unfinished period. Week 1 is eligible daily at 16:00 from two days before the opener through the end of Week 1. |

The weekly pipeline ensures the daily player-metadata import succeeded and imports the NFL schedule, then
refreshes player context with weekly stats and snap counts. It imports team
stats before D/ST, then opportunity and advanced team data. After rebuilding
the kicker snapshot, it builds team and matchup features, refreshes Sleeper
market projections, and generates active-week model projections, market ranks, and
Boom/Bust in that order. Each step must succeed before the next starts. The
standalone GitHub Actions Boom/Bust schedule is retired. All times are UTC
throughout the year. The weekly slot follows nflverse's nightly updates
for player and team stats. Injury/depth refreshes use Sleeper's filtered
player endpoint. [nflverse update schedule](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html) Â· [Sleeper player endpoint](https://docs.sleeper.com/#fetch-all-players).

Week 1 uses the season's NFL schedule and available historical inputs.
Team and matchup snapshots begin in Week 2 because the builders require
prior games. Injury-duration profiles rebuild on the first weekly run each month with completed games and again at
regular-season closeout. The
closeout runs after Sleeper switches to postseason and includes Week 18
statistics. The legacy `load_current_player`, `load_current_players` and
`load_player_stats` scripts are excluded from the schedule.

The scheduler logs UTC start/end timestamps and command output, including
import counts and failures. Rerun against the active season/week from the
same production environment:

```sh
python manage.py run_scheduled_refreshes --job weekly
```

Replace `weekly` with any seeded job name. A failed step stops the pipeline
and leaves previously committed, validated steps available for rerun.
PostgreSQL prevents concurrent import pipelines with a two-hour lease.
A process killed before releasing its lease can be retried after the lease
expires. The cache job has its own lease.
