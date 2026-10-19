# scripts/imports/load_dst_stats.py
#
# Adds the D/ST columns that load_team_data.py does not populate and
# computes dst_fantasy_points for every team-week.
#
# Run AFTER load_team_data.py:
#     python -m scripts.imports.load_dst_stats
#
# New team_weekly_stats columns:
#     fumble_recoveries, defensive_tds, special_teams_tds, safeties,
#     dst_fantasy_points
#
# NOTE: field names below come from nflreadpy.load_team_stats().
# If a name differs in your installed version, the script prints the
# available columns and stops so you can fix the mapping.

import os

import nflreadpy as nfl
import psycopg
from dotenv import load_dotenv

from scripts.algorithm.dst.scoring import dst_fantasy_points

load_dotenv()

SEASONS = [2023, 2024, 2025]

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
    "fumble_recovery_opp",
    "def_tds",
    "def_safeties",
    "special_teams_tds",
]

with conn.cursor() as cur:
    cur.execute("""
        ALTER TABLE team_weekly_stats
            ADD COLUMN IF NOT EXISTS fumble_recoveries numeric(10,2),
            ADD COLUMN IF NOT EXISTS defensive_tds numeric(10,2),
            ADD COLUMN IF NOT EXISTS special_teams_tds numeric(10,2),
            ADD COLUMN IF NOT EXISTS safeties numeric(10,2),
            ADD COLUMN IF NOT EXISTS dst_fantasy_points numeric(10,2)
    """)
conn.commit()

team_stats = nfl.load_team_stats(seasons=SEASONS)

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
        safeties = row["def_safeties"] or 0
        def_tds = row["def_tds"] or 0
        st_tds = row["special_teams_tds"] or 0

        points = dst_fantasy_points(
            sacks=sacks,
            interceptions=ints,
            fumble_recoveries=fum_rec,
            safeties=safeties,
            touchdowns=def_tds + st_tds,
            points_allowed=found[0],
        )

        cur.execute("""
            UPDATE team_weekly_stats
            SET fumble_recoveries = %s,
                defensive_tds = %s,
                special_teams_tds = %s,
                safeties = %s,
                dst_fantasy_points = %s,
                updated_at = NOW()
            WHERE team_id = %s AND season = %s
              AND week = %s AND season_type = 1
        """, (fum_rec, def_tds, st_tds, safeties, points,
              team_id, row["season"], row["week"]))
        updated += 1

conn.commit()
conn.close()
print(f"Updated {updated} team-week rows with D/ST stats.")
