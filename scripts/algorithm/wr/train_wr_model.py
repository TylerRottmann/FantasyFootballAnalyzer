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
from scripts.algorithm.features.wr_features import build_wr_features
from scripts.algorithm.wr.feature_names import (
    TARGET_SHARE_FEATURE_NAMES,
    WR_FEATURE_NAMES,
)
from scripts.algorithm.wr.wr_model import (
    create_model,
    predict,
    train_model,
)


SEASONS = [2023, 2024, 2025]

# The most recent season is held out for an honest accuracy check
# before the final model is retrained on every season.
HOLDOUT_SEASON = 2025

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
# GET WR GAMES
# ============================================================

def get_wr_games(season, wr_ids):
    """
    Retrieve every regular-season WR game for a season.

    Unlike the QB script (which infers QBs from passing stats),
    WRs are identified by Player.position == 'WR'.
    """

    if not wr_ids:
        return []

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
                  AND player_id = ANY(%s)
                ORDER BY player_id, week
                """,
                (season, list(wr_ids)),
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

    games = get_wr_games(season, players_by_id.keys())

    print()
    print(f"Building dataset for {season}...")
    print(f"Games found: {len(games)}")

    for index, (player_id, week, actual_points) in enumerate(
        games,
        start=1,
    ):

        # Cannot predict Week 1 from previous games.
        if week <= 1:
            continue

        player = players_by_id.get(player_id)

        if player is None:
            continue

        try:
            features = build_wr_features(
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

        for feature_name in WR_FEATURE_NAMES:

            value = features.get(feature_name)

            if value is None:
                row.append(np.nan)
            else:
                row.append(float(value))

        X.append(row)
        y.append(float(actual_points))

        if index % 500 == 0:
            print(f"Processed {index}/{len(games)}")

    return np.array(X), np.array(y)


# ============================================================
# EVALUATION HELPERS
# ============================================================

def report(label, predictions, actual):
    errors = np.abs(predictions - actual)

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
    print("BUILDING WR TRAINING DATA")
    print("=" * 60)

    players_by_id = {
        player.id: player
        for player in Player.objects.filter(position="WR")
    }

    print(f"WR players in database: {len(players_by_id)}")

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

    for index, feature_name in enumerate(WR_FEATURE_NAMES):

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
    # HOLDOUT CHECK (train on earlier seasons, test on latest)
    # --------------------------------------------------------

    train_seasons = [s for s in SEASONS if s != HOLDOUT_SEASON]

    X_holdout, y_holdout = datasets[HOLDOUT_SEASON]

    train_parts = [
        datasets[s] for s in train_seasons if len(datasets[s][0])
    ]

    if len(X_holdout) > 0 and train_parts:

        X_train = np.concatenate([p[0] for p in train_parts], axis=0)
        y_train = np.concatenate([p[1] for p in train_parts], axis=0)

        # create_model() (not train_model) so the holdout model
        # is NOT written to disk.
        holdout_model = create_model()
        holdout_model.fit(X_train, y_train)

        print()
        print("=" * 60)
        print(
            f"HOLDOUT: trained on {train_seasons}, "
            f"tested on {HOLDOUT_SEASON}"
        )
        print("=" * 60)

        report(
            "WR model (all features)",
            predict(holdout_model, X_holdout),
            y_holdout,
        )

        # Same model, same data, but with the target share columns
        # removed, to show what target share is actually adding.
        base_columns = [
            index
            for index, name in enumerate(WR_FEATURE_NAMES)
            if name not in TARGET_SHARE_FEATURE_NAMES
        ]

        base_model = create_model()
        base_model.fit(X_train[:, base_columns], y_train)

        report(
            "WR model (no target share)",
            predict(base_model, X_holdout[:, base_columns]),
            y_holdout,
        )

        # Baseline: just use the player's last-3-game average.
        l3_index = WR_FEATURE_NAMES.index("fantasy_points_l3")
        l3 = X_holdout[:, l3_index]
        has_l3 = ~np.isnan(l3)

        if has_l3.any():
            report(
                "Baseline (last-3 average)",
                l3[has_l3],
                y_holdout[has_l3],
            )

    # --------------------------------------------------------
    # FINAL MODEL (all seasons) -> saved to wr_model.pkl
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
        "WR model (in-sample)",
        predict(model, X_all),
        y_all,
    )


if __name__ == "__main__":
    main()
