import os
import statistics

import psycopg
from dotenv import load_dotenv


load_dotenv()


# ============================================================
# DATABASE CONNECTION
# ============================================================

_connection = None


def get_connection():
    """
    Return a reusable PostgreSQL database connection.
    """

    global _connection

    if _connection is None or _connection.closed:
        _connection = psycopg.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
        )

    return _connection


# ============================================================
# HELPERS
# ============================================================

def average(values):
    """
    Calculate the average of non-null values.
    """

    valid_values = [
        float(value)
        for value in values
        if value is not None
    ]

    if not valid_values:
        return None

    return sum(valid_values) / len(valid_values)


def safe_rate(numerator_values, denominator_values):
    """
    Calculate a rate using:

        total numerator / total denominator

    Example:

        passing TDs / passing attempts
    """

    numerators = [
        float(value)
        for value in numerator_values
        if value is not None
    ]

    denominators = [
        float(value)
        for value in denominator_values
        if value is not None
    ]

    if not numerators or not denominators:
        return None

    denominator = sum(denominators)

    if denominator == 0:
        return None

    return sum(numerators) / denominator


def yards_per_attempt(yards_values, attempt_values):
    """
    Calculate yards per attempt.
    """

    yards = [
        float(value)
        for value in yards_values
        if value is not None
    ]

    attempts = [
        float(value)
        for value in attempt_values
        if value is not None
    ]

    if not yards or not attempts:
        return None

    total_attempts = sum(attempts)

    if total_attempts == 0:
        return None

    return sum(yards) / total_attempts


def standard_deviation(values):
    """
    Calculate sample standard deviation of non-null values.

    Returns None when there are fewer than two valid values.
    """

    valid_values = [
        float(value)
        for value in values
        if value is not None
    ]

    if len(valid_values) < 2:
        return None

    return statistics.stdev(valid_values)


def trend(recent_value, longer_value):
    """
    Calculate a simple trend:

        recent window - longer window

    Positive values indicate improvement in the recent window.
    Negative values indicate decline.
    """

    if recent_value is None or longer_value is None:
        return None

    return float(recent_value) - float(longer_value)


# ============================================================
# QB HISTORY
# ============================================================

def get_qb_history(player_id, season, week):
    """
    Get all QB statistics from games BEFORE the prediction week.

    IMPORTANT:
    No statistics from the prediction week are included.
    """

    query = """
        SELECT
            week,
            completions,
            attempts,
            passing_yards,
            passing_tds,
            passing_interceptions,
            carries,
            rushing_yards,
            rushing_tds,
            fantasy_points_ppr
        FROM player_weekly_stats
        WHERE player_id = %s
          AND season = %s
          AND season_type = 'REG'
          AND week < %s
        ORDER BY week
    """

    conn = get_connection()

    with conn.cursor() as cur:
        cur.execute(
            query,
            (
                player_id,
                season,
                week,
            ),
        )

        return cur.fetchall()


# ============================================================
# HISTORICAL GAME CONTEXT
# ============================================================

def get_player_game_context(player_id, season, week):
    """
    Determine the player's actual team and opponent for a game.

    The player's current team is NOT used because it would cause
    historical backtesting problems.
    """

    query = """
        SELECT
            pws.opponent_team,
            tws.team_id,
            tws.opponent_team_id,
            tws.is_home
        FROM player_weekly_stats pws

        JOIN teams opponent
            ON opponent.abbreviation = pws.opponent_team

        JOIN team_weekly_stats tws
            ON tws.opponent_team_id = opponent.id
            AND tws.season = pws.season
            AND tws.week = pws.week
            AND tws.season_type = 1

        WHERE pws.player_id = %s
          AND pws.season = %s
          AND pws.week = %s
          AND pws.season_type = 'REG'

        LIMIT 1
    """

    conn = get_connection()

    with conn.cursor() as cur:
        cur.execute(
            query,
            (
                player_id,
                season,
                week,
            ),
        )

        row = cur.fetchone()

    if row is None:
        return None

    return {
        "opponent_team": row[0],
        "team_id": row[1],
        "opponent_team_id": row[2],
        "is_home": row[3],
    }


# ============================================================
# TEAM HISTORY
# ============================================================

def get_team_games(team_id, season, week):
    """
    Get team performance from games BEFORE the prediction week.
    """

    query = """
        SELECT
            week,
            is_home,
            points_for,
            passing_yards,
            rushing_yards,
            total_yards
        FROM team_weekly_stats
        WHERE team_id = %s
          AND season = %s
          AND season_type = 1
          AND week < %s
        ORDER BY week
    """

    conn = get_connection()

    with conn.cursor() as cur:
        cur.execute(
            query,
            (
                team_id,
                season,
                week,
            ),
        )

        return cur.fetchall()


