import argparse
import json
import os

import psycopg
from dotenv import load_dotenv

import django

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "FantasyFootballAnalyzer.settings",
)

django.setup()

from scripts.algorithm.predictor import predict_defense, predict_player
from scripts.algorithm.stat_targets import POSITION_STAT_TARGETS
from leagues.services.scoring import REFERENCE_SKILL_SCORING, score_stat_line
from scripts.algorithm.k.scoring import REFERENCE_SCORING as K_REFERENCE_SCORING


load_dotenv()


conn = psycopg.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
)


SEASONS = [2023, 2024, 2025]

POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]

RECENT_GAMES = 4
SUCCESS_THRESHOLD = 3
ERROR_THRESHOLDS = [2, 3, 5, 7]
TOP_PLAYERS_PER_POSITION = 30


def get_top_players(season, position):
    """
    Get the top players by season fantasy points at a position.
    """

    with conn.cursor() as cur:

        cur.execute("""
            SELECT
                p.id,
                p.full_name,
                p.position,
                SUM(pws.fantasy_points_ppr) AS total_points
            FROM player_weekly_stats pws
            JOIN players p
                ON pws.player_id = p.id
            WHERE pws.season = %s
              AND pws.season_type = 'REG'
              AND p.position = %s
            GROUP BY
                p.id,
                p.full_name,
                p.position
            ORDER BY total_points DESC NULLS LAST, p.id
            LIMIT %s
        """, (
            season,
            position,
            TOP_PLAYERS_PER_POSITION,
        ))

        return cur.fetchall()

def get_player_games(player_id, season, position):
    """
    Get all regular-season games for a player in chronological order.
    """

    target_names = POSITION_STAT_TARGETS[position]
    # Model outputs use the descriptive name ``passing_attempts``, while the
    # player_weekly_stats table stores that count in its ``attempts`` column.
    # Alias it back to the model name so the actual stat line stays aligned
    # with POSITION_STAT_TARGETS when it is zipped below.
    columns = ", ".join(
        "pws.attempts AS passing_attempts"
        if name == "passing_attempts"
        else f"pws.{name}"
        for name in target_names
    )
    with conn.cursor() as cur:

        cur.execute("""
            SELECT
                pws.week,
                pws.opponent_team,
                {columns}
            FROM player_weekly_stats pws
            WHERE pws.player_id = %s
              AND pws.season = %s
              AND pws.season_type = 'REG'
            ORDER BY pws.week
        """.format(columns=columns), (
            player_id,
            season,
        ))

        return cur.fetchall()

def get_opponent_matchup(opponent, season, week, position):
    """
    Get the opponent's average PPR fantasy points allowed
    to a position before the player's upcoming game.

    Only games before the current week are included.
    """

    column_map = {
        "QB": "qb_fantasy_points_allowed",
        "RB": "rb_fantasy_points_allowed",
        "WR": "wr_fantasy_points_allowed",
        "TE": "te_fantasy_points_allowed",
    }

    column = column_map[position]

    query = f"""
        SELECT AVG({column})
        FROM team_weekly_stats tws
        JOIN teams t
            ON tws.team_id = t.id
        WHERE t.abbreviation = %s
          AND tws.season = %s
          AND tws.season_type = 1
          AND tws.week < %s
    """

    with conn.cursor() as cur:

        cur.execute(
            query,
            (
                opponent,
                season,
                week,
            )
        )

        result = cur.fetchone()

    return result[0] if result and result[0] is not None else None

