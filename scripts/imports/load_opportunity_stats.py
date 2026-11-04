"""Import weekly workload and scoring opportunity data from nflverse.

The model feature builders can consume this table after it is populated. This
script intentionally keeps the source columns separate from player_weekly_stats
so source refreshes cannot overwrite the canonical fantasy stat lines.

Examples:
    python -m scripts.imports.load_opportunity_stats --seasons 2023 2024 2025 2026
"""
import argparse
import os
from collections import defaultdict

import nflreadpy as nfl
import psycopg
import polars as pl
from dotenv import load_dotenv


load_dotenv()


def _number(value):
    return float(value) if value is not None else 0.0


def _truth(value):
    return value is True or value == 1


def _rows(frame):
    return frame.to_dicts()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", nargs="+", type=int, default=[2023, 2024, 2025, 2026])
    args = parser.parse_args()

    print(f"Loading play-by-play and snap counts for {args.seasons}...")
    pbp = _rows(nfl.load_pbp(seasons=args.seasons).filter(pl.col("season_type") == "REG"))
    snaps = _rows(nfl.load_snap_counts(seasons=args.seasons).filter(pl.col("game_type") == "REG"))
    ids = _rows(nfl.load_ff_playerids())

    conn = psycopg.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS player_weekly_opportunity_stats (
                    player_id bigint NOT NULL REFERENCES players(id),
                    season integer NOT NULL,
                    week integer NOT NULL,
                    offense_snaps integer,
                    offense_snap_share double precision,
                    qb_dropbacks integer,
                    pressured_dropbacks integer,
                    qb_scrambles integer,
                    receiving_air_yards double precision,
                    red_zone_targets integer,
                    red_zone_rushes integer,
                    goal_line_carries integer,
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (player_id, season, week)
                );
                CREATE TABLE IF NOT EXISTS team_weekly_opportunity_stats (
                    team_id bigint NOT NULL REFERENCES teams(id),
                    season integer NOT NULL,
                    week integer NOT NULL,
                    offensive_plays integer,
                    offensive_dropbacks integer,
                    red_zone_trips integer,
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (team_id, season, week)
                );
            """)
            cur.execute("SELECT id, sleeper_id FROM players")
            players = {str(sleeper_id): player_id for player_id, sleeper_id in cur.fetchall()}
            cur.execute("SELECT id, abbreviation FROM teams")
            teams = {abbr: team_id for team_id, abbr in cur.fetchall()}

        gsis_to_sleeper = {}
        pfr_to_sleeper = {}
        for row in ids:
            sleeper = row.get("sleeper_id")
            if sleeper is None:
                continue
            if row.get("gsis_id"):
                gsis_to_sleeper[str(row["gsis_id"])] = str(sleeper)
            if row.get("pfr_id"):
                pfr_to_sleeper[str(row["pfr_id"])] = str(sleeper)

        player_rows = defaultdict(lambda: defaultdict(float))
        team_rows = defaultdict(lambda: {"offensive_plays": 0, "offensive_dropbacks": 0, "_red_zone_drives": set()})
        for play in pbp:
            season, week = play.get("season"), play.get("week")
            team = play.get("posteam")
            if season not in args.seasons or week is None:
                continue
            valid = not _truth(play.get("play_deleted")) and not _truth(play.get("aborted_play"))
            if not valid:
                continue
            key = (season, week)
            if team and team in teams and play.get("play_type") in ("pass", "run") and not _truth(play.get("qb_kneel")):
                t = team_rows[(teams[team], *key)]
                t["offensive_plays"] += 1
                t["offensive_dropbacks"] += int(_truth(play.get("qb_dropback")))
                if play.get("yardline_100") is not None and float(play["yardline_100"]) <= 20:
                    # Count a trip once per team drive, not once per red-zone play.
                    t["_red_zone_drives"].add((play.get("game_id"), play.get("drive")))

            passer = gsis_to_sleeper.get(str(play.get("passer_player_id")))
            rusher = gsis_to_sleeper.get(str(play.get("rusher_player_id")))
            receiver = gsis_to_sleeper.get(str(play.get("receiver_player_id")))
            if passer and play.get("qb_dropback") is not None:
                p = player_rows[(players.get(passer), *key)] if players.get(passer) else None
                if p is not None:
                    # Keep zero counts as zero, rather than NULL, so rate
                    # features remain defined for QBs without a scramble.
                    p.setdefault("qb_scrambles", 0)
                    if _truth(play.get("qb_dropback")):
                        p["qb_dropbacks"] += 1
                        # qb_hit is a consistent PBP proxy; it misses pressures
                        # without contact. A PFR pressure source can replace it later.
                        p["pressured_dropbacks"] += int(_truth(play.get("qb_hit")))
            if _truth(play.get("qb_scramble")):
                # nflverse identifies the QB as the rusher on scramble plays;
                # passer_player_id can be blank on those records.
                scramble_qb = rusher or passer
                scramble_player_id = players.get(scramble_qb) if scramble_qb else None
                if scramble_player_id is not None:
                    player_rows[(scramble_player_id, *key)]["qb_scrambles"] += 1
            if rusher and players.get(rusher) and play.get("play_type") == "run":
                p = player_rows[(players[rusher], *key)]
                if play.get("yardline_100") is not None and float(play["yardline_100"]) <= 20:
                    p["red_zone_rushes"] += 1
                if play.get("yardline_100") is not None and float(play["yardline_100"]) <= 5:
                    p["goal_line_carries"] += 1
            if receiver and players.get(receiver) and play.get("pass_attempt") is not None and _truth(play.get("pass_attempt")):
                p = player_rows[(players[receiver], *key)]
                if play.get("air_yards") is not None:
                    p["receiving_air_yards"] += float(play["air_yards"])
                if play.get("yardline_100") is not None and float(play["yardline_100"]) <= 20:
                    p["red_zone_targets"] += 1

        for row in snaps:
            sleeper = pfr_to_sleeper.get(str(row.get("pfr_player_id")))
            player_id = players.get(sleeper) if sleeper else None
            season, week = row.get("season"), row.get("week")
            if player_id is None or season not in args.seasons or week is None:
                continue
            key = (player_id, season, week)
            player_rows[key]["offense_snaps"] = int(_number(row.get("offense_snaps")))
            player_rows[key]["offense_snap_share"] = _number(row.get("offense_pct"))

        # Finalize drive-set counts and convert the feature rows to SQL tuples.
        team_values = []
        for key, values in team_rows.items():
            values["red_zone_trips"] = len(values.pop("_red_zone_drives", set()))
            team_values.append((*key, int(values["offensive_plays"]), int(values["offensive_dropbacks"]), int(values["red_zone_trips"])))
        player_values = []
        fields = ("offense_snaps", "offense_snap_share", "qb_dropbacks", "pressured_dropbacks", "qb_scrambles", "receiving_air_yards", "red_zone_targets", "red_zone_rushes", "goal_line_carries")
        for (player_id, season, week), values in player_rows.items():
            if player_id is None:
                continue
            player_values.append((
                player_id, season, week,
                *(values.get(field, 0 if field == "qb_scrambles" else None) for field in fields),
            ))

        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO player_weekly_opportunity_stats
                    (player_id, season, week, offense_snaps, offense_snap_share, qb_dropbacks,
                     pressured_dropbacks, qb_scrambles, receiving_air_yards, red_zone_targets,
                     red_zone_rushes, goal_line_carries)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (player_id, season, week) DO UPDATE SET
                    offense_snaps=EXCLUDED.offense_snaps,
                    offense_snap_share=EXCLUDED.offense_snap_share,
                    qb_dropbacks=EXCLUDED.qb_dropbacks,
                    pressured_dropbacks=EXCLUDED.pressured_dropbacks,
                    qb_scrambles=EXCLUDED.qb_scrambles,
                    receiving_air_yards=EXCLUDED.receiving_air_yards,
                    red_zone_targets=EXCLUDED.red_zone_targets,
                    red_zone_rushes=EXCLUDED.red_zone_rushes,
                    goal_line_carries=EXCLUDED.goal_line_carries,
                    updated_at=now()
            """, player_values)
            cur.executemany("""
                INSERT INTO team_weekly_opportunity_stats
                    (team_id, season, week, offensive_plays, offensive_dropbacks, red_zone_trips)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (team_id, season, week) DO UPDATE SET
                    offensive_plays=EXCLUDED.offensive_plays,
                    offensive_dropbacks=EXCLUDED.offensive_dropbacks,
                    red_zone_trips=EXCLUDED.red_zone_trips,
                    updated_at=now()
            """, team_values)
        conn.commit()
        print(f"Imported {len(player_values)} player-week and {len(team_values)} team-week opportunity rows.")
        print("Note: nflverse play-by-play does not provide route counts or pressure flags consistently; pressured_dropbacks may be zero/missing and route usage will need a separate source.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
