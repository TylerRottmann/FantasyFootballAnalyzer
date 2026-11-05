"""Authenticated, roster-authorized Boom/Bust v2 prediction API."""

import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from analyzer.models import Players
from leagues.models import FantasyRosterPlayer, UserLeagueConnection

from leagues.services.boom_bust_storage_v2 import save_boom_bust_prediction_v2

from scripts.algorithm.boom_bust.boom_bust_context_v2 import (
    GameContextUnavailable,
    PlayerOnBye,
)
from scripts.algorithm.boom_bust.boom_bust_kickoff_v2 import (
    GameAlreadyStarted,
)
from scripts.algorithm.boom_bust.boom_bust_predict_v2 import (
    PlayerUnavailableForPrediction,
    predict_boom_bust_v2,
)

logger = logging.getLogger(__name__)

SUPPORTED_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})


@login_required
@require_GET
def boom_bust_prediction_v2(request, player_id):
    return _generate_authorized_boom_bust_v2(request, player_id)


def _generate_authorized_boom_bust_v2(request, player_id):
    """Return calibrated pregame probabilities for an authorized player."""

    active_league_id = request.session.get("active_league_id")

    connection = (
        UserLeagueConnection.objects
        .filter(
            user=request.user,
            league_id=active_league_id,
        )
        .select_related("league")
        .first()
    ) if active_league_id else None

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

    try:
        result = predict_boom_bust_v2(
            player=player,
            season=league.season,
            week=week,
        )

    except PlayerUnavailableForPrediction as error:
        return JsonResponse(
            {"error": str(error)},
            status=409,
        )

    except GameAlreadyStarted:
        return JsonResponse(
            {"error": "Predictions close at scheduled kickoff."},
            status=409,
        )

    except PlayerOnBye:
        return JsonResponse(
            {"error": "Player is on a bye week."},
            status=409,
        )

    except GameContextUnavailable:
        return JsonResponse(
            {"error": "Verified pregame matchup unavailable."},
            status=422,
        )

    except ValueError:
        logger.exception(
            "Boom/Bust v2 prediction validation failed "
            "for player_id=%s season=%s week=%s",
            player_id,
            league.season,
            week,
        )
        return JsonResponse(
            {"error": "Unable to generate a valid prediction."},
            status=422,
        )

    except Exception:
        logger.exception(
            "Boom/Bust v2 unexpected failure "
            "for player_id=%s season=%s week=%s",
            player_id,
            league.season,
            week,
        )
        return JsonResponse(
            {"error": "Prediction service temporarily unavailable."},
            status=500,
        )

    return JsonResponse(result)



@login_required
@require_POST
def save_boom_bust_prediction_v2_view(request, player_id):
    """Explicitly persist an authorized pregame Boom/Bust prediction.

    Reuse the GET view's roster authorization, week validation,
    kickoff restrictions, and prediction generation. Do not trust
    prediction values supplied by the browser.
    """
    prediction_response = _generate_authorized_boom_bust_v2(request, player_id)

    if prediction_response.status_code != 200:
        return prediction_response

    import json

    try:
        result = json.loads(prediction_response.content)
        prediction, created = save_boom_bust_prediction_v2(result)
    except ValueError:
        return JsonResponse(
            {"error": "Unable to validate prediction for storage."},
            status=422,
        )
    except Exception:
        logger.exception(
            "Boom/Bust v2 storage failure for player_id=%s",
            player_id,
        )
        return JsonResponse(
            {"error": "Unable to save prediction."},
            status=500,
        )

    return JsonResponse({
        "saved": True,
        "created": created,
        "player_id": prediction.player_id,
        "season": prediction.season,
        "week": prediction.week,
        "model_version": prediction.model_version,
    })
