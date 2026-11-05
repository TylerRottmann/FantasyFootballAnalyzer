WR_BASE_FEATURE_NAMES = [

    # ========================================================
    # WR PRODUCTION
    # ========================================================

    "fantasy_points_l1",
    "fantasy_points_l3",
    "fantasy_points_l5",
    "fantasy_points_l8",
    "fantasy_points_season",

    "targets_l1",
    "targets_l3",
    "targets_l5",
    "targets_l8",
    "targets_season",

    "receptions_l1",
    "receptions_l3",
    "receptions_l5",
    "receptions_l8",
    "receptions_season",

    "receiving_yards_l1",
    "receiving_yards_l3",
    "receiving_yards_l5",
    "receiving_yards_l8",
    "receiving_yards_season",

    "receiving_tds_l1",
    "receiving_tds_l3",
    "receiving_tds_l5",
    "receiving_tds_l8",
    "receiving_tds_season",

    # ========================================================
    # RECEIVING EFFICIENCY
    # ========================================================

    "catch_rate_l1",
    "catch_rate_l3",
    "catch_rate_l5",
    "catch_rate_l8",
    "catch_rate_season",

    "receiving_yards_per_target_l1",
    "receiving_yards_per_target_l3",
    "receiving_yards_per_target_l5",
    "receiving_yards_per_target_l8",
    "receiving_yards_per_target_season",

    "receiving_yards_per_reception_l1",
    "receiving_yards_per_reception_l3",
    "receiving_yards_per_reception_l5",
    "receiving_yards_per_reception_l8",
    "receiving_yards_per_reception_season",

    "receiving_td_rate_l1",
    "receiving_td_rate_l3",
    "receiving_td_rate_l5",
    "receiving_td_rate_l8",
    "receiving_td_rate_season",

    # ========================================================
    # WR CONSISTENCY / VOLATILITY
    # ========================================================

    "fantasy_points_stddev_l3",
    "fantasy_points_stddev_l5",
    "fantasy_points_stddev_l8",
    "fantasy_points_stddev_season",

    "targets_stddev_l3",
    "targets_stddev_l5",
    "targets_stddev_l8",
    "targets_stddev_season",

    "receptions_stddev_l3",
    "receptions_stddev_l5",
    "receptions_stddev_l8",
    "receptions_stddev_season",

    "receiving_yards_stddev_l3",
    "receiving_yards_stddev_l5",
    "receiving_yards_stddev_l8",
    "receiving_yards_stddev_season",

    # ========================================================
    # WR SAMPLE SIZE
    # ========================================================

    "games_played",
    "games_played_l8",

    # ========================================================
    # WR TRENDS
    # ========================================================

    "fantasy_points_trend_l3_l8",
    "targets_trend_l3_l8",
    "receiving_yards_trend_l3_l8",
    "receiving_yards_per_target_trend_l3_l8",
    "catch_rate_trend_l3_l8",

    # ========================================================
    # TEAM OFFENSE
    # ========================================================

    "team_points_l3",
    "team_points_l5",
    "team_points_l8",
    "team_points_season",

    "team_passing_yards_l3",
    "team_passing_yards_l5",
    "team_passing_yards_l8",
    "team_passing_yards_season",

    "team_rushing_yards_l3",
    "team_rushing_yards_l5",
    "team_rushing_yards_l8",
    "team_rushing_yards_season",

    "team_total_yards_l3",
    "team_total_yards_l5",
    "team_total_yards_l8",
    "team_total_yards_season",

    # ========================================================
    # TEAM TRENDS
    # ========================================================

    "team_points_trend_l3_l8",
    "team_passing_yards_trend_l3_l8",
    "team_total_yards_trend_l3_l8",

    # ========================================================
    # OPPONENT DEFENSE
    # ========================================================

    "opponent_wr_fantasy_allowed_l3",
    "opponent_passing_yards_allowed_l3",
    "opponent_points_allowed_l3",
    "opponent_total_yards_allowed_l3",
    "opponent_sacks_l3",
    "opponent_interceptions_l3",

    # ========================================================
    # GAME ENVIRONMENT
    # ========================================================

    "game_environment_l3",

    # ========================================================
    # HOME / AWAY
    # ========================================================

    "is_home",
]


# ============================================================
# TARGET SHARE
# ============================================================
# Share of the team's targets the receiver sees. Kept as its own list
# so the training script can compare the model with and without it.

TARGET_SHARE_FEATURE_NAMES = [
    "target_share_l1",
    "target_share_l3",
    "target_share_l5",
    "target_share_l8",
    "target_share_season",

    "target_share_stddev_l3",
    "target_share_stddev_l5",
    "target_share_stddev_l8",
    "target_share_stddev_season",

    "target_share_trend_l3_l8",
]


# The full feature list, in the exact order the model is trained on.
WR_FEATURE_NAMES = WR_BASE_FEATURE_NAMES + TARGET_SHARE_FEATURE_NAMES
WR_OPPORTUNITY_FEATURE_NAMES = [
    f"{stat}_{window}"
    for window in ("l1", "l3", "l5", "l8", "season")
    for stat in ("offense_snap_share", "receiving_air_yards", "average_target_depth", "air_yard_share", "targets_per_team_dropback", "red_zone_targets")
]
WR_OPPORTUNITY_FEATURE_NAMES += [
    f"team_{stat}_{window}"
    for window in ("l3", "l5", "l8", "season")
    for stat in ("pass_yards_per_dropback", "rush_yards_per_play")
] + [
    "opponent_turnovers_forced_l3", "opponent_sack_rate_l3",
    "opponent_pass_yards_allowed_per_dropback_l3",
    "opponent_rush_yards_allowed_per_play_l3",
]
WR_FEATURE_NAMES += WR_OPPORTUNITY_FEATURE_NAMES
WR_FEATURE_NAMES += [
    "prior_season_games", "prior_season_ppr_points", "prior_season_targets",
    "prior_season_carries", "prior_season_snap_share", "prior_season_is_player_history",
    "team_changed_since_prior_season",
    "position_prior_avg_ppr_points", "position_prior_avg_targets",
    "position_prior_avg_carries", "position_prior_avg_snap_share",
]
