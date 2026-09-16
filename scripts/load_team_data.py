import os
import nflreadpy as nfl
import psycopg
from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------
# Database
# --------------------------------------------------

conn = psycopg.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
)

# --------------------------------------------------
# Load NFL data
# --------------------------------------------------

SEASON = 2026

team_stats = nfl.load_team_stats(seasons=[SEASON])
schedules = nfl.load_schedules(seasons=[SEASON])

# Only completed/available regular-season games
schedules = schedules.filter(
    (schedules["game_type"] == "REG") &
    (schedules["week"] >= 1)
)

# --------------------------------------------------
# Load our team IDs
# --------------------------------------------------

with conn.cursor() as cur:
    cur.execute("""
        SELECT id, external_id, abbreviation
        FROM teams
    """)

    team_rows = cur.fetchall()

team_map = {
    abbreviation: team_id
    for team_id, external_id, abbreviation in team_rows
}

if "LAR" in team_map:
    team_map["LA"] = team_map["LAR"]

print(f"Loaded {len(team_map)} teams from database.")

# --------------------------------------------------
# Insert weekly team data
# --------------------------------------------------

inserted = 0

for game in schedules.iter_rows(named=True):

    week = game["week"]

    away = game["away_team"]
    home = game["home_team"]

    # Skip games that haven't been played yet
    if game["away_score"] is None or game["home_score"] is None:
        continue

    away_score = game["away_score"]
    home_score = game["home_score"]

    game_date = game["gameday"]

    # Find each team's stats for this game
    away_stats = team_stats.filter(
        (team_stats["game_id"] == game["game_id"]) &
        (team_stats["team"] == away)
    )

    home_stats = team_stats.filter(
        (team_stats["game_id"] == game["game_id"]) &
        (team_stats["team"] == home)
    )

    if len(away_stats) == 0 or len(home_stats) == 0:
        print(f"Skipping {game['game_id']} - team stats unavailable")
        continue

    away_stats = away_stats.row(0, named=True)
    home_stats = home_stats.row(0, named=True)

    # --------------------------------------------------
    # Helper for inserting one team
    # --------------------------------------------------

    def insert_team(
        team,
        opponent,
        is_home,
        points_for,
        points_against,
        stats,
        opponent_stats
    ):
        team_id = team_map.get(team)
        opponent_id = team_map.get(opponent)

        if team_id is None:
            print(f"Unknown team: {team}")
            return

        passing_yards = stats["passing_yards"] or 0
        rushing_yards = stats["rushing_yards"] or 0

        opponent_passing_yards = opponent_stats["passing_yards"] or 0
        opponent_rushing_yards = opponent_stats["rushing_yards"] or 0

        total_yards = passing_yards + rushing_yards
        opponent_total_yards = (
            opponent_passing_yards +
            opponent_rushing_yards
        )

        sacks = stats["def_sacks"] or 0
        interceptions = stats["def_interceptions"] or 0
        fumbles_forced = stats["def_fumbles_forced"] or 0

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO team_weekly_stats (
                    team_id,
                    season,
                    week,
                    season_type,
                    opponent_team_id,
                    is_home,

                    points_for,
                    points_against,

                    total_yards,
                    passing_yards,
                    rushing_yards,

                    total_yards_against,
                    passing_yards_against,
                    rushing_yards_against,

                    interceptions,
                    sacks,
                    fumbles_forced,

                    game_date,

                    created_at,
                    updated_at
                )
                VALUES (
                    %s, %s, %s, 1, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s,
                    NOW(),
                    NOW()
                )
                ON CONFLICT (team_id, season, week, season_type)
                DO UPDATE SET
                    opponent_team_id = EXCLUDED.opponent_team_id,
                    is_home = EXCLUDED.is_home,

                    points_for = EXCLUDED.points_for,
                    points_against = EXCLUDED.points_against,

                    total_yards = EXCLUDED.total_yards,
                    passing_yards = EXCLUDED.passing_yards,
                    rushing_yards = EXCLUDED.rushing_yards,

                    total_yards_against = EXCLUDED.total_yards_against,
                    passing_yards_against = EXCLUDED.passing_yards_against,
                    rushing_yards_against = EXCLUDED.rushing_yards_against,

                    interceptions = EXCLUDED.interceptions,
                    sacks = EXCLUDED.sacks,
                    fumbles_forced = EXCLUDED.fumbles_forced,

                    game_date = EXCLUDED.game_date,
                    updated_at = NOW()
            """, (
                team_id,
                SEASON,
                week,
                opponent_id,
                is_home,

                points_for,
                points_against,

                total_yards,
                passing_yards,
                rushing_yards,

                opponent_total_yards,
                opponent_passing_yards,
                opponent_rushing_yards,

                interceptions,
                sacks,
                fumbles_forced,

                game_date,
            ))

    # Away team
    insert_team(
        away,
        home,
        False,
        away_score,
        home_score,
        away_stats,
        home_stats
    )

    # Home team
    insert_team(
        home,
        away,
        True,
        home_score,
        away_score,
        home_stats,
        away_stats
    )

    inserted += 2

    print(f"Loaded Week {week}: {away} @ {home}")
# --------------------------------------------------
# Load fantasy points allowed by position
# --------------------------------------------------

print()
print("Loading fantasy points allowed by position...")

player_stats = nfl.load_player_stats(seasons=[SEASON])

for week in sorted(player_stats["week"].unique().to_list()):

    week_players = player_stats.filter(
        (player_stats["week"] == week) &
        (player_stats["season_type"] == "REG")
    )

    # Group opposing player production by defense.
    #
    # A player's opponent_team is the defense that
    # allowed the player's fantasy points.
    for defense in week_players["opponent_team"].unique().to_list():

        defense_players = week_players.filter(
            week_players["opponent_team"] == defense
        )

        qb_points = defense_players.filter(
            defense_players["position_group"] == "QB"
        )["fantasy_points_ppr"].sum()

        rb_points = defense_players.filter(
            defense_players["position_group"] == "RB"
        )["fantasy_points_ppr"].sum()

        wr_points = defense_players.filter(
            defense_players["position_group"] == "WR"
        )["fantasy_points_ppr"].sum()

        te_points = defense_players.filter(
            defense_players["position_group"] == "TE"
        )["fantasy_points_ppr"].sum()

        team_id = team_map.get(defense)

        if team_id is None:
            print(f"Unknown defensive team: {defense}")
            continue

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE team_weekly_stats
                SET
                    qb_fantasy_points_allowed = %s,
                    rb_fantasy_points_allowed = %s,
                    wr_fantasy_points_allowed = %s,
                    te_fantasy_points_allowed = %s,
                    updated_at = NOW()
                WHERE team_id = %s
                  AND season = %s
                  AND week = %s
                  AND season_type = 1
            """, (
                qb_points or 0,
                rb_points or 0,
                wr_points or 0,
                te_points or 0,
                team_id,
                SEASON,
                week,
            ))

print("Fantasy matchup data loaded.")
conn.commit()
conn.close()

print()
print(f"Finished. Loaded/updated {inserted} team-week records.")