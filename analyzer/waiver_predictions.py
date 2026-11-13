"""Read saved model forecasts without generating predictions during page requests."""
from dataclasses import dataclass, field
from math import isfinite

from leagues.models import FantasyProjection, Player
from leagues.services.kicker_scoring import league_projection_values
from leagues.services.player_availability import (
    availability, forecast_season_absences, projection_context,
)


@dataclass(frozen=True)
class WaiverPrediction:
    this_week: float | None = None
    rest_of_season: float | None = None
    weekly: dict[int, float | None] = field(default_factory=dict, compare=False)


class WaiverForecasts(dict):
    def __init__(self):
        super().__init__()
        self.injured_player_ids = set()
        self.nonstarter_qb_ids = set()
        self.temporary_role_player_ids = set()


def load_waiver_predictions(player_ids, league, week):
    context = projection_context(league.season, week)
    forecasts = WaiverForecasts()
    forecasts.temporary_role_player_ids = {pid for pid, value in context['values'].items() if value.horizon == 'short'}
    players = Player.objects.only('position', 'team_id', 'status', 'injury_status', 'updated_at').in_bulk(player_ids)
    projections = FantasyProjection.objects.filter(
        player_id__in=players, season=league.season,
        week__gte=week, week__lte=18, model_version='v2_stat',
    )
    for saved in projections:
        saved.player = players[saved.player_id]
        value, status, _ = league_projection_values(saved, league, context=context)
        if status in ('qb_backup', 'qb_uncertain'):
            forecasts.nonstarter_qb_ids.add(saved.player_id)
        if (status in ('ml_model', 'projected', 'bye', 'inactive', 'injury_out', 'qb_backup')
                and value is not None and isfinite(value)):
            forecasts[(saved.player_id, saved.week)] = float(value)
    season_absences = forecast_season_absences(league.season, week, context)
    for player_id in set(player_ids) & season_absences:
        for remaining_week in range(week,19):
            forecasts[(player_id,remaining_week)] = 0.0
    if week == context['active_week']:
        for player in players.values():
            _, factor = availability(
                player,
                league.season,
                week,
                reports=context['reports'],
                duration_profiles=context['duration_profiles'],
                absence_start_weeks=context['absence_start_weeks'],
                active_week=context['active_week'],
                season_absences=season_absences,
            )
            if factor == 0:
                forecasts[(player.pk, week)] = 0.0
                if player.pk not in season_absences:
                    forecasts.injured_player_ids.add(player.pk)
    return forecasts


def predict_waiver_player(player, league, week, forecasts):
    """Only report a season total when all remaining weeks have valid forecasts."""
    remaining = [forecasts.get((player.pk, w)) for w in range(week, 19)]
    season_total_unavailable = any(player.pk in getattr(forecasts, group, ()) for group in (
        'injured_player_ids', 'nonstarter_qb_ids', 'temporary_role_player_ids',
    ))
    return WaiverPrediction(
        this_week=forecasts.get((player.pk, week)),
        rest_of_season=sum(remaining) if not season_total_unavailable and all(v is not None for v in remaining) else None,
        weekly={w: forecasts.get((player.pk, w)) for w in range(week, 19)},
    )
