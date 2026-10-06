import numpy as np

from scripts.algorithm.features.wr_features import build_wr_features
from scripts.algorithm.wr.feature_names import WR_FEATURE_NAMES
from scripts.algorithm.wr.wr_model import load_model, predict


def build_model_row(features):
    """
    Build the feature vector in the exact same order
    used when training the WR model.
    """

    row = []

    for feature_name in WR_FEATURE_NAMES:

        value = features.get(feature_name)

        if value is None:
            row.append(np.nan)
        else:
            row.append(float(value))

    return np.array([row], dtype=float)


def predict_wr(player, season, week):
    """
    Generate a WR fantasy projection (PPR) using the trained
    machine-learning model.
    """

    # --------------------------------------------------------
    # BUILD PRE-GAME FEATURES
    # --------------------------------------------------------

    features = build_wr_features(
        player=player,
        season=season,
        week=week,
    )

    # --------------------------------------------------------
    # LOAD TRAINED MODEL
    # --------------------------------------------------------

    model = load_model()

    if model is None:
        return {
            "player_id": player.id,
            "position": "WR",
            "season": season,
            "week": week,
            "projected_fantasy_points": None,
            "status": "model_not_found",
        }

    # --------------------------------------------------------
    # BUILD MODEL INPUT + PREDICT
    # --------------------------------------------------------

    X = build_model_row(features)

    projected_fantasy_points = float(
        predict(model, X)[0]
    )

    return {
        "player_id": player.id,
        "position": "WR",
        "season": season,
        "week": week,

        "projected_fantasy_points": round(
            projected_fantasy_points,
            2,
        ),

        "status": "ml_model",

        "features": features,
    }
