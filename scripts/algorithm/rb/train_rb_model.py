import argparse
import json
import os
from datetime import date
from pathlib import Path

import django
import joblib
import numpy as np
import sklearn

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "FantasyFootballAnalyzer.settings")
django.setup()

from leagues.models import Player
from scripts.algorithm.features.rb_features import RBSeasonData, build_rb_features
from scripts.algorithm.rb.feature_names import RB_FEATURE_NAMES
from scripts.algorithm.rb.rb_model import create_model, predict, train_model
from scripts.algorithm.rb.rb_predictor import build_model_row


METRICS_PATH = Path(__file__).with_name("rb_model_metrics.json")
ERROR_THRESHOLDS = (2, 3, 5, 7)


def get_rb_players():
    return {
        player.id: player
        for player in Player.objects.filter(position="RB").only("id", "team_id", "position", "full_name")
    }


def build_dataset(season, players_by_id, data=None):
    """Identify RBs by position, retaining recorded zero-point games."""
    if data is None:
        data = RBSeasonData.load(season)
    X, y, rows = [], [], []
    counts = {"recorded_games": 0, "missing_target": 0, "no_history": 0, "missing_matchup": 0}
    for player_id in sorted(players_by_id):
        player = players_by_id[player_id]
        for game in data.players.get(player_id, []):
            counts["recorded_games"] += 1
            actual = game["fantasy_points_ppr"]
            if actual is None:
                counts["missing_target"] += 1
                continue
            features = build_rb_features(player, season, game["week"], data)
            if features["games_played"] == 0:
                counts["no_history"] += 1
                continue
            if features["game_status"] != "GAME":
                counts["missing_matchup"] += 1
                continue
            X.append(build_model_row(features)[0])
            y.append(float(actual))
            rows.append({"player_id": player_id, "week": game["week"]})
    counts["usable_games"] = len(y)
    print(f"{season} dataset: {counts}", flush=True)
    return np.asarray(X, dtype=float).reshape(-1, len(RB_FEATURE_NAMES)), np.asarray(y, dtype=float), rows, counts


def metrics(predictions, actual):
    if len(actual) == 0:
        raise ValueError("Cannot evaluate an empty RB dataset.")
    errors = np.asarray(predictions, dtype=float) - np.asarray(actual, dtype=float)
    return {
        "predictions": len(actual),
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors ** 2))),
        "bias": float(np.mean(errors)),
        "within_points_percent": {
            str(threshold): float(np.mean(np.abs(errors) <= threshold) * 100)
            for threshold in ERROR_THRESHOLDS
        },
    }


def compare_baseline(model, X, y):
    """Compare predictions on exactly the same rows as the last-three-game baseline."""
    predictions = predict(model, X)
    baseline = X[:, RB_FEATURE_NAMES.index("fantasy_points_l3")]
    available = np.isfinite(baseline)
    result = {"model_all_rows": metrics(predictions, y)}
    if available.any():
        result["model_baseline_rows"] = metrics(predictions[available], y[available])
        result["last_three_average"] = metrics(baseline[available], y[available])
    return result


def main(projection_season):
    seasons = list(range(projection_season - 3, projection_season))
    players = get_rb_players()
    datasets = {season: build_dataset(season, players) for season in seasons}
    if any(len(datasets[season][1]) == 0 for season in seasons):
        raise ValueError("Each of the previous three seasons must contain usable RB training data.")
    X_train = np.concatenate([datasets[season][0] for season in seasons[:-1]])
    y_train = np.concatenate([datasets[season][1] for season in seasons[:-1]])
    X_holdout, y_holdout = datasets[seasons[-1]][:2]
    # The evaluation model is never saved over the production artifact.
    evaluation_model = create_model()
    evaluation_model.fit(X_train, y_train)
    holdout = compare_baseline(evaluation_model, X_holdout, y_holdout)
    print(f"Holdout {seasons[-1]} (trained on {seasons[:-1]}):\n{json.dumps(holdout, indent=2)}", flush=True)

    X_all = np.concatenate([datasets[season][0] for season in seasons])
    y_all = np.concatenate([datasets[season][1] for season in seasons])
    empty_features = [name for index, name in enumerate(RB_FEATURE_NAMES) if np.isnan(X_all[:, index]).all()]
    if empty_features:
        raise ValueError(f"RB features have no source values: {empty_features}")
    model = train_model(X_all, y_all, seasons)
    report = {
        "scoring": "PPR",
        "projection_season": projection_season,
        "training_seasons": seasons,
        "features": len(RB_FEATURE_NAMES),
        "library_versions": {
            "numpy": np.__version__, "scikit-learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "datasets": {str(season): datasets[season][3] for season in seasons},
        "holdout": {"training_seasons": seasons[:-1], "test_season": seasons[-1], **holdout},
        "final_training_fit_in_sample": metrics(predict(model, X_all), y_all),
    }
    METRICS_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Saved RB model trained on {seasons}; final training fit is in-sample.", flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train the RB PPR model on the previous three seasons.")
    parser.add_argument("--projection-season", type=int, default=date.today().year)
    args = parser.parse_args()
    main(args.projection_season)
