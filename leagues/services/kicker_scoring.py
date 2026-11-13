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
        from leagues.services.scoring_settings import normalize_scoring_settings
        settings = normalize_scoring_settings(league.scoring_settings)

        if settings.get('source') == 'espn':
            from leagues.services.espn_dst_scoring import score_espn_dst

            from leagues.services.espn_dst_yards import estimate_yards_allowed
            from scripts.algorithm.features.dst_features import build_dst_features

            features = build_dst_features(
                projection.team_id,
                projection.season,
                projection.week,
            )
            yards_estimate = estimate_yards_allowed(features)

            scored = score_espn_dst(
                stats,
                league.scoring_settings,
                yards_estimate=yards_estimate,
            )
            result.projected_fantasy_points = scored['supported_points']
            if not scored['complete']:
                result.status = 'partial_scoring'
                result.usable_partial_scoring = (
                    yards_estimate is not None
                    and set(scored['unsupported_stat_ids'])
                    <= {93, 97, 206, 209}
                )
            return result

        result.projected_fantasy_points = round(
            score_stat_line(stats, league.scoring_settings, 'DEF'), 2
        )
    except (TypeError, ValueError, KeyError):
        result.projected_fantasy_points = None
        result.status = 'unsupported_scoring'
    return result
