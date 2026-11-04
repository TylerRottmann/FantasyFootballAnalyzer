"""Train D/ST stat components and compare league-scored holdout results."""
import os

import numpy as np
import psycopg
from dotenv import load_dotenv

load_dotenv()

from scripts.algorithm.dst.dst_model import TARGETS, create_model, predict, train_model
from scripts.algorithm.dst.feature_names import DST_FEATURE_NAMES
from scripts.algorithm.features.dst_features import build_dst_features
from leagues.services.scoring import REFERENCE_SKILL_SCORING, score_stat_line

SEASONS = [2023, 2024, 2025]
# Each fold uses only seasons before its holdout. Keep the most recent season
# out of the final fold's training data, then fit the production model on all
# configured seasons after evaluation is complete.
ROLLING_HOLDOUT_SEASONS = SEASONS[1:]


def get_connection():
    return psycopg.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def get_dst_games(season):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT team_id, week, COALESCE(sacks, 0), COALESCE(interceptions, 0),
                       COALESCE(forced_fumbles, 0), COALESCE(fumble_recoveries, 0),
                       COALESCE(defensive_tds, 0), COALESCE(special_teams_tds, 0),
                       COALESCE(safeties, 0), COALESCE(points_against, 0)
                FROM team_weekly_stats
                WHERE season = %s AND season_type = 1
                ORDER BY team_id, week
            """, (season,))
            return cur.fetchall()
    finally:
        conn.close()


def build_dataset(season):
    X, y = [], []
    games = get_dst_games(season)
    for team_id, week, *actual_stats in games:
        if week <= 1:
            continue
        features = build_dst_features(team_id, season, week)
        X.append([np.nan if features.get(name) is None else float(features[name]) for name in DST_FEATURE_NAMES])
        y.append([float(value) for value in actual_stats])
    return (np.asarray(X, dtype=float).reshape(-1, len(DST_FEATURE_NAMES)),
            np.asarray(y, dtype=float).reshape(-1, len(TARGETS)))


def score_rows(rows):
    return np.asarray([
        score_stat_line(dict(zip(TARGETS, row)), REFERENCE_SKILL_SCORING, "DEF")
        for row in rows
    ])


def report(label, actual_stats, predicted_stats):
    actual_points = score_rows(actual_stats)
    predicted_points = np.asarray(predicted_stats, dtype=float)
    errors = predicted_points - actual_points
    print(
        f"  {label}: MAE {np.abs(errors).mean():.2f} | "
        f"RMSE {np.sqrt(np.mean(errors ** 2)):.2f} | "
        f"bias {errors.mean():+.2f} | within 3 pts "
        f"{(np.abs(errors) <= 3).mean() * 100:.1f}%"
    )


def evaluate_rolling_holdouts(datasets):
    """Compare D/ST model with simple scoring baselines on future seasons."""
    for holdout_season in ROLLING_HOLDOUT_SEASONS:
        train_seasons = [season for season in SEASONS if season < holdout_season]
        if not train_seasons:
            continue

        X_train = np.concatenate([datasets[season][0] for season in train_seasons])
        y_train = np.concatenate([datasets[season][1] for season in train_seasons])
        X_holdout, y_holdout = datasets[holdout_season]
        if not len(X_train) or not len(X_holdout):
            print(f"Skipping holdout {holdout_season}: missing train or holdout rows.")
            continue

        model = create_model().fit(X_train, y_train)
        model_points = score_rows(predict(model, X_holdout))
        train_points = score_rows(y_train)
        league_average = np.full(len(y_holdout), float(np.mean(train_points)))

        # This historical D/ST score uses the same reference scoring rules as
        # score_rows(), and is built only from games before each target week.
        recent_index = DST_FEATURE_NAMES.index("dst_fantasy_points_l3")
        recent_points = X_holdout[:, recent_index].copy()
        recent_points[~np.isfinite(recent_points)] = float(np.mean(train_points))

        print(f"Rolling holdout {holdout_season} trained on {train_seasons} ({len(y_holdout)} rows)")
        report("D/ST stat model", y_holdout, model_points)
        report("League-average baseline", y_holdout, league_average)
        report("Team last-3-game baseline", y_holdout, recent_points)


def main():
    datasets = {season: build_dataset(season) for season in SEASONS}
    evaluate_rolling_holdouts(datasets)

    X_all = np.concatenate([datasets[season][0] for season in SEASONS])
    y_all = np.concatenate([datasets[season][1] for season in SEASONS])
    if not len(y_all):
        raise ValueError("No D/ST stat-line training rows were created.")
    model = train_model(X_all, y_all)
    print(f"Saved D/ST stat model trained on {SEASONS} ({len(y_all)} rows).")


if __name__ == "__main__":
    main()
