"""Convert projected kicking statistics using imported Sleeper league rules."""
import math
from scripts.algorithm.k.feature_names import BUCKETS, TARGETS

# A named reference for league-independent evaluation, not a league override.
REFERENCE_SCORING = {
    'fgm_0_19': 3, 'fgm_20_29': 3, 'fgm_30_39': 3,
    'fgm_40_49': 4, 'fgm_50p': 5, 'xpm': 1, 'fgmiss': -1, 'xpmiss': -1,
}
SUPPORTED = {
    'fgm', 'fgm_yds', 'fgm_yds_over_30', 'fgm_50p', 'fgmiss', 'xpm', 'xpmiss',
    *[f'{prefix}_{b}' for prefix in ('fgm', 'fgmiss') for b in BUCKETS[:-1]],
    'fgm_60p', 'fgmiss_60p', 'fgmiss_50p',
}

def score_kicking(stats, settings):
    """Add generic and distance bonuses; absent rules are zero, never defaults.

    Yahoo's nested stat modifiers and unknown kicking rules are rejected instead
    of presenting a reference score as an exact custom-league result.
    """
    if not isinstance(settings, dict) or 'yahoo' in settings or 'stat_modifiers' in settings:
        raise ValueError('Unsupported kicker scoring settings.')
    unknown = [key for key, value in settings.items()
               if key.startswith(('fg', 'xp')) and value and key not in SUPPORTED]
    if unknown:
        raise ValueError('Unsupported kicker scoring rules: ' + ', '.join(unknown))
    if not any(key in SUPPORTED for key in settings):
        raise ValueError('No kicker scoring rules were imported for this league.')
    if any(stats.get(name) is None or not math.isfinite(float(stats[name])) for name in TARGETS):
        raise ValueError('Incomplete kicking stat line.')
    def rule(name):
        value = float(settings.get(name, 0))
        if not math.isfinite(value):
            raise ValueError('Non-finite scoring weight.')
        return value
    made = sum(stats[f'fg_made_{b}'] for b in BUCKETS)
    missed = sum(stats[f'fg_missed_{b}'] for b in BUCKETS)
    points = made * rule('fgm') + missed * rule('fgmiss')
    points += stats['fg_made_distance'] * rule('fgm_yds')
    points += stats['fg_made_yards_over_30'] * rule('fgm_yds_over_30')
    points += stats['pat_made'] * rule('xpm')
    points += stats['pat_missed'] * rule('xpmiss')
    for bucket in BUCKETS:
        suffix = '60p' if bucket == '60_' else bucket
        points += stats[f'fg_made_{bucket}'] * rule(f'fgm_{suffix}')
        points += stats[f'fg_missed_{bucket}'] * rule(f'fgmiss_{suffix}')
    for prefix, stat in (('fgm', 'fg_made'), ('fgmiss', 'fg_missed')):
        points += sum(stats[f'{stat}_{b}'] for b in ('50_59', '60_')) * rule(f'{prefix}_50p')
    return float(points)
