import os

import django
import numpy as np
import psycopg
from dotenv import load_dotenv

load_dotenv()

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "FantasyFootballAnalyzer.settings",
)

django.setup()

from leagues.models import Player
from scripts.algorithm.features.qb_features import build_qb_features
from scripts.algorithm.qb.qb_model import train_model, predict
from scripts.algorithm.qb.feature_names import QB_FEATURE_NAMES


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


# ============================================================
# GET QB GAMES
# ============================================================

def get_qb_games(season):
    """
    Retrieve QB games directly from player_weekly_stats.

    A player is treated as a QB if they have passing attempts
    or passing production in the historical game.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    player_id,
                    week,
                    fantasy_points_ppr
                FROM player_weekly_stats
                WHERE season = %s
                  AND season_type = 'REG'
                  AND fantasy_points_ppr IS NOT NULL
                  AND (
                      attempts > 0
                      OR passing_yards > 0
                      OR passing_tds > 0
                  )
                ORDER BY player_id, week
                """,
                (season,),
            )

            return cur.fetchall()

    finally:
        conn.close()


# ============================================================
# BUILD DATASET
# ============================================================

def build_dataset(season):
    """
    Build the training dataset for one season.

    All features are built using only information available
    before the prediction week.
    """

    X = []
    y = []

    games = get_qb_games(season)

    print()
    print(f"Building dataset for {season}...")
    print(f"Games found: {len(games)}")

    for index, (player_id, week, actual_points) in enumerate(
        games,
        start=1,
    ):

        # ----------------------------------------------------
        # Cannot predict Week 1 from previous games
        # ----------------------------------------------------

        if week <= 1:
            continue

        player = Player.objects.filter(
            id=player_id,
        ).first()

        if player is None:
            continue

        # ----------------------------------------------------
        # Build pre-game features
        # ----------------------------------------------------

        try:
            features = build_qb_features(
                player=player,
                season=season,
                week=week,
            )

        except Exception as exc:
            print(
                f"Skipping player {player_id}, "
                f"Week {week}: {exc}"
            )
            continue

        # ----------------------------------------------------
        # Build model row
        # ----------------------------------------------------

        row = []

        for feature_name in QB_FEATURE_NAMES:

            value = features.get(feature_name)

            if value is None:
                row.append(np.nan)
            else:
                row.append(float(value))

        X.append(row)
        y.append(float(actual_points))

        # ----------------------------------------------------
        # Progress
        # ----------------------------------------------------

        if index % 100 == 0:
            print(
                f"Processed {index}/{len(games)}"
            )

    return np.array(X), np.array(y)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("BUILDING QB TRAINING DATA")
    print("=" * 60)

    # ========================================================
    # BUILD ALL THREE SEASONS
    # ========================================================

    X_train_2023, y_train_2023 = build_dataset(2023)

    X_train_2024, y_train_2024 = build_dataset(2024)

    X_train_2025, y_train_2025 = build_dataset(2025)

    # ========================================================
    # COMBINE DATASETS
    # ========================================================

    X_train = np.concatenate(
        [
            X_train_2023,
            X_train_2024,
            X_train_2025,
        ],
        axis=0,
    )

    y_train = np.concatenate(
        [
            y_train_2023,
            y_train_2024,
            y_train_2025,
        ],
        axis=0,
    )

    print()
    print("=" * 60)
    print("COMBINED TRAINING DATA")
    print("=" * 60)

    print(
        f"2023 rows: {len(X_train_2023)}"
    )

    print(
        f"2024 rows: {len(X_train_2024)}"
    )

    print(
        f"2025 rows: {len(X_train_2025)}"
    )

    print(
        f"Total training rows: {len(X_train)}"
    )

    print(
        f"Features: {X_train.shape[1]}"
    )

    if len(X_train) == 0:
        print("No training data was created.")
        return

    # ========================================================
    # FEATURE DIAGNOSTICS
    # ========================================================

    print()
    print("=" * 80)
    print("FEATURE DIAGNOSTICS")
    print("=" * 80)

    invalid_features = []

    for index, feature_name in enumerate(
        QB_FEATURE_NAMES
    ):

        column = X_train[:, index]

        valid_values = column[
            ~np.isnan(column)
        ]

        unique_values = np.unique(
            valid_values
        )

        print(
            f"{index:3d} | "
            f"{feature_name:<50} | "
            f"valid={len(valid_values):5d} | "
            f"unique={len(unique_values):5d}"
        )

        if len(valid_values) == 0:
            invalid_features.append(
                feature_name
            )

    # ========================================================
    # CHECK FOR COMPLETELY EMPTY FEATURES
    # ========================================================

    if invalid_features:

        print()
        print("=" * 60)
        print("ERROR: EMPTY FEATURES FOUND")
        print("=" * 60)

        for feature in invalid_features:
            print(feature)

        print()
        print(
            "Training stopped because one or more "
            "features contain no valid values."
        )

        return

    # ========================================================
    # TRAIN MODEL
    # ========================================================

    print()
    print("=" * 60)
    print("TRAINING MODEL")
    print("=" * 60)

    model = train_model(
        X_train,
        y_train,
    )

    print()
    print("Model trained and saved.")

    # ========================================================
    # TRAINING PERFORMANCE
    # ========================================================

    print()
    print("=" * 60)
    print("TRAINING PERFORMANCE")
    print("=" * 60)

    predictions = predict(
        model,
        X_train,
    )

    errors = np.abs(
        predictions - y_train
    )

    mae = np.mean(errors)

    success_rate = (
        np.mean(errors <= 3.0)
        * 100
    )

    print(
        f"Training MAE: {mae:.2f}"
    )

    print(
        f"Training success rate: "
        f"{success_rate:.2f}%"
    )


if __name__ == "__main__":
    main()