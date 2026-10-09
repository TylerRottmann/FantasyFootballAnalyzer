import numpy as np

from scripts.algorithm.features.qb_features import build_qb_features
from scripts.algorithm.qb.feature_names import QB_FEATURE_NAMES
from scripts.algorithm.qb.qb_model import load_model, predict


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
    Generate a QB fantasy projection using the trained
    machine-learning model.
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

    projected_fantasy_points = float(
        predict(model, X)[0]
    )

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

        "features": features,
    }