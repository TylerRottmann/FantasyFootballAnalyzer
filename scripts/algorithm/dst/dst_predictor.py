import numpy as np

from scripts.algorithm.dst.dst_model import load_model, predict
from scripts.algorithm.dst.feature_names import DST_FEATURE_NAMES
from scripts.algorithm.features.dst_features import build_dst_features
from scripts.algorithm.dst.dst_model import TARGETS
from leagues.services.scoring import REFERENCE_SKILL_SCORING, score_stat_line


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
        return {**base, "projected_fantasy_points": 0, "projected_stats": {}, "status": "bye",
                "features": features}

    model = load_model()

    if model is None:
        return {**base, "projected_fantasy_points": None,
                "status": "model_not_found"}

    X = build_model_row(features)
    values = predict(model, X)[0]
    projected_stats = {name: float(value) for name, value in zip(TARGETS, values)}
    uncertainty = model.predict_uncertainty(X)
    if uncertainty is not None:
        projected_stats["_uncertainty"] = {
            name: float(value) for name, value in zip(TARGETS, uncertainty[0])
        }
    projected = score_stat_line(projected_stats, REFERENCE_SKILL_SCORING, "DEF")

    return {
        **base,
        "projected_fantasy_points": round(projected, 2),
        "projected_stats": projected_stats,
        "status": "ml_model",
        "features": features,
    }
