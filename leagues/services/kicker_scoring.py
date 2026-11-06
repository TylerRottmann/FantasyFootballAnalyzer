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
