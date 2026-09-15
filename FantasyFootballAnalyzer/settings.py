import argparse
import os
import sys
from collections import defaultdict

import psycopg
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()


def get_connection():
    """Create a PostgreSQL connection using the project's .env settings."""

    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dbname=os.getenv("DB_NAME"),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe_number(value):
    """Convert None to 0 and leave numeric values usable."""

    if value is None:
        return 0.0

    return float(value)


def average(values):
    """Return an average while safely handling empty lists."""

    if not values:
        return 0.0

    return sum(values) / len(values)


def weighted_average(values, weights):
    """Calculate a weighted average."""

    if not values or not weights:
        return 0.0

    total_weight = sum(weights)

    if total_weight == 0:
        return 0.0

    return sum(v * w for v, w in zip(values, weights)) / total_weight


# ---------------------------------------------------------------------------
# Database loading
# ---------------------------------------------------------------------------

def load_team_names(conn):
    """Load team IDs and abbreviations."""

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, abbreviation, name
            FROM teams
            ORDER BY abbreviation
            """
        )

        rows = cur.fetchall()

    teams = {}

    for team_id, abbreviation, name in rows:
        teams[team_id] = {
            "abbreviation": abbreviation,
            "name": name,
        }

    return teams


def load_team_weekly_stats(conn, season, through_week):
    """Load traditional team statistics through the requested week."""

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                team_id,
                season,
                week,
                opponent_team_id,
                is_home,

                points_for,
                points_against,

                total_yards,
                passing_yards,
                rushing_yards,

                total_yards_against,
                passing_yards_against,
                rushing_yards_against,

                turnovers_forced,
                interceptions,
                sacks,
                fumbles_forced,

                third_down_attempts,
                third_down_conversions,
                third_down_attempts_against,
                third_down_conversions_against,

                fourth_down_attempts,
                fourth_down_conversions,
                fourth_down_attempts_against,
                fourth_down_conversions_against,

                kicking_points_for,
                kicking_points_against,

                qb_fantasy_points_allowed,
                rb_fantasy_points_allowed,
                wr_fantasy_points_allowed,
                te_fantasy_points_allowed

            FROM team_weekly_stats

            WHERE season = %s
              AND season_type = 1
              AND week <= %s

            ORDER BY team_id, week
            """,
            (season, through_week),
        )

        return cur.fetchall()


