# scripts/algorithm/predictor.py

from leagues.models import Player
from scripts.algorithm.k.k_predictor import predict_k
from scripts.algorithm.qb.qb_predictor import predict_qb
from scripts.algorithm.rb.rb_predictor import predict_rb
from scripts.algorithm.wr.wr_predictor import predict_wr
from scripts.algorithm.te.te_predictor import predict_te
from scripts.algorithm.dst.dst_predictor import predict_dst


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
    "K": predict_k,
    "QB": predict_qb,
    "RB": predict_rb,
    "WR": predict_wr,
    "TE": predict_te,
}


def predict_player(player_id, season, week, scoring_settings=None, context=None):
    """
    Main entry point for all fantasy player predictions.

    The frontend/API should call this function rather than
    calling a position-specific predictor directly.
    """

    player = Player.objects.filter(id=player_id).first()

    if player is None:
        return None

    from leagues.services.player_availability import availability, adjusted_forecast, quarterback_role
    label, factor = availability(player, season, week, reports=context['reports'] if context else None)
    if factor == 0:
        return {'player_id': player.id, 'position': player.position, 'season': season,
                'week': week, 'projected_fantasy_points': 0.0, 'status': 'injury_out',
                'projected_stats': {'_context': {'base_points': None, 'base_status': 'insufficient_history'}}}
    qb_role = quarterback_role(player, season, week, reports=context['reports'] if context else None)
    if qb_role in ('qb_backup', 'qb_uncertain'):
        return {'player_id': player.id, 'position': player.position, 'season': season,
                'week': week, 'projected_fantasy_points': 0.0 if qb_role == 'qb_backup' else None,
                'status': qb_role, 'projected_stats': {'_context': {'base_points': None, 'base_status': 'insufficient_history', 'qb_role': qb_role}}}
    predictor = PREDICTORS.get(player.position)
    if player.position == 'K':
        result = predictor(player, season, week, scoring_settings=scoring_settings)
    elif predictor is not None:
        result = predictor(player, season, week)
    else:
        result = predict_placeholder(player, season, week)
    points, status, stats = adjusted_forecast(player, season, week,
        result.get('projected_fantasy_points'), result['status'], result.get('projected_stats'), context=context)
    return {**result, 'projected_fantasy_points': points, 'status': status, 'projected_stats': stats}


def predict_defense(team_id, season, week):
    """
    Entry point for D/ST projections.

    Defenses are teams, not rows in the players table (the roster
    stores them with player=None and a team), so they are looked up by
    team_id rather than through predict_player().
    """

    return predict_dst(team_id, season, week)
