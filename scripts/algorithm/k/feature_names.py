"""Ordered kicker inputs and stat targets shared by training and inference."""
BUCKETS = ('0_19', '20_29', '30_39', '40_49', '50_59', '60_')
TARGETS = [f'fg_made_{b}' for b in BUCKETS] + [
    f'fg_missed_{b}' for b in BUCKETS
] + ['pat_made', 'pat_missed', 'fg_blocked', 'pat_blocked', 'fg_made_distance', 'fg_made_yards_over_30']
PLAYER_STATS = ['fg_att', 'fg_made', 'fg_missed', 'pat_att', *TARGETS]
PLAYER_STATS = list(dict.fromkeys(PLAYER_STATS))
TEAM_STATS = ['points_for', 'total_yards', 'kicking_points_for', 'offensive_plays', 'offensive_dropbacks', 'red_zone_trips']
OPPONENT_STATS = ['points_against', 'total_yards_against', 'kicking_points_against']
WINDOWS = ('l1', 'l3', 'l8', 'season')
K_FEATURE_NAMES = ['games_played', 'is_home'] + [
    f'{stat}_{window}' for window in WINDOWS for stat in PLAYER_STATS
] + [f'{rate}_{window}' for window in WINDOWS for rate in ('fg_rate', 'pat_rate')] + [
    f'{prefix}_{stat}_{window}' for window in ('l3', 'season')
    for prefix, stats in (('team', TEAM_STATS), ('opponent', OPPONENT_STATS))
    for stat in stats
]

K_FEATURE_NAMES += [
    f'team_{name}_{window}'
    for window in ('l3', 'season')
    for name in (
        'points_per_play', 'pass_yards_per_dropback',
        'rush_yards_per_play', 'kicking_points_per_red_zone_trip',
    )
]

SOURCE_STATS = [n for n in PLAYER_STATS if n != 'fg_made_yards_over_30']
