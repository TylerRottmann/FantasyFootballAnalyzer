"""Leakage-aware historical scoring features for Boom/Bust v2."""

from statistics import mean, stdev


def historical_scoring_features(previous_points):
    """
    Build scoring features from games completed before the target week.

    previous_points must contain no target-week or future results.
    """
    points = [float(p) for p in previous_points if p is not None]
    recent_3 = points[-3:]
    recent_8 = points[-8:]

    baseline = mean(recent_8) if recent_8 else None

    return {
        "baseline": round(baseline, 3) if baseline is not None else None,
        "games_played": len(points),
        "history_l3_count": len(recent_3),
        "history_l8_count": len(recent_8),
        "fantasy_points_mean_l3": round(mean(recent_3), 3) if recent_3 else None,
        "fantasy_points_mean_l8": round(mean(recent_8), 3) if recent_8 else None,
        "fantasy_points_stddev_l8": (
            round(stdev(recent_8), 3) if len(recent_8) >= 2 else None
        ),
        "fantasy_points_min_l8": min(recent_8) if recent_8 else None,
        "fantasy_points_max_l8": max(recent_8) if recent_8 else None,
        "limited_history": int(len(points) < 3),
        "no_history": int(len(points) == 0),
    }


def build_boom_bust_features_v2(player, season, week, previous_points, data=None, historical=False):
    """Combine existing position features with a pregame scoring profile."""
    from scripts.algorithm.boom_bust.boom_bust_features import FEATURE_BUILDERS

    if player.position not in FEATURE_BUILDERS:
        raise ValueError(f"Unsupported position: {player.position}")

    if not 1 <= week <= 18:
        raise ValueError("Week must be between 1 and 18.")

    builder = FEATURE_BUILDERS[player.position]

    if historical and player.position in ("QB", "WR", "TE"):
        position_features = build_with_verified_historical_context(
            player, season, week
        )
        if position_features is None:
            return None
    elif player.position == "RB":
        position_features = builder(player, season, week, data=data)
    else:
        position_features = builder(player, season, week)

    features = dict(position_features)
    scoring = historical_scoring_features(previous_points)

    # Keep the original builder's game and matchup context.
    # The new scoring profile replaces its overlapping scoring fields.
    features.update(scoring)

    features["position_qb"] = int(player.position == "QB")
    features["position_rb"] = int(player.position == "RB")
    features["position_wr"] = int(player.position == "WR")
    features["position_te"] = int(player.position == "TE")

    return features



def verified_historical_matchup(player_id, season, week):
    """Resolve a player's historical team and opponent from its game ID."""
    from scripts.algorithm.features.qb_features import get_connection

    query = """
        SELECT pws.game_id, pws.opponent_team
        FROM player_weekly_stats pws
        WHERE pws.player_id = %s
          AND pws.season = %s
          AND pws.week = %s
          AND pws.season_type = 'REG'
    """

    unknown = {
        "game_status": "UNKNOWN",
        "team_id": None,
        "opponent_team_id": None,
        "opponent_team": None,
        "is_home": None,
    }

    with get_connection().cursor() as cursor:
        cursor.execute(query, (player_id, season, week))
        records = cursor.fetchall()

        if len(records) != 1:
            return unknown

        game_id, opponent = records[0]
        if not game_id or not opponent:
            return unknown

        parts = game_id.split("_")
        if len(parts) != 4:
            return unknown

        game_season, game_week, away, home = parts

        if str(season) != game_season or str(week).zfill(2) != game_week:
            return unknown

        if opponent == away:
            historical_team = home
            is_home = True
        elif opponent == home:
            historical_team = away
            is_home = False
        else:
            return unknown

        # nflverse uses LA; our teams table uses LAR.
        historical_team = "LAR" if historical_team == "LA" else historical_team
        opponent = "LAR" if opponent == "LA" else opponent

        cursor.execute("""
            SELECT tws.team_id, tws.opponent_team_id, tws.is_home
            FROM team_weekly_stats tws
            JOIN teams team ON team.id = tws.team_id
            JOIN teams opp ON opp.id = tws.opponent_team_id
            WHERE tws.season = %s
              AND tws.week = %s
              AND tws.season_type = 1
              AND team.abbreviation = %s
              AND opp.abbreviation = %s
        """, (season, week, historical_team, opponent))

        matchups = cursor.fetchall()

    if len(matchups) != 1 or matchups[0][2] != is_home:
        return unknown

    team_id, opponent_team_id, _ = matchups[0]

    return {
        "game_status": "GAME",
        "team_id": team_id,
        "opponent_team_id": opponent_team_id,
        "opponent_team": opponent,
        "is_home": is_home,
    }


def build_with_verified_historical_context(player, season, week):
    """Build historical features using a verified game matchup.

    This helper is intended only for historical rows with a recorded game.
    It must not be used to infer participation in future games.
    """
    from unittest.mock import patch
    from scripts.algorithm.boom_bust.boom_bust_features import FEATURE_BUILDERS

    context = verified_historical_matchup(player.id, season, week)

    if context["game_status"] != "GAME":
        return None

    module_names = {
        "QB": "scripts.algorithm.features.qb_features",
        "WR": "scripts.algorithm.features.wr_features",
        "TE": "scripts.algorithm.features.te_features",
    }

    if player.position not in module_names:
        raise ValueError("This helper supports QB, WR, and TE only.")

    module_name = module_names[player.position]
    builder = FEATURE_BUILDERS[player.position]

    with patch(
        f"{module_name}.get_player_game_context",
        return_value=context,
    ):
        return builder(player, season, week)
