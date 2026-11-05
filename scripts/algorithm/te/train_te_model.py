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
from scripts.algorithm.features.te_features import build_te_features
from scripts.algorithm.te.feature_names import (
    TE_FEATURE_NAMES,
)
from scripts.algorithm.te.te_model import (
    create_model,
    predict,
    train_model,
)
from scripts.algorithm.te.te_model import TARGETS
from leagues.services.scoring import REFERENCE_SKILL_SCORING, score_stat_line
from scripts.algorithm.rolling_evaluation import evaluate_walk_forward


SEASONS = [2023, 2024, 2025]

SUCCESS_THRESHOLD = 3.0


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
# GET TE GAMES
# ============================================================

def get_te_games(season, te_ids):
    """
    Retrieve every regular-season TE game for a season.

    Unlike the QB script (which infers QBs from passing stats),
    TEs are identified by Player.position == 'TE'.
    """

    if not te_ids:
        return []

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    player_id,
                    week,
                    COALESCE(passing_yards, 0), COALESCE(passing_tds, 0),
                    COALESCE(passing_interceptions, 0), COALESCE(passing_2pt_conversions, 0),
                    COALESCE(carries, 0),
                    COALESCE(rushing_yards, 0), COALESCE(rushing_tds, 0),
                    COALESCE(rushing_2pt_conversions, 0),
                    COALESCE(targets, 0), COALESCE(receptions, 0),
                    COALESCE(receiving_yards, 0), COALESCE(receiving_tds, 0),
                    COALESCE(receiving_2pt_conversions, 0),
                    COALESCE(fumbles_lost, 0)
                FROM player_weekly_stats
                WHERE season = %s
                  AND season_type = 'REG'
                  AND player_id = ANY(%s)
                ORDER BY player_id, week
                """,
                (season, list(te_ids)),
            )

            return cur.fetchall()

    finally:
        conn.close()


# ============================================================
# BUILD DATASET
# ============================================================

def build_dataset(season, players_by_id):
    """
    Build the training dataset for one season.

    All features are built using only information available
    before the prediction week.
    """

    X = []
    y = []

    games = get_te_games(season, players_by_id.keys())

    print()
    print(f"Building dataset for {season}...")
    print(f"Games found: {len(games)}")

    for index, game in enumerate(
        games,
        start=1,
    ):
        player_id, week, *actual_stats = game

        player = players_by_id.get(player_id)

        if player is None:
            continue

        try:
            features = build_te_features(
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

        row = []

        for feature_name in TE_FEATURE_NAMES:

            value = features.get(feature_name)

            if value is None:
                row.append(np.nan)
            else:
                row.append(float(value))

        X.append(row)
        y.append([float(value) for value in actual_stats])

        if index % 500 == 0:
            print(f"Processed {index}/{len(games)}")

    return np.asarray(X, dtype=float).reshape(-1, len(TE_FEATURE_NAMES)), np.asarray(y, dtype=float).reshape(-1, len(TARGETS))


# ============================================================
# EVALUATION HELPERS
# ============================================================

def report(label, predictions, actual):
    def score_rows(rows):
        return np.asarray([
            score_stat_line(dict(zip(TARGETS, row)), REFERENCE_SKILL_SCORING, "TE")
            for row in rows
        ])
    errors = np.abs(score_rows(predictions) - score_rows(actual))

    print(
        f"{label:<34} "
        f"MAE {np.mean(errors):5.2f} | "
        f"within {SUCCESS_THRESHOLD:.0f} pts "
        f"{np.mean(errors <= SUCCESS_THRESHOLD) * 100:5.1f}%"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("BUILDING TE TRAINING DATA")
    print("=" * 60)

    players_by_id = {
        player.id: player
        for player in Player.objects.filter(position="TE")
    }

    print(f"TE players in database: {len(players_by_id)}")

    datasets = {}

    for season in SEASONS:
        datasets[season] = build_dataset(season, players_by_id)

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("DATASET SUMMARY")
    print("=" * 60)

    for season in SEASONS:
        print(f"{season} rows: {len(datasets[season][0])}")

    all_parts = [
        datasets[season]
        for season in SEASONS
        if len(datasets[season][0]) > 0
    ]

    if not all_parts:
        print("No training data was created.")
        return

    X_all = np.concatenate([part[0] for part in all_parts], axis=0)
    y_all = np.concatenate([part[1] for part in all_parts], axis=0)

    print(f"Total rows: {len(X_all)}")
    print(f"Features: {X_all.shape[1]}")

    # --------------------------------------------------------
    # FEATURE DIAGNOSTICS
    # --------------------------------------------------------

    print()
    print("=" * 80)
    print("FEATURE DIAGNOSTICS")
    print("=" * 80)

    invalid_features = []

    for index, feature_name in enumerate(TE_FEATURE_NAMES):

        column = X_all[:, index]
        valid_values = column[~np.isnan(column)]
        unique_values = np.unique(valid_values)

        print(
            f"{index:3d} | "
            f"{feature_name:<50} | "
            f"valid={len(valid_values):5d} | "
            f"unique={len(unique_values):5d}"
        )

        if len(valid_values) == 0:
            invalid_features.append(feature_name)

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

    # --------------------------------------------------------
    # Rolling-origin evaluation: each later season is held out once.
    # --------------------------------------------------------
    folds = evaluate_walk_forward(
        datasets, SEASONS, create_model, predict, TARGETS, TE_FEATURE_NAMES,
        REFERENCE_SKILL_SCORING, "TE",
    )
    print("Walk-forward evaluation (same held-out rows for model and baselines):")
    for fold in folds:
        print(fold)

    # --------------------------------------------------------
    # FINAL MODEL (all seasons) -> saved to te_model.pkl
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("TRAINING FINAL MODEL ON ALL SEASONS")
    print("=" * 60)

    model = train_model(X_all, y_all)

    print("Model trained and saved.")

    print()
    print("Training-set fit (in-sample, optimistic):")

    report(
        "TE model (in-sample)",
        predict(model, X_all),
        y_all,
    )


if __name__ == "__main__":
    main()