# ============================================================
# OPPONENT HISTORY
# ============================================================

def get_opponent_defense(opponent_team_id, season, week):
    """
    Get opponent defensive performance from games BEFORE
    the prediction week.
    """

    query = """
        SELECT
            qb_fantasy_points_allowed,
            passing_yards_against,
            points_against,
            total_yards_against,
            rushing_yards_against,
            sacks,
            interceptions
        FROM team_weekly_stats
        WHERE team_id = %s
          AND season = %s
          AND season_type = 1
          AND week < %s
        ORDER BY week
    """

    conn = get_connection()

    with conn.cursor() as cur:
        cur.execute(
            query,
            (
                opponent_team_id,
                season,
                week,
            ),
        )

        return cur.fetchall()


# ============================================================
# MAIN FEATURE BUILDER
# ============================================================

def build_qb_features(player, season, week):
    """
    Build the complete pre-game feature set for a QB.

    All performance statistics come from games BEFORE the
    prediction week.

    Feature groups:

        1. QB production
        2. QB efficiency
        3. QB consistency / volatility
        4. QB trends
        5. Team offensive environment
        6. Opponent defensive matchup
        7. Game context
    """

    # ========================================================
    # 1. QB HISTORY
    # ========================================================

    qb_games = get_qb_history(
        player.id,
        season,
        week,
    )

    last_1_qb = qb_games[-1:]
    last_3_qb = qb_games[-3:]
    last_5_qb = qb_games[-5:]
    last_8_qb = qb_games[-8:]

    # ========================================================
    # 2. HISTORICAL GAME CONTEXT
    # ========================================================

    game_context = get_player_game_context(
        player.id,
        season,
        week,
    )

    team_games = []
    opponent_games = []

    team_id = None
    opponent_team_id = None
    is_home = None
    opponent_team = None

    if game_context is not None:

        team_id = game_context["team_id"]
        opponent_team_id = game_context["opponent_team_id"]
        is_home = game_context["is_home"]
        opponent_team = game_context["opponent_team"]

        # ====================================================
        # 3. TEAM HISTORY
        # ====================================================

        if team_id is not None:

            team_games = get_team_games(
                team_id,
                season,
                week,
            )

        # ====================================================
        # 4. OPPONENT HISTORY
        # ====================================================

        if opponent_team_id is not None:

            opponent_games = get_opponent_defense(
                opponent_team_id,
                season,
                week,
            )

    # ========================================================
    # 5. FEATURE WINDOWS
    # ========================================================

    qb_windows = {
        "l1": last_1_qb,
        "l3": last_3_qb,
        "l5": last_5_qb,
        "l8": last_8_qb,
        "season": qb_games,
    }

    team_windows = {
        "l3": team_games[-3:],
        "l5": team_games[-5:],
        "l8": team_games[-8:],
        "season": team_games,
    }

    features = {

        # ----------------------------------------------------
        # IDENTIFICATION
        # ----------------------------------------------------

        "player_id": player.id,
        "season": season,
        "week": week,

        # ----------------------------------------------------
        # GAME CONTEXT
        # ----------------------------------------------------

        "team_id": team_id,
        "opponent_team": opponent_team,
        "opponent_team_id": opponent_team_id,
        "is_home": is_home,

        # ----------------------------------------------------
        # QB EXPERIENCE / SAMPLE SIZE
        # ----------------------------------------------------

        "games_played": len(qb_games),
        "games_played_l8": len(last_8_qb),
    }

    # ========================================================
    # 6. QB PRODUCTION / EFFICIENCY / CONSISTENCY
    # ========================================================

    for name, games in qb_windows.items():

        # ----------------------------------------------------
        # PRODUCTION
        # ----------------------------------------------------

        features[f"fantasy_points_{name}"] = average(
            [game[9] for game in games]
        )

        features[f"passing_attempts_{name}"] = average(
            [game[2] for game in games]
        )

        features[f"passing_yards_{name}"] = average(
            [game[3] for game in games]
        )

        features[f"passing_tds_{name}"] = average(
            [game[4] for game in games]
        )

        features[f"interceptions_{name}"] = average(
            [game[5] for game in games]
        )

        features[f"rushing_attempts_{name}"] = average(
            [game[6] for game in games]
        )

        features[f"rushing_yards_{name}"] = average(
            [game[7] for game in games]
        )

        features[f"rushing_tds_{name}"] = average(
            [game[8] for game in games]
        )

        # ----------------------------------------------------
        # PASSING EFFICIENCY
        # ----------------------------------------------------

        features[f"completion_rate_{name}"] = safe_rate(
            [game[1] for game in games],
            [game[2] for game in games],
        )

        features[f"passing_yards_per_attempt_{name}"] = (
            yards_per_attempt(
                [game[3] for game in games],
                [game[2] for game in games],
            )
        )

        features[f"passing_td_rate_{name}"] = safe_rate(
            [game[4] for game in games],
            [game[2] for game in games],
        )

        features[f"interception_rate_{name}"] = safe_rate(
            [game[5] for game in games],
            [game[2] for game in games],
        )

        # ----------------------------------------------------
        # RUSHING EFFICIENCY
        # ----------------------------------------------------

        features[f"rushing_yards_per_attempt_{name}"] = (
            yards_per_attempt(
                [game[7] for game in games],
                [game[6] for game in games],
            )
        )

        features[f"rushing_td_rate_{name}"] = safe_rate(
            [game[8] for game in games],
            [game[6] for game in games],
        )

        # ----------------------------------------------------
        # CONSISTENCY / VOLATILITY
        # ----------------------------------------------------

        features[f"fantasy_points_stddev_{name}"] = (
            standard_deviation(
                [game[9] for game in games]
            )
        )

        features[f"passing_yards_stddev_{name}"] = (
            standard_deviation(
                [game[3] for game in games]
            )
        )

        features[f"passing_attempts_stddev_{name}"] = (
            standard_deviation(
                [game[2] for game in games]
            )
        )

        features[f"rushing_yards_stddev_{name}"] = (
            standard_deviation(
                [game[7] for game in games]
            )
        )

    # ========================================================
    # 7. QB TREND FEATURES
    # ========================================================

    # Recent performance vs longer-term performance.

    features["fantasy_points_trend_l3_l8"] = trend(
        features["fantasy_points_l3"],
        features["fantasy_points_l8"],
    )

    features["passing_yards_trend_l3_l8"] = trend(
        features["passing_yards_l3"],
        features["passing_yards_l8"],
    )

    features["passing_attempts_trend_l3_l8"] = trend(
        features["passing_attempts_l3"],
        features["passing_attempts_l8"],
    )

    features["passing_yards_per_attempt_trend_l3_l8"] = trend(
        features["passing_yards_per_attempt_l3"],
        features["passing_yards_per_attempt_l8"],
    )

    features["completion_rate_trend_l3_l8"] = trend(
        features["completion_rate_l3"],
        features["completion_rate_l8"],
    )

    features["rushing_yards_trend_l3_l8"] = trend(
        features["rushing_yards_l3"],
        features["rushing_yards_l8"],
    )

    # ========================================================
    # 8. TEAM OFFENSIVE ENVIRONMENT
    # ========================================================

    for name, games in team_windows.items():

        features[f"team_points_{name}"] = average(
            [game[2] for game in games]
        )

        features[f"team_passing_yards_{name}"] = average(
            [game[3] for game in games]
        )

        features[f"team_rushing_yards_{name}"] = average(
            [game[4] for game in games]
        )

        features[f"team_total_yards_{name}"] = average(
            [game[5] for game in games]
        )

    # --------------------------------------------------------
    # TEAM TRENDS
    # --------------------------------------------------------

    features["team_points_trend_l3_l8"] = trend(
        features["team_points_l3"],
        features["team_points_l8"],
    )

    features["team_passing_yards_trend_l3_l8"] = trend(
        features["team_passing_yards_l3"],
        features["team_passing_yards_l8"],
    )

    features["team_total_yards_trend_l3_l8"] = trend(
        features["team_total_yards_l3"],
        features["team_total_yards_l8"],
    )

    # ========================================================
    # 9. OPPONENT DEFENSE — LAST 3
    # ========================================================

    recent_opponent_games = opponent_games[-3:]

    features["opponent_qb_fantasy_allowed_l3"] = average(
        [game[0] for game in recent_opponent_games]
    )

    features["opponent_passing_yards_allowed_l3"] = average(
        [game[1] for game in recent_opponent_games]
    )

    features["opponent_points_allowed_l3"] = average(
        [game[2] for game in recent_opponent_games]
    )

    features["opponent_total_yards_allowed_l3"] = average(
        [game[3] for game in recent_opponent_games]
    )

    features["opponent_rushing_yards_allowed_l3"] = average(
        [game[4] for game in recent_opponent_games]
    )

    features["opponent_sacks_l3"] = average(
        [game[5] for game in recent_opponent_games]
    )

    features["opponent_interceptions_l3"] = average(
        [game[6] for game in recent_opponent_games]
    )

    # ========================================================
    # 10. GAME ENVIRONMENT
    # ========================================================

    if (
        features["team_points_l3"] is not None
        and features["opponent_points_allowed_l3"] is not None
    ):
        features["game_environment_l3"] = (
            features["team_points_l3"]
            + features["opponent_points_allowed_l3"]
        ) / 2
    else:
        features["game_environment_l3"] = None

    # ========================================================
    # 11. RETURN FEATURES
    # ========================================================

    return features