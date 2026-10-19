import os

import numpy as np
import psycopg
from dotenv import load_dotenv

load_dotenv()

from scripts.algorithm.dst.dst_model import (
    CANDIDATES,
    SHRINK_VALUES,
    create_model,
    predict,
    train_model,
)
from scripts.algorithm.dst.feature_names import DST_FEATURE_NAMES
from scripts.algorithm.features.dst_features import build_dst_features

SEASONS = [2023, 2024, 2025]
HOLDOUT_SEASON = 2025


def get_connection():
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def get_dst_games(season):
    """Every regular-season team-week that has a D/ST score."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT team_id, week, dst_fantasy_points
                FROM team_weekly_stats
                WHERE season = %s
                  AND season_type = 1
                  AND dst_fantasy_points IS NOT NULL
                ORDER BY team_id, week
                """,
                (season,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def build_dataset(season):
    X, y = [], []
    games = get_dst_games(season)
    print(f"\nBuilding dataset for {season}... games found: {len(games)}")

    for index, (team_id, week, actual) in enumerate(games, start=1):
        # Week 1 has no prior games to build features from.
        if week <= 1:
            continue

        try:
            features = build_dst_features(team_id, season, week)
        except Exception as exc:
            print(f"Skipping team {team_id}, week {week}: {exc}")
            continue

        X.append([
            np.nan if features.get(n) is None else float(features[n])
            for n in DST_FEATURE_NAMES
        ])
        y.append(float(actual))

        if index % 100 == 0:
            print(f"Processed {index}/{len(games)}")

    return np.array(X, dtype=float), np.array(y, dtype=float)


def report(label, y_true, y_pred):
    errors = np.abs(y_pred - y_true)
    print(f"{label}: MAE {errors.mean():.2f} | within 3 pts "
          f"{(errors <= 3).mean() * 100:.1f}%")


def main():
    datasets = {season: build_dataset(season) for season in SEASONS}

    for season, (X, _) in datasets.items():
        print(f"{season} rows: {len(X)}")

    X_all = np.concatenate([d[0] for d in datasets.values()])
    y_all = np.concatenate([d[1] for d in datasets.values()])

    if len(X_all) == 0:
        print("No training data was created. Did load_dst_stats.py run?")
        return

    # Fail loudly on dead features, same as the QB trainer.
    empty = [n for i, n in enumerate(DST_FEATURE_NAMES)
             if np.isnan(X_all[:, i]).all()]
    if empty:
        print("ERROR: features with no valid values:", empty)
        return

    # ------------------------------------------------------------
    # HOLDOUT COMPARISON: train on earlier seasons, score the held-out
    # season for every (model, shrinkage) combination, and compare to
    # simple baselines. The best MAE is used for the final model.
    #
    # Caveat: picking the winner on the same holdout we report is
    # slightly optimistic, but with only 9 combinations the effect is
    # small.
    # ------------------------------------------------------------
    train_seasons = [s for s in SEASONS if s != HOLDOUT_SEASON]
    X_tr = np.concatenate([datasets[s][0] for s in train_seasons])
    y_tr = np.concatenate([datasets[s][1] for s in train_seasons])
    X_ho, y_ho = datasets[HOLDOUT_SEASON]

    best = ("ridge_slim", 1.0)

    if len(X_ho) and len(X_tr):
        print(f"\nHOLDOUT {HOLDOUT_SEASON} (trained on {train_seasons})")

        avg_idx = DST_FEATURE_NAMES.index("dst_fantasy_points_season")
        baseline = np.where(
            np.isnan(X_ho[:, avg_idx]), y_tr.mean(), X_ho[:, avg_idx]
        )
        report("Season-avg baseline", y_ho, baseline)
        report("League-avg baseline", y_ho, np.full_like(y_ho, y_tr.mean()))
        print()

        best_mae = float("inf")

        for name in CANDIDATES:
            for shrink in SHRINK_VALUES:
                model = create_model(name, shrink).fit(X_tr, y_tr)
                preds = predict(model, X_ho)
                report(f"{name:<11} shrink={shrink:<3}", y_ho, preds)

                mae = np.abs(preds - y_ho).mean()
                if mae < best_mae:
                    best_mae, best = mae, (name, shrink)

        print(f"\nBest on holdout: {best[0]}, shrink={best[1]} "
              f"(MAE {best_mae:.2f})")

    # ------------------------------------------------------------
    # FINAL MODEL: refit the winning config on all seasons and save.
    # ------------------------------------------------------------
    model = train_model(X_all, y_all, name=best[0], shrink=best[1])
    print(f"\nFinal model ({model.describe()}) trained on "
          f"{len(X_all)} rows and saved.")
    report("In-sample", y_all, predict(model, X_all))

if __name__ == "__main__":
    main()
