"""Rescore universal kicking stat projections for the selected league."""
from copy import copy
from leagues.services.scoring import (
    score_projection,
    score_stat_line,
)

def _league_kicker_projection(projection, league):
    result = copy(projection)
    stats = getattr(projection, 'projected_stats', {})
    if projection.status in ('bye', 'inactive', 'injury_out', 'qb_backup'):
        return result
    prediction = {
        'position': projection.player.position,
        'projected_stats': stats,
        'projected_fantasy_points': projection.projected_fantasy_points,
    }
    points = score_projection(prediction, league)
    if points is None:
        result.projected_fantasy_points = None
        if stats or projection.projected_fantasy_points is not None:
            result.status = 'unsupported_scoring' if stats else 'stats_not_found'
    else:
        result.projected_fantasy_points = round(float(points), 2)
    return result


def league_projection(projection, league, *, context=None):
    from .player_availability import apply_availability
    result = _league_kicker_projection(projection, league)
    return apply_availability(result, rescore=True, context=context)


def league_defense_projection(projection, league):
    """Rescore a D/ST stat-line projection for one league."""
    result = copy(projection)
    if projection.status == 'bye':
        return result
    stats = getattr(projection, 'projected_stats', {})
    if not stats:
        result.projected_fantasy_points = None
        result.status = 'stats_not_found'
        return result
    try:
        result.projected_fantasy_points = round(
            score_stat_line(stats, league.scoring_settings, 'DEF'), 2
        )
    except (TypeError, ValueError):
        result.projected_fantasy_points = None
        result.status = 'unsupported_scoring'
    return result
