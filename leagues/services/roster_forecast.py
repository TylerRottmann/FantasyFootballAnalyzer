from scripts.algorithm.predictor import predict_player


def forecast_roster_players(roster_players, season, weeks):
    forecasts = {}

    for roster_player in roster_players:
        player = roster_player.player
        if player is None:
            # Team defense needs its own forecast path.
            continue

        for week in weeks:
            prediction = predict_player(player.id, season, week)

            forecasts[(roster_player.id, week)] = {
                "player_id": player.id,
                "position": player.position,
                "week": week,
                "projected_points": (
                    prediction.get("projected_fantasy_points")
                    if prediction else None
                ),
                "status": prediction.get("status", "missing") if prediction else "missing",
                "model_version": prediction.get("model_version", "current"),
            }

    return forecasts