DST_ALL_FEATURE_NAMES = [
    # ========================================================
    # D/ST PRODUCTION
    # ========================================================

    "dst_fantasy_points_l1",
    "dst_fantasy_points_l3",
    "sacks_l3",
    "interceptions_l3",
    "fumble_recoveries_l3",
    "dst_tds_l3",
    "turnovers_l3",
    "dst_fantasy_points_l5",
    "sacks_l5",
    "interceptions_l5",
    "fumble_recoveries_l5",
    "dst_tds_l5",
    "turnovers_l5",
    "dst_fantasy_points_l8",
    "sacks_l8",
    "interceptions_l8",
    "fumble_recoveries_l8",
    "dst_tds_l8",
    "turnovers_l8",
    "dst_fantasy_points_season",
    "sacks_season",
    "interceptions_season",
    "fumble_recoveries_season",
    "dst_tds_season",
    "turnovers_season",
    "turnovers_trend_l3_l8",

    # ========================================================
    # POINTS / YARDS ALLOWED
    # ========================================================

    "points_against_l1",
    "points_against_l3",
    "total_yards_against_l3",
    "points_against_l5",
    "total_yards_against_l5",
    "points_against_l8",
    "total_yards_against_l8",
    "points_against_season",
    "total_yards_against_season",

    # ========================================================
    # CONSISTENCY / VOLATILITY
    # ========================================================

    "dst_fantasy_points_stddev_l3",
    "dst_fantasy_points_stddev_l5",
    "dst_fantasy_points_stddev_l8",
    "dst_fantasy_points_stddev_season",

    # ========================================================
    # TRENDS
    # ========================================================

    "dst_fantasy_points_trend_l3_l8",
    "sacks_trend_l3_l8",
    "points_against_trend_l3_l8",

    # ========================================================
    # OPPOSING OFFENSE
    # ========================================================

    "opponent_points_for_l3",
    "opponent_total_yards_l3",
    "opponent_passing_yards_l3",
    "opponent_sacks_taken_l3",
    "opponent_giveaways_l3",
    "opponent_points_for_l5",
    "opponent_total_yards_l5",
    "opponent_passing_yards_l5",
    "opponent_sacks_taken_l5",
    "opponent_giveaways_l5",
    "opponent_points_for_l8",
    "opponent_total_yards_l8",
    "opponent_passing_yards_l8",
    "opponent_sacks_taken_l8",
    "opponent_giveaways_l8",
    "opponent_points_for_season",
    "opponent_total_yards_season",
    "opponent_passing_yards_season",
    "opponent_sacks_taken_season",
    "opponent_giveaways_season",

    # ========================================================
    # OWN OFFENSE (GAME SCRIPT)
    # ========================================================

    "team_points_for_l3",
    "team_giveaways_l3",
    "team_points_for_l5",
    "team_giveaways_l5",
    "team_points_for_season",
    "team_giveaways_season",

    # ========================================================
    # SAMPLE SIZE / CONTEXT
    # ========================================================

    "is_home",
    "games_played",
    "games_played_l8",

]

# Full list is what the feature builder / predictor produce for every row.
# Kept under the old name too so existing imports keep working.
DST_FEATURE_NAMES = DST_ALL_FEATURE_NAMES

# Small, low-noise subset (season + l5 windows only). With ~1,500 training
# rows and a very noisy target, fewer inputs generalize better than all 71.
DST_SLIM_FEATURE_NAMES = [
    "dst_fantasy_points_season",
    "dst_fantasy_points_l5",
    "sacks_season",
    "sacks_l5",
    "turnovers_season",
    "turnovers_l5",
    "points_against_season",
    "points_against_l5",
    "total_yards_against_season",
    "opponent_points_for_season",
    "opponent_points_for_l5",
    "opponent_total_yards_season",
    "opponent_giveaways_season",
    "opponent_sacks_taken_season",
    "team_points_for_season",
    "is_home",
    "games_played",
]
