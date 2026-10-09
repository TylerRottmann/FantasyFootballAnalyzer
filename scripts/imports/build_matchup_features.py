"""
Build team matchup features for a prediction week.

Example:
    python scripts/build_matchup_features.py --season 2026 --week 2

The script:
1. Loads the NFL schedule.
2. Finds the games for the prediction week.
3. Loads each team's feature snapshot from the previous week.
4. Attaches the opponent's defensive profile.
5. Saves one matchup row per team.
"""

import argparse
import os
import sys
from datetime import datetime

import nflreadpy as nfl
import psycopg
from dotenv import load_dotenv


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def die(message):
    print(f"\nERROR: {message}")
    sys.exit(1)


def value(row, index):
    """Safely convert a database value to a number."""
    if row[index] is None:
        return 0
    return float(row[index])


def get_team_map(conn):
    """
    Return:
        abbreviation -> team_id

    Includes LA -> LAR because nflverse uses LA while
    our database uses LAR.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, abbreviation
            FROM teams
            WHERE is_active = TRUE
        """)

        rows = cur.fetchall()

    team_map = {}

    for team_id, abbreviation in rows:
        team_map[abbreviation] = team_id

    # nflverse uses LA for the Rams
    if "LAR" in team_map:
        team_map["LA"] = team_map["LAR"]

    return team_map


