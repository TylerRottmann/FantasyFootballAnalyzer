"""Shared chronological evaluation helpers for position projection models."""
import numpy as np


STAT_FEATURE_ALIASES = {
    "passing_interceptions": "interceptions",
    "passing_attempts": "passing_attempts",
    "carries": "rushing_attempts",
    "points_allowed": "points_against",
}


def score_stat_rows(rows, target_names, scoring_settings, position):
    if position == "K":
        from scripts.algorithm.k.scoring import score_kicking
        return np.asarray([
            score_kicking(dict(zip(target_names, row)), scoring_settings)
            for row in rows
        ], dtype=float)
    from leagues.services.scoring import score_stat_line
    return np.asarray([
        score_stat_line(dict(zip(target_names, row)), scoring_settings, position)
        for row in rows
    ], dtype=float)


def point_metrics(predicted_points, actual_points):
    predicted_points = np.asarray(predicted_points, dtype=float)
    actual_points = np.asarray(actual_points, dtype=float)
    errors = predicted_points - actual_points
    if not len(errors):
        return {"coverage": 0, "mae": None, "rmse": None, "bias": None, "within_3_points_pct": None}
    return {
        "coverage": int(len(errors)),
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors ** 2))),
        "bias": float(np.mean(errors)),
        "within_3_points_pct": float(np.mean(np.abs(errors) <= 3) * 100),
    }


def recent_stat_baseline(X, feature_names, target_names, explicit=None):
    """Make a last-three-game stat forecast from available lagged features."""
    if explicit is not None:
        baseline = np.asarray(explicit, dtype=float).copy()
        return np.nan_to_num(baseline, nan=0.0, posinf=0.0, neginf=0.0)
    feature_index = {name: index for index, name in enumerate(feature_names)}
    columns = []
    for target in target_names:
        index = feature_index.get(f"{target}_l3")
        if index is None:
            source = STAT_FEATURE_ALIASES.get(target)
            index = feature_index.get(f"{source}_l3") if source else None
        if index is None:
            columns.append(np.zeros(len(X), dtype=float))
        else:
            values = np.asarray(X[:, index], dtype=float).copy()
            columns.append(np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0))
    return np.column_stack(columns) if columns else np.empty((len(X), 0))


def evaluate_walk_forward(
    datasets, seasons, create_model, predict, target_names, feature_names,
    scoring_settings, position, *, recent_baseline_index=None,
):
    """Train on all earlier seasons and evaluate every later season once.

    Dataset values are tuples beginning with X, y. If recent_baseline_index is
    given, that tuple element supplies a prebuilt baseline matrix (for K).
    """
    results = []
    for test_index in range(1, len(seasons)):
        test_season = seasons[test_index]
        train_seasons = seasons[:test_index]
        train_parts = [datasets[s] for s in train_seasons if len(datasets[s][1])]
        test = datasets[test_season]
        X_test, y_test = test[:2]
        if not train_parts or not len(y_test):
            results.append({"test_season": test_season, "training_seasons": train_seasons,
                            "coverage": 0, "skipped": True})
            continue
        X_train = np.concatenate([part[0] for part in train_parts], axis=0)
        y_train = np.concatenate([part[1] for part in train_parts], axis=0)
        model = create_model().fit(X_train, y_train)
        predicted_points = score_stat_rows(predict(model, X_test), target_names, scoring_settings, position)
        actual_points = score_stat_rows(y_test, target_names, scoring_settings, position)
        if recent_baseline_index is None:
            baseline_stats = recent_stat_baseline(X_test, feature_names, target_names)
        else:
            baseline_stats = np.asarray(test[recent_baseline_index], dtype=float)
            baseline_stats = np.nan_to_num(baseline_stats, nan=0.0, posinf=0.0, neginf=0.0)
        recent_points = score_stat_rows(baseline_stats, target_names, scoring_settings, position)
        position_mean = float(np.mean(score_stat_rows(y_train, target_names, scoring_settings, position)))
        average_points = np.full(len(y_test), position_mean, dtype=float)
        results.append({
            "test_season": test_season,
            "training_seasons": train_seasons,
            "coverage": int(len(y_test)),
            "total_test_rows": int(len(y_test)),
            "model": point_metrics(predicted_points, actual_points),
            "last_three_game_baseline": point_metrics(recent_points, actual_points),
            "training_position_average_baseline": point_metrics(average_points, actual_points),
        })
    return results
