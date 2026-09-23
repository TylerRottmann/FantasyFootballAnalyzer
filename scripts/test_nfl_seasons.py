import nflreadpy as nfl

SEASONS = [2023, 2024, 2025]

print("Loading schedules...")

schedules = nfl.load_schedules(seasons=SEASONS)

schedules = schedules.filter(
    (schedules["game_type"] == "REG") &
    (schedules["week"] >= 1)
)

print(f"Total games loaded: {len(schedules)}")
print()

# Show the first few games
for game in schedules.head(10).iter_rows(named=True):
    print(
        f"Season: {game['season']} | "
        f"Week: {game['week']} | "
        f"{game['away_team']} @ {game['home_team']}"
    )

print()
print("Seasons found:")

for season in SEASONS:
    count = len(
        schedules.filter(schedules["season"] == season)
    )

    print(f"{season}: {count} games")