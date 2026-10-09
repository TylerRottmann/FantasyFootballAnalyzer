import os
import argparse
import psycopg
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# ARGUMENTS
# ============================================================

parser = argparse.ArgumentParser(
    description="Build team feature snapshots from weekly team data."
)

parser.add_argument(
    "--season",
    type=int,
    default=2026,
    help="NFL season to build features for.",
)

parser.add_argument(
    "--through-week",
    type=int,
    required=True,
    help="Last completed week available to the prediction model.",
)

parser.add_argument(
    "--recent-weeks",
    type=int,
    default=4,
    help="Number of most recent games used for recent-form features.",
)

args = parser.parse_args()

SEASON = args.season
THROUGH_WEEK = args.through_week
RECENT_WEEKS = max(1, args.recent_weeks)
PREDICTION_WEEK = THROUGH_WEEK + 1


# ============================================================
# DATABASE
# ============================================================

conn = psycopg.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
)


# ============================================================
# HELPERS
# ============================================================

def avg(values):
    values = [
        float(v)
        for v in values
        if v is not None
    ]
    return sum(values) / len(values) if values else 0.0


def total(values):
    values = [
        float(v)
        for v in values
        if v is not None
    ]
    return sum(values) if values else 0.0


def rate(conversions, attempts):
    attempts = total(attempts)
    return total(conversions) / attempts if attempts else 0.0


def recent(values):
    return values[-RECENT_WEEKS:]


def safe_float(value):
    return float(value) if value is not None else 0.0


# ============================================================
# LOAD TRADITIONAL WEEKLY DATA
# ============================================================

print()
print("=" * 80)
print("LOADING TRADITIONAL TEAM DATA")
print("=" * 80)

with conn.cursor() as cur:
    cur.execute(
        """
        SELECT
            team_id,
            season,
            week,

            points_for,
            points_against,

            total_yards,
            passing_yards,
            rushing_yards,

            total_yards_against,
            passing_yards_against,
            rushing_yards_against,

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

        WHERE season = %(season)s
          AND season_type = 1
          AND week <= %(through_week)s

        ORDER BY team_id, week
        """,
        {
            "season": SEASON,
            "through_week": THROUGH_WEEK,
        },
    )

    weekly_rows = cur.fetchall()

print(f"Loaded {len(weekly_rows)} traditional team-week records.")


# ============================================================
# LOAD ADVANCED WEEKLY DATA
# ============================================================

