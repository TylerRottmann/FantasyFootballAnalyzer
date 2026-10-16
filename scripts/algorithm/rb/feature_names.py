"""Ordered pre-game features shared by RB training and inference."""

PLAYER_WINDOWS = ("l1", "l3", "l5", "l8", "season")
CONTEXT_WINDOWS = ("l3", "l5", "l8", "season")
PRODUCTION_STATS = (
    "fantasy_points", "carries", "rushing_yards", "rushing_tds",
    "targets", "receptions", "receiving_yards", "receiving_tds",
    "fumbles_lost", "touches", "opportunities",
)
RATE_STATS = (
    "rushing_yards_per_carry", "rushing_td_rate", "catch_rate",
    "receiving_yards_per_target", "receiving_td_rate",
    "carry_share", "target_share",
)
TREND_STATS = (
    "fantasy_points", "carries", "targets", "touches",
    "rushing_yards_per_carry", "carry_share", "target_share",
)
TEAM_STATS = ("points", "passing_yards", "rushing_yards", "total_yards")
DEFENSE_STATS = (
    "rb_fantasy_allowed", "rushing_yards_allowed", "passing_yards_allowed",
    "points_allowed", "total_yards_allowed",
)

RB_FEATURE_NAMES = [
    f"{stat}_{window}"
    for stat in PRODUCTION_STATS + RATE_STATS
    for window in PLAYER_WINDOWS
] + [
    f"{stat}_stddev_{window}"
    for stat in ("fantasy_points", "carries", "targets", "touches")
    for window in CONTEXT_WINDOWS
] + [
    "games_played", "games_played_l8", "is_home",
] + [
    f"{stat}_trend_l3_l8" for stat in TREND_STATS
] + [
    f"team_{stat}_{window}"
    for stat in TEAM_STATS for window in CONTEXT_WINDOWS
] + [
    f"opponent_{stat}_{window}"
    for stat in DEFENSE_STATS for window in CONTEXT_WINDOWS
] + ["game_environment_l3"]
