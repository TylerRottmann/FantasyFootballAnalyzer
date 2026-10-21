import csv
import os
from datetime import datetime
from io import StringIO

import django
import requests


os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "FantasyFootballAnalyzer.settings",
)

django.setup()

from analyzer.models import NFLGame, Teams


NFL_SCHEDULE_URL = (
    "https://github.com/nflverse/nfldata/"
    "raw/refs/heads/master/data/games.csv"
)


def import_nfl_schedule(season=None, *, missing_only=False):
    print("Downloading NFL schedule...")

    response = requests.get(
        NFL_SCHEDULE_URL,
        timeout=30,
    )
    response.raise_for_status()

    reader = csv.DictReader(
        StringIO(response.text)
    )

    teams = {
        team.abbreviation: team
        for team in Teams.objects.all()
    }

    # nflverse uses LA for the Rams; the teams table stores LAR.
    team_aliases = {"LA": "LAR"}
    existing_keys = set()
    if missing_only:
        existing = NFLGame.objects.filter(season=season) if season is not None else NFLGame.objects.all()
        existing_keys = set(existing.values_list("season", "week", "away_team_id", "home_team_id"))

    imported = 0
    skipped = 0

    for row in reader:
        row_season = int(row["season"])

        if season is not None and row_season != season:
            continue

        if row["game_type"] not in {"REG", "POST"}:
            skipped += 1
            continue

        away_team = teams.get(team_aliases.get(row["away_team"], row["away_team"]))
        home_team = teams.get(team_aliases.get(row["home_team"], row["home_team"]))

        if away_team is None or home_team is None:
            skipped += 1
            continue

        key = (row_season, int(row["week"]), away_team.id, home_team.id)
        if missing_only and key in existing_keys:
            continue

        game_date = datetime.strptime(
            row["gameday"],
            "%Y-%m-%d",
        ).date()

        game_time = None

        if row.get("gametime"):
            game_time = datetime.strptime(
                row["gametime"],
                "%H:%M",
            ).time()

        save_game = NFLGame.objects.get_or_create if missing_only else NFLGame.objects.update_or_create
        _, created = save_game(
            season=row_season,
            week=int(row["week"]),
            away_team=away_team,
            home_team=home_team,
            defaults={
                "game_type": row["game_type"],
                "game_date": game_date,
                "game_time": game_time,
            },
        )

        if not missing_only or created:
            imported += 1
        existing_keys.add(key)

    print(f"Successfully imported {imported} NFL games.")

    if skipped:
        print(f"Skipped {skipped} rows.")


if __name__ == "__main__":
    import_nfl_schedule(season=2026)