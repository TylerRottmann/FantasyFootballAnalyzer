"""Read saved model forecasts without generating predictions during page requests."""
from dataclasses import dataclass
from math import isfinite

from leagues.models import FantasyProjection
from leagues.services.kicker_scoring import league_projection


@dataclass(frozen=True)
class WaiverPrediction:
    this_week: float | None = None
    rest_of_season: float | None = None


class WaiverForecasts(dict):
    def __init__(self):
        super().__init__()
        self.injured_player_ids = set()
        self.nonstarter_qb_ids = set()
        self.temporary_role_player_ids = set()


def load_waiver_predictions(player_ids, league, week):
    from leagues.services.player_availability import projection_context
    context = projection_context(league.season, week)
    forecasts = WaiverForecasts()
    forecasts.temporary_role_player_ids = {pid for pid, value in context['values'].items() if value.horizon == 'short'}
    projections = FantasyProjection.objects.select_related('player').filter(
        player_id__in=player_ids, season=league.season,
        week__gte=week, week__lte=18, model_version='v1',
    )
    for saved in projections:
        projection = league_projection(saved, league, context=context)
        if projection.status in ('qb_backup', 'qb_uncertain'):
            forecasts.nonstarter_qb_ids.add(projection.player_id)
        value = projection.projected_fantasy_points
        if (projection.status in ('ml_model', 'projected', 'bye', 'inactive', 'injury_out', 'qb_backup')
                and value is not None and isfinite(value)):
            forecasts[(projection.player_id, projection.week)] = float(value)
    from analyzer.injury_outlooks import season_ending_player_ids
    season_absences = season_ending_player_ids(league.season, week)
    for player_id in set(player_ids) & season_absences:
        for remaining_week in range(week,19):
            forecasts[(player_id,remaining_week)] = 0.0
    from leagues.services.player_availability import availability, live_week
    if live_week(league.season, week):
        from leagues.models import Player
        for player in Player.objects.filter(pk__in=player_ids):
            _, factor = availability(player, league.season, week, reports=context['reports'])
            if factor == 0:
                forecasts[(player.pk, week)] = 0.0
                if player.pk not in season_absences:
                    forecasts.injured_player_ids.add(player.pk)
    return forecasts


def predict_waiver_player(player, league, week, forecasts):
    """Only report a season total when all remaining weeks have valid forecasts."""
    remaining = [forecasts.get((player.pk, w)) for w in range(week, 19)]
    return WaiverPrediction(
        this_week=forecasts.get((player.pk, week)),
        rest_of_season=sum(remaining) if all(v is not None for v in remaining) and player.pk not in (getattr(forecasts, 'injured_player_ids', set()) | getattr(forecasts, 'nonstarter_qb_ids', set()) | getattr(forecasts, 'temporary_role_player_ids', set())) else None,
    )
