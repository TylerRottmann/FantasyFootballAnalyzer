import os

import nflreadpy as nfl
import psycopg
from dotenv import load_dotenv


load_dotenv()


SEASON = 2026


# ============================================================
# LOAD CURRENT NFL ROSTERS
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
# IMPORT PLAYERS
# ============================================================

inserted = 0
updated = 0
skipped = 0


print()
print("Importing current NFL players...")
print()


with conn.cursor() as cur:

    # --------------------------------------------------------
    # Get the most recent roster record for each player
    # --------------------------------------------------------

    players = {}

    for row in rosters.to_dicts():

        gsis_id = row.get("gsis_id")
        sleeper_id = row.get("sleeper_id")

        if gsis_id is None:
            continue

        if sleeper_id is None:
            continue

        gsis_id = str(gsis_id)
        sleeper_id = str(sleeper_id)

        players[gsis_id] = row


    print(
        f"Found {len(players)} unique players "
        f"with Sleeper IDs."
    )


    # --------------------------------------------------------
    # Insert / update players
    # --------------------------------------------------------

    for gsis_id, player in players.items():

        sleeper_id = str(player["sleeper_id"])

        first_name = player.get("first_name")
        last_name = player.get("last_name")

        full_name = (
            player.get("full_name")
            or player.get("player_name")
            or player.get("display_name")
        )

        if not full_name:

            if first_name and last_name:
                full_name = f"{first_name} {last_name}"

            elif first_name:
                full_name = first_name

            elif last_name:
                full_name = last_name

            else:
                skipped += 1
                continue


        position = player.get("position")

        team_abbr = player.get("team")


        # ----------------------------------------------------
        # Player headshot
        # ----------------------------------------------------

        headshot_url = (
            f"https://sleepercdn.com/content/nfl/players/thumb/"
            f"{sleeper_id}.jpg"
        )

        # ----------------------------------------------------
        # Find team ID
        # ----------------------------------------------------

        team_id = None

        if team_abbr:

            cur.execute(
                """
                SELECT id
                FROM teams
                WHERE abbreviation = %s
                LIMIT 1
                """,
                (team_abbr,),
            )

            team = cur.fetchone()

            if team:
                team_id = team[0]


        # ----------------------------------------------------
        # Check whether player already exists
        # ----------------------------------------------------

        cur.execute(
            """
            SELECT id
            FROM players
            WHERE sleeper_id = %s
            LIMIT 1
            """,
            (sleeper_id,),
        )

        existing = cur.fetchone()


        # ----------------------------------------------------
        # Update existing player
        # ----------------------------------------------------

        if existing:

            cur.execute(
                """
                UPDATE players
                SET
                    first_name = %s,
                    last_name = %s,
                    full_name = %s,
                    position = %s,
                    team_id = %s,
                    headshot_url = %s,
                    status = %s,
                    injury_status = %s,
                    years_exp = %s,
                    jersey_number = %s,
                    height = %s,
                    weight = %s,
                    college = %s,
                    updated_at = NOW()
                WHERE sleeper_id = %s
                """,
                (
                    first_name,
                    last_name,
                    full_name,
                    position,
                    team_id,
                    headshot_url,
                    player.get("status"),
                    player.get("injury_status"),
                    player.get("years_exp"),
                    player.get("jersey_number"),
                    player.get("height"),
                    player.get("weight"),
                    player.get("college"),
                    sleeper_id,
                ),
            )

            updated += 1


        # ----------------------------------------------------
        # Insert new player
        # ----------------------------------------------------

        else:

            cur.execute(
                """
                INSERT INTO players (
                    sleeper_id,
                    first_name,
                    last_name,
                    full_name,
                    position,
                    team_id,
                    headshot_url,
                    status,
                    injury_status,
                    years_exp,
                    jersey_number,
                    height,
                    weight,
                    college,
                    created_at,
                    updated_at
                )

                VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    NOW(),
                    NOW()
                )
                """,
                (
                    sleeper_id,
                    first_name,
                    last_name,
                    full_name,
                    position,
                    team_id,
                    headshot_url,
                    player.get("status"),
                    player.get("injury_status"),
                    player.get("years_exp"),
                    player.get("jersey_number"),
                    player.get("height"),
                    player.get("weight"),
                    player.get("college"),
                ),
            )

            inserted += 1


# ============================================================
# COMMIT
# ============================================================

conn.commit()
conn.close()


# ============================================================
# SUMMARY
# ============================================================

print()
print("========== CURRENT PLAYER IMPORT ==========")
print(f"Season:              {SEASON}")
print(f"New players:         {inserted}")
print(f"Updated players:     {updated}")
print(f"Skipped:             {skipped}")
print("============================================")