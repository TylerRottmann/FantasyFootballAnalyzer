import numpy as np

from scripts.algorithm.features.rb_features import build_rb_features
from scripts.algorithm.rb.feature_names import RB_FEATURE_NAMES
from scripts.algorithm.rb.rb_model import load_model, predict
from scripts.algorithm.rb.rb_model import TARGETS
from leagues.services.scoring import REFERENCE_SKILL_SCORING, score_stat_line


def build_model_row(features):
    """Use the same feature order and missing values during training and inference."""
    return np.array([[
        np.nan if features[name] is None else float(features[name])
        for name in RB_FEATURE_NAMES
    ]], dtype=float)


def predict_rb(player, season, week):
    """Project weekly RB statistics using only earlier performance statistics."""
    features = build_rb_features(player, season, week)
    result = {
        "player_id": player.id,
        "position": "RB",
        "season": season,
        "week": week,
        "projected_fantasy_points": None,
        "features": features,
    }
    if features["game_status"] == "BYE":
        return {**result, "projected_fantasy_points": 0, "status": "bye"}
    if features["game_status"] != "GAME":
        return {**result, "status": "matchup_not_found"}
    model = load_model()
    if model is None:
        return {**result, "status": "model_not_found"}
    if (features["games_played"] == 0
            and not features.get("prior_season_games")
            and features.get("position_prior_avg_ppr_points") is None):
        return {**result, "status": "insufficient_history"}
    X = build_model_row(features)
    stat_values = predict(model, X)[0]
    projected_stats = {name: float(value) for name, value in zip(TARGETS, stat_values)}
    uncertainty = model.predict_uncertainty(X)
    if uncertainty is not None:
        projected_stats["_uncertainty"] = {
            name: float(value) for name, value in zip(TARGETS, uncertainty[0])
        }
    points = score_stat_line(projected_stats, REFERENCE_SKILL_SCORING, "RB")
    return {
        **result,
        "projected_fantasy_points": round(points, 2),
        "status": "ml_model",
        "projected_stats": projected_stats,
    }
