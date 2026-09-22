from .models import UserLeagueConnection


def league_selector(request):
    if not request.user.is_authenticated:
        return {
            "connected_leagues": [],
            "active_league": None,
        }

    connections = list(
        UserLeagueConnection.objects
        .filter(user=request.user)
        .select_related("league")
        .order_by("-league__updated_at")
    )

    if not connections:
        return {
            "connected_leagues": [],
            "active_league": None,
        }

    active_league_id = request.session.get("active_league_id")

    active_connection = None

    if active_league_id:
        active_connection = next(
            (
                connection
                for connection in connections
                if connection.league.id == active_league_id
            ),
            None,
        )

    # If no valid league is selected, use the first connected league.
    if active_connection is None:
        active_connection = connections[0]

    return {
        "connected_leagues": connections,
        "active_league": active_connection.league,
    }