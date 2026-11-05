QB_FEATURE_NAMES = [
    # ========================================================
    # QB PRODUCTION
    # ========================================================

    "fantasy_points_l1",
    "fantasy_points_l3",
    "fantasy_points_l5",
    "fantasy_points_l8",
    "fantasy_points_season",

    "passing_attempts_l1",
    "passing_attempts_l3",
    "passing_attempts_l5",
    "passing_attempts_l8",
    "passing_attempts_season",

    "passing_yards_l1",
    "passing_yards_l3",
    "passing_yards_l5",
    "passing_yards_l8",
    "passing_yards_season",

    "passing_tds_l1",
    "passing_tds_l3",
    "passing_tds_l5",
    "passing_tds_l8",
    "passing_tds_season",

    "interceptions_l1",
    "interceptions_l3",
    "interceptions_l5",
    "interceptions_l8",
    "interceptions_season",

    "rushing_attempts_l1",
    "rushing_attempts_l3",
    "rushing_attempts_l5",
    "rushing_attempts_l8",
    "rushing_attempts_season",

    "rushing_yards_l1",
    "rushing_yards_l3",
    "rushing_yards_l5",
    "rushing_yards_l8",
    "rushing_yards_season",

    "rushing_tds_l1",
    "rushing_tds_l3",
    "rushing_tds_l5",
    "rushing_tds_l8",
    "rushing_tds_season",

    # ========================================================
    # PASSING EFFICIENCY
    # ========================================================

    "completion_rate_l1",
    "completion_rate_l3",
    "completion_rate_l5",
    "completion_rate_l8",
    "completion_rate_season",

    "passing_yards_per_attempt_l1",
    "passing_yards_per_attempt_l3",
    "passing_yards_per_attempt_l5",
    "passing_yards_per_attempt_l8",
    "passing_yards_per_attempt_season",

    "passing_td_rate_l1",
    "passing_td_rate_l3",
    "passing_td_rate_l5",
    "passing_td_rate_l8",
    "passing_td_rate_season",

    "interception_rate_l1",
    "interception_rate_l3",
    "interception_rate_l5",
    "interception_rate_l8",
    "interception_rate_season",

    # ========================================================
    # RUSHING EFFICIENCY
    # ========================================================

    "rushing_yards_per_attempt_l1",
    "rushing_yards_per_attempt_l3",
    "rushing_yards_per_attempt_l5",
    "rushing_yards_per_attempt_l8",
    "rushing_yards_per_attempt_season",

    "rushing_td_rate_l1",
    "rushing_td_rate_l3",
    "rushing_td_rate_l5",
    "rushing_td_rate_l8",
    "rushing_td_rate_season",

    # ========================================================
    # QB CONSISTENCY / VOLATILITY
    # ========================================================

    "fantasy_points_stddev_l3",
    "fantasy_points_stddev_l5",
    "fantasy_points_stddev_l8",
    "fantasy_points_stddev_season",

    "passing_yards_stddev_l3",
    "passing_yards_stddev_l5",
    "passing_yards_stddev_l8",
    "passing_yards_stddev_season",

    "passing_attempts_stddev_l3",
    "passing_attempts_stddev_l5",
    "passing_attempts_stddev_l8",
    "passing_attempts_stddev_season",

    "rushing_yards_stddev_l3",
    "rushing_yards_stddev_l5",
    "rushing_yards_stddev_l8",
    "rushing_yards_stddev_season",

    # ========================================================
    # QB SAMPLE SIZE
    # ========================================================

    "games_played",
    "games_played_l8",

    # ========================================================
    # QB TRENDS
    # ========================================================

    "fantasy_points_trend_l3_l8",
    "passing_yards_trend_l3_l8",
    "passing_attempts_trend_l3_l8",
    "passing_yards_per_attempt_trend_l3_l8",
    "completion_rate_trend_l3_l8",
    "rushing_yards_trend_l3_l8",

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

    "opponent_qb_fantasy_allowed_l3",
    "opponent_passing_yards_allowed_l3",
    "opponent_points_allowed_l3",
    "opponent_total_yards_allowed_l3",
    "opponent_rushing_yards_allowed_l3",
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

# Workload, pressure, and team play-volume data imported from nflverse.
_OPPORTUNITY_WINDOWS = ("l1", "l3", "l5", "l8", "season")
QB_FEATURE_NAMES += [
    f"{name}_{window}"
    for window in _OPPORTUNITY_WINDOWS
    for name in ("qb_dropbacks", "qb_hit_rate", "scramble_rate")
] + [
    f"team_{name}_{window}"
    for window in ("l3", "l5", "l8", "season")
    for name in ("offensive_plays", "offensive_dropbacks", "red_zone_trips")
]
QB_FEATURE_NAMES += [
    f"team_{name}_{window}"
    for window in ("l3", "l5", "l8", "season")
    for name in ("pass_yards_per_dropback", "rush_yards_per_play")
] + [
    "opponent_turnovers_forced_l3",
    "opponent_sack_rate_l3",
    "opponent_pass_yards_allowed_per_dropback_l3",
    "opponent_rush_yards_allowed_per_play_l3",
]
QB_FEATURE_NAMES += [
    "prior_season_games", "prior_season_ppr_points", "prior_season_targets",
    "prior_season_carries", "prior_season_snap_share", "prior_season_is_player_history",
    "team_changed_since_prior_season",
    "position_prior_avg_ppr_points", "position_prior_avg_targets",
    "position_prior_avg_carries", "position_prior_avg_snap_share",
]
