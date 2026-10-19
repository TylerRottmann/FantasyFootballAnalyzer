# scripts/algorithm/features/dst_features.py
#
# Pre-game feature builder for team defense / special teams (D/ST).
#
# Unlike QB/RB/WR/TE, a D/ST is a team, not a row in `players`, so the
# entry point takes a team_id. Every query only reads weeks BEFORE the
# prediction week, so training rows and live predictions use identical
# information.
#
# The feature math lives in compute_dst_features(), which takes plain
# lists and does no database access, so it can be unit tested.

from scripts.algorithm.features.qb_features import (
    average,
    get_connection,
    standard_deviation,
    trend,
)

WINDOWS = {"l1": 1, "l3": 3, "l5": 5, "l8": 8, "season": None}


# ============================================================
# QUERIES
# ============================================================

def get_dst_history(team_id, season, week):
    """
    The team's own defensive production before `week`.

    Column order:
        0 week
        1 dst_fantasy_points
        2 sacks
        3 interceptions
        4 fumble_recoveries
        5 touchdowns (defensive + special teams)
        6 points_against
        7 total_yards_against
    """
    query = """
        SELECT
            week,
            dst_fantasy_points,
            sacks,
            interceptions,
            fumble_recoveries,
            COALESCE(defensive_tds, 0) + COALESCE(special_teams_tds, 0),
            points_against,
            total_yards_against
        FROM team_weekly_stats
        WHERE team_id = %s
          AND season = %s
          AND season_type = 1
          AND week < %s
        ORDER BY week
    """
    with get_connection().cursor() as cur:
        cur.execute(query, (team_id, season, week))
        return cur.fetchall()


def get_offense_history(team_id, season, week):
    """
    A team's OFFENSIVE history before `week`, including how often that
    offense gave the ball away and got sacked. Giveaways and sacks taken
    are the other side of the defense's own sack/INT/fumble columns, so
    they are found by joining to the opposing team's row for that game.

    Column order:
        0 week
        1 points_for
        2 total_yards
        3 passing_yards
        4 sacks_taken
        5 giveaways (interceptions thrown + fumbles lost)
    """
    query = """
        SELECT
            a.week,
            a.points_for,
            a.total_yards,
            a.passing_yards,
            d.sacks,
            COALESCE(d.interceptions, 0) + COALESCE(d.fumble_recoveries, 0)
        FROM team_weekly_stats a
        LEFT JOIN team_weekly_stats d
            ON d.team_id = a.opponent_team_id
           AND d.season = a.season
           AND d.week = a.week
           AND d.season_type = a.season_type
        WHERE a.team_id = %s
          AND a.season = %s
          AND a.season_type = 1
          AND a.week < %s
        ORDER BY a.week
    """
    with get_connection().cursor() as cur:
        cur.execute(query, (team_id, season, week))
        return cur.fetchall()


def get_dst_game_context(team_id, season, week):
    """
    Opponent and home/away for the team in this week.

    Historical weeks come from team_weekly_stats (the real game), future
    weeks from the nfl_games schedule. No game either way = BYE.
    """
    conn = get_connection()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT opponent_team_id, is_home
            FROM team_weekly_stats
            WHERE team_id = %s AND season = %s
              AND week = %s AND season_type = 1
            """,
            (team_id, season, week),
        )
        row = cur.fetchone()

    if row is not None and row[0] is not None:
        return {
            "game_status": "GAME",
            "opponent_team_id": row[0],
            "is_home": row[1],
        }

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                CASE WHEN home_team_id = %s THEN away_team_id
                     ELSE home_team_id END,
                (home_team_id = %s)
            FROM nfl_games
            WHERE season = %s AND week = %s AND game_type = 'REG'
              AND (home_team_id = %s OR away_team_id = %s)
            LIMIT 1
            """,
            (team_id, team_id, season, week, team_id, team_id),
        )
        row = cur.fetchone()

    if row is None:
        return {"game_status": "BYE", "opponent_team_id": None, "is_home": None}

    return {"game_status": "GAME", "opponent_team_id": row[0], "is_home": row[1]}


# ============================================================
# PURE FEATURE MATH
# ============================================================

def _windows(rows):
    return {
        name: (rows if size is None else rows[-size:])
        for name, size in WINDOWS.items()
    }


def _col(rows, index):
    return [r[index] for r in rows]


def compute_dst_features(dst_rows, opp_offense_rows, own_offense_rows, context):
    """
    Turn raw history rows into the feature dict (no database access).
    """
    features = {
        "game_status": context["game_status"],
        "opponent_team_id": context["opponent_team_id"],
        "is_home": (
            None if context["is_home"] is None else int(bool(context["is_home"]))
        ),
        "games_played": len(dst_rows),
        "games_played_l8": len(dst_rows[-8:]),
    }

    # ---------------- team defense / ST production ----------------
    dst_stats = {
        "dst_fantasy_points": 1,
        "sacks": 2,
        "interceptions": 3,
        "fumble_recoveries": 4,
        "dst_tds": 5,
        "points_against": 6,
        "total_yards_against": 7,
    }

    # l1 is only kept for the two headline numbers; it is too noisy
    # for the others.
    l1_stats = {"dst_fantasy_points", "points_against"}

    for name, rows in _windows(dst_rows).items():
        for stat, index in dst_stats.items():
            if name == "l1" and stat not in l1_stats:
                continue
            features[f"{stat}_{name}"] = average(_col(rows, index))

        if name != "l1":
            features[f"turnovers_{name}"] = _sum_avg(
                rows, (3, 4)
            )

    for name in ("l3", "l5", "l8", "season"):
        rows = _windows(dst_rows)[name]
        features[f"dst_fantasy_points_stddev_{name}"] = standard_deviation(
            _col(rows, 1)
        )

    # ---------------- trends ----------------
    for stat in ("dst_fantasy_points", "sacks", "turnovers", "points_against"):
        features[f"{stat}_trend_l3_l8"] = trend(
            features.get(f"{stat}_l3"),
            features.get(f"{stat}_l8"),
        )

    # ---------------- opposing offense ----------------
    opp_stats = {
        "points_for": 1,
        "total_yards": 2,
        "passing_yards": 3,
        "sacks_taken": 4,
        "giveaways": 5,
    }
    for name, rows in _windows(opp_offense_rows).items():
        if name == "l1":
            continue
        for stat, index in opp_stats.items():
            features[f"opponent_{stat}_{name}"] = average(_col(rows, index))

    # ---------------- own offense (game script / field position) -------
    for name, rows in _windows(own_offense_rows).items():
        if name in ("l1", "l8"):
            continue
        features[f"team_points_for_{name}"] = average(_col(rows, 1))
        features[f"team_giveaways_{name}"] = average(_col(rows, 5))

    return features


def _sum_avg(rows, indexes):
    """Average of (sum of several columns) per game, None if no data."""
    totals = []
    for r in rows:
        vals = [r[i] for i in indexes]
        if any(v is None for v in vals):
            continue
        totals.append(sum(float(v) for v in vals))
    return average(totals)


# ============================================================
# MAIN FEATURE BUILDER
# ============================================================

def build_dst_features(team_id, season, week):
    context = get_dst_game_context(team_id, season, week)

    dst_rows = get_dst_history(team_id, season, week)
    own_offense = get_offense_history(team_id, season, week)

    opp_offense = []
    if context["opponent_team_id"] is not None:
        opp_offense = get_offense_history(
            context["opponent_team_id"], season, week
        )

    features = compute_dst_features(dst_rows, opp_offense, own_offense, context)
    features.update({"team_id": team_id, "season": season, "week": week})
    return features
