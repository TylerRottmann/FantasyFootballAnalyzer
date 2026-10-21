import numpy as np
from scripts.algorithm.features.k_features import build_k_features, KSourceUnavailable
from scripts.algorithm.k.feature_names import K_FEATURE_NAMES, TARGETS
from scripts.algorithm.k.k_model import load_model, predict
from scripts.algorithm.k.scoring import REFERENCE_SCORING, score_kicking

def build_model_row(features):
    return np.array([[np.nan if features[n] is None else float(features[n])
                      for n in K_FEATURE_NAMES]], dtype=float)

def predict_k(player, season, week, scoring_settings=None):
    result = {'player_id': player.id, 'position': 'K', 'season': season,
              'week': week, 'projected_fantasy_points': None}
    try:
        features = build_k_features(player, season, week)
    except (FileNotFoundError, KSourceUnavailable):
        return {**result, 'status': 'data_not_found'}
    result['features'] = features
    if features['game_status'] == 'BYE':
        return {**result, 'projected_stats': dict.fromkeys(TARGETS, 0),
                'projected_fantasy_points': 0, 'status': 'bye'}
    if features['game_status'] != 'GAME':
        return {**result, 'status': 'matchup_not_found'}
    if features['games_played'] == 0:
        return {**result, 'status': 'insufficient_history'}
    model = load_model()
    if model is None:
        return {**result, 'status': 'model_not_found'}
    stats = dict(zip(TARGETS, map(float, predict(model, build_model_row(features))[0])))
    result['projected_stats'] = stats
    settings = REFERENCE_SCORING if scoring_settings is None else scoring_settings
    try:
        points = score_kicking(stats, settings)
    except (ValueError, TypeError):
        return {**result, 'status': 'unsupported_scoring'}
    return {**result, 'projected_fantasy_points': round(points, 2), 'status': 'ml_model',
            'scoring': 'reference_kicking' if scoring_settings is None else 'league_kicking'}
