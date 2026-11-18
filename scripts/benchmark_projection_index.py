"""Compare saved-projection query plans using a session-private table copy.

Run with the project virtualenv: python scripts/benchmark_projection_index.py
No permanent tables or indexes are changed. EXPLAIN ANALYZE executes SELECTs.
"""

import json
import os
from pathlib import Path
import statistics
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FantasyFootballAnalyzer.settings')

import django
django.setup()

from django.db import connection, transaction
from django.db.models import Count, Max
from leagues.models import FantasyProjection, FantasyRosterPlayer, Player


def plan_summary(node):
    keys = ('Node Type', 'Index Name', 'Actual Rows', 'Actual Loops',
            'Shared Hit Blocks', 'Shared Read Blocks', 'Local Hit Blocks',
            'Local Read Blocks', 'Rows Removed by Filter')
    result = {key: node[key] for key in keys if key in node}
    if 'Plans' in node:
        result['Plans'] = [plan_summary(child) for child in node['Plans']]
    return result


def measure(cursor, queries, repetitions=5):
    results = {}
    for name, query in queries.items():
        sql, params = query.query.sql_with_params()
        samples = []
        # First run is a warmup; do not call these cold-cache measurements.
        for iteration in range(repetitions + 1):
            cursor.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + sql, params)
            plan = cursor.fetchone()[0][0]
            if iteration:
                samples.append(plan)
        times = [plan['Execution Time'] for plan in samples]
        results[name] = {
            'execution_ms': times,
            'median_execution_ms': statistics.median(times),
            'median_planning_ms': statistics.median(plan['Planning Time'] for plan in samples),
            'plan': plan_summary(samples[-1]['Plan']),
        }
        print(f"{name}: {statistics.median(times):.3f} ms", flush=True)
    return results


def main():
    connection.ensure_connection()
    output = {'measured_at_utc': datetime.now(timezone.utc).isoformat()}
    # Scope live reads to a read-only transaction and cap each query's runtime.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            season = FantasyProjection.objects.aggregate(value=Max('season'))['value']
            if season is None:
                raise RuntimeError('No saved projections available to benchmark.')
            players = list(Player.objects.filter(position__in=['QB', 'RB', 'WR', 'TE', 'K'])
                           .exclude(full_name__isnull=True).exclude(full_name='')
                           .values_list('pk', flat=True))
            league = (FantasyRosterPlayer.objects.values('roster__league_id')
                      .annotate(size=Count('id')).order_by('-size').first())
            if not league:
                raise RuntimeError('No roster membership available for power rankings benchmark.')
            roster_players = list(FantasyRosterPlayer.objects.filter(
                roster__league_id=league['roster__league_id'], player_id__isnull=False,
            ).values_list('player_id', flat=True).distinct())
            queries = {}
            for week in (1, 11, 18):
                queries[f'waivers_week_{week}'] = FantasyProjection.objects.filter(
                    player_id__in=players, season=season, week__gte=week,
                    week__lte=18, model_version='v2_stat',
                )
            for name, ids, weekly in [('power_rankings', roster_players, False),
                                      ('market_weekly', players, True),
                                      ('market_rest_of_season', players, False)]:
                query = FantasyProjection.objects.filter(
                    player_id__in=ids, season=season, model_version='v2_stat',
                ).select_related('player')
                queries[name] = query.filter(week=11) if weekly else query.filter(week__gte=11, week__lte=18)
            cursor.execute("SELECT indexname, indexdef FROM pg_indexes "
                           "WHERE schemaname='public' AND tablename='fantasy_projections'")
            output['existing_indexes'] = cursor.fetchall()
            cursor.execute('SELECT season, model_version, count(*) FROM public.fantasy_projections '
                           'GROUP BY season, model_version ORDER BY season, model_version')
            output['projection_counts'] = cursor.fetchall()
            output['season'] = season
            output['player_count'] = len(players)
            output['league_player_count'] = len(roster_players)
            print('Measuring live baseline (read only)', flush=True)
            output['live_baseline'] = measure(cursor, queries)

    # Temporary objects are private to this connection; public tables remain
    # unchanged. Clone every existing projection index, not just model metadata.
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '60s'")
            cursor.execute('CREATE TEMP TABLE fantasy_projections '
                           '(LIKE public.fantasy_projections INCLUDING ALL) ON COMMIT DROP')
            cursor.execute('INSERT INTO pg_temp.fantasy_projections '
                           'SELECT * FROM public.fantasy_projections')
            cursor.execute('ANALYZE pg_temp.fantasy_projections')
            cursor.execute('SELECT count(*) FROM pg_temp.fantasy_projections')
            output['copied_projection_rows'] = cursor.fetchone()[0]
            cursor.execute("SELECT indexdef FROM pg_indexes WHERE schemaname LIKE 'pg_temp_%' "
                           "AND tablename='fantasy_projections'")
            output['copy_indexes_before'] = [row[0] for row in cursor.fetchall()]
            # Explicitly verify ORM's unqualified table now resolves to the copy.
            cursor.execute("SELECT 'fantasy_projections'::regclass::oid = "
                           "'pg_temp.fantasy_projections'::regclass::oid")
            if not cursor.fetchone()[0]:
                raise RuntimeError('Projection queries did not resolve to the private copy.')
            print('Measuring copy with existing indexes', flush=True)
            output['copy_baseline'] = measure(cursor, queries)
            cursor.execute('CREATE INDEX bench_projection_season_model_week '
                           'ON pg_temp.fantasy_projections (season, model_version, week)')
            print('Measuring copy with candidate index', flush=True)
            output['copy_candidate'] = measure(cursor, queries)
            print('Repeating existing-index measurements to check ordering effects', flush=True)
            cursor.execute('DROP INDEX pg_temp.bench_projection_season_model_week')
            output['copy_baseline_repeat'] = measure(cursor, queries)
    finally:
        connection.close()  # PostgreSQL drops the private copy and its indexes.
        path = ROOT / 'docs' / 'projection-index-benchmark.json'
        path.write_text(json.dumps(output, indent=2), encoding='utf-8')
        print(f'Results saved to {path}', flush=True)


if __name__ == '__main__':
    main()
