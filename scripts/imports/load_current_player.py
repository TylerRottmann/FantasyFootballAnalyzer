import os

import nflreadpy as nfl
import psycopg
from dotenv import load_dotenv


load_dotenv()


SEASON = 2026


# ============================================================
# LOAD CURRENT PLAYER STATS
# ============================================================

print(f"Loading {SEASON} player stats...")

stats = nfl.load_player_stats(
    seasons=SEASON,
    summary_level="week",
)

print(f"Loaded {stats.height} total stat rows.")


# ============================================================
# LOAD WEEKLY ROSTERS
# ============================================================

print(f"Loading {SEASON} weekly rosters...")

rosters = nfl.load_rosters_weekly(
    seasons=SEASON,
)

print(f"Loaded {rosters.height} roster rows.")


# ============================================================
# DATABASE
# ============================================================

print("Connecting to database...")

conn = psycopg.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
)


# ============================================================
# LOAD DATABASE PLAYERS
# ============================================================

with conn.cursor() as cur:

    cur.execute("""
        SELECT
            id,
            sleeper_id,
            full_name
        FROM players
    """)

    db_players = cur.fetchall()


sleeper_to_player = {}

for player_id, sleeper_id, full_name in db_players:

    if sleeper_id is None:
        continue

    sleeper_to_player[str(sleeper_id)] = {
        "id": player_id,
        "name": full_name,
    }


print(
    f"Loaded {len(sleeper_to_player)} players "
    f"from database."
)


# ============================================================
# BUILD GSIS -> SLEEPER MAPPING
# ============================================================

print("Building GSIS -> Sleeper player mapping...")

gsis_to_sleeper = {}


for row in rosters.select(
    [
        "gsis_id",
        "sleeper_id",
    ]
).to_dicts():

    gsis_id = row.get("gsis_id")
    sleeper_id = row.get("sleeper_id")

    if gsis_id is None:
        continue

    if sleeper_id is None:
        continue

    gsis_to_sleeper[str(gsis_id)] = str(sleeper_id)


print(
    f"Built mappings for "
    f"{len(gsis_to_sleeper)} players."
)


# ============================================================
# IMPORT
# ============================================================

imported = 0
no_sleeper_mapping = 0
not_in_database = 0


print()
print("Importing ALL 2026 weekly player stats...")
print()