def backtest_player(player_id, season, position, scoring_settings=REFERENCE_SKILL_SCORING):
    """
    Backtest one player for one season.
    """

    games = get_player_games(
        player_id,
        season,
        position,
    )

    first_game = True

    results = []

    for game in games:
        week, opponent, *actual_values = game
        actual_stats = dict(zip(POSITION_STAT_TARGETS[position], actual_values))

        # We need previous games before making a prediction.
        if first_game:
            first_game = False
            continue

        prediction = predict_player(
            player_id=player_id,
            season=season,
            week=week,
            scoring_settings=scoring_settings,
        )

        if prediction is None:
            continue

        projected_stats = prediction.get("projected_stats")
        if not projected_stats:
            continue
        try:
            projected = score_stat_line(projected_stats, scoring_settings, position)
            actual_points = score_stat_line(actual_stats, scoring_settings, position)
        except (TypeError, ValueError):
            continue

        if projected is None:
            continue

        difference = abs(
            float(projected) - float(actual_points)
        )

        results.append({
            "week": week,
            "opponent": opponent,
            "projected": projected,
            "actual": actual_points,
            "difference": difference,
        })

        # Only add the actual result AFTER
        # the prediction has been made.

    return results

def backtest_dst(season, scoring_settings=REFERENCE_SKILL_SCORING):
    """
    Backtest the top D/ST units by season fantasy points.

    D/ST is keyed by team, so select the top units in SQL before replaying
    their games.
    """

    with conn.cursor() as cur:
        cur.execute("""
            SELECT team_id, week, sacks, interceptions, fumble_recoveries,
                   defensive_tds, special_teams_tds, safeties, points_against
            FROM team_weekly_stats
            WHERE season = %s
              AND season_type = 1
              AND dst_fantasy_points IS NOT NULL
              AND team_id IN (
                  SELECT team_id
                  FROM team_weekly_stats
                  WHERE season = %s
                    AND season_type = 1
                    AND dst_fantasy_points IS NOT NULL
                  GROUP BY team_id
                  ORDER BY SUM(dst_fantasy_points) DESC NULLS LAST, team_id
                  LIMIT %s
              )
            ORDER BY team_id, week
        """, (season, season, TOP_PLAYERS_PER_POSITION))
        games = cur.fetchall()

    results = []

    target_names = POSITION_STAT_TARGETS["DEF"]
    for team_id, week, *actual_values in games:
        actual_stats = dict(zip(target_names, actual_values))

        # Need at least one prior game to build features.
        if week <= 1:
            continue

        prediction = predict_defense(team_id, season, week)

        if prediction is None:
            continue

        try:
            projected = score_stat_line(prediction.get("projected_stats", {}), scoring_settings, "DEF")
            actual_points = score_stat_line(actual_stats, scoring_settings, "DEF")
        except (TypeError, ValueError):
            continue

        if projected is None:
            continue

        results.append({
            "week": week,
            "opponent": team_id,
            "projected": projected,
            "actual": actual_points,
            "difference": abs(float(projected) - float(actual_points)),
        })

    return results


def backtest_k(season, scoring_settings=K_REFERENCE_SCORING):
    from scripts.algorithm.k.train_k_model import build_dataset, get_players, score_rows
    from scripts.algorithm.k.k_model import load_model, predict
    model = load_model()
    if model is None:
        return []
    X, y, baseline, rows, counts = build_dataset(season, get_players())
    if not len(y):
        return []
    actual_scores = score_rows(y, scoring_settings)
    points_by_player = {}
    for row, actual in zip(rows, actual_scores):
        points_by_player[row['player_id']] = (
            points_by_player.get(row['player_id'], 0.0) + float(actual)
        )
    top_player_ids = {
        player_id
        for player_id, _ in sorted(
            points_by_player.items(),
            key=lambda item: (-item[1], item[0]),
        )[:TOP_PLAYERS_PER_POSITION]
    }
    selected = [
        index for index, row in enumerate(rows)
        if row['player_id'] in top_player_ids
    ]
    projected_scores = score_rows(predict(model, X[selected]), scoring_settings)
    return [{**rows[row_index], 'projected': float(projected_scores[index]),
             'actual': float(actual_scores[row_index]),
             'difference': abs(float(projected_scores[index])-float(actual_scores[row_index]))}
            for index, row_index in enumerate(selected)]


