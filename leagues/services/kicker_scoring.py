"""Rescore universal kicking stat projections for the selected league."""
from copy import copy
from scripts.algorithm.k.scoring import score_kicking

def _league_kicker_projection(projection, league):
    if projection.player.position != 'K':
        return projection
    result = copy(projection)
    stats = getattr(projection, 'projected_stats', {})
    if projection.status in ('bye', 'inactive'):
        return result
    if not stats:
        result.projected_fantasy_points = None
        result.status = 'stats_not_found'
        return result
    try:
        result.projected_fantasy_points = round(score_kicking(stats, league.scoring_settings), 2)
    except (ValueError, TypeError):
        result.projected_fantasy_points = None
        result.status = 'unsupported_scoring'
    return result


def league_projection(projection, league, *, context=None):
    from .player_availability import apply_availability
    result = _league_kicker_projection(projection, league)
    return apply_availability(result, rescore=projection.player.position == 'K', context=context)
