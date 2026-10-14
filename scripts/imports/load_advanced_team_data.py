import os

import nflreadpy as nfl
import psycopg
from dotenv import load_dotenv

load_dotenv()

SEASON = 2026


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
# LOAD PBP
# ============================================================

print(f"Loading {SEASON} play-by-play data...")

pbp = nfl.load_pbp(seasons=[SEASON])

# Regular season only
pbp = pbp.filter(
    pbp["season_type"] == "REG"
)

print(f"Loaded {len(pbp)} play records.")


# ============================================================
# TEAM MAPPING
# ============================================================

with conn.cursor() as cur:
    cur.execute("""
        SELECT id, abbreviation
        FROM teams
    """)

    team_rows = cur.fetchall()


team_map = {
    abbreviation: team_id
    for team_id, abbreviation in team_rows
}

# nflverse uses LA for the Rams.
# Our database uses LAR as the canonical abbreviation.
if "LAR" in team_map:
    team_map["LA"] = team_map["LAR"]

print(f"Loaded {len(team_map)} team mappings.")


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def safe_float(value):
    if value is None:
        return 0.0
    return float(value)


def count_true(df, column):
    """
    Counts rows where a boolean/numeric indicator is true/1.
    """
    if len(df) == 0:
        return 0

    return len(
        df.filter(
            df[column] == True
        )
    )


# ============================================================
# PROCESS EACH WEEK
# ============================================================

weeks = (
    pbp["week"]
    .drop_nulls()
    .unique()
    .sort()
    .to_list()
)


