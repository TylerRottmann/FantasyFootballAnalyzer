# scripts/algorithm/features/wr_features.py
#
# Pre-game feature builder for wide receivers.
#
# This mirrors qb_features.py. The generic helpers and the queries
# that are not position-specific (game context, team history) are
# reused from the QB module. Only the WR history query and the
# opponent-defense query (which needs wr_fantasy_points_allowed
# instead of the QB column) are new.

from scripts.algorithm.features.qb_features import (
    average,
    get_connection,
    get_player_game_context,
    get_team_games,
    safe_rate,
    standard_deviation,
    trend,
    yards_per_attempt,
)


# ============================================================
# WR HISTORY
# ============================================================

def get_wr_history(player_id, season, week):
    """
    Get all WR statistics from games BEFORE the prediction week.

    IMPORTANT:
    No statistics from the prediction week are included.

    Column order (used by index below):

        0 week
        1 targets
        2 receptions
        3 receiving_yards
        4 receiving_tds
        5 fantasy_points_ppr
        6 team_targets

    team_targets is the total targets thrown to the receiver's whole
    team in that game, used to compute target share. It is built by
    summing targets for every player whose opponent_team matches this
    player's opponent_team in the same week. Every player on one team
    has the same opponent in a given week, and a team plays only one
    game per week, so that grouping identifies a single team's game.

    NOTE: the total only includes players present in
    player_weekly_stats (QB/RB/WR/TE that mapped to a Sleeper ID), so
    it can slightly undercount real team targets. Shares are therefore
    a touch high, but consistent from player to player.
    """

    query = """
        WITH team_totals AS (
            SELECT
                week,
                opponent_team,
                SUM(targets) AS team_targets
            FROM player_weekly_stats
            WHERE season = %s
              AND season_type = 'REG'
              AND week < %s
            GROUP BY week, opponent_team
        )
        SELECT
            p.week,
            p.targets,
            p.receptions,
            p.receiving_yards,
            p.receiving_tds,
            p.fantasy_points_ppr,
            t.team_targets
        FROM player_weekly_stats p
        LEFT JOIN team_totals t
            ON t.week = p.week
           AND t.opponent_team = p.opponent_team
        WHERE p.player_id = %s
          AND p.season = %s
          AND p.season_type = 'REG'
          AND p.week < %s
        ORDER BY p.week
    """

    conn = get_connection()

    with conn.cursor() as cur:
        cur.execute(
            query,
            (
                season,
                week,
                player_id,
                season,
                week,
            ),
        )

        return cur.fetchall()


# ============================================================
# OPPONENT HISTORY (WR-SPECIFIC)
# ============================================================