def load_team_advanced_stats(conn, season, through_week):
    """Load advanced team statistics through the requested week."""

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                team_id,
                season,
                week,

                offensive_plays,
                pass_attempts,
                rush_attempts,

                offensive_epa,
                offensive_epa_per_play,

                pass_epa,
                pass_epa_per_play,

                rush_epa,
                rush_epa_per_play,

                offensive_success_rate,
                pass_success_rate,
                rush_success_rate,

                explosive_pass_plays,
                explosive_rush_plays,
                explosive_plays,

                defensive_epa,
                defensive_epa_per_play,
                defensive_success_rate,

                explosive_pass_plays_allowed,
                explosive_rush_plays_allowed,
                explosive_plays_allowed,

                sacks,
                qb_hits,
                sack_rate,

                interceptions,
                forced_fumbles

            FROM team_advanced_weekly

            WHERE season = %s
              AND season_type = 1
              AND week <= %s

            ORDER BY team_id, week
            """,
            (season, through_week),
        )

        return cur.fetchall()


# ---------------------------------------------------------------------------
# Feature construction
# ---------------------------------------------------------------------------

def build_team_features(team_rows, advanced_rows, teams):
    """
    Build one prediction feature record per team.

    Both season-to-date and recent-4-game features are produced.
    """

    traditional_by_team = defaultdict(list)
    advanced_by_team = defaultdict(list)

    for row in team_rows:
        traditional_by_team[row[0]].append(row)

    for row in advanced_rows:
        advanced_by_team[row[0]].append(row)

    features = []

    all_team_ids = sorted(
        set(traditional_by_team.keys()) |
        set(advanced_by_team.keys())
    )

    for team_id in all_team_ids:

        traditional = traditional_by_team.get(team_id, [])
        advanced = advanced_by_team.get(team_id, [])

        if not traditional:
            continue

        team_info = teams.get(team_id)

        if not team_info:
            continue

        # ---------------------------------------------------------------
        # Recent games
        # ---------------------------------------------------------------

        traditional = sorted(traditional, key=lambda row: row[2])
        advanced = sorted(advanced, key=lambda row: row[2])

        recent_traditional = traditional[-4:]
        recent_advanced = advanced[-4:]

        # ---------------------------------------------------------------
        # Traditional season totals
        # ---------------------------------------------------------------

        games = len(traditional)

        points_for = [
            safe_number(row[5])
            for row in traditional
        ]

        points_against = [
            safe_number(row[6])
            for row in traditional
        ]

        total_yards = [
            safe_number(row[7])
            for row in traditional
        ]

        passing_yards = [
            safe_number(row[8])
            for row in traditional
        ]

        rushing_yards = [
            safe_number(row[9])
            for row in traditional
        ]

        total_yards_against = [
            safe_number(row[10])
            for row in traditional
        ]

        passing_yards_against = [
            safe_number(row[11])
            for row in traditional
        ]

        rushing_yards_against = [
            safe_number(row[12])
            for row in traditional
        ]

        turnovers_forced = [
            safe_number(row[13])
            for row in traditional
        ]

        interceptions = [
            safe_number(row[14])
            for row in traditional
        ]

        sacks = [
            safe_number(row[15])
            for row in traditional
        ]

        fumbles_forced = [
            safe_number(row[16])
            for row in traditional
        ]

        third_down_attempts = [
            safe_number(row[17])
            for row in traditional
        ]

        third_down_conversions = [
            safe_number(row[18])
            for row in traditional
        ]

        third_down_attempts_against = [
            safe_number(row[19])
            for row in traditional
        ]

        third_down_conversions_against = [
            safe_number(row[20])
            for row in traditional
        ]

        fourth_down_attempts = [
            safe_number(row[21])
            for row in traditional
        ]

        fourth_down_conversions = [
            safe_number(row[22])
            for row in traditional
        ]

        fourth_down_attempts_against = [
            safe_number(row[23])
            for row in traditional
        ]

        fourth_down_conversions_against = [
            safe_number(row[24])
            for row in traditional
        ]

        kicking_points_for = [
            safe_number(row[25])
            for row in traditional
        ]

        kicking_points_against = [
            safe_number(row[26])
            for row in traditional
        ]

        qb_fantasy_allowed = [
            safe_number(row[27])
            for row in traditional
        ]

        rb_fantasy_allowed = [
            safe_number(row[28])
            for row in traditional
        ]

        wr_fantasy_allowed = [
            safe_number(row[29])
            for row in traditional
        ]

        te_fantasy_allowed = [
            safe_number(row[30])
            for row in traditional
        ]

        # ---------------------------------------------------------------
        # Advanced season data
        # ---------------------------------------------------------------

        offensive_plays = [
            safe_number(row[3])
            for row in advanced
        ]

        pass_attempts = [
            safe_number(row[4])
            for row in advanced
        ]

        rush_attempts = [
            safe_number(row[5])
            for row in advanced
        ]

        offensive_epa = [
            safe_number(row[6])
            for row in advanced
        ]

        pass_epa = [
            safe_number(row[8])
            for row in advanced
        ]

        rush_epa = [
            safe_number(row[10])
            for row in advanced
        ]

        offensive_success_rate = [
            safe_number(row[12])
            for row in advanced
        ]

        pass_success_rate = [
            safe_number(row[13])
            for row in advanced
        ]

        rush_success_rate = [
            safe_number(row[14])
            for row in advanced
        ]

        explosive_pass_plays = [
            safe_number(row[15])
            for row in advanced
        ]

        explosive_rush_plays = [
            safe_number(row[16])
            for row in advanced
        ]

        explosive_plays = [
            safe_number(row[17])
            for row in advanced
        ]

        defensive_epa = [
            safe_number(row[18])
            for row in advanced
        ]

        defensive_epa_per_play = [
            safe_number(row[19])
            for row in advanced
        ]

        defensive_success_rate = [
            safe_number(row[20])
            for row in advanced
        ]

        explosive_pass_allowed = [
            safe_number(row[21])
            for row in advanced
        ]

        explosive_rush_allowed = [
            safe_number(row[22])
            for row in advanced
        ]

        explosive_allowed = [
            safe_number(row[23])
            for row in advanced
        ]

        advanced_sacks = [
            safe_number(row[24])
            for row in advanced
        ]

        qb_hits = [
            safe_number(row[25])
            for row in advanced
        ]

        sack_rate = [
            safe_number(row[26])
            for row in advanced
        ]

        advanced_interceptions = [
            safe_number(row[27])
            for row in advanced
        ]

        forced_fumbles = [
            safe_number(row[28])
            for row in advanced
        ]

        # ---------------------------------------------------------------
        # Rates
        # ---------------------------------------------------------------

        third_down_rate = (
            sum(third_down_conversions) /
            sum(third_down_attempts)
            if sum(third_down_attempts) > 0
            else 0.0
        )

        third_down_defense_rate = (
            sum(third_down_conversions_against) /
            sum(third_down_attempts_against)
            if sum(third_down_attempts_against) > 0
            else 0.0
        )

        fourth_down_rate = (
            sum(fourth_down_conversions) /
            sum(fourth_down_attempts)
            if sum(fourth_down_attempts) > 0
            else 0.0
        )

        fourth_down_defense_rate = (
            sum(fourth_down_conversions_against) /
            sum(fourth_down_attempts_against)
            if sum(fourth_down_attempts_against) > 0
            else 0.0
        )

        # ---------------------------------------------------------------
        # Weighted offensive advanced rates
        # ---------------------------------------------------------------

        weighted_off_success = weighted_average(
            offensive_success_rate,
            offensive_plays,
        )

        weighted_pass_success = weighted_average(
            pass_success_rate,
            pass_attempts,
        )

        weighted_rush_success = weighted_average(
            rush_success_rate,
            rush_attempts,
        )

        total_offensive_plays = sum(offensive_plays)

        offensive_epa_per_play = (
            sum(offensive_epa) / total_offensive_plays
            if total_offensive_plays > 0
            else 0.0
        )

        total_pass_attempts = sum(pass_attempts)

        pass_epa_per_play = (
            sum(pass_epa) / total_pass_attempts
            if total_pass_attempts > 0
            else 0.0
        )

        total_rush_attempts = sum(rush_attempts)

        rush_epa_per_play = (
            sum(rush_epa) / total_rush_attempts
            if total_rush_attempts > 0
            else 0.0
        )

        # ---------------------------------------------------------------
        # Recent-4 features
        # ---------------------------------------------------------------

        recent_games = len(recent_traditional)

        recent_points_for = average(
            [safe_number(row[5]) for row in recent_traditional]
        )

        recent_points_against = average(
            [safe_number(row[6]) for row in recent_traditional]
        )

        recent_total_yards = average(
            [safe_number(row[7]) for row in recent_traditional]
        )

        recent_passing_yards = average(
            [safe_number(row[8]) for row in recent_traditional]
        )

        recent_rushing_yards = average(
            [safe_number(row[9]) for row in recent_traditional]
        )

        recent_total_yards_against = average(
            [safe_number(row[10]) for row in recent_traditional]
        )

        recent_passing_yards_against = average(
            [safe_number(row[11]) for row in recent_traditional]
        )

        recent_rushing_yards_against = average(
            [safe_number(row[12]) for row in recent_traditional]
        )

        recent_turnovers_forced = average(
            [safe_number(row[13]) for row in recent_traditional]
        )

        recent_qb_fantasy_allowed = average(
            [safe_number(row[27]) for row in recent_traditional]
        )

        recent_rb_fantasy_allowed = average(
            [safe_number(row[28]) for row in recent_traditional]
        )

        recent_wr_fantasy_allowed = average(
            [safe_number(row[29]) for row in recent_traditional]
        )

        recent_te_fantasy_allowed = average(
            [safe_number(row[30]) for row in recent_traditional]
        )

        recent_offensive_epa = average(
            [safe_number(row[6]) for row in recent_advanced]
        )

        recent_offensive_epa_per_play = average(
            [safe_number(row[7]) for row in recent_advanced]
        )

        recent_pass_epa_per_play = average(
            [safe_number(row[9]) for row in recent_advanced]
        )

        recent_rush_epa_per_play = average(
            [safe_number(row[11]) for row in recent_advanced]
        )

        recent_offensive_success = average(
            [safe_number(row[12]) for row in recent_advanced]
        )

        recent_pass_success = average(
            [safe_number(row[13]) for row in recent_advanced]
        )

        recent_rush_success = average(
            [safe_number(row[14]) for row in recent_advanced]
        )

        recent_explosive_plays = average(
            [safe_number(row[17]) for row in recent_advanced]
        )

        recent_defensive_epa = average(
            [safe_number(row[18]) for row in recent_advanced]
        )

        recent_defensive_epa_per_play = average(
            [safe_number(row[19]) for row in recent_advanced]
        )

        recent_defensive_success = average(
            [safe_number(row[20]) for row in recent_advanced]
        )

        recent_explosive_allowed = average(
            [safe_number(row[23]) for row in recent_advanced]
        )

        recent_sack_rate = average(
            [safe_number(row[26]) for row in recent_advanced]
        )

        recent_qb_hits = average(
            [safe_number(row[25]) for row in recent_advanced]
        )

        # ---------------------------------------------------------------
        # Final feature object
        # ---------------------------------------------------------------

        feature = {
            "team_id": team_id,
            "team": team_info["abbreviation"],
            "team_name": team_info["name"],
            "games": games,
            "recent_games": recent_games,

            # Traditional offense
            "points_for_per_game": average(points_for),
            "total_yards_per_game": average(total_yards),
            "passing_yards_per_game": average(passing_yards),
            "rushing_yards_per_game": average(rushing_yards),

            # Traditional defense
            "points_against_per_game": average(points_against),
            "total_yards_against_per_game": average(total_yards_against),
            "passing_yards_against_per_game": average(passing_yards_against),
            "rushing_yards_against_per_game": average(rushing_yards_against),

            # Turnovers
            "turnovers_forced_per_game": average(turnovers_forced),
            "interceptions_per_game": average(interceptions),
            "sacks_per_game": average(sacks),
            "fumbles_forced_per_game": average(fumbles_forced),

            # Situational
            "third_down_conversion_rate": third_down_rate,
            "third_down_defense_rate": third_down_defense_rate,
            "fourth_down_conversion_rate": fourth_down_rate,
            "fourth_down_defense_rate": fourth_down_defense_rate,

            # Special teams
            "kicking_points_for_per_game": average(kicking_points_for),
            "kicking_points_against_per_game": average(kicking_points_against),

            # Fantasy points allowed
            "qb_fantasy_allowed_per_game": average(qb_fantasy_allowed),
            "rb_fantasy_allowed_per_game": average(rb_fantasy_allowed),
            "wr_fantasy_allowed_per_game": average(wr_fantasy_allowed),
            "te_fantasy_allowed_per_game": average(te_fantasy_allowed),

            # Advanced offense
            "offensive_epa_per_play": offensive_epa_per_play,
            "pass_epa_per_play": pass_epa_per_play,
            "rush_epa_per_play": rush_epa_per_play,

            "offensive_success_rate": weighted_off_success,
            "pass_success_rate": weighted_pass_success,
            "rush_success_rate": weighted_rush_success,

            "explosive_pass_plays_per_game": average(explosive_pass_plays),
            "explosive_rush_plays_per_game": average(explosive_rush_plays),
            "explosive_plays_per_game": average(explosive_plays),

            # Advanced defense
            "defensive_epa_per_play": average(defensive_epa_per_play),
            "defensive_success_rate": average(defensive_success_rate),

            "explosive_pass_plays_allowed_per_game": average(
                explosive_pass_allowed
            ),

            "explosive_rush_plays_allowed_per_game": average(
                explosive_rush_allowed
            ),

            "explosive_plays_allowed_per_game": average(
                explosive_allowed
            ),

            "advanced_sack_rate": average(sack_rate),
            "qb_hits_per_game": average(qb_hits),

            # -----------------------------------------------------------
            # Recent form
            # -----------------------------------------------------------

            "recent_points_for_per_game": recent_points_for,
            "recent_points_against_per_game": recent_points_against,

            "recent_total_yards_per_game": recent_total_yards,
            "recent_passing_yards_per_game": recent_passing_yards,
            "recent_rushing_yards_per_game": recent_rushing_yards,

            "recent_total_yards_against_per_game":
                recent_total_yards_against,

            "recent_passing_yards_against_per_game":
                recent_passing_yards_against,

            "recent_rushing_yards_against_per_game":
                recent_rushing_yards_against,

            "recent_turnovers_forced_per_game":
                recent_turnovers_forced,

            "recent_qb_fantasy_allowed_per_game":
                recent_qb_fantasy_allowed,

            "recent_rb_fantasy_allowed_per_game":
                recent_rb_fantasy_allowed,

            "recent_wr_fantasy_allowed_per_game":
                recent_wr_fantasy_allowed,

            "recent_te_fantasy_allowed_per_game":
                recent_te_fantasy_allowed,

            "recent_offensive_epa":
                recent_offensive_epa,

            "recent_offensive_epa_per_play":
                recent_offensive_epa_per_play,

            "recent_pass_epa_per_play":
                recent_pass_epa_per_play,

            "recent_rush_epa_per_play":
                recent_rush_epa_per_play,

            "recent_offensive_success_rate":
                recent_offensive_success,

            "recent_pass_success_rate":
                recent_pass_success,

            "recent_rush_success_rate":
                recent_rush_success,

            "recent_explosive_plays_per_game":
                recent_explosive_plays,

            "recent_defensive_epa":
                recent_defensive_epa,

            "recent_defensive_epa_per_play":
                recent_defensive_epa_per_play,

            "recent_defensive_success_rate":
                recent_defensive_success,

            "recent_explosive_plays_allowed_per_game":
                recent_explosive_allowed,

            "recent_sack_rate":
                recent_sack_rate,

            "recent_qb_hits_per_game":
                recent_qb_hits,
        }

        features.append(feature)

    return features


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_feature_table(features, season, through_week):
    """Print a compact prediction-oriented summary."""

    print()
    print("=" * 110)
    print(
        f"TEAM FEATURES — {season} THROUGH WEEK {through_week}"
    )
    print("=" * 110)

    print(
        f"{'TEAM':<6}"
        f"{'GP':>4}"
        f"{'PF/G':>8}"
        f"{'PA/G':>8}"
        f"{'YDS/G':>9}"
        f"{'YDSA/G':>10}"
        f"{'OFF EPA':>10}"
        f"{'DEF EPA':>10}"
        f"{'OFF SR':>9}"
        f"{'DEF SR':>9}"
        f"{'REC EPA':>10}"
    )

    print("-" * 110)

    features = sorted(
        features,
        key=lambda x: x["offensive_epa_per_play"],
        reverse=True,
    )

    for feature in features:
        print(
            f"{feature['team']:<6}"
            f"{feature['games']:>4}"
            f"{feature['points_for_per_game']:>8.1f}"
            f"{feature['points_against_per_game']:>8.1f}"
            f"{feature['total_yards_per_game']:>9.1f}"
            f"{feature['total_yards_against_per_game']:>10.1f}"
            f"{feature['offensive_epa_per_play']:>10.3f}"
            f"{feature['defensive_epa_per_play']:>10.3f}"
            f"{feature['offensive_success_rate'] * 100:>8.1f}%"
            f"{feature['defensive_success_rate'] * 100:>8.1f}%"
            f"{feature['recent_offensive_epa_per_play']:>10.3f}"
        )

    print("=" * 110)
    print(f"Teams with available data: {len(features)}")
    print()

def save_team_features(conn, features, season, through_week):
    """
    Save calculated team features into team_feature_snapshots.

    Existing snapshots for the same team/season/data-through-week
    are updated instead of creating duplicates.
    """

    prediction_week = through_week + 1

    with conn.cursor() as cur:

        for feature in features:

            cur.execute(
                """
                INSERT INTO team_feature_snapshots (
                    team_id,
                    season,
                    data_through_week,
                    prediction_week,

                    games_played,
                    recent_games,

                    points_for_per_game,
                    total_yards_per_game,
                    passing_yards_per_game,
                    rushing_yards_per_game,

                    points_against_per_game,
                    total_yards_against_per_game,
                    passing_yards_against_per_game,
                    rushing_yards_against_per_game,

                    turnovers_forced_per_game,
                    interceptions_per_game,
                    sacks_per_game,
                    fumbles_forced_per_game,

                    third_down_conversion_rate,
                    third_down_defense_rate,
                    fourth_down_conversion_rate,
                    fourth_down_defense_rate,

                    kicking_points_for_per_game,
                    kicking_points_against_per_game,

                    qb_fantasy_allowed_per_game,
                    rb_fantasy_allowed_per_game,
                    wr_fantasy_allowed_per_game,
                    te_fantasy_allowed_per_game,

                    offensive_epa_per_play,
                    pass_epa_per_play,
                    rush_epa_per_play,

                    offensive_success_rate,
                    pass_success_rate,
                    rush_success_rate,

                    explosive_pass_plays_per_game,
                    explosive_rush_plays_per_game,
                    explosive_plays_per_game,

                    defensive_epa_per_play,
                    defensive_success_rate,

                    explosive_pass_plays_allowed_per_game,
                    explosive_rush_plays_allowed_per_game,
                    explosive_plays_allowed_per_game,

                    advanced_sack_rate,
                    qb_hits_per_game,

                    recent_points_for_per_game,
                    recent_points_against_per_game,

                    recent_total_yards_per_game,
                    recent_passing_yards_per_game,
                    recent_rushing_yards_per_game,

                    recent_total_yards_against_per_game,
                    recent_passing_yards_against_per_game,
                    recent_rushing_yards_against_per_game,

                    recent_turnovers_forced_per_game,

                    recent_qb_fantasy_allowed_per_game,
                    recent_rb_fantasy_allowed_per_game,
                    recent_wr_fantasy_allowed_per_game,
                    recent_te_fantasy_allowed_per_game,

                    recent_offensive_epa,
                    recent_offensive_epa_per_play,
                    recent_pass_epa_per_play,
                    recent_rush_epa_per_play,

                    recent_offensive_success_rate,
                    recent_pass_success_rate,
                    recent_rush_success_rate,

                    recent_explosive_plays_per_game,

                    recent_defensive_epa,
                    recent_defensive_epa_per_play,
                    recent_defensive_success_rate,

                    recent_explosive_plays_allowed_per_game,

                    recent_sack_rate,
                    recent_qb_hits_per_game,

                    updated_at
                )

                VALUES (
                    %(team_id)s,
                    %(season)s,
                    %(through_week)s,
                    %(prediction_week)s,

                    %(games)s,
                    %(recent_games)s,

                    %(points_for_per_game)s,
                    %(total_yards_per_game)s,
                    %(passing_yards_per_game)s,
                    %(rushing_yards_per_game)s,

                    %(points_against_per_game)s,
                    %(total_yards_against_per_game)s,
                    %(passing_yards_against_per_game)s,
                    %(rushing_yards_against_per_game)s,

                    %(turnovers_forced_per_game)s,
                    %(interceptions_per_game)s,
                    %(sacks_per_game)s,
                    %(fumbles_forced_per_game)s,

                    %(third_down_conversion_rate)s,
                    %(third_down_defense_rate)s,
                    %(fourth_down_conversion_rate)s,
                    %(fourth_down_defense_rate)s,

                    %(kicking_points_for_per_game)s,
                    %(kicking_points_against_per_game)s,

                    %(qb_fantasy_allowed_per_game)s,
                    %(rb_fantasy_allowed_per_game)s,
                    %(wr_fantasy_allowed_per_game)s,
                    %(te_fantasy_allowed_per_game)s,

                    %(offensive_epa_per_play)s,
                    %(pass_epa_per_play)s,
                    %(rush_epa_per_play)s,

                    %(offensive_success_rate)s,
                    %(pass_success_rate)s,
                    %(rush_success_rate)s,

                    %(explosive_pass_plays_per_game)s,
                    %(explosive_rush_plays_per_game)s,
                    %(explosive_plays_per_game)s,

                    %(defensive_epa_per_play)s,
                    %(defensive_success_rate)s,

                    %(explosive_pass_plays_allowed_per_game)s,
                    %(explosive_rush_plays_allowed_per_game)s,
                    %(explosive_plays_allowed_per_game)s,

                    %(advanced_sack_rate)s,
                    %(qb_hits_per_game)s,

                    %(recent_points_for_per_game)s,
                    %(recent_points_against_per_game)s,

                    %(recent_total_yards_per_game)s,
                    %(recent_passing_yards_per_game)s,
                    %(recent_rushing_yards_per_game)s,

                    %(recent_total_yards_against_per_game)s,
                    %(recent_passing_yards_against_per_game)s,
                    %(recent_rushing_yards_against_per_game)s,

                    %(recent_turnovers_forced_per_game)s,

                    %(recent_qb_fantasy_allowed_per_game)s,
                    %(recent_rb_fantasy_allowed_per_game)s,
                    %(recent_wr_fantasy_allowed_per_game)s,
                    %(recent_te_fantasy_allowed_per_game)s,

                    %(recent_offensive_epa)s,
                    %(recent_offensive_epa_per_play)s,
                    %(recent_pass_epa_per_play)s,
                    %(recent_rush_epa_per_play)s,

                    %(recent_offensive_success_rate)s,
                    %(recent_pass_success_rate)s,
                    %(recent_rush_success_rate)s,

                    %(recent_explosive_plays_per_game)s,

                    %(recent_defensive_epa)s,
                    %(recent_defensive_epa_per_play)s,
                    %(recent_defensive_success_rate)s,

                    %(recent_explosive_plays_allowed_per_game)s,

                    %(recent_sack_rate)s,
                    %(recent_qb_hits_per_game)s,

                    NOW()
                )

                ON CONFLICT (team_id, season, data_through_week)

                DO UPDATE SET
                    prediction_week = EXCLUDED.prediction_week,

                    games_played = EXCLUDED.games_played,
                    recent_games = EXCLUDED.recent_games,

                    points_for_per_game =
                        EXCLUDED.points_for_per_game,

                    total_yards_per_game =
                        EXCLUDED.total_yards_per_game,

                    passing_yards_per_game =
                        EXCLUDED.passing_yards_per_game,

                    rushing_yards_per_game =
                        EXCLUDED.rushing_yards_per_game,

                    points_against_per_game =
                        EXCLUDED.points_against_per_game,

                    total_yards_against_per_game =
                        EXCLUDED.total_yards_against_per_game,

                    passing_yards_against_per_game =
                        EXCLUDED.passing_yards_against_per_game,

                    rushing_yards_against_per_game =
                        EXCLUDED.rushing_yards_against_per_game,

                    turnovers_forced_per_game =
                        EXCLUDED.turnovers_forced_per_game,

                    interceptions_per_game =
                        EXCLUDED.interceptions_per_game,

                    sacks_per_game =
                        EXCLUDED.sacks_per_game,

                    fumbles_forced_per_game =
                        EXCLUDED.fumbles_forced_per_game,

                    third_down_conversion_rate =
                        EXCLUDED.third_down_conversion_rate,

                    third_down_defense_rate =
                        EXCLUDED.third_down_defense_rate,

                    fourth_down_conversion_rate =
                        EXCLUDED.fourth_down_conversion_rate,

                    fourth_down_defense_rate =
                        EXCLUDED.fourth_down_defense_rate,

                    kicking_points_for_per_game =
                        EXCLUDED.kicking_points_for_per_game,

                    kicking_points_against_per_game =
                        EXCLUDED.kicking_points_against_per_game,

                    qb_fantasy_allowed_per_game =
                        EXCLUDED.qb_fantasy_allowed_per_game,

                    rb_fantasy_allowed_per_game =
                        EXCLUDED.rb_fantasy_allowed_per_game,

                    wr_fantasy_allowed_per_game =
                        EXCLUDED.wr_fantasy_allowed_per_game,

                    te_fantasy_allowed_per_game =
                        EXCLUDED.te_fantasy_allowed_per_game,

                    offensive_epa_per_play =
                        EXCLUDED.offensive_epa_per_play,

                    pass_epa_per_play =
                        EXCLUDED.pass_epa_per_play,

                    rush_epa_per_play =
                        EXCLUDED.rush_epa_per_play,

                    offensive_success_rate =
                        EXCLUDED.offensive_success_rate,

                    pass_success_rate =
                        EXCLUDED.pass_success_rate,

                    rush_success_rate =
                        EXCLUDED.rush_success_rate,

                    explosive_pass_plays_per_game =
                        EXCLUDED.explosive_pass_plays_per_game,

                    explosive_rush_plays_per_game =
                        EXCLUDED.explosive_rush_plays_per_game,

                    explosive_plays_per_game =
                        EXCLUDED.explosive_plays_per_game,

                    defensive_epa_per_play =
                        EXCLUDED.defensive_epa_per_play,

                    defensive_success_rate =
                        EXCLUDED.defensive_success_rate,

                    explosive_pass_plays_allowed_per_game =
                        EXCLUDED.explosive_pass_plays_allowed_per_game,

                    explosive_rush_plays_allowed_per_game =
                        EXCLUDED.explosive_rush_plays_allowed_per_game,

                    explosive_plays_allowed_per_game =
                        EXCLUDED.explosive_plays_allowed_per_game,

                    advanced_sack_rate =
                        EXCLUDED.advanced_sack_rate,

                    qb_hits_per_game =
                        EXCLUDED.qb_hits_per_game,

                    recent_points_for_per_game =
                        EXCLUDED.recent_points_for_per_game,

                    recent_points_against_per_game =
                        EXCLUDED.recent_points_against_per_game,

                    recent_total_yards_per_game =
                        EXCLUDED.recent_total_yards_per_game,

                    recent_passing_yards_per_game =
                        EXCLUDED.recent_passing_yards_per_game,

                    recent_rushing_yards_per_game =
                        EXCLUDED.recent_rushing_yards_per_game,

                    recent_total_yards_against_per_game =
                        EXCLUDED.recent_total_yards_against_per_game,

                    recent_passing_yards_against_per_game =
                        EXCLUDED.recent_passing_yards_against_per_game,

                    recent_rushing_yards_against_per_game =
                        EXCLUDED.recent_rushing_yards_against_per_game,

                    recent_turnovers_forced_per_game =
                        EXCLUDED.recent_turnovers_forced_per_game,

                    recent_qb_fantasy_allowed_per_game =
                        EXCLUDED.recent_qb_fantasy_allowed_per_game,

                    recent_rb_fantasy_allowed_per_game =
                        EXCLUDED.recent_rb_fantasy_allowed_per_game,

                    recent_wr_fantasy_allowed_per_game =
                        EXCLUDED.recent_wr_fantasy_allowed_per_game,

                    recent_te_fantasy_allowed_per_game =
                        EXCLUDED.recent_te_fantasy_allowed_per_game,

                    recent_offensive_epa =
                        EXCLUDED.recent_offensive_epa,

                    recent_offensive_epa_per_play =
                        EXCLUDED.recent_offensive_epa_per_play,

                    recent_pass_epa_per_play =
                        EXCLUDED.recent_pass_epa_per_play,

                    recent_rush_epa_per_play =
                        EXCLUDED.recent_rush_epa_per_play,

                    recent_offensive_success_rate =
                        EXCLUDED.recent_offensive_success_rate,

                    recent_pass_success_rate =
                        EXCLUDED.recent_pass_success_rate,

                    recent_rush_success_rate =
                        EXCLUDED.recent_rush_success_rate,

                    recent_explosive_plays_per_game =
                        EXCLUDED.recent_explosive_plays_per_game,

                    recent_defensive_epa =
                        EXCLUDED.recent_defensive_epa,

                    recent_defensive_epa_per_play =
                        EXCLUDED.recent_defensive_epa_per_play,

                    recent_defensive_success_rate =
                        EXCLUDED.recent_defensive_success_rate,

                    recent_explosive_plays_allowed_per_game =
                        EXCLUDED.recent_explosive_plays_allowed_per_game,

                    recent_sack_rate =
                        EXCLUDED.recent_sack_rate,

                    recent_qb_hits_per_game =
                        EXCLUDED.recent_qb_hits_per_game,

                    updated_at = NOW()
                """,
                {
                    **feature,
                    "season": season,
                    "through_week": through_week,
                    "prediction_week": prediction_week,
                },
            )

    conn.commit()

    print(
        f"Saved {len(features)} team feature snapshots "
        f"for Week {prediction_week} predictions."
    )



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description="Build prediction-ready NFL team features."
    )

    parser.add_argument(
        "--season",
        type=int,
        default=2026,
        help="NFL season to process.",
    )

    parser.add_argument(
        "--through-week",
        type=int,
        required=True,
        help=(
            "Last completed week to include. "
            "For Week 2 predictions, use --through-week 1."
        ),
    )

    args = parser.parse_args()
    prediction_week = args.through_week + 1

    if args.through_week < 1:
        print("ERROR: --through-week must be at least 1.")
        sys.exit(1)

    print()
    print("=" * 80)
    print("BUILDING TEAM FEATURES")
    print("=" * 80)
    print(f"Season:       {args.season}")
    print(f"Through week: {args.through_week}")
    print()
    print("Loading database...")

    try:
        conn = get_connection()
    except Exception as exc:
        print(f"ERROR: Could not connect to database: {exc}")
        sys.exit(1)

    try:

        teams = load_team_names(conn)

        team_rows = load_team_weekly_stats(
            conn,
            args.season,
            args.through_week,
        )

        advanced_rows = load_team_advanced_stats(
            conn,
            args.season,
            args.through_week,
        )

        print(f"Loaded {len(teams)} teams.")
        print(f"Loaded {len(team_rows)} traditional team-game rows.")
        print(f"Loaded {len(advanced_rows)} advanced team-game rows.")
        print()

        if not team_rows:
            print(
                "No team statistics were found for the requested "
                "season/week range."
            )
            return

        features = build_team_features(
            team_rows,
            advanced_rows,
            teams,
        )

        print_feature_table(
            features,
            args.season,
            args.through_week,
        )

        save_team_features(
            conn,
            features,
            args.season,
            args.through_week,
        )

        print("TEAM FEATURE BUILD COMPLETED SUCCESSFULLY")
        print()

    finally:
        conn.close()


if __name__ == "__main__":
    main()