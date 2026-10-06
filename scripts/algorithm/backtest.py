import os

import psycopg
from dotenv import load_dotenv

import django

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "FantasyFootballAnalyzer.settings",
)

django.setup()

from scripts.algorithm.predictor import predict_player


load_dotenv()


conn = psycopg.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
)


SEASONS = [2023, 2024, 2025]

POSITIONS = ["QB", "RB", "WR", "TE"]

RECENT_GAMES = 4
SUCCESS_THRESHOLD = 3
ERROR_THRESHOLDS = [2, 3, 5, 7]


def get_top_players(season, position):
    """
    Get the top 30 players at a position for a season.

    Ranking is based on total PPR fantasy points.
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
            ORDER BY total_points DESC
            LIMIT 30
        """, (
            season,
            position,
        ))

        return cur.fetchall()

def get_player_games(player_id, season):
    """
    Get all regular-season games for a player in chronological order.
    """

    with conn.cursor() as cur:

        cur.execute("""
            SELECT
                pws.week,
                pws.opponent_team,
                pws.fantasy_points_ppr
            FROM player_weekly_stats pws
            WHERE pws.player_id = %s
              AND pws.season = %s
              AND pws.season_type = 'REG'
            ORDER BY pws.week
        """, (
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

def backtest_player(player_id, season, position):
    """
    Backtest one player for one season.
    """

    games = get_player_games(
        player_id,
        season,
    )

    recent_games = []

    results = []

    for week, opponent, actual_points in games:

        # We need previous games before making a prediction.
        if len(recent_games) < 1:
            recent_games.append(actual_points)
            continue

        prediction = predict_player(
            player_id=player_id,
            season=season,
            week=week,
        )

        if prediction is None:
            continue

        projected = prediction["projected_fantasy_points"]

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
        recent_games.append(actual_points)

    return results

def main():

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
        for position in POSITIONS
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
        for season in SEASONS
    }

    for season in SEASONS:

        print()
        print(f"========== {season} ==========")

        for position in POSITIONS:

            players = get_top_players(
                season,
                position,
            )

            print(
                f"{position}: "
                f"{len(players)} players"
            )

            for player in players:

                player_id = player[0]

                results = backtest_player(
                    player_id,
                    season,
                    position,
                )

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
                    for position in POSITIONS
                )
                / total_predictions
        )

        print(f"Average absolute error: {average_error:.2f}")

        for threshold in ERROR_THRESHOLDS:
            count = sum(
                position_stats[position]["within_threshold"][threshold]
                for position in POSITIONS
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

    for position in POSITIONS:

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
    main()
