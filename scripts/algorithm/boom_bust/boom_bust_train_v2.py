"""Leakage-aware training utilities for Boom/Bust v2.

No models are trained or saved when this module is imported.
"""

from pathlib import Path

import pandas as pd


POSITIONS = ("QB", "RB", "WR", "TE")
CLASSES = ("boom", "bust", "normal")

# Never allow targets, postgame outcomes, identifiers, or game metadata
# to enter the model's predictor matrix.
EXCLUDED_COLUMNS = frozenset({
    "player_id",
    "season",
    "week",
    "team_id",
    "opponent_team_id",
    "opponent_team",
    "game_id",
    "game_status",
    "actual_points",
    "label",
    "boom_threshold",
    "bust_threshold",
    "baseline_source",
})


def select_feature_columns(rows):
    """Select numeric, non-outcome predictors from historical rows."""
    if not rows:
        raise ValueError("Cannot select features from an empty dataset.")

    frame = pd.DataFrame(rows)

    schema_path = Path(__file__).with_name("boom_bust_feature_schema_v2.txt")
    approved = set(schema_path.read_text().splitlines())

    if not approved:
        raise ValueError("The v2 feature schema is empty.")

    candidates = set(frame.columns) - EXCLUDED_COLUMNS
    unexpected = sorted(
        column
        for column in candidates - approved
        if frame[column].notna().any()
    )

    if unexpected:
        raise ValueError(f"Unapproved predictor columns: {unexpected}")

    columns = [
        column
        for column in sorted(approved)
        if column in frame.columns
        and pd.api.types.is_numeric_dtype(frame[column])
        and frame[column].notna().any()
    ]

    if not columns:
        raise ValueError("No usable numeric predictors found.")

    return columns


def prepare_labeled_data(rows, feature_columns):
    """Build X and y, excluding rows without a historical label."""
    frame = pd.DataFrame(rows)

    if "label" not in frame.columns:
        raise ValueError("Dataset is missing the label column.")

    labeled = frame.loc[frame["label"].isin(CLASSES)].copy()

    if labeled.empty:
        raise ValueError("Dataset contains no labeled examples.")

    X = labeled.reindex(columns=feature_columns)
    X = X.apply(pd.to_numeric, errors="coerce")
    y = labeled["label"].copy()

    return X, y


def build_position_model():
    """Create an unfitted Boom/Bust v2 classifier."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline

    return Pipeline([
        ("imputer", SimpleImputer(
            strategy="median",
            keep_empty_features=True,
        )),
        ("classifier", RandomForestClassifier(
            n_estimators=300,
            min_samples_leaf=5,
            max_features="sqrt",
            class_weight="balanced_subsample",
            random_state=42,
            n_jobs=-1,
        )),
    ])


def prepare_position_splits(train_rows, calibration_rows, test_rows, position):
    """Prepare chronological datasets with training-only feature selection."""
    if position not in POSITIONS:
        raise ValueError(f"Unsupported position: {position}")

    def validate_season(rows, partition):
        if not rows:
            raise ValueError(f"{partition} dataset is empty")

        seasons = {row.get("season") for row in rows}
        if len(seasons) != 1:
            raise ValueError(
                f"{partition} must contain exactly one season: {seasons}"
            )

        season = next(iter(seasons))
        if type(season) is not int:
            raise ValueError(
                f"{partition} has an invalid season: {season!r}"
            )

        return season

    train_season = validate_season(train_rows, "Training")
    cal_season = validate_season(calibration_rows, "Calibration")
    test_season = validate_season(test_rows, "Testing")

    if not train_season < cal_season < test_season:
        raise ValueError(
            "Seasons must be chronological: "
            f"training={train_season}, "
            f"calibration={cal_season}, testing={test_season}"
        )

    position_flag = f"position_{position.lower()}"

    def filter_position(rows):
        return [
            row for row in rows
            if row.get(position_flag) == 1
        ]

    train = filter_position(train_rows)
    calibration = filter_position(calibration_rows)
    test = filter_position(test_rows)

    if not train or not calibration or not test:
        raise ValueError(f"Missing historical records for {position}")

    feature_columns = select_feature_columns(train)

    X_train, y_train = prepare_labeled_data(train, feature_columns)
    X_cal, y_cal = prepare_labeled_data(calibration, feature_columns)
    X_test, y_test = prepare_labeled_data(test, feature_columns)

    for name, labels in (
        ("training", y_train),
        ("calibration", y_cal),
        ("testing", y_test),
    ):
        missing = set(CLASSES) - set(labels)
        if missing:
            raise ValueError(
                f"{position} {name} data missing classes: {sorted(missing)}"
            )

    return {
        "position": position,
        "feature_columns": feature_columns,
        "X_train": X_train,
        "y_train": y_train,
        "X_cal": X_cal,
        "y_cal": y_cal,
        "X_test": X_test,
        "y_test": y_test,
    }


def fit_calibrated_position_model(splits):
    """Fit on training data and calibrate on a later, separate season."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.frozen import FrozenEstimator

    model = build_position_model()
    model.fit(splits["X_train"], splits["y_train"])

    # FrozenEstimator prevents calibration from refitting the base model.
    calibrated = CalibratedClassifierCV(
        estimator=FrozenEstimator(model),
        method="sigmoid",
    )
    calibrated.fit(splits["X_cal"], splits["y_cal"])

    expected_classes = set(CLASSES)
    actual_classes = set(calibrated.classes_)

    if actual_classes != expected_classes:
        raise ValueError(
            f"Unexpected calibrated classes: {sorted(actual_classes)}"
        )

    return calibrated