print()
print("=" * 80)
print("LOADING ADVANCED TEAM DATA")
print("=" * 80)

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

        WHERE season = %(season)s
          AND season_type = 1
          AND week <= %(through_week)s

        ORDER BY team_id, week
        """,
        {
            "season": SEASON,
            "through_week": THROUGH_WEEK,
        },
    )

    advanced_rows = cur.fetchall()

print(f"Loaded {len(advanced_rows)} advanced team-week records.")


# ============================================================
# ORGANIZE DATA
# ============================================================

team_weekly = {}

for row in weekly_rows:
    team_id = row[0]
    week = row[2]

    team_weekly.setdefault(team_id, {})
    team_weekly[team_id][week] = row


team_advanced = {}

for row in advanced_rows:
    team_id = row[0]
    week = row[2]

    team_advanced.setdefault(team_id, {})
    team_advanced[team_id][week] = row


# ============================================================
# BUILD FEATURES
# ============================================================

print()
print("=" * 80)
print("BUILDING TEAM FEATURE SNAPSHOTS")
print("=" * 80)

features = []

for team_id in sorted(team_weekly.keys()):

    available_weeks = sorted(team_weekly[team_id].keys())

    if not available_weeks:
        continue

    # Only weeks for which traditional team data exists.
    weekly = [
        team_weekly[team_id][week]
        for week in available_weeks
    ]

    # --------------------------------------------------------
    # Traditional data
    # --------------------------------------------------------

    points_for = [row[3] for row in weekly]
    points_against = [row[4] for row in weekly]

    total_yards = [row[5] for row in weekly]
    passing_yards = [row[6] for row in weekly]
    rushing_yards = [row[7] for row in weekly]

    total_yards_against = [row[8] for row in weekly]
    passing_yards_against = [row[9] for row in weekly]
    rushing_yards_against = [row[10] for row in weekly]

    interceptions = [row[11] for row in weekly]
    sacks = [row[12] for row in weekly]
    fumbles_forced = [row[13] for row in weekly]

    third_down_attempts = [row[14] for row in weekly]
    third_down_conversions = [row[15] for row in weekly]
    third_down_attempts_against = [row[16] for row in weekly]
    third_down_conversions_against = [row[17] for row in weekly]

    fourth_down_attempts = [row[18] for row in weekly]
    fourth_down_conversions = [row[19] for row in weekly]
    fourth_down_attempts_against = [row[20] for row in weekly]
    fourth_down_conversions_against = [row[21] for row in weekly]

    kicking_points_for = [row[22] for row in weekly]
    kicking_points_against = [row[23] for row in weekly]

    qb_fantasy_allowed = [row[24] for row in weekly]
    rb_fantasy_allowed = [row[25] for row in weekly]
    wr_fantasy_allowed = [row[26] for row in weekly]
    te_fantasy_allowed = [row[27] for row in weekly]

    # --------------------------------------------------------
    # Advanced data
    # --------------------------------------------------------

    advanced_weeks = sorted(
        set(available_weeks)
        & set(team_advanced.get(team_id, {}).keys())
    )

    advanced = [
        team_advanced[team_id][week]
        for week in advanced_weeks
    ]

    offensive_epa = [row[6] for row in advanced]
    offensive_epa_per_play = [row[7] for row in advanced]

    pass_epa = [row[8] for row in advanced]
    pass_epa_per_play = [row[9] for row in advanced]

    rush_epa = [row[10] for row in advanced]
    rush_epa_per_play = [row[11] for row in advanced]

    offensive_success = [row[12] for row in advanced]
    pass_success = [row[13] for row in advanced]
    rush_success = [row[14] for row in advanced]

    explosive_pass = [row[15] for row in advanced]
    explosive_rush = [row[16] for row in advanced]
    explosive_plays = [row[17] for row in advanced]

    defensive_epa = [row[18] for row in advanced]
    defensive_epa_per_play = [row[19] for row in advanced]
    defensive_success = [row[20] for row in advanced]

    explosive_pass_allowed = [row[21] for row in advanced]
    explosive_rush_allowed = [row[22] for row in advanced]
    explosive_allowed = [row[23] for row in advanced]

    advanced_sacks = [row[24] for row in advanced]
    qb_hits = [row[25] for row in advanced]
    advanced_sack_rate = [row[26] for row in advanced]

    advanced_interceptions = [row[27] for row in advanced]
    advanced_forced_fumbles = [row[28] for row in advanced]

    # --------------------------------------------------------
    # Recent data
    # --------------------------------------------------------

    r_points_for = recent(points_for)
    r_points_against = recent(points_against)

    r_total_yards = recent(total_yards)
    r_passing_yards = recent(passing_yards)
    r_rushing_yards = recent(rushing_yards)

    r_total_yards_against = recent(total_yards_against)
    r_passing_yards_against = recent(passing_yards_against)
    r_rushing_yards_against = recent(rushing_yards_against)

    r_turnovers = recent(
        [
            (float(i or 0) + float(f or 0))
            for i, f in zip(interceptions, fumbles_forced)
        ]
    )

    r_qb_fantasy = recent(qb_fantasy_allowed)
    r_rb_fantasy = recent(rb_fantasy_allowed)
    r_wr_fantasy = recent(wr_fantasy_allowed)
    r_te_fantasy = recent(te_fantasy_allowed)

    r_offensive_epa = recent(offensive_epa)
    r_offensive_epa_per_play = recent(offensive_epa_per_play)
    r_pass_epa_per_play = recent(pass_epa_per_play)
    r_rush_epa_per_play = recent(rush_epa_per_play)

    r_offensive_success = recent(offensive_success)
    r_pass_success = recent(pass_success)
    r_rush_success = recent(rush_success)

    r_explosive = recent(explosive_plays)

    r_defensive_epa = recent(defensive_epa)
    r_defensive_epa_per_play = recent(defensive_epa_per_play)
    r_defensive_success = recent(defensive_success)

    r_explosive_allowed = recent(explosive_allowed)
    r_sack_rate = recent(advanced_sack_rate)
    r_qb_hits = recent(qb_hits)

    # --------------------------------------------------------
    # Feature dictionary
    # --------------------------------------------------------

    feature = {
        "team_id": team_id,
        "season": SEASON,
        "data_through_week": THROUGH_WEEK,
        "prediction_week": PREDICTION_WEEK,

        "games_played": len(weekly),
        "recent_games": min(len(weekly), RECENT_WEEKS),

        # Traditional offense
        "points_for_per_game": avg(points_for),
        "total_yards_per_game": avg(total_yards),
        "passing_yards_per_game": avg(passing_yards),
        "rushing_yards_per_game": avg(rushing_yards),

        # Traditional defense
        "points_against_per_game": avg(points_against),
        "total_yards_against_per_game": avg(total_yards_against),
        "passing_yards_against_per_game": avg(passing_yards_against),
        "rushing_yards_against_per_game": avg(rushing_yards_against),

        "turnovers_forced_per_game": avg(
            [
                float(i or 0) + float(f or 0)
                for i, f in zip(interceptions, fumbles_forced)
            ]
        ),

        "interceptions_per_game": avg(interceptions),
        "sacks_per_game": avg(sacks),
        "fumbles_forced_per_game": avg(fumbles_forced),

        # Down conversion
        "third_down_conversion_rate":
            rate(third_down_conversions, third_down_attempts),

        "third_down_defense_rate":
            rate(
                third_down_conversions_against,
                third_down_attempts_against,
            ),

        "fourth_down_conversion_rate":
            rate(fourth_down_conversions, fourth_down_attempts),

        "fourth_down_defense_rate":
            rate(
                fourth_down_conversions_against,
                fourth_down_attempts_against,
            ),

        # Special teams
        "kicking_points_for_per_game":
            avg(kicking_points_for),

        "kicking_points_against_per_game":
            avg(kicking_points_against),

        # Fantasy matchup
        "qb_fantasy_allowed_per_game":
            avg(qb_fantasy_allowed),

        "rb_fantasy_allowed_per_game":
            avg(rb_fantasy_allowed),

        "wr_fantasy_allowed_per_game":
            avg(wr_fantasy_allowed),

        "te_fantasy_allowed_per_game":
            avg(te_fantasy_allowed),

        # Advanced offense
        "offensive_epa_per_play":
            avg(offensive_epa_per_play),

        "pass_epa_per_play":
            avg(pass_epa_per_play),

        "rush_epa_per_play":
            avg(rush_epa_per_play),

        "offensive_success_rate":
            avg(offensive_success),

        "pass_success_rate":
            avg(pass_success),

        "rush_success_rate":
            avg(rush_success),

        "explosive_pass_plays_per_game":
            avg(explosive_pass),

        "explosive_rush_plays_per_game":
            avg(explosive_rush),

        "explosive_plays_per_game":
            avg(explosive_plays),

        # Advanced defense
        "defensive_epa_per_play":
            avg(defensive_epa_per_play),

        "defensive_success_rate":
            avg(defensive_success),

        "explosive_pass_plays_allowed_per_game":
            avg(explosive_pass_allowed),

        "explosive_rush_plays_allowed_per_game":
            avg(explosive_rush_allowed),

        "explosive_plays_allowed_per_game":
            avg(explosive_allowed),

        "advanced_sack_rate":
            avg(advanced_sack_rate),

        "qb_hits_per_game":
            avg(qb_hits),

        # Recent traditional
        "recent_points_for_per_game":
            avg(r_points_for),

        "recent_points_against_per_game":
            avg(r_points_against),

        "recent_total_yards_per_game":
            avg(r_total_yards),

        "recent_passing_yards_per_game":
            avg(r_passing_yards),

        "recent_rushing_yards_per_game":
            avg(r_rushing_yards),

        "recent_total_yards_against_per_game":
            avg(r_total_yards_against),

        "recent_passing_yards_against_per_game":
            avg(r_passing_yards_against),

        "recent_rushing_yards_against_per_game":
            avg(r_rushing_yards_against),

        "recent_turnovers_forced_per_game":
            avg(r_turnovers),

        # Recent fantasy matchup
        "recent_qb_fantasy_allowed_per_game":
            avg(r_qb_fantasy),

        "recent_rb_fantasy_allowed_per_game":
            avg(r_rb_fantasy),

        "recent_wr_fantasy_allowed_per_game":
            avg(r_wr_fantasy),

        "recent_te_fantasy_allowed_per_game":
            avg(r_te_fantasy),

        # Recent advanced offense
        "recent_offensive_epa":
            avg(r_offensive_epa),

        "recent_offensive_epa_per_play":
            avg(r_offensive_epa_per_play),

        "recent_pass_epa_per_play":
            avg(r_pass_epa_per_play),

        "recent_rush_epa_per_play":
            avg(r_rush_epa_per_play),

        "recent_offensive_success_rate":
            avg(r_offensive_success),

        "recent_pass_success_rate":
            avg(r_pass_success),

        "recent_rush_success_rate":
            avg(r_rush_success),

        "recent_explosive_plays_per_game":
            avg(r_explosive),

        # Recent advanced defense
        "recent_defensive_epa":
            avg(r_defensive_epa),

        "recent_defensive_epa_per_play":
            avg(r_defensive_epa_per_play),

        "recent_defensive_success_rate":
            avg(r_defensive_success),

        "recent_explosive_plays_allowed_per_game":
            avg(r_explosive_allowed),

        "recent_sack_rate":
            avg(r_sack_rate),

        "recent_qb_hits_per_game":
            avg(r_qb_hits),
    }

    features.append(feature)


print(f"Built {len(features)} team feature snapshots.")


# ============================================================
# SAVE SNAPSHOTS
# ============================================================

print()
print("=" * 80)
print("SAVING TEAM FEATURE SNAPSHOTS")
print("=" * 80)

inserted = 0

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
                %(data_through_week)s,
                %(prediction_week)s,

                %(games_played)s,
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

            ON CONFLICT (
                team_id,
                season,
                data_through_week
            )

            DO UPDATE SET

                prediction_week = EXCLUDED.prediction_week,

                games_played = EXCLUDED.games_played,
                recent_games = EXCLUDED.recent_games,

                points_for_per_game = EXCLUDED.points_for_per_game,
                total_yards_per_game = EXCLUDED.total_yards_per_game,
                passing_yards_per_game = EXCLUDED.passing_yards_per_game,
                rushing_yards_per_game = EXCLUDED.rushing_yards_per_game,

                points_against_per_game = EXCLUDED.points_against_per_game,
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
            feature,
        )

        inserted += 1


conn.commit()

print()
print(f"Saved {inserted} team feature snapshots.")
print(
    f"Data through Week {THROUGH_WEEK} "
    f"→ Prediction Week {PREDICTION_WEEK}"
)


# ============================================================
# VERIFY
# ============================================================

with conn.cursor() as cur:
    cur.execute(
        """
        SELECT
            COUNT(*),
            MIN(data_through_week),
            MAX(data_through_week),
            MIN(prediction_week),
            MAX(prediction_week)
        FROM team_feature_snapshots
        WHERE season = %(season)s
          AND data_through_week = %(through_week)s
        """,
        {
            "season": SEASON,
            "through_week": THROUGH_WEEK,
        },
    )

    count, min_week, max_week, min_prediction, max_prediction = cur.fetchone()


print()
print("=" * 80)
print("VERIFICATION")
print("=" * 80)
print(f"Rows saved:       {count}")
print(f"Data through:     Week {min_week} - Week {max_week}")
print(f"Prediction week:  Week {min_prediction} - Week {max_prediction}")

if count == 0:
    print("WARNING: No feature snapshots were saved.")
elif min_prediction != PREDICTION_WEEK or max_prediction != PREDICTION_WEEK:
    print("WARNING: Prediction week does not match expected value.")
else:
    print("Team feature snapshots verified successfully.")


conn.close()

print()
print("=" * 80)
print("TEAM FEATURE BUILD COMPLETED SUCCESSFULLY")
print("=" * 80)