def get_opponent_defense_wr(opponent_team_id, season, week):
    """
    Get opponent defensive performance from games BEFORE
    the prediction week.

    Same as the QB version, except the first column is
    wr_fantasy_points_allowed.

    Column order:

        0 wr_fantasy_points_allowed
        1 passing_yards_against
        2 points_against
        3 total_yards_against
        4 sacks
        5 interceptions
    """

    query = """
        SELECT
            wr_fantasy_points_allowed,
            passing_yards_against,
            points_against,
            total_yards_against,
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

def build_wr_features(player, season, week):
    """
    Build the complete pre-game feature set for a WR.

    All performance statistics come from games BEFORE the
    prediction week.

    Feature groups:

        1. WR production
        2. Receiving efficiency
        3. WR consistency / volatility
        4. WR trends (including target share)
        5. Team offensive environment
        6. Opponent defensive matchup
        7. Game context
    """

    # ========================================================
    # 1. WR HISTORY
    # ========================================================

    wr_games = get_wr_history(
        player.id,
        season,
        week,
    )

    wr_windows = {
        "l1": wr_games[-1:],
        "l3": wr_games[-3:],
        "l5": wr_games[-5:],
        "l8": wr_games[-8:],
        "season": wr_games,
    }

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
    game_status = "BYE"

    if game_context is not None:

        game_status = game_context["game_status"]
        team_id = game_context["team_id"]
        opponent_team_id = game_context["opponent_team_id"]
        is_home = game_context["is_home"]
        opponent_team = game_context["opponent_team"]

        if team_id is not None:
            team_games = get_team_games(
                team_id,
                season,
                week,
            )

        if opponent_team_id is not None:
            opponent_games = get_opponent_defense_wr(
                opponent_team_id,
                season,
                week,
            )

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

        "game_status": game_status,
        "team_id": team_id,
        "opponent_team": opponent_team,
        "opponent_team_id": opponent_team_id,
        "is_home": is_home,

        # ----------------------------------------------------
        # WR EXPERIENCE / SAMPLE SIZE
        # ----------------------------------------------------

        "games_played": len(wr_games),
        "games_played_l8": len(wr_windows["l8"]),
    }

    # ========================================================
    # 3. WR PRODUCTION / EFFICIENCY / CONSISTENCY
    # ========================================================

    for name, games in wr_windows.items():

        targets = [game[1] for game in games]
        receptions = [game[2] for game in games]
        rec_yards = [game[3] for game in games]
        rec_tds = [game[4] for game in games]
        fantasy = [game[5] for game in games]

        # ----------------------------------------------------
        # PRODUCTION
        # ----------------------------------------------------

        features[f"fantasy_points_{name}"] = average(fantasy)
        features[f"targets_{name}"] = average(targets)
        features[f"receptions_{name}"] = average(receptions)
        features[f"receiving_yards_{name}"] = average(rec_yards)
        features[f"receiving_tds_{name}"] = average(rec_tds)

        # ----------------------------------------------------
        # RECEIVING EFFICIENCY
        # ----------------------------------------------------

        features[f"catch_rate_{name}"] = safe_rate(
            receptions,
            targets,
        )

        features[f"receiving_yards_per_target_{name}"] = (
            yards_per_attempt(rec_yards, targets)
        )

        features[f"receiving_yards_per_reception_{name}"] = (
            yards_per_attempt(rec_yards, receptions)
        )

        features[f"receiving_td_rate_{name}"] = safe_rate(
            rec_tds,
            targets,
        )

        # ----------------------------------------------------
        # TARGET SHARE
        # ----------------------------------------------------
        # Only games with a known, non-zero team total are used, and
        # each game's targets stay paired with that game's team total.

        paired = [
            (game[1], game[6])
            for game in games
            if game[1] is not None and game[6]
        ]

        paired_targets = [pair[0] for pair in paired]
        paired_team_targets = [pair[1] for pair in paired]

        features[f"target_share_{name}"] = safe_rate(
            paired_targets,
            paired_team_targets,
        )

        features[f"target_share_stddev_{name}"] = standard_deviation(
            [
                float(player_targets) / float(team_targets)
                for player_targets, team_targets in paired
            ]
        )

        # ----------------------------------------------------
        # CONSISTENCY / VOLATILITY
        # ----------------------------------------------------

        features[f"fantasy_points_stddev_{name}"] = (
            standard_deviation(fantasy)
        )

        features[f"targets_stddev_{name}"] = (
            standard_deviation(targets)
        )

        features[f"receptions_stddev_{name}"] = (
            standard_deviation(receptions)
        )

        features[f"receiving_yards_stddev_{name}"] = (
            standard_deviation(rec_yards)
        )

    # ========================================================
    # 4. WR TREND FEATURES
    # ========================================================

    # Recent performance (last 3) vs longer-term (last 8).

    features["fantasy_points_trend_l3_l8"] = trend(
        features["fantasy_points_l3"],
        features["fantasy_points_l8"],
    )

    features["targets_trend_l3_l8"] = trend(
        features["targets_l3"],
        features["targets_l8"],
    )

    features["receiving_yards_trend_l3_l8"] = trend(
        features["receiving_yards_l3"],
        features["receiving_yards_l8"],
    )

    features["receiving_yards_per_target_trend_l3_l8"] = trend(
        features["receiving_yards_per_target_l3"],
        features["receiving_yards_per_target_l8"],
    )

    features["catch_rate_trend_l3_l8"] = trend(
        features["catch_rate_l3"],
        features["catch_rate_l8"],
    )

    features["target_share_trend_l3_l8"] = trend(
        features["target_share_l3"],
        features["target_share_l8"],
    )

    # ========================================================
    # 5. TEAM OFFENSIVE ENVIRONMENT
    # ========================================================

    # team_games columns: week, is_home, points_for,
    # passing_yards, rushing_yards, total_yards

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
    # 6. OPPONENT DEFENSE — LAST 3
    # ========================================================

    recent_opponent_games = opponent_games[-3:]

    features["opponent_wr_fantasy_allowed_l3"] = average(
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

    features["opponent_sacks_l3"] = average(
        [game[4] for game in recent_opponent_games]
    )

    features["opponent_interceptions_l3"] = average(
        [game[5] for game in recent_opponent_games]
    )

    # ========================================================
    # 7. GAME ENVIRONMENT
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
    # 8. RETURN FEATURES
    # ========================================================

    return features
