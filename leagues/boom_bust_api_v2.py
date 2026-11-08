"""Authenticated, roster-authorized Boom/Bust v2 prediction API."""

import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from analyzer.models import Players
from leagues.models import BoomBustWeeklyPrediction, FantasyRosterPlayer, UserLeagueConnection


logger = logging.getLogger(__name__)

SUPPORTED_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})


@login_required
@require_GET
def boom_bust_prediction_v2(request, player_id):
    return _generate_authorized_boom_bust_v2(request, player_id)


def _generate_authorized_boom_bust_v2(request, player_id):
    """Return calibrated pregame probabilities for an authorized player."""

    active_league_id = request.session.get("active_league_id")

    active_connection_id = request.session.get("active_connection_id")

    connections = UserLeagueConnection.objects.filter(
        user=request.user,
        league_id=active_league_id,
    ).select_related("league")

    if active_connection_id:
        connection = connections.filter(pk=active_connection_id).first()
    else:
        connection = connections.first() if active_league_id else None

    if connection is None:
        return JsonResponse(
            {"error": "Select a connected league first."},
            status=404,
        )

    raw_week = request.GET.get("week", "1")

    try:
        week = int(raw_week)
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "Invalid week."},
            status=400,
        )

    if not 1 <= week <= 18:
        return JsonResponse(
            {"error": "Week must be between 1 and 18."},
            status=400,
        )

    league = connection.league

    rostered = FantasyRosterPlayer.objects.filter(
        roster__league=league,
        roster__owner_sleeper_id=connection.external_user_id,
        player_id=player_id,
    ).exists()

    if not rostered:
        return JsonResponse(
            {"error": "Player is not on your active roster."},
            status=404,
        )

    # analyzer.Players and leagues.Player map to the same
    # PostgreSQL 'players' table, verified in Step 305.
    player = Players.objects.filter(pk=player_id).first()

    if player is None:
        return JsonResponse(
            {"error": "Player not found."},
            status=404,
        )

    if player.position not in SUPPORTED_POSITIONS:
        return JsonResponse(
            {"error": "Boom/Bust v2 supports QB, RB, WR, and TE."},
            status=400,
        )

    prediction = (
        BoomBustWeeklyPrediction.objects
        .filter(
            player_id=player_id,
            season=league.season,
            week=week,
        )
        .order_by("-generated_at", "-id")
        .first()
    )

    if prediction is None:
        return JsonResponse(
            {"error": "Weekly Boom/Bust prediction not yet available."},
            status=404,
        )

    return JsonResponse(prediction.prediction_data)
