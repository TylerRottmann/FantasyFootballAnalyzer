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
from scripts.algorithm.qb.qb_model import train_model, predict, create_model, TARGETS
from leagues.services.scoring import REFERENCE_SKILL_SCORING, score_stat_line
from scripts.algorithm.qb.feature_names import QB_FEATURE_NAMES
from scripts.algorithm.rolling_evaluation import evaluate_walk_forward

SEASONS = [2023, 2024, 2025]


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
                    COALESCE(passing_yards, 0),
                    COALESCE(passing_tds, 0),
                    COALESCE(passing_interceptions, 0),
                    COALESCE(passing_2pt_conversions, 0),
                    COALESCE(rushing_yards, 0),
                    COALESCE(rushing_tds, 0),
                    COALESCE(rushing_2pt_conversions, 0),
                    COALESCE(targets, 0), COALESCE(receptions, 0),
                    COALESCE(receiving_yards, 0), COALESCE(receiving_tds, 0),
                    COALESCE(receiving_2pt_conversions, 0),
                    COALESCE(fumbles_lost, 0),
                    COALESCE(attempts, 0),
                    COALESCE(carries, 0)
                FROM player_weekly_stats
                WHERE season = %s
                  AND season_type = 'REG'
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

    for index, game in enumerate(
        games,
        start=1,
    ):
        player_id, week, *actual_stats = game

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
        y.append([float(value) for value in actual_stats])

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

    datasets = {season: build_dataset(season) for season in SEASONS}

    # ========================================================
    # COMBINE DATASETS
    # ========================================================

    X_train = np.concatenate([datasets[season][0] for season in SEASONS], axis=0)
    y_train = np.concatenate([datasets[season][1] for season in SEASONS], axis=0)

    print()
    print("=" * 60)
    print("COMBINED TRAINING DATA")
    print("=" * 60)

    print(
        f"2023 rows: {len(datasets[2023][0])}"
    )

    print(
        f"2024 rows: {len(datasets[2024][0])}"
    )

    print(
        f"2025 rows: {len(datasets[2025][0])}"
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

    folds = evaluate_walk_forward(
        datasets, SEASONS, create_model, predict, TARGETS, QB_FEATURE_NAMES,
        REFERENCE_SKILL_SCORING, "QB",
    )
    print("Walk-forward evaluation (same held-out player-weeks for all baselines):")
    for fold in folds:
        print(fold)

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

    component_mae = np.mean(np.abs(predictions - y_train), axis=0)
    print("In-sample component MAE:", dict(zip(TARGETS, np.round(component_mae, 2))))
    scored_predictions = [score_stat_line(dict(zip(TARGETS, row)), REFERENCE_SKILL_SCORING, "QB") for row in predictions]
    scored_actual = [score_stat_line(dict(zip(TARGETS, row)), REFERENCE_SKILL_SCORING, "QB") for row in y_train]
    print(f"In-sample reference-score MAE: {np.mean(np.abs(np.asarray(scored_predictions) - scored_actual)):.2f}")


if __name__ == "__main__":
    main()