with conn.cursor() as cur:

    for stat in stats.to_dicts():

        position = stat.get("position")

        gsis_id = stat.get("player_id")


        # ----------------------------------------------------
        # Find Sleeper ID
        # ----------------------------------------------------

        sleeper_id = gsis_to_sleeper.get(
            str(gsis_id)
        )


        if sleeper_id is None:

            print(
                f"SKIPPED: "
                f"{stat.get('player_display_name')} "
                f"({position}) - "
                f"no Sleeper ID mapping"
            )

            no_sleeper_mapping += 1
            continue


        # ----------------------------------------------------
        # Find player in our database
        # ----------------------------------------------------

        player = sleeper_to_player.get(
            sleeper_id
        )


        if player is None:

            print(
                f"SKIPPED: "
                f"{stat.get('player_display_name')} "
                f"({position}) - "
                f"not in players table"
            )

            not_in_database += 1
            continue


        player_id = player["id"]


        # ----------------------------------------------------
        # Fumbles
        # ----------------------------------------------------

        fumbles = stat.get(
            "fumbles_total"
        )

        fumbles_lost = stat.get(
            "fumbles_lost_total"
        )


        # ----------------------------------------------------
        # Insert / update
        # ----------------------------------------------------

        cur.execute("""
            INSERT INTO player_weekly_stats (
                player_id,
                nflverse_player_id,
                season,
                week,
                season_type,
                game_id,
                opponent_team,

                completions,
                attempts,
                passing_yards,
                passing_tds,
                passing_interceptions,

                carries,
                rushing_yards,
                rushing_tds,

                targets,
                receptions,
                receiving_yards,
                receiving_tds,

                fumbles,
                fumbles_lost,

                fantasy_points,
                fantasy_points_ppr
            )

            VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s
            )

            ON CONFLICT (
                player_id,
                season,
                week,
                season_type
            )

            DO UPDATE SET

                nflverse_player_id =
                    COALESCE(
                        EXCLUDED.nflverse_player_id,
                        player_weekly_stats.nflverse_player_id
                    ),

                game_id =
                    COALESCE(
                        EXCLUDED.game_id,
                        player_weekly_stats.game_id
                    ),

                opponent_team =
                    COALESCE(
                        EXCLUDED.opponent_team,
                        player_weekly_stats.opponent_team
                    ),

                completions =
                    COALESCE(
                        EXCLUDED.completions,
                        player_weekly_stats.completions
                    ),

                attempts =
                    COALESCE(
                        EXCLUDED.attempts,
                        player_weekly_stats.attempts
                    ),

                passing_yards =
                    COALESCE(
                        EXCLUDED.passing_yards,
                        player_weekly_stats.passing_yards
                    ),

                passing_tds =
                    COALESCE(
                        EXCLUDED.passing_tds,
                        player_weekly_stats.passing_tds
                    ),

                passing_interceptions =
                    COALESCE(
                        EXCLUDED.passing_interceptions,
                        player_weekly_stats.passing_interceptions
                    ),

                carries =
                    COALESCE(
                        EXCLUDED.carries,
                        player_weekly_stats.carries
                    ),

                rushing_yards =
                    COALESCE(
                        EXCLUDED.rushing_yards,
                        player_weekly_stats.rushing_yards
                    ),

                rushing_tds =
                    COALESCE(
                        EXCLUDED.rushing_tds,
                        player_weekly_stats.rushing_tds
                    ),

                targets =
                    COALESCE(
                        EXCLUDED.targets,
                        player_weekly_stats.targets
                    ),

                receptions =
                    COALESCE(
                        EXCLUDED.receptions,
                        player_weekly_stats.receptions
                    ),

                receiving_yards =
                    COALESCE(
                        EXCLUDED.receiving_yards,
                        player_weekly_stats.receiving_yards
                    ),

                receiving_tds =
                    COALESCE(
                        EXCLUDED.receiving_tds,
                        player_weekly_stats.receiving_tds
                    ),

                fumbles =
                    COALESCE(
                        EXCLUDED.fumbles,
                        player_weekly_stats.fumbles
                    ),

                fumbles_lost =
                    COALESCE(
                        EXCLUDED.fumbles_lost,
                        player_weekly_stats.fumbles_lost
                    ),

                fantasy_points =
                    COALESCE(
                        EXCLUDED.fantasy_points,
                        player_weekly_stats.fantasy_points
                    ),

                fantasy_points_ppr =
                    COALESCE(
                        EXCLUDED.fantasy_points_ppr,
                        player_weekly_stats.fantasy_points_ppr
                    ),

                updated_at = NOW()

        """, (
            player_id,
            str(gsis_id),

            stat.get("season"),
            stat.get("week"),
            stat.get("season_type"),
            stat.get("game_id"),
            stat.get("opponent_team"),

            stat.get("completions"),
            stat.get("attempts"),
            stat.get("passing_yards"),
            stat.get("passing_tds"),
            stat.get("passing_interceptions"),

            stat.get("carries"),
            stat.get("rushing_yards"),
            stat.get("rushing_tds"),

            stat.get("targets"),
            stat.get("receptions"),
            stat.get("receiving_yards"),
            stat.get("receiving_tds"),

            fumbles,
            fumbles_lost,

            stat.get("fantasy_points"),
            stat.get("fantasy_points_ppr"),
        ))


        imported += 1


# ============================================================
# COMMIT
# ============================================================

conn.commit()
conn.close()


# ============================================================
# SUMMARY
# ============================================================

print()
print("========== CURRENT PLAYER STATS IMPORT ==========")
print(f"Season:                    {SEASON}")
print(f"Inserted/updated:          {imported}")
print(f"No Sleeper ID mapping:     {no_sleeper_mapping}")
print(f"Not in players table:      {not_in_database}")
print("=================================================")