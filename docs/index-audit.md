# Database index audit — November 16, 2026

Compared application ORM queries, raw SQL feature builders and imports with the
configured PostgreSQL database's `pg_indexes`, table statistics and representative
`EXPLAIN` plans. No live schema changes were made.

## Prepared indexes

| Table | Columns | Query paths |
| --- | --- | --- |
| player_weekly_stats | season, season_type, week | WR/TE feature totals, injury history, waiver value, Boom/Bust datasets |
| team_weekly_stats | season, season_type, week | WR/TE team pass totals, kicker season data, defensive rankings |
| analyzer_playerinjuryreport | season, week | Weekly availability cache, waiver injury history |
| analyzer_playersnapcount | season, week | Waiver recent participation, season injury history |
| fantasy_roster_players | roster_id | Roster prefetches, lineup/trade pages, import deletion |
| fantasy_roster_players | player_id | Player roster membership checks |

Existing stats uniqueness indexes start with player/team, so they do not provide
the same access path for season-wide batches. The roster table only has partial
unique indexes `(roster_id, player_id) WHERE player_id IS NOT NULL` and
`(roster_id, team_id) WHERE team_id IS NOT NULL`. A roster-only read cannot use
either predicate; a player lookup also lacks a player-leading index.

The representative player stats query (`season=2026`, `season_type='REG'`,
`week<11`) uses a sequential scan (estimated cost 1483.55, 24,260 estimated live
rows in the table). A roster-only lookup scans all 1,820 estimated live rows.
Team season reads scan the existing team-leading index; the new index puts the
batch predicates first. Injury and snap queries also currently use sequential
scans. These may remain appropriate when a query selects a large share of rows;
index availability does not guarantee a faster plan.

## Existing coverage and deferred changes

- Player/team histories and opportunity-stat joins have entity/season/week
  uniqueness indexes already. No additional per-entity history indexes added.
- Fantasy and defense projections have both entity/week uniqueness indexes and
  season/week lookup indexes. Market projections, market ranks and Boom/Bust
  week lookups also have relevant indexes.
- League/roster/player platform identities have platform/external-id and
  entity/platform unique indexes. ADP lookups include player IDs and use the
  existing player/season/scoring-format index.
- League matchup queries can use the league index. Current league/table sizes
  do not justify adding every possible matchup filter combination.
- Teams and schedules are small and already have primary/unique lookup indexes.
  Player name substring searches would need a separately evaluated trigram or
  expression index; a plain name B-tree would not fix `icontains`.
- Some existing indexes overlap unique-index prefixes (for example,
  `player_projection_idx`). Leave removal to a separate usage/constraint audit.

## Deployment and verification

The two new migrations create and drop indexes concurrently, outside a
transaction, to allow normal writes during PostgreSQL index builds. Unmanaged
legacy tables require explicit SQL plus migration state operations; a normal
`AddIndex` alone would silently skip those tables.

Apply with `python manage.py migrate` through the normal deployment process.
These migrations assume the legacy stats and roster tables already exist, as
the application's earlier unmanaged models do. If a concurrent build fails,
inspect for an invalid index and remove it before retrying the migration.

After applying, compare `EXPLAIN (ANALYZE, BUFFERS)` on representative real
queries and monitor index usage and write overhead. No post-index speedup has
been measured; the audit collected baseline plans only. Table scan counters
are cumulative and do not by themselves prove a slow query.
