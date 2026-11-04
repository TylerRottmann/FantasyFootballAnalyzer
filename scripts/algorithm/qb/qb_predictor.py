import numpy as np

from scripts.algorithm.features.qb_features import build_qb_features
from scripts.algorithm.qb.feature_names import QB_FEATURE_NAMES
from scripts.algorithm.qb.qb_model import load_model, predict
from scripts.algorithm.qb.qb_model import TARGETS
from leagues.services.scoring import REFERENCE_SKILL_SCORING, score_stat_line


def build_model_row(features):
    """
    Build the feature vector in the exact same order
    used when training the QB model.
    """

    row = []

    for feature_name in QB_FEATURE_NAMES:

        value = features.get(feature_name)

        if value is None:
            row.append(np.nan)
        else:
            row.append(float(value))

    return np.array([row], dtype=float)


def predict_qb(player, season, week):
    """
    Generate a QB projected stat line and a reference fantasy score.
    """

    # --------------------------------------------------------
    # BUILD PRE-GAME FEATURES
    # --------------------------------------------------------

    features = build_qb_features(
        player=player,
        season=season,
        week=week,
    )

    if features.get("game_status") == "BYE":
        return {
            "player_id": player.id,
            "position": "QB",
            "season": season,
            "week": week,
            "projected_fantasy_points": 0,
            "status": "bye",
            "features": features,
        }

    model = load_model()

    if model is None:
        return {
            "player_id": player.id,
            "position": "QB",
            "season": season,
            "week": week,
            "projected_fantasy_points": None,
            "status": "model_not_found",
        }

    # --------------------------------------------------------
    # BUILD MODEL INPUT
    # --------------------------------------------------------

    X = build_model_row(features)

    # --------------------------------------------------------
    # MAKE PREDICTION
    # --------------------------------------------------------

    stat_values = predict(model, X)[0]
    projected_stats = {name: float(value) for name, value in zip(TARGETS, stat_values)}
    uncertainty = model.predict_uncertainty(X)
    if uncertainty is not None:
        projected_stats["_uncertainty"] = {
            name: float(value) for name, value in zip(TARGETS, uncertainty[0])
        }
    projected_fantasy_points = score_stat_line(projected_stats, REFERENCE_SKILL_SCORING, "QB")

    return {
        "player_id": player.id,
        "position": "QB",
        "season": season,
        "week": week,

        "projected_fantasy_points": round(
            projected_fantasy_points,
            2,
        ),

        "status": "ml_model",
        "projected_stats": projected_stats,

        "features": features,
    }
