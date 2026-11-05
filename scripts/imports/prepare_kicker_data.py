"""Build a local nflverse kicker snapshot; never write the shared database."""
import argparse
import json
import math
from collections import Counter
from pathlib import Path
import nflreadpy as nfl
import polars as pl
from scripts.algorithm.features.qb_features import get_connection
from scripts.algorithm.features.k_features import DATA_PATH
from scripts.algorithm.k.feature_names import PLAYER_STATS, SOURCE_STATS

def normalize_stats(row):
    """Sleeper counts blocked attempts as misses, including distance penalties."""
    stats = {n: row[n] for n in SOURCE_STATS}
    made = row.get('fg_made_list')
    made_distances = [] if made is None or made == '' else [int(float(d)) for d in str(made).split(';')]
    if len(made_distances) != stats['fg_made']:
        raise ValueError('Made FG count has no matching distance list.')
    stats['fg_made_yards_over_30'] = sum(max(distance-30, 0) for distance in made_distances)
    blocked = row.get('fg_blocked_list')
    distances = [] if blocked is None or blocked == '' else [int(float(d)) for d in str(blocked).split(';')]
    if len(distances) != stats['fg_blocked']:
        raise ValueError('Blocked FG count has no matching distance list.')
    for distance in distances:
        bucket = ('0_19' if distance < 20 else '20_29' if distance < 30 else
                  '30_39' if distance < 40 else '40_49' if distance < 50 else
                  '50_59' if distance < 60 else '60_')
        stats[f'fg_missed_{bucket}'] += 1
    stats['fg_missed'] += stats['fg_blocked']
    stats['pat_missed'] += stats['pat_blocked']
    return stats

def main(seasons, output=DATA_PATH):
    seasons = sorted(set(seasons))
    frame = nfl.load_player_stats(seasons=seasons, summary_level='week')
    required = {'position', 'season_type', 'season', 'week', 'player_id', 'team', 'opponent_team', 'fg_blocked_list', 'fg_made_list', *SOURCE_STATS}
    if required - set(frame.columns):
        raise ValueError('nflverse kicker fields missing: ' + ', '.join(sorted(required-set(frame.columns))))
    ids = nfl.load_ff_playerids().select(['gsis_id', 'sleeper_id']).to_dicts()
    gsis_to_sleeper = {str(r['gsis_id']): str(r['sleeper_id']) for r in ids
                       if r['gsis_id'] is not None and r['sleeper_id'] is not None}
    with get_connection().cursor() as cur:
        cur.execute("SELECT id, sleeper_id FROM players WHERE position='K'")
        players = {str(sleeper): pid for pid, sleeper in cur.fetchall() if sleeper is not None}
    games, seen, skipped = [], set(), Counter()
    counts = Counter()
    for row in frame.filter((pl.col('position') == 'K') & (pl.col('season_type') == 'REG')).to_dicts():
        counts[row['season']] += 1
        pid = players.get(gsis_to_sleeper.get(str(row['player_id'])))
        if pid is None:
            skipped['unmapped_player'] += 1
            continue
        key = (pid, row['season'], row['week'])
        if key in seen:
            raise ValueError('Duplicate player-season-week in kicker source.')
        seen.add(key)
        stats = {n: row[n] for n in SOURCE_STATS}
        if any(v is None or not math.isfinite(float(v)) or v < 0 for v in stats.values()):
            skipped['incomplete_stats'] += 1
            continue
        stats = normalize_stats(row)
        games.append({'player_id': pid, 'nflverse_player_id': row['player_id'],
                      'season': row['season'], 'week': row['week'],
                      'opponent_team': row['opponent_team'], 'source_team': row['team'], **stats})
    if any(not any(g['season'] == s for g in games) for s in seasons):
        raise ValueError('A requested season has no mapped, complete kicker games.')
    report = {'source_regular_season_rows': dict(counts), 'skipped': dict(skipped),
              'usable_by_season': dict(Counter(g['season'] for g in games))}
    payload = {'schema_version': 2, 'source': 'nflverse load_player_stats',
               'seasons': seasons, 'coverage': report, 'games': games}
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)
    print(json.dumps(report, indent=2))
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seasons', nargs='+', type=int, required=True)
    parser.add_argument('--output', type=Path, default=DATA_PATH)
    args = parser.parse_args()
    main(args.seasons, args.output)
