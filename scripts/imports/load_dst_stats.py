# scripts/imports/load_dst_stats.py
#
# Adds the D/ST columns that load_team_data.py does not populate and
# computes dst_fantasy_points for every team-week.
#
# Run AFTER load_team_data.py:
#     python -m scripts.imports.load_dst_stats
#
# New team_weekly_stats columns:
#     forced_fumbles, fumble_recoveries, defensive_tds, special_teams_tds,
#     safeties,
#     dst_fantasy_points
#
# NOTE: field names below come from nflreadpy.load_team_stats().
# If a name differs in your installed version, the script prints the
# available columns and stops so you can fix the mapping.

import argparse
import os

import nflreadpy as nfl
import psycopg
from dotenv import load_dotenv

from scripts.algorithm.dst.scoring import dst_fantasy_points

from scripts.imports.scheduled_coverage import completed_games, regular_through, require_team_coverage

load_dotenv()

parser = argparse.ArgumentParser(description="Import weekly D/ST statistics.")
parser.add_argument("--seasons", nargs="+", type=int, default=[2023, 2024, 2025])
parser.add_argument("--through-week", type=int)
args = parser.parse_args()
SEASONS = sorted(set(args.seasons))
if args.through_week is not None and len(SEASONS) != 1:
    parser.error("--through-week requires one season.")

conn = psycopg.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    prepare_threshold=None,
)

REQUIRED = [
    "def_sacks",
    "def_interceptions",
    "def_fumbles_forced",
    "fumble_recovery_opp",
    "def_tds",
    "def_safeties",
    "special_teams_tds",
]

with conn.cursor() as cur:
    cur.execute("""
        ALTER TABLE team_weekly_stats
            ADD COLUMN IF NOT EXISTS fumble_recoveries numeric(10,2),
            ADD COLUMN IF NOT EXISTS forced_fumbles numeric(10,2),
            ADD COLUMN IF NOT EXISTS defensive_tds numeric(10,2),
            ADD COLUMN IF NOT EXISTS special_teams_tds numeric(10,2),
            ADD COLUMN IF NOT EXISTS safeties numeric(10,2),
            ADD COLUMN IF NOT EXISTS dst_fantasy_points numeric(10,2)
    """)

team_stats = nfl.load_team_stats(seasons=SEASONS)
if args.through_week is not None:
    games = completed_games(SEASONS[0], args.through_week)
    team_stats = regular_through(team_stats, args.through_week)
    require_team_coverage(games, team_stats.to_dicts(), "NFL team stats", "team")

missing = [c for c in REQUIRED if c not in team_stats.columns]
if missing:
    print("Missing expected columns:", missing)
    print("Available columns:", sorted(team_stats.columns))
    raise SystemExit(1)

with conn.cursor() as cur:
    cur.execute("SELECT id, abbreviation FROM teams")
    team_map = {abbr: tid for tid, abbr in cur.fetchall()}
if "LAR" in team_map:
    team_map["LA"] = team_map["LAR"]

updated = 0

for row in team_stats.filter(team_stats["season_type"] == "REG").iter_rows(named=True):
    team_id = team_map.get(row["team"])
    if team_id is None:
        continue

    with conn.cursor() as cur:
        cur.execute("""
            SELECT points_against
            FROM team_weekly_stats
            WHERE team_id = %s AND season = %s
              AND week = %s AND season_type = 1
        """, (team_id, row["season"], row["week"]))
        found = cur.fetchone()

        if found is None:
            continue

        sacks = row["def_sacks"] or 0
        ints = row["def_interceptions"] or 0
        fum_rec = row["fumble_recovery_opp"] or 0
        forced_fumbles = row["def_fumbles_forced"] or 0
        # Team-level def_tds already includes fumble-return touchdowns; the
        # upstream team stats do not expose a separate recovery-TD split.
        safeties = row["def_safeties"] or 0
        def_tds = row["def_tds"] or 0
        st_tds = row["special_teams_tds"] or 0

        points = dst_fantasy_points(
            sacks=sacks,
            interceptions=ints,
            fumble_recoveries=fum_rec,
            forced_fumbles=forced_fumbles,
            safeties=safeties,
            touchdowns=def_tds + st_tds,
            points_allowed=found[0],
        )

        cur.execute("""
            UPDATE team_weekly_stats
            SET fumble_recoveries = %s,
                forced_fumbles = %s,
                defensive_tds = %s,
                special_teams_tds = %s,
                safeties = %s,
                dst_fantasy_points = %s,
                updated_at = NOW()
            WHERE team_id = %s AND season = %s
              AND week = %s AND season_type = 1
        """, (fum_rec, forced_fumbles, def_tds, st_tds, safeties, points,
              team_id, row["season"], row["week"]))
        updated += 1

if args.through_week is not None and updated != 2 * len(games):
    raise ValueError(f"Expected {2 * len(games)} D/ST team-week rows; updated {updated}.")
conn.commit()
conn.close()
print(f"Updated {updated} team-week rows with D/ST stats.")