def get_snapshots(conn, season, through_week):
    """
    Load the feature snapshot for every team using data
    available through the week before the prediction.
    """

    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                team_id,

                points_against_per_game,
                total_yards_against_per_game,
                passing_yards_against_per_game,
                rushing_yards_against_per_game,

                turnovers_forced_per_game,
                interceptions_per_game,
                sacks_per_game,
                fumbles_forced_per_game,

                third_down_defense_rate,
                fourth_down_defense_rate,

                qb_fantasy_allowed_per_game,
                rb_fantasy_allowed_per_game,
                wr_fantasy_allowed_per_game,
                te_fantasy_allowed_per_game,

                defensive_epa_per_play,
                defensive_success_rate,

                explosive_pass_plays_allowed_per_game,
                explosive_rush_plays_allowed_per_game,
                explosive_plays_allowed_per_game,

                advanced_sack_rate,
                qb_hits_per_game,

                recent_points_against_per_game,
                recent_total_yards_against_per_game,
                recent_passing_yards_against_per_game,
                recent_rushing_yards_against_per_game,

                recent_turnovers_forced_per_game,

                recent_qb_fantasy_allowed_per_game,
                recent_rb_fantasy_allowed_per_game,
                recent_wr_fantasy_allowed_per_game,
                recent_te_fantasy_allowed_per_game,

                recent_defensive_epa_per_play,
                recent_defensive_success_rate,
                recent_explosive_plays_allowed_per_game,
                recent_sack_rate,
                recent_qb_hits_per_game

            FROM team_feature_snapshots
            WHERE season = %s
              AND data_through_week = %s
        """, (season, through_week))

        rows = cur.fetchall()

    snapshots = {}

    for row in rows:
        snapshots[row[0]] = row

    return snapshots


def load_schedule(season, week):
    """
    Load the requested week's NFL schedule.
    """

    print(f"Loading {season} Week {week} schedule...")

    schedule = nfl.load_schedules(seasons=[season])

    # Convert Polars -> dictionaries
    records = schedule.to_dicts()

    games = []

    for game in records:
        game_week = game.get("week")
        game_type = game.get("game_type")

        if game_week != week:
            continue

        # Regular season only
        if game_type not in ("REG", "REGULAR", "Regular Season"):
            continue

        home_team = game.get("home_team")
        away_team = game.get("away_team")

        if not home_team or not away_team:
            continue

        # We only want games that have a real matchup.
        games.append(game)

    return games


def get_game_date(game):
    """
    Extract the schedule date while remaining tolerant
    of nflreadpy/nflverse field naming.
    """

    date_value = (
        game.get("gameday")
        or game.get("game_date")
        or game.get("gamedate")
        or game.get("start_time")
    )

    if not date_value:
        return None

    if isinstance(date_value, datetime):
        return date_value

    try:
        return datetime.fromisoformat(str(date_value).replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------
# Build matchup rows
# ---------------------------------------------------------

def build_matchups(conn, season, prediction_week):
    through_week = prediction_week - 1

    print("=" * 80)
    print("BUILDING TEAM MATCHUP FEATURES")
    print("=" * 80)

    print(f"Season:              {season}")
    print(f"Prediction week:     {prediction_week}")
    print(f"Data through week:   {through_week}")
    print()

    team_map = get_team_map(conn)

    print(f"Loaded {len(team_map)} team mappings.")

    snapshots = get_snapshots(
        conn,
        season,
        through_week
    )

    print(f"Loaded {len(snapshots)} team feature snapshots.")

    if len(snapshots) == 0:
        die(
            f"No team snapshots found for season {season}, "
            f"through Week {through_week}."
        )

    games = load_schedule(season, prediction_week)

    print(f"Found {len(games)} Week {prediction_week} games.")

    if len(games) == 0:
        die("No games found for the requested prediction week.")

    matchup_rows = []

    for game in games:

        home_abbr = game.get("home_team")
        away_abbr = game.get("away_team")

        home_id = team_map.get(home_abbr)
        away_id = team_map.get(away_abbr)

        if home_id is None:
            print(f"WARNING: Could not find {home_abbr} in teams table.")
            continue

        if away_id is None:
            print(f"WARNING: Could not find {away_abbr} in teams table.")
            continue

        home_snapshot = snapshots.get(home_id)
        away_snapshot = snapshots.get(away_id)

        if home_snapshot is None:
            print(
                f"WARNING: No snapshot for {home_abbr} "
                f"through Week {through_week}."
            )
            continue

        if away_snapshot is None:
            print(
                f"WARNING: No snapshot for {away_abbr} "
                f"through Week {through_week}."
            )
            continue

        game_date = get_game_date(game)

        # -------------------------------------------------
        # Home team faces away team's defense
        # -------------------------------------------------

        matchup_rows.append({
            "team_id": home_id,
            "opponent_team_id": away_id,
            "season": season,
            "prediction_week": prediction_week,
            "is_home": True,
            "game_date": game_date,
            "snapshot": away_snapshot,
        })

        # -------------------------------------------------
        # Away team faces home team's defense
        # -------------------------------------------------

        matchup_rows.append({
            "team_id": away_id,
            "opponent_team_id": home_id,
            "season": season,
            "prediction_week": prediction_week,
            "is_home": False,
            "game_date": game_date,
            "snapshot": home_snapshot,
        })

        print(
            f"{away_abbr} @ {home_abbr}"
        )

    return matchup_rows


# ---------------------------------------------------------
# Save
# ---------------------------------------------------------

def save_matchups(conn, matchup_rows):

    print()
    print("=" * 80)
    print("SAVING MATCHUP FEATURES")
    print("=" * 80)

    insert_sql = """
        INSERT INTO team_matchup_features (
            team_id,
            opponent_team_id,
            season,
            prediction_week,
            is_home,
            game_date,

            opponent_points_against_per_game,
            opponent_total_yards_against_per_game,
            opponent_passing_yards_against_per_game,
            opponent_rushing_yards_against_per_game,

            opponent_turnovers_forced_per_game,
            opponent_interceptions_per_game,
            opponent_sacks_per_game,
            opponent_fumbles_forced_per_game,

            opponent_third_down_defense_rate,
            opponent_fourth_down_defense_rate,

            opponent_qb_fantasy_allowed_per_game,
            opponent_rb_fantasy_allowed_per_game,
            opponent_wr_fantasy_allowed_per_game,
            opponent_te_fantasy_allowed_per_game,

            opponent_defensive_epa_per_play,
            opponent_defensive_success_rate,

            opponent_explosive_pass_plays_allowed_per_game,
            opponent_explosive_rush_plays_allowed_per_game,
            opponent_explosive_plays_allowed_per_game,

            opponent_sack_rate,
            opponent_qb_hits_per_game,

            opponent_recent_points_against_per_game,
            opponent_recent_total_yards_against_per_game,
            opponent_recent_passing_yards_against_per_game,
            opponent_recent_rushing_yards_against_per_game,

            opponent_recent_turnovers_forced_per_game,

            opponent_recent_qb_fantasy_allowed_per_game,
            opponent_recent_rb_fantasy_allowed_per_game,
            opponent_recent_wr_fantasy_allowed_per_game,
            opponent_recent_te_fantasy_allowed_per_game,

            opponent_recent_defensive_epa_per_play,
            opponent_recent_defensive_success_rate,
            opponent_recent_explosive_plays_allowed_per_game,
            opponent_recent_sack_rate,
            opponent_recent_qb_hits_per_game,

            updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s, %s, %s,
            %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            NOW()
        )
        ON CONFLICT (team_id, season, prediction_week)
        DO UPDATE SET
            opponent_team_id = EXCLUDED.opponent_team_id,
            is_home = EXCLUDED.is_home,
            game_date = EXCLUDED.game_date,

            opponent_points_against_per_game =
                EXCLUDED.opponent_points_against_per_game,

            opponent_total_yards_against_per_game =
                EXCLUDED.opponent_total_yards_against_per_game,

            opponent_passing_yards_against_per_game =
                EXCLUDED.opponent_passing_yards_against_per_game,

            opponent_rushing_yards_against_per_game =
                EXCLUDED.opponent_rushing_yards_against_per_game,

            opponent_turnovers_forced_per_game =
                EXCLUDED.opponent_turnovers_forced_per_game,

            opponent_interceptions_per_game =
                EXCLUDED.opponent_interceptions_per_game,

            opponent_sacks_per_game =
                EXCLUDED.opponent_sacks_per_game,

            opponent_fumbles_forced_per_game =
                EXCLUDED.opponent_fumbles_forced_per_game,

            opponent_third_down_defense_rate =
                EXCLUDED.opponent_third_down_defense_rate,

            opponent_fourth_down_defense_rate =
                EXCLUDED.opponent_fourth_down_defense_rate,

            opponent_qb_fantasy_allowed_per_game =
                EXCLUDED.opponent_qb_fantasy_allowed_per_game,

            opponent_rb_fantasy_allowed_per_game =
                EXCLUDED.opponent_rb_fantasy_allowed_per_game,

            opponent_wr_fantasy_allowed_per_game =
                EXCLUDED.opponent_wr_fantasy_allowed_per_game,

            opponent_te_fantasy_allowed_per_game =
                EXCLUDED.opponent_te_fantasy_allowed_per_game,

            opponent_defensive_epa_per_play =
                EXCLUDED.opponent_defensive_epa_per_play,

            opponent_defensive_success_rate =
                EXCLUDED.opponent_defensive_success_rate,

            opponent_explosive_pass_plays_allowed_per_game =
                EXCLUDED.opponent_explosive_pass_plays_allowed_per_game,

            opponent_explosive_rush_plays_allowed_per_game =
                EXCLUDED.opponent_explosive_rush_plays_allowed_per_game,

            opponent_explosive_plays_allowed_per_game =
                EXCLUDED.opponent_explosive_plays_allowed_per_game,

            opponent_sack_rate =
                EXCLUDED.opponent_sack_rate,

            opponent_qb_hits_per_game =
                EXCLUDED.opponent_qb_hits_per_game,

            opponent_recent_points_against_per_game =
                EXCLUDED.opponent_recent_points_against_per_game,

            opponent_recent_total_yards_against_per_game =
                EXCLUDED.opponent_recent_total_yards_against_per_game,

            opponent_recent_passing_yards_against_per_game =
                EXCLUDED.opponent_recent_passing_yards_against_per_game,

            opponent_recent_rushing_yards_against_per_game =
                EXCLUDED.opponent_recent_rushing_yards_against_per_game,

            opponent_recent_turnovers_forced_per_game =
                EXCLUDED.opponent_recent_turnovers_forced_per_game,

            opponent_recent_qb_fantasy_allowed_per_game =
                EXCLUDED.opponent_recent_qb_fantasy_allowed_per_game,

            opponent_recent_rb_fantasy_allowed_per_game =
                EXCLUDED.opponent_recent_rb_fantasy_allowed_per_game,

            opponent_recent_wr_fantasy_allowed_per_game =
                EXCLUDED.opponent_recent_wr_fantasy_allowed_per_game,

            opponent_recent_te_fantasy_allowed_per_game =
                EXCLUDED.opponent_recent_te_fantasy_allowed_per_game,

            opponent_recent_defensive_epa_per_play =
                EXCLUDED.opponent_recent_defensive_epa_per_play,

            opponent_recent_defensive_success_rate =
                EXCLUDED.opponent_recent_defensive_success_rate,

            opponent_recent_explosive_plays_allowed_per_game =
                EXCLUDED.opponent_recent_explosive_plays_allowed_per_game,

            opponent_recent_sack_rate =
                EXCLUDED.opponent_recent_sack_rate,

            opponent_recent_qb_hits_per_game =
                EXCLUDED.opponent_recent_qb_hits_per_game,

            updated_at = NOW()
    """

    with conn.cursor() as cur:

        for matchup in matchup_rows:

            snapshot = matchup["snapshot"]

            # Snapshot indexes correspond to get_snapshots()
            params = (
                matchup["team_id"],
                matchup["opponent_team_id"],
                matchup["season"],
                matchup["prediction_week"],
                matchup["is_home"],
                matchup["game_date"],

                value(snapshot, 1),
                value(snapshot, 2),
                value(snapshot, 3),
                value(snapshot, 4),

                value(snapshot, 5),
                value(snapshot, 6),
                value(snapshot, 7),
                value(snapshot, 8),

                value(snapshot, 9),
                value(snapshot, 10),

                value(snapshot, 11),
                value(snapshot, 12),
                value(snapshot, 13),
                value(snapshot, 14),

                value(snapshot, 15),
                value(snapshot, 16),

                value(snapshot, 17),
                value(snapshot, 18),
                value(snapshot, 19),

                value(snapshot, 20),
                value(snapshot, 21),

                value(snapshot, 22),
                value(snapshot, 23),
                value(snapshot, 24),
                value(snapshot, 25),

                value(snapshot, 26),

                value(snapshot, 27),
                value(snapshot, 28),
                value(snapshot, 29),
                value(snapshot, 30),

                value(snapshot, 31),
                value(snapshot, 32),
                value(snapshot, 33),
                value(snapshot, 34),
                value(snapshot, 35),
            )

            cur.execute(insert_sql, params)

    conn.commit()

    print()
    print(f"Saved {len(matchup_rows)} matchup rows.")


# ---------------------------------------------------------
# Verification
# ---------------------------------------------------------

def verify(conn, season, prediction_week):

    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*)
            FROM team_matchup_features
            WHERE season = %s
              AND prediction_week = %s
        """, (season, prediction_week))

        count = cur.fetchone()[0]

        cur.execute("""
            SELECT
                t.abbreviation,
                o.abbreviation,
                m.is_home,
                m.opponent_defensive_epa_per_play,
                m.opponent_wr_fantasy_allowed_per_game,
                m.opponent_rb_fantasy_allowed_per_game,
                m.opponent_qb_fantasy_allowed_per_game,
                m.opponent_te_fantasy_allowed_per_game
            FROM team_matchup_features m
            JOIN teams t
                ON t.id = m.team_id
            JOIN teams o
                ON o.id = m.opponent_team_id
            WHERE m.season = %s
              AND m.prediction_week = %s
            ORDER BY t.abbreviation
            LIMIT 10
        """, (season, prediction_week))

        rows = cur.fetchall()

    print()
    print("=" * 80)
    print("VERIFICATION")
    print("=" * 80)

    print(f"Rows saved: {count}")

    if count == 0:
        die("No matchup rows were saved.")

    print()
    print(
        f"{'TEAM':<6}"
        f"{'OPP':<6}"
        f"{'HOME':<6}"
        f"{'DEF EPA':<10}"
        f"{'WR FPA':<10}"
        f"{'RB FPA':<10}"
        f"{'QB FPA':<10}"
        f"{'TE FPA':<10}"
    )

    print("-" * 72)

    for row in rows:
        team, opponent, home, def_epa, wr, rb, qb, te = row

        print(
            f"{team:<6}"
            f"{opponent:<6}"
            f"{str(home):<6}"
            f"{float(def_epa):<10.4f}"
            f"{float(wr):<10.2f}"
            f"{float(rb):<10.2f}"
            f"{float(qb):<10.2f}"
            f"{float(te):<10.2f}"
        )

    print()
    print("Matchup features verified successfully.")


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description="Build NFL team matchup features."
    )

    parser.add_argument(
        "--season",
        type=int,
        required=True
    )

    parser.add_argument(
        "--week",
        type=int,
        required=True
    )

    args = parser.parse_args()

    if args.week < 2:
        die(
            "Prediction week must be at least Week 2 because "
            "we need a previous week's snapshot."
        )

    through_week = args.week - 1

    print()
    print("=" * 80)
    print("TEAM MATCHUP FEATURE BUILDER")
    print("=" * 80)
    print()

    try:
        with psycopg.connect(**DB_CONFIG) as conn:

            matchup_rows = build_matchups(
                conn,
                args.season,
                args.week
            )

            if not matchup_rows:
                die("No matchup rows were created.")

            save_matchups(
                conn,
                matchup_rows
            )

            verify(
                conn,
                args.season,
                args.week
            )

    except psycopg.Error as exc:
        die(f"Database error: {exc}")

    except Exception as exc:
        die(f"Unexpected error: {exc}")

    print()
    print("=" * 80)
    print("MATCHUP FEATURE BUILD COMPLETED SUCCESSFULLY")
    print("=" * 80)
    print()
    print(
        f"Data through Week {through_week} "
        f"-> Prediction Week {args.week}"
    )


if __name__ == "__main__":
    main()