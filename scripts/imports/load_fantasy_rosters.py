import os
import json
from urllib.request import urlopen

import psycopg
from dotenv import load_dotenv


load_dotenv()

LEAGUE_ID = "1394729610037460992"

LEAGUE_URL = (
    f"https://api.sleeper.app/v1/league/{LEAGUE_ID}"
)

ROSTERS_URL = (
    f"https://api.sleeper.app/v1/league/{LEAGUE_ID}/rosters"
)

USERS_URL = (
    f"https://api.sleeper.app/v1/league/{LEAGUE_ID}/users"
)


print("Loading Sleeper league...")

with urlopen(LEAGUE_URL) as response:
    league = json.load(response)

league_name = league.get("name")
league_season = league.get("season")

if league_season is not None:
    league_season = int(league_season)

print(f"League: {league_name}")
print(f"Season: {league_season}")



print("Loading Sleeper rosters...")

with urlopen(ROSTERS_URL) as response:
    rosters = json.load(response)

print(f"Loaded {len(rosters)} rosters.")


print("Loading Sleeper league users...")

with urlopen(USERS_URL) as response:
    users = json.load(response)

user_map = {
    str(user.get("user_id")): user.get("display_name")
    for user in users
}


print("Connecting to database...")

conn = psycopg.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
)


try:



    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, sleeper_id, full_name, position
            FROM players
        """)

        db_players = cur.fetchall()

    player_map = {}

    for player_id, sleeper_id, full_name, position in db_players:
        player_map[str(sleeper_id)] = {
            "id": player_id,
            "name": full_name,
            "position": position,
        }


    with conn.cursor() as cur:

        cur.execute("""
            INSERT INTO fantasy_leagues (
                sleeper_league_id,
                name,
                season
            )

            VALUES (%s, %s, %s)

            ON CONFLICT (sleeper_league_id)
            DO UPDATE SET
                name = EXCLUDED.name,
                season = EXCLUDED.season,
                updated_at = NOW()

            RETURNING id
        """, (
            LEAGUE_ID,
            league_name,
            league_season,
        ))

        fantasy_league_id = cur.fetchone()[0]



    imported_rosters = 0
    imported_players = 0
    ignored_slots = 0

    print()
    print("Importing fantasy rosters...")


    for roster in rosters:

        sleeper_roster_id = roster.get("roster_id")
        owner_id = roster.get("owner_id")

        owner_name = user_map.get(
            str(owner_id),
            "Unknown"
        )

        roster_players = roster.get("players") or []



        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO fantasy_rosters (
                    league_id,
                    sleeper_roster_id,
                    owner_sleeper_id,
                    owner_name
                )

                VALUES (%s, %s, %s, %s)

                ON CONFLICT (
                    league_id,
                    sleeper_roster_id
                )

                DO UPDATE SET
                    owner_sleeper_id =
                        EXCLUDED.owner_sleeper_id,

                    owner_name =
                        EXCLUDED.owner_name,

                    updated_at = NOW()

                RETURNING id
            """, (
                fantasy_league_id,
                sleeper_roster_id,
                owner_id,
                owner_name,
            ))

            fantasy_roster_id = cur.fetchone()[0]



        with conn.cursor() as cur:

            cur.execute("""
                DELETE FROM fantasy_roster_players
                WHERE roster_id = %s
            """, (
                fantasy_roster_id,
            ))


        roster_imported = 0
        roster_ignored = 0


        with conn.cursor() as cur:

            for sleeper_id in roster_players:

                player = player_map.get(
                    str(sleeper_id)
                )

                if player is None:
                    ignored_slots += 1
                    roster_ignored += 1
                    continue

                cur.execute("""
                    INSERT INTO fantasy_roster_players (
                        roster_id,
                        player_id
                    )

                    VALUES (%s, %s)

                    ON CONFLICT (
                        roster_id,
                        player_id
                    )
                    DO NOTHING
                """, (
                    fantasy_roster_id,
                    player["id"],
                ))

                imported_players += 1
                roster_imported += 1


        imported_rosters += 1

        print(
            f"Roster {sleeper_roster_id} "
            f"({owner_name}): "
            f"{roster_imported} players imported, "
            f"{roster_ignored} ignored"
        )


    conn.commit()


except Exception:

    conn.rollback()

    print()
    print("IMPORT FAILED - database changes rolled back.")

    raise


finally:

    conn.close()

print()
print("========== FANTASY ROSTER IMPORT ==========")
print(f"League: {league_name}")
print(f"Rosters imported/updated: {imported_rosters}")
print(f"Player ownerships imported: {imported_players}")
print(f"Non-QB/RB/WR/TE slots ignored: {ignored_slots}")
print("===========================================")