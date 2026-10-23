from pathlib import Path

import joblib
import pandas as pd

from scripts.algorithm.boom_bust.boom_bust_features import (
    build_boom_bust_features,
)


MODEL_PATH = Path(__file__).resolve().parent / "rb_boom_bust_model.pkl"


def predict_boom_bust(player, season, week):
    if player.position != "RB":
        raise ValueError("Boom/Bust predictions currently support RB only.")

    saved = joblib.load(MODEL_PATH)

    features = build_boom_bust_features(player, season, week)

    if features.get("baseline") is None or features["baseline"] < 5:
        raise ValueError(
            "Not enough qualifying historical data for a Boom/Bust prediction."
        )

    if features.get("game_status") != "GAME":
        raise ValueError(
            "No confirmed game matchup for this player and week."
        )

    X = pd.DataFrame([features])
    X = X.reindex(columns=saved["feature_columns"])
    X = X.apply(pd.to_numeric, errors="coerce")

    probabilities = saved["model"].predict_proba(X)[0]
    classes = saved["model"].classes_

    results = {
        label: round(float(probability), 4)
        for label, probability in zip(classes, probabilities)
    }

    return {
        "player_id": player.id,
        "season": season,
        "week": week,
        "baseline": features["baseline"],
        "boom_probability": results["boom"],
        "normal_probability": results["normal"],
        "bust_probability": results["bust"],
    }