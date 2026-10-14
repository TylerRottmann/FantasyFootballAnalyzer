import numpy as np

from scripts.algorithm.features.rb_features import build_rb_features
from scripts.algorithm.rb.feature_names import RB_FEATURE_NAMES
from scripts.algorithm.rb.rb_model import load_model, predict


def build_model_row(features):
    """Use the same feature order and missing values during training and inference."""
    return np.array([[
        np.nan if features[name] is None else float(features[name])
        for name in RB_FEATURE_NAMES
    ]], dtype=float)


def predict_rb(player, season, week):
    """Project weekly RB PPR points using only earlier performance statistics."""
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
    if features["games_played"] == 0:
        return {**result, "status": "insufficient_history"}
    points = float(predict(model, build_model_row(features))[0])
    return {
        **result,
        "projected_fantasy_points": round(points, 2),
        "status": "ml_model",
    }
