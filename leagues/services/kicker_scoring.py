"""Rescore universal kicking stat projections for the selected league."""
from copy import copy
from leagues.services.scoring import (
    score_projection,
    score_stat_line,
)

def _league_score(projection, league):
    stats = getattr(projection, 'projected_stats', {})
    status = projection.status
    if status in ('bye', 'inactive', 'injury_out', 'qb_backup'):
        return projection.projected_fantasy_points, status
    points = score_projection({
        'position': projection.player.position,
        'projected_stats': stats,
        'projected_fantasy_points': projection.projected_fantasy_points,
    }, league)
    if points is None:
        if stats or projection.projected_fantasy_points is not None:
            status = 'unsupported_scoring' if stats else 'stats_not_found'
        return None, status
    return round(float(points), 2), status


def _league_kicker_projection(projection, league):
    result = copy(projection)
    result.projected_fantasy_points, result.status = _league_score(projection, league)
    return result


def league_projection_values(projection, league, *, context=None):
    from .player_availability import adjusted_forecast
    points, status = _league_score(projection, league)
    return adjusted_forecast(
        projection.player, projection.season, projection.week, points, status,
        getattr(projection, 'projected_stats', None), rescore=True, context=context,
    )


def league_projection(projection, league, *, context=None):
    result = copy(projection)
    result.projected_fantasy_points, result.status, result.projected_stats = league_projection_values(
        projection, league, context=context,
    )
    return result


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
