import os

import nflreadpy as nfl
import psycopg
from dotenv import load_dotenv


load_dotenv()

SEASON = 2026
FANTASY_POSITIONS = {"QB", "RB", "WR", "TE"}


print(f"Loading {SEASON} player stats...")

stats = nfl.load_player_stats(seasons=[SEASON])

print(f"Loaded {stats.height} total stat rows.")


print("Loading nflverse player ID mappings...")

ids = nfl.load_ff_playerids()


print("Connecting to database...")

conn = psycopg.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
)


with conn.cursor() as cur:
    cur.execute("""
        SELECT id, sleeper_id, full_name
        FROM players
    """)

    db_players = cur.fetchall()


gsis_to_sleeper = {}

for row in ids.select(
    ["gsis_id", "sleeper_id"]
).to_dicts():

    gsis_id = row["gsis_id"]
    sleeper_id = row["sleeper_id"]

    if gsis_id is not None and sleeper_id is not None:
        gsis_to_sleeper[str(gsis_id)] = str(sleeper_id)


sleeper_to_player = {}

for player_id, sleeper_id, full_name in db_players:

    sleeper_to_player[str(sleeper_id)] = {
        "id": player_id,
        "name": full_name,
    }


imported = 0
no_sleeper_mapping = 0
not_in_database = 0

print()
print("Importing fantasy-relevant weekly stats...")


with conn.cursor() as cur:

    for stat in stats.to_dicts():

        position = stat["position"]

        if position not in FANTASY_POSITIONS:
            continue

        gsis_id = stat["player_id"]

        sleeper_id = gsis_to_sleeper.get(str(gsis_id))

        if sleeper_id is None:
            print(
                f"SKIPPED: {stat['player_display_name']} "
                f"({position}) - no Sleeper ID mapping"
            )

            no_sleeper_mapping += 1
            continue

        player = sleeper_to_player.get(sleeper_id)

        if player is None:
            print(
                f"SKIPPED: {stat['player_display_name']} "
                f"({position}) - not in players table"
            )

            not_in_database += 1
            continue

        player_id = player["id"]

        fumbles = stat.get("fumbles_total")
        fumbles_lost = stat.get("fumbles_lost_total")

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


conn.commit()
conn.close()

print()
print("========== PLAYER STATS IMPORT ==========")
print(f"Inserted/updated: {imported}")
print(f"No Sleeper ID mapping: {no_sleeper_mapping}")
print(f"Not in players table: {not_in_database}")
print("=========================================")