def main(seasons=SEASONS, positions=POSITIONS, scoring_settings=None):

    print("Historical replay of saved models; training-season results are in-sample.")

    total_predictions = 0
    #successful_predictions = 0

    position_stats = {
        position: {
            "predictions": 0,
            "absolute_error": 0.0,
            "within_threshold": {
                threshold: 0
                for threshold in ERROR_THRESHOLDS
            },
        }
        for position in positions
    }

    season_stats = {
        season: {
            "predictions": 0,
            "absolute_error": 0.0,
            "within_threshold": {
                threshold: 0
                for threshold in ERROR_THRESHOLDS
            },
        }
        for season in seasons
    }

    for season in seasons:

        print()
        print(f"========== {season} ==========")

        for position in positions:

            if position == "K":
                batches = [backtest_k(season, scoring_settings or K_REFERENCE_SCORING)]
                print(f"K: top {TOP_PLAYERS_PER_POSITION} kickers by season points")
            elif position == "DST":
                batches = [backtest_dst(season, scoring_settings or REFERENCE_SKILL_SCORING)]
                print(f"{position}: top {TOP_PLAYERS_PER_POSITION} defenses by season points")
            else:
                players = get_top_players(
                    season,
                    position,
                )

                print(
                    f"{position}: "
                    f"{len(players)} players (top {TOP_PLAYERS_PER_POSITION})"
                )

                batches = (
                    backtest_player(player[0], season, position, scoring_settings or REFERENCE_SKILL_SCORING)
                    for player in players
                )

            for results in batches:

                for result in results:

                    total_predictions += 1

                    difference = result["difference"]

                    for threshold in ERROR_THRESHOLDS:
                        if difference <= threshold:
                            position_stats[position]["within_threshold"][threshold] += 1
                            season_stats[season]["within_threshold"][threshold] += 1



                    # Position statistics
                    position_stats[position]["predictions"] += 1
                    position_stats[position]["absolute_error"] += difference



                    # Season statistics
                    season_stats[season]["predictions"] += 1
                    season_stats[season]["absolute_error"] += difference

    print()
    print("========== OVERALL RESULTS ==========")

    print(f"Total predictions: {total_predictions}")

    if total_predictions > 0:

        average_error = (
                sum(
                    position_stats[position]["absolute_error"]
                    for position in positions
                )
                / total_predictions
        )

        print(f"Average absolute error: {average_error:.2f}")

        for threshold in ERROR_THRESHOLDS:
            count = sum(
                position_stats[position]["within_threshold"][threshold]
                for position in positions
            )

            percentage = (
                                 count / total_predictions
                         ) * 100

            print(
                f"Within {threshold} points: "
                f"{percentage:.2f}%"
            )

    print()
    print("========== BY POSITION ==========")

    for position in positions:

        stats = position_stats[position]

        if stats["predictions"] == 0:
            continue

        average_error = (
                stats["absolute_error"]
                / stats["predictions"]
        )

        print()
        print(f"{position}:")
        print(f"  Predictions: {stats['predictions']}")
        print(f"  Average absolute error: {average_error:.2f}")

        for threshold in ERROR_THRESHOLDS:
            percentage = (
                                 stats["within_threshold"][threshold]
                                 / stats["predictions"]
                         ) * 100

            print(
                f"  Within {threshold} points: "
                f"{percentage:.2f}%"
            )



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay saved position models against recorded games.")
    parser.add_argument("--seasons", type=int, nargs="+", default=SEASONS)
    parser.add_argument("--positions", nargs="+", choices=POSITIONS, default=POSITIONS)
    parser.add_argument("--scoring-settings", help="JSON scoring rules, e.g. '{\"pass_td\":6,\"rec\":1}'")
    args = parser.parse_args()
    scoring_settings = json.loads(args.scoring_settings) if args.scoring_settings else None
    try:
        main(args.seasons, args.positions, scoring_settings)
    finally:
        conn.close()
