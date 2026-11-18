"""Read-only before/after market benchmark against pre-fix commit d51dad3."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FantasyFootballAnalyzer.settings')
import django
django.setup()

from django.db import connection, transaction
from django.test import RequestFactory
from analyzer import market, waiver_moves
from analyzer.waiver_predictions import WaiverPrediction
from analyzer.waiver_value import PlayerValue
from leagues.models import FantasyLeague


def original(name):
    source = subprocess.check_output(['git', 'show', f'd51dad3:analyzer/{name}.py'], cwd=ROOT, text=True)
    module = ModuleType(f'analyzer._original_{name}')
    exec(compile(source, name, 'exec'), module.__dict__)
    return module


def summarize(context, long_term):
    fields = ['entity_key', 'weekly_our', 'weekly_sleeper', 'weekly_our_rank', 'weekly_sleeper_rank']
    if long_term:
        fields += ['adp', 'our_ros', 'sleeper_ros', 'our_ros_rank', 'sleeper_ros_rank', 'market_signal']
    return [{field: row.get(field) for field in fields} for row in context['page_obj'].paginator.object_list]


def main():
    before_market = original('market')
    before_moves = original('waiver_moves')
    results = {}
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='30s'")
        league = FantasyLeague.objects.filter(season=2026).order_by('pk').first()
        if league is None:
            raise RuntimeError('No league available for benchmarking.')
        for route in ('market_short_term', 'market_long_term'):
            samples = {'before': [], 'after': []}
            summaries = {}
            for _ in range(2):
                for label, module in [('before', before_market), ('after', market)]:
                    request = RequestFactory().get('/market/', {'week': 11})
                    request.resolver_match = SimpleNamespace(url_name=route)
                    query_times = []
                    def record(execute, sql, params, many, context):
                        started = time.perf_counter()
                        try:
                            return execute(sql, params, many, context)
                        finally:
                            query_times.append(time.perf_counter() - started)
                    with patch.object(module, 'league_selector', return_value={'active_league': league}):
                        with connection.execute_wrapper(record):
                            started = time.perf_counter()
                            context = module._filtered_rows(request)
                            elapsed = time.perf_counter() - started
                    samples[label].append({'seconds': elapsed, 'queries': len(query_times), 'db_seconds': sum(query_times)})
                    summaries[label] = summarize(context, route == 'market_long_term')
                    print(route, label, samples[label][-1], flush=True)
            if summaries['before'] != summaries['after']:
                raise AssertionError(f'{route} displayed rankings changed')
            results[route] = samples
            results[route]['displayed_rankings_match'] = True

    # Exercise the same lineup algorithm before/after with forecasts and flex
    # slots, checking exact outputs as well as runtime.
    def row(pk, position, points):
        return {'player': SimpleNamespace(pk=pk, full_name=str(pk), position=position),
                'prediction': WaiverPrediction(points, points * 8, {w: points for w in range(11, 19)}),
                'value': PlayerValue(horizon='long'), 'roster_slot': 'BN'}
    positions = ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'RB', 'WR', 'TE', 'QB', 'RB', 'WR', 'TE', 'WR']
    owned = [row(i, p, 8 + i % 7) for i, p in enumerate(positions)]
    available = [row(100+i, p, 18 + i) for i, p in enumerate(['QB', 'RB', 'WR', 'TE'])]
    slots = ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'FLEX', 'SUPER_FLEX']
    outputs = {}
    for label, module in [('before', before_moves), ('after', waiver_moves)]:
        started = time.perf_counter()
        tags = module.suggested_pickup_horizons(available, owned, slots)
        cards = module.suggested_moves(available, owned, slots, tags)
        elapsed = time.perf_counter() - started
        outputs[label] = (tags, cards)
        results[f'waiver_synthetic_{label}_seconds'] = elapsed
        print('waiver_synthetic', label, elapsed, flush=True)
    if outputs['before'] != outputs['after']:
        raise AssertionError('Waiver suggestion outputs changed')
    results['waiver_synthetic_outputs_match'] = True
    connection.close()
    path = ROOT / 'docs' / 'page-fix-benchmark.json'
    path.write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(f'Saved {path}', flush=True)


if __name__ == '__main__':
    main()
