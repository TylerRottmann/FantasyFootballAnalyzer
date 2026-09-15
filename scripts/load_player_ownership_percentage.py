import os
import json
from urllib.request import Request, urlopen

import psycopg
from dotenv import load_dotenv


load_dotenv()

SEASON = 2026

RESEARCH_URL = (
    f"https://api.sleeper.com/players/nfl/research/regular/{SEASON}"
)

print(f"Loading {SEASON} Sleeper ownership percentages...")

request = Request(
    RESEARCH_URL,
    headers={
        "User-Agent": "Mozilla/5.0"
    }
)

with urlopen(request, timeout=30) as response:
    research_data = json.load(response)

print(f"Loaded {len(research_data)} Sleeper research records.")


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
            SELECT id, sleeper_id, full_name
            FROM players
        """)

        players = cur.fetchall()


    print(f"Loaded {len(players)} players from database.")
    print()
    print("Updating ownership percentages...")


    updated = 0
    no_research_data = 0

    with conn.cursor() as cur:

        for player_id, sleeper_id, full_name in players:

            sleeper_id = str(sleeper_id)

            research = research_data.get(sleeper_id)

            if research is None:
                no_research_data += 1
                continue

            owned = research.get("owned")

            if owned is None:
                no_research_data += 1
                continue

            cur.execute("""
                UPDATE players
                SET
                    owned_percentage = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (
                owned,
                player_id,
            ))

            updated += 1


    conn.commit()


except Exception:

    conn.rollback()

    print()
    print("IMPORT FAILED - database changes rolled back.")

    raise


finally:

    conn.close()


print()
print("========== OWNERSHIP IMPORT ==========")
print(f"Players updated: {updated}")
print(f"No Sleeper ownership data: {no_research_data}")
print("======================================")