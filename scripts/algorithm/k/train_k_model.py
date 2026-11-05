"""Train kicker stat components with a chronological season holdout."""
import argparse
import json
import hashlib
import platform
import joblib
import os
from datetime import date
from pathlib import Path
import django
import numpy as np
import sklearn
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FantasyFootballAnalyzer.settings')
django.setup()
from leagues.models import Player
from scripts.algorithm.features.k_features import KSeasonData, build_k_features, DATA_PATH
from scripts.algorithm.k.feature_names import K_FEATURE_NAMES, TARGETS
from scripts.algorithm.k.k_model import train_model, predict
from scripts.algorithm.k.k_predictor import build_model_row
from scripts.algorithm.k.scoring import REFERENCE_SCORING, score_kicking

def build_dataset(season, players, data=None):
    data = data if data is not None else KSeasonData.load(season)
    X, y, baseline, rows = [], [], [], []
    counts = {'recorded_games': 0, 'no_history': 0, 'missing_matchup': 0, 'missing_target': 0}
    for pid, player in sorted(players.items()):
        for game in data.players.get(pid, []):
            counts['recorded_games'] += 1
            if any(game.get(n) is None for n in TARGETS):
                counts['missing_target'] += 1
                continue
            features = build_k_features(player, season, game['week'], data)
            if features['games_played'] == 0:
                counts['no_history'] += 1
                continue
            if features['game_status'] != 'GAME':
                counts['missing_matchup'] += 1
                continue
            X.append(build_model_row(features)[0])
            y.append([game[n] for n in TARGETS])
            baseline.append([features[f'{n}_l3'] for n in TARGETS])
            rows.append({'player_id': pid, 'week': game['week']})
    counts['usable_games'] = len(y)
    return (np.asarray(X).reshape(-1, len(K_FEATURE_NAMES)),
            np.asarray(y).reshape(-1, len(TARGETS)),
            np.asarray(baseline).reshape(-1, len(TARGETS)), rows, counts)

def metrics(predictions, actual):
    if not len(actual):
        raise ValueError('Cannot evaluate an empty kicker dataset.')
    errors = np.asarray(predictions) - np.asarray(actual)
    return {'predictions': len(actual), 'mae': float(np.abs(errors).mean()),
            'rmse': float(np.sqrt((errors ** 2).mean())), 'bias': float(errors.mean()),
            'within_points_percent': {str(n): float((np.abs(errors) <= n).mean()*100) for n in (2,3,5,7)}}

def score_rows(rows, settings=REFERENCE_SCORING):
    return np.array([score_kicking(dict(zip(TARGETS, row)), settings) for row in rows])

def evaluate(model, dataset):
    X, y, baseline = dataset[:3]
    actual = score_rows(y)
    return {'reference_model': metrics(score_rows(predict(model, X)), actual),
            'reference_last_three_average': metrics(score_rows(baseline), actual)}

def get_players():
    return {p.id: p for p in Player.objects.filter(position='K').only('id', 'team_id', 'position')}

def main(projection_season):
    seasons = list(range(projection_season-3, projection_season))
    players = get_players()
    data = {s: build_dataset(s, players) for s in seasons}
    if any(not len(d[1]) for d in data.values()):
        raise ValueError('All three prior seasons need usable kicker history.')
    X = np.concatenate([data[s][0] for s in seasons[:-1]])
    y = np.concatenate([data[s][1] for s in seasons[:-1]])
    evaluation_model = train_model(X, y, seasons[:-1], save=False)
    holdout = evaluate(evaluation_model, data[seasons[-1]])
    X_all = np.concatenate([data[s][0] for s in seasons])
    y_all = np.concatenate([data[s][1] for s in seasons])
    empty = [name for i, name in enumerate(K_FEATURE_NAMES) if np.isnan(X_all[:, i]).all()]
    if empty:
        raise ValueError('Features with no source values: ' + ', '.join(empty))
    train_model(X_all, y_all, seasons)
    report = {'projection_season': projection_season, 'training_seasons': seasons,
              'features': K_FEATURE_NAMES, 'targets': TARGETS, 'reference_scoring': REFERENCE_SCORING,
              'numpy_version': np.__version__, 'sklearn_version': sklearn.__version__,
              'python_version': platform.python_version(), 'joblib_version': joblib.__version__,
              'source_sha256': hashlib.sha256(DATA_PATH.read_bytes()).hexdigest(),
              'source_coverage': json.loads(DATA_PATH.read_text(encoding='utf-8'))['coverage'],
              'datasets': {s: data[s][4] for s in seasons},
              'holdout': {'training_seasons': seasons[:-1], 'test_season': seasons[-1], **holdout}}
    Path(__file__).with_name('k_model_metrics.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projection-season', type=int, default=date.today().year)
    main(parser.parse_args().projection_season)
