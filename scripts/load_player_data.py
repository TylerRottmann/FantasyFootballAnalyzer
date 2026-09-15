import os
import json
from urllib.request import urlopen

import psycopg
from dotenv import load_dotenv


load_dotenv()

SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"

OFFENSIVE_POSITIONS = {"QB", "RB", "WR", "TE"}


conn = psycopg.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
)


print("Downloading players from Sleeper...")

with urlopen(SLEEPER_PLAYERS_URL) as response:
    players = json.load(response)

print(f"Downloaded {len(players)} player records from Sleeper.")


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

print(f"Loaded {len(team_map)} NFL teams from database.")


imported = 0
skipped = 0
missing_team = 0


with conn.cursor() as cur:

    for sleeper_id, player in players.items():

        if not player.get("active"):
            skipped += 1
            continue

        position = player.get("position")

        if position not in OFFENSIVE_POSITIONS:
            skipped += 1
            continue

        team_abbreviation = player.get("team")

        if not team_abbreviation:
            skipped += 1
            continue

        team_id = team_map.get(team_abbreviation)

        if team_id is None:
            print(
                f"WARNING: Team {team_abbreviation} not found "
                f"for {player.get('full_name')}"
            )
            missing_team += 1
            continue

        # Sleeper player headshot
        headshot_url = (
            f"https://sleepercdn.com/content/nfl/players/"
            f"{sleeper_id}.jpg"
        )

        cur.execute("""
            INSERT INTO players (
                sleeper_id,
                first_name,
                last_name,
                full_name,
                position,
                age,
                team_id,
                headshot_url,
                status,
                injury_status,
                years_exp,
                jersey_number,
                height,
                weight,
                college
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )

            ON CONFLICT (sleeper_id)
            DO UPDATE SET

                first_name =
                    COALESCE(EXCLUDED.first_name, players.first_name),

                last_name =
                    COALESCE(EXCLUDED.last_name, players.last_name),

                full_name =
                    COALESCE(EXCLUDED.full_name, players.full_name),

                position =
                    COALESCE(EXCLUDED.position, players.position),

                age =
                    COALESCE(EXCLUDED.age, players.age),

                team_id =
                    COALESCE(EXCLUDED.team_id, players.team_id),

                headshot_url =
                    COALESCE(EXCLUDED.headshot_url, players.headshot_url),

                status =
                    COALESCE(EXCLUDED.status, players.status),

                injury_status =
                    COALESCE(
                        EXCLUDED.injury_status,
                        players.injury_status
                    ),

                years_exp =
                    COALESCE(EXCLUDED.years_exp, players.years_exp),

                jersey_number =
                    COALESCE(
                        EXCLUDED.jersey_number,
                        players.jersey_number
                    ),

                height =
                    COALESCE(EXCLUDED.height, players.height),

                weight =
                    COALESCE(EXCLUDED.weight, players.weight),

                college =
                    COALESCE(EXCLUDED.college, players.college),

                updated_at = NOW()
        """, (
            sleeper_id,
            player.get("first_name"),
            player.get("last_name"),
            player.get("full_name"),
            position,
            player.get("age"),
            team_id,
            headshot_url,
            player.get("status"),
            player.get("injury_status"),
            player.get("years_exp"),
            player.get("number"),
            player.get("height"),
            player.get("weight"),
            player.get("college"),
        ))

        imported += 1


conn.commit()
conn.close()

print()
print("========== PLAYER IMPORT ==========")
print(f"Inserted/updated: {imported}")
print(f"Skipped: {skipped}")
print(f"Missing teams: {missing_team}")
print("===================================")