def evaluate_probabilities(y_true, probabilities, classes=CLASSES):
    """Evaluate multiclass probability quality and classification accuracy."""
    import numpy as np
    from sklearn.metrics import accuracy_score, log_loss

    classes = list(classes)
    y_true = pd.Series(y_true).reset_index(drop=True)
    probabilities = np.asarray(probabilities, dtype=float)

    if probabilities.shape != (len(y_true), len(classes)):
        raise ValueError("Probability matrix dimensions do not match labels/classes.")

    if not np.isfinite(probabilities).all():
        raise ValueError("Probabilities contain non-finite values.")

    if (probabilities < 0).any() or (probabilities > 1).any():
        raise ValueError("Probabilities must be between 0 and 1.")

    if not np.allclose(probabilities.sum(axis=1), 1.0):
        raise ValueError("Each probability row must sum to 1.")

    if not y_true.isin(classes).all():
        raise ValueError("Unknown outcome labels detected.")

    actual = np.column_stack([
        (y_true == label).to_numpy(dtype=float)
        for label in classes
    ])

    predictions = np.asarray(classes)[probabilities.argmax(axis=1)]

    return {
        "log_loss": float(log_loss(y_true, probabilities, labels=classes)),
        "brier_score": float(np.mean(np.sum((probabilities - actual) ** 2, axis=1))),
        "accuracy": float(accuracy_score(y_true, predictions)),
        "samples": len(y_true),
    }


def class_frequency_baseline(y_train, n_predictions, classes=CLASSES):
    """Predict training-season class frequencies for every evaluation record."""
    import numpy as np

    if n_predictions < 1:
        raise ValueError("n_predictions must be positive.")

    frequencies = pd.Series(y_train).value_counts(normalize=True)
    if not set(classes).issubset(frequencies.index):
        raise ValueError("Training labels must contain all three classes.")

    row = np.array([frequencies[label] for label in classes])
    return np.tile(row, (n_predictions, 1))


def compare_position_models(splits):
    """Compare baseline, raw, and calibrated probabilities on held-out data."""
    import numpy as np

    calibrated = fit_calibrated_position_model(splits)

    # The fitted Random Forest is wrapped inside FrozenEstimator.
    raw_model = calibrated.calibrated_classifiers_[0].estimator.estimator

    X_test = splits["X_test"]
    y_test = splits["y_test"]

    def aligned_probabilities(model):
        probabilities = model.predict_proba(X_test)
        class_indices = [
            list(model.classes_).index(label)
            for label in CLASSES
        ]
        return probabilities[:, class_indices]

    baseline_probabilities = class_frequency_baseline(
        splits["y_train"], len(y_test), CLASSES
    )

    raw_probabilities = aligned_probabilities(raw_model)
    calibrated_probabilities = aligned_probabilities(calibrated)

    results = {
        "position": splits["position"],
        "baseline": evaluate_probabilities(
            y_test, baseline_probabilities, CLASSES
        ),
        "uncalibrated": evaluate_probabilities(
            y_test, raw_probabilities, CLASSES
        ),
        "calibrated": evaluate_probabilities(
            y_test, calibrated_probabilities, CLASSES
        ),
    }

    results["calibration_log_loss_improvement"] = (
        results["uncalibrated"]["log_loss"]
        - results["calibrated"]["log_loss"]
    )

    results["calibration_brier_improvement"] = (
        results["uncalibrated"]["brier_score"]
        - results["calibrated"]["brier_score"]
    )

    return results


def load_historical_position_splits(
    train_season=2023,
    calibration_season=2024,
    test_season=2025,
):
    """Load historical records and prepare four position-specific splits."""
    from scripts.algorithm.boom_bust.boom_bust_dataset_v2 import (
        build_rb_dataset_v2,
        build_other_positions_dataset_v2,
    )

    seasons = (train_season, calibration_season, test_season)

    if not all(type(season) is int for season in seasons):
        raise ValueError("All seasons must be integers.")

    if not train_season < calibration_season < test_season:
        raise ValueError("Training, calibration, and testing seasons must increase.")

    from django.db import connections
    from scripts.algorithm.boom_bust.boom_bust_cache_v2 import (
        load_cached_season,
        save_cached_season,
    )

    datasets = {}

    for season in seasons:
        print(f"Loading historical season {season}...", flush=True)

        try:
            cached_rows = load_cached_season(season)

            if cached_rows is not None:
                datasets[season] = cached_rows
                print(
                    f"Season {season}: {len(cached_rows)} cached records loaded",
                    flush=True,
                )
                continue

            rb_rows = build_rb_dataset_v2(season)
            other_rows = build_other_positions_dataset_v2(season)

            datasets[season] = rb_rows + other_rows

            cache_path = save_cached_season(
                season, datasets[season]
            )

            print(
                f"Season {season}: {len(datasets[season])} records built "
                f"and cached at {cache_path}",
                flush=True,
            )
        finally:
            connections.close_all()

    splits = {}

    for position in POSITIONS:
        splits[position] = prepare_position_splits(
            datasets[train_season],
            datasets[calibration_season],
            datasets[test_season],
            position,
        )

        print(
            f"{position}: "
            f"train={len(splits[position]['y_train'])}, "
            f"calibration={len(splits[position]['y_cal'])}, "
            f"test={len(splits[position]['y_test'])}",
            flush=True,
        )

    return splits