for week in weeks:

    print()
    print(f"Processing Week {week}...")

    week_pbp = pbp.filter(
        pbp["week"] == week
    )

    # Remove deleted/aborted plays where possible.
    week_pbp = week_pbp.filter(
        (week_pbp["play_deleted"] != True) &
        (week_pbp["aborted_play"] != True)
    )

    # ========================================================
    # FIND TEAMS
    # ========================================================

    teams_this_week = set()

    posteams = (
        week_pbp["posteam"]
        .drop_nulls()
        .unique()
        .to_list()
    )

    defteams = (
        week_pbp["defteam"]
        .drop_nulls()
        .unique()
        .to_list()
    )

    teams_this_week.update(posteams)
    teams_this_week.update(defteams)

    # Only actual NFL teams
    teams_this_week = {
        team
        for team in teams_this_week
        if team in team_map
    }

    # ========================================================
    # PROCESS EACH TEAM
    # ========================================================

    for team in sorted(teams_this_week):

        team_id = team_map[team]

        # ----------------------------------------------------
        # OFFENSE
        # ----------------------------------------------------

        offense = week_pbp.filter(
            week_pbp["posteam"] == team
        )

        # Standard offensive EPA sample:
        # pass plays + run plays, excluding kneels.
        #
        # play_type == pass includes sacks.
        # play_type == run includes scrambles.
        offense = offense.filter(
            (
                (offense["play_type"] == "pass") |
                (offense["play_type"] == "run")
            ) &
            (offense["qb_kneel"] != True)
        )

        offensive_plays = len(offense)

        # ----------------------------------------------------
        # OFFENSIVE EPA
        # ----------------------------------------------------

        offensive_epa = (
            offense["epa"]
            .drop_nulls()
            .sum()
            if offensive_plays > 0
            else 0
        )

        offensive_epa_per_play = (
            offensive_epa / offensive_plays
            if offensive_plays > 0
            else 0
        )

        # ----------------------------------------------------
        # PASSING / DROPBACKS
        # ----------------------------------------------------

        pass_plays = offense.filter(
            offense["qb_dropback"] == True
        )

        pass_attempts = len(pass_plays)

        pass_epa = (
            pass_plays["epa"]
            .drop_nulls()
            .sum()
            if pass_attempts > 0
            else 0
        )

        pass_epa_per_play = (
            pass_epa / pass_attempts
            if pass_attempts > 0
            else 0
        )

        # ----------------------------------------------------
        # RUSHING
        # ----------------------------------------------------

        rush_plays = offense.filter(
            offense["qb_dropback"] != True
        )

        rush_attempts = len(rush_plays)

        rush_epa = (
            rush_plays["epa"]
            .drop_nulls()
            .sum()
            if rush_attempts > 0
            else 0
        )

        rush_epa_per_play = (
            rush_epa / rush_attempts
            if rush_attempts > 0
            else 0
        )

        # ----------------------------------------------------
        # SUCCESS RATE
        # ----------------------------------------------------

        offensive_successes = count_true(
            offense,
            "success"
        )

        offensive_success_rate = (
            offensive_successes / offensive_plays
            if offensive_plays > 0
            else 0
        )

        pass_successes = count_true(
            pass_plays,
            "success"
        )

        pass_success_rate = (
            pass_successes / pass_attempts
            if pass_attempts > 0
            else 0
        )

        rush_successes = count_true(
            rush_plays,
            "success"
        )

        rush_success_rate = (
            rush_successes / rush_attempts
            if rush_attempts > 0
            else 0
        )

        # ----------------------------------------------------
        # EXPLOSIVE OFFENSIVE PLAYS
        # ----------------------------------------------------

        explosive_pass_plays = len(
            pass_plays.filter(
                pass_plays["yards_gained"] >= 20
            )
        )

        explosive_rush_plays = len(
            rush_plays.filter(
                rush_plays["yards_gained"] >= 10
            )
        )

        explosive_plays = (
            explosive_pass_plays +
            explosive_rush_plays
        )

        # ----------------------------------------------------
        # DEFENSE
        # ----------------------------------------------------

        defense = week_pbp.filter(
            week_pbp["defteam"] == team
        )

        defense = defense.filter(
            (
                (defense["play_type"] == "pass") |
                (defense["play_type"] == "run")
            ) &
            (defense["qb_kneel"] != True)
        )

        defensive_plays = len(defense)

        # ----------------------------------------------------
        # DEFENSIVE EPA
        # ----------------------------------------------------
        #
        # EPA belongs to the offense.
        #
        # Therefore:
        #
        # Positive offensive EPA against a defense
        # = negative defensive value.
        #
        # Example:
        #
        # Opponent +0.40 EPA
        # Defense = -0.40 EPA
        #
        # Higher defensive EPA is therefore better.
        # ----------------------------------------------------

        opponent_epa = (
            defense["epa"]
            .drop_nulls()
            .sum()
            if defensive_plays > 0
            else 0
        )

        defensive_epa = -opponent_epa

        defensive_epa_per_play = (
            defensive_epa / defensive_plays
            if defensive_plays > 0
            else 0
        )

        # ----------------------------------------------------
        # DEFENSIVE SUCCESS RATE
        # ----------------------------------------------------

        defensive_successes_allowed = count_true(
            defense,
            "success"
        )

        opponent_success_rate = (
            defensive_successes_allowed / defensive_plays
            if defensive_plays > 0
            else 0
        )

        defensive_success_rate = (
            1 - opponent_success_rate
            if defensive_plays > 0
            else 0
        )

        # ----------------------------------------------------
        # EXPLOSIVE PLAYS ALLOWED
        # ----------------------------------------------------

        explosive_pass_allowed = defense.filter(
            (defense["qb_dropback"] == True) &
            (defense["yards_gained"] >= 20)
        )

        explosive_rush_allowed = defense.filter(
            (defense["qb_dropback"] != True) &
            (defense["yards_gained"] >= 10)
        )

        explosive_pass_plays_allowed = len(
            explosive_pass_allowed
        )

        explosive_rush_plays_allowed = len(
            explosive_rush_allowed
        )

        explosive_plays_allowed = (
            explosive_pass_plays_allowed +
            explosive_rush_plays_allowed
        )

        # ----------------------------------------------------
        # PASS RUSH
        # ----------------------------------------------------

        sacks = count_true(
            defense,
            "sack"
        )

        qb_hits = count_true(
            defense,
            "qb_hit"
        )

        # Sack rate should use dropbacks rather than
        # pass attempts because sacks are themselves
        # dropback outcomes.
        sack_rate = (
            sacks / pass_attempts
            if pass_attempts > 0
            else 0
        )

        # ----------------------------------------------------
        # TURNOVERS
        # ----------------------------------------------------

        interceptions = count_true(
            defense,
            "interception"
        )

        forced_fumbles = count_true(
            defense,
            "fumble_forced"
        )

        # ----------------------------------------------------
        # INSERT / UPDATE
        # ----------------------------------------------------
        #
        # Named parameters are used here intentionally.
        # This eliminates the placeholder-count problem
        # from the previous version.
        # ----------------------------------------------------

        data = {
            "team_id": team_id,
            "season": SEASON,
            "week": week,

            "offensive_plays": offensive_plays,
            "pass_attempts": pass_attempts,
            "rush_attempts": rush_attempts,

            "offensive_epa": safe_float(
                offensive_epa
            ),

            "offensive_epa_per_play": safe_float(
                offensive_epa_per_play
            ),

            "pass_epa": safe_float(
                pass_epa
            ),

            "pass_epa_per_play": safe_float(
                pass_epa_per_play
            ),

            "rush_epa": safe_float(
                rush_epa
            ),

            "rush_epa_per_play": safe_float(
                rush_epa_per_play
            ),

            "offensive_success_rate": safe_float(
                offensive_success_rate
            ),

            "pass_success_rate": safe_float(
                pass_success_rate
            ),

            "rush_success_rate": safe_float(
                rush_success_rate
            ),

            "explosive_pass_plays":
                explosive_pass_plays,

            "explosive_rush_plays":
                explosive_rush_plays,

            "explosive_plays":
                explosive_plays,

            "defensive_epa": safe_float(
                defensive_epa
            ),

            "defensive_epa_per_play": safe_float(
                defensive_epa_per_play
            ),

            "defensive_success_rate": safe_float(
                defensive_success_rate
            ),

            "explosive_pass_plays_allowed":
                explosive_pass_plays_allowed,

            "explosive_rush_plays_allowed":
                explosive_rush_plays_allowed,

            "explosive_plays_allowed":
                explosive_plays_allowed,

            "sacks": sacks,

            "qb_hits": qb_hits,

            "sack_rate": safe_float(
                sack_rate
            ),

            "interceptions": interceptions,

            "forced_fumbles": forced_fumbles,
        }

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO team_advanced_weekly (
                    team_id,
                    season,
                    week,
                    season_type,

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
                    forced_fumbles,

                    updated_at
                )

                VALUES (
                    %(team_id)s,
                    %(season)s,
                    %(week)s,
                    1,

                    %(offensive_plays)s,
                    %(pass_attempts)s,
                    %(rush_attempts)s,

                    %(offensive_epa)s,
                    %(offensive_epa_per_play)s,

                    %(pass_epa)s,
                    %(pass_epa_per_play)s,

                    %(rush_epa)s,
                    %(rush_epa_per_play)s,

                    %(offensive_success_rate)s,
                    %(pass_success_rate)s,
                    %(rush_success_rate)s,

                    %(explosive_pass_plays)s,
                    %(explosive_rush_plays)s,
                    %(explosive_plays)s,

                    %(defensive_epa)s,
                    %(defensive_epa_per_play)s,
                    %(defensive_success_rate)s,

                    %(explosive_pass_plays_allowed)s,
                    %(explosive_rush_plays_allowed)s,
                    %(explosive_plays_allowed)s,

                    %(sacks)s,
                    %(qb_hits)s,
                    %(sack_rate)s,

                    %(interceptions)s,
                    %(forced_fumbles)s,

                    NOW()
                )

                ON CONFLICT (
                    team_id,
                    season,
                    week,
                    season_type
                )

                DO UPDATE SET

                    offensive_plays =
                        EXCLUDED.offensive_plays,

                    pass_attempts =
                        EXCLUDED.pass_attempts,

                    rush_attempts =
                        EXCLUDED.rush_attempts,

                    offensive_epa =
                        EXCLUDED.offensive_epa,

                    offensive_epa_per_play =
                        EXCLUDED.offensive_epa_per_play,

                    pass_epa =
                        EXCLUDED.pass_epa,

                    pass_epa_per_play =
                        EXCLUDED.pass_epa_per_play,

                    rush_epa =
                        EXCLUDED.rush_epa,

                    rush_epa_per_play =
                        EXCLUDED.rush_epa_per_play,

                    offensive_success_rate =
                        EXCLUDED.offensive_success_rate,

                    pass_success_rate =
                        EXCLUDED.pass_success_rate,

                    rush_success_rate =
                        EXCLUDED.rush_success_rate,

                    explosive_pass_plays =
                        EXCLUDED.explosive_pass_plays,

                    explosive_rush_plays =
                        EXCLUDED.explosive_rush_plays,

                    explosive_plays =
                        EXCLUDED.explosive_plays,

                    defensive_epa =
                        EXCLUDED.defensive_epa,

                    defensive_epa_per_play =
                        EXCLUDED.defensive_epa_per_play,

                    defensive_success_rate =
                        EXCLUDED.defensive_success_rate,

                    explosive_pass_plays_allowed =
                        EXCLUDED.explosive_pass_plays_allowed,

                    explosive_rush_plays_allowed =
                        EXCLUDED.explosive_rush_plays_allowed,

                    explosive_plays_allowed =
                        EXCLUDED.explosive_plays_allowed,

                    sacks =
                        EXCLUDED.sacks,

                    qb_hits =
                        EXCLUDED.qb_hits,

                    sack_rate =
                        EXCLUDED.sack_rate,

                    interceptions =
                        EXCLUDED.interceptions,

                    forced_fumbles =
                        EXCLUDED.forced_fumbles,

                    updated_at =
                        NOW()
                """,
                data,
            )

        print(
            f"  {team}: "
            f"EPA/play={offensive_epa_per_play:.3f} | "
            f"Success={offensive_success_rate:.1%} | "
            f"Def EPA/play={defensive_epa_per_play:.3f}"
        )

    conn.commit()


# ============================================================
# FINISH
# ============================================================

conn.close()

print()
print("Advanced team analytics loaded successfully.")