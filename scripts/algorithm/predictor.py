# scripts/algorithm/predictor.py

from leagues.models import Player
from scripts.algorithm.qb.qb_predictor import predict_qb


def predict_placeholder(player, season, week):
    """
    Temporary prediction logic for positions that do not
    have a dedicated model yet.
    """

    return {
        "player_id": player.id,
        "position": player.position,
        "season": season,
        "week": week,
        "projected_fantasy_points": None,
        "status": "placeholder",
    }


PREDICTORS = {
    "QB": predict_qb,
}


def predict_player(player_id, season, week):
    """
    Main entry point for all fantasy player predictions.

    The frontend/API should call this function rather than
    calling a position-specific predictor directly.
    """

    player = Player.objects.filter(id=player_id).first()

    if player is None:
        return None

    predictor = PREDICTORS.get(player.position)

    if predictor is not None:
        return predictor(player, season, week)

    return predict_placeholder(player, season, week)