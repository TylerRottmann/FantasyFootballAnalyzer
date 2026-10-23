"""Authenticated API endpoint for RB Boom/Bust predictions."""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from .models import FantasyRosterPlayer, Player, UserLeagueConnection
from scripts.algorithm.boom_bust.boom_bust_predict import predict_boom_bust


@login_required
@require_GET
def boom_bust_prediction(request, player_id):
    """Return Boom/Normal/Bust probabilities for a rostered RB."""
    active_league_id = request.session.get("active_league_id")

    connection = (
        UserLeagueConnection.objects
        .filter(user=request.user, league_id=active_league_id)
        .select_related("league")
        .first()
    ) if active_league_id else None

    if connection is None:
        return JsonResponse(
            {"error": "Select a connected league first."},
            status=404,
        )

    try:
        week = int(request.GET.get("week", 1))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid week."}, status=400)

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

    player = get_object_or_404(Player, pk=player_id)

    if player.position != "RB":
        return JsonResponse(
            {"error": "Boom/Bust predictions currently support RB only."},
            status=400,
        )

    try:
        result = predict_boom_bust(player, league.season, week)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse(result)
