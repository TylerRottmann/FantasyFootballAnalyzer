def predict_fantasy_points(
    recent_games,
    opponent_points_allowed,
):
    """
    Predict a player's fantasy points for the upcoming game.

    recent_games:
        List of the player's previous fantasy-point totals.

    opponent_points_allowed:
        Average fantasy points the upcoming opponent has allowed
        to this player's position.
    """

    if not recent_games:
        return None

    # Use the player's recent average as our baseline.
    player_average = sum(recent_games) / len(recent_games)

    # Start with the player's own production.
    projection = player_average

    # If matchup information is available, adjust the projection
    # based on how many points the opponent typically allows.
    if opponent_points_allowed is not None:
        projection = (player_average + opponent_points_allowed) / 2

    return projection