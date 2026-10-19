import numpy as np

from scripts.algorithm.dst.dst_model import load_model, predict
from scripts.algorithm.dst.feature_names import DST_FEATURE_NAMES
from scripts.algorithm.features.dst_features import build_dst_features


def build_model_row(features):
    """Feature vector in the exact order used during training."""
    row = []
    for name in DST_FEATURE_NAMES:
        value = features.get(name)
        row.append(np.nan if value is None else float(value))
    return np.array([row], dtype=float)


def predict_dst(team_id, season, week):
    """
    Project a team's D/ST fantasy points for one week.

    D/ST is keyed by team_id (not player_id) because defenses are not
    rows in the players table.
    """
    base = {
        "team_id": team_id,
        "position": "DEF",
        "season": season,
        "week": week,
    }

    features = build_dst_features(team_id, season, week)

    if features.get("game_status") == "BYE":
        return {**base, "projected_fantasy_points": 0, "status": "bye",
                "features": features}

    model = load_model()

    if model is None:
        return {**base, "projected_fantasy_points": None,
                "status": "model_not_found"}

    projected = float(predict(model, build_model_row(features))[0])

    return {
        **base,
        "projected_fantasy_points": round(projected, 2),
        "status": "ml_model",
        "features": features,
    }
