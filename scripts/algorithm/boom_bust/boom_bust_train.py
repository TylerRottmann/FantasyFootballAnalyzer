
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    log_loss,
)
from sklearn.pipeline import Pipeline

from scripts.algorithm.boom_bust.boom_bust_dataset import (
    build_rb_training_dataset,
)


EXCLUDED_COLUMNS = {
    "player_id",
    "season",
    "week",
    "team_id",
    "opponent_team_id",
    "opponent_team",
    "game_status",
    "is_home",
    "actual_points",
    "label",
}



def prepare_features(rows, feature_columns=None):
    df = pd.DataFrame(rows)

    if feature_columns is None:
        candidate_columns = [
            col
            for col in df.columns
            if col not in EXCLUDED_COLUMNS
        ]

        # Convert PostgreSQL Decimal values into numeric columns.
        numeric_df = df[candidate_columns].apply(
            pd.to_numeric, errors="coerce"
        )

        # Exclude fields with no numeric values.
        feature_columns = [
            col
            for col in numeric_df.columns
            if numeric_df[col].notna().any()
        ]

    X = df.reindex(columns=feature_columns).apply(
        pd.to_numeric, errors="coerce"
    )

    return X, df["label"], feature_columns



def train():
    print("Loading training data...")

    training_rows = (
        build_rb_training_dataset(2023)
        + build_rb_training_dataset(2024)
    )

    print("Loading test data...")
    test_rows = build_rb_training_dataset(2025)

    X_train, y_train, feature_columns = prepare_features(
        training_rows
    )

    X_test, y_test, _ = prepare_features(
        test_rows, feature_columns
    )

    print("Training examples:", len(X_train))
    print("Testing examples:", len(X_test))
    print("Features:", len(feature_columns))

    model = Pipeline([
        ("imputer", SimpleImputer(
            strategy="median",
            keep_empty_features=True,
        )),
        ("classifier", RandomForestClassifier(
            n_estimators=200,
            min_samples_leaf=5,
            random_state=42,
            n_jobs=-1,
        )),
    ])

    model.fit(X_train, y_train)

    predictions = model.predict(X_test)
    probabilities = model.predict_proba(X_test)
    classes = model.named_steps["classifier"].classes_

    print("\nAccuracy:", round(
        accuracy_score(y_test, predictions), 4
    ))

    print("\nClassification report:")
    print(classification_report(
        y_test,
        predictions,
        zero_division=0,
    ))

    print("Log loss:", round(
        log_loss(y_test, probabilities, labels=classes), 4
    ))

    majority_class = y_train.value_counts().idxmax()
    baseline_accuracy = (y_test == majority_class).mean()
    print("Majority baseline accuracy:", round(
        baseline_accuracy, 4
    ))

    model_path = (
        Path(__file__).resolve().parent / "rb_boom_bust_model.pkl"
    )

    joblib.dump({
        "model": model,
        "feature_columns": feature_columns,
        "classes": list(classes),
    }, model_path)

    print("\nSaved model to:", model_path)


if __name__ == "__main__":
    train()
