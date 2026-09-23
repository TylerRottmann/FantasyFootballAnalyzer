import os

import psycopg
from dotenv import load_dotenv

from predictor import predict_fantasy_points


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

        # Use only the previous games.
        recent_for_prediction = recent_games[-RECENT_GAMES:]

        opponent_points_allowed = get_opponent_matchup(
            opponent,
            season,
            week,
            position,
        )

        projected = predict_fantasy_points(
            recent_for_prediction,
            opponent_points_allowed,
        )

        difference = float(abs(projected - actual_points))

        success = difference <= SUCCESS_THRESHOLD

        results.append({
            "week": week,
            "opponent": opponent,
            "projected": projected,
            "actual": actual_points,
            "difference": difference,
            "success": success,
        })

        # Only add the actual result AFTER
        # the prediction has been made.
        recent_games.append(actual_points)

    return results

def main():

    total_predictions = 0
    successful_predictions = 0

    position_stats = {
        position: {
            "predictions": 0,
            "successes": 0,
            "absolute_error": 0.0,
        }
        for position in POSITIONS
    }

    season_stats = {
        season: {
            "predictions": 0,
            "successes": 0,
            "absolute_error": 0.0,
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

                    if result["success"]:
                        successful_predictions += 1

                    # Position statistics
                    position_stats[position]["predictions"] += 1
                    position_stats[position]["absolute_error"] += difference

                    if result["success"]:
                        position_stats[position]["successes"] += 1

                    # Season statistics
                    season_stats[season]["predictions"] += 1
                    season_stats[season]["absolute_error"] += difference

                    if result["success"]:
                        season_stats[season]["successes"] += 1

    print()
    print("========== OVERALL RESULTS ==========")

    print(f"Total predictions: {total_predictions}")
    print(f"Successful predictions: {successful_predictions}")

    if total_predictions > 0:

        success_rate = (
            successful_predictions /
            total_predictions
        ) * 100

        average_error = (
            sum(
                position_stats[position]["absolute_error"]
                for position in POSITIONS
            ) /
            total_predictions
        )

        print(f"Success rate: {success_rate:.2f}%")
        print(f"Average absolute error: {average_error:.2f}")
        print("Target: 70.00%")

    print()
    print("========== BY POSITION ==========")

    for position in POSITIONS:

        stats = position_stats[position]

        if stats["predictions"] == 0:
            continue

        success_rate = (
            stats["successes"] /
            stats["predictions"]
        ) * 100

        average_error = (
            stats["absolute_error"] /
            stats["predictions"]
        )

        print(
            f"{position}: "
            f"{success_rate:.2f}% success | "
            f"{average_error:.2f} avg error | "
            f"{stats['predictions']} predictions"
        )

    print()
    print("========== BY SEASON ==========")

    for season in SEASONS:

        stats = season_stats[season]

        if stats["predictions"] == 0:
            continue

        success_rate = (
            stats["successes"] /
            stats["predictions"]
        ) * 100

        average_error = (
            stats["absolute_error"] /
            stats["predictions"]
        )

        print(
            f"{season}: "
            f"{success_rate:.2f}% success | "
            f"{average_error:.2f} avg error | "
            f"{stats['predictions']} predictions"
        )


if __name__ == "__main__":
    main()
