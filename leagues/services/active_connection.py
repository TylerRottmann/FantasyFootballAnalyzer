"""Resolve the fantasy league connection selected in the user's session."""

from leagues.models import UserLeagueConnection


def get_active_connection(request, *, fallback_to_recent=True):
    """Return the user's selected connection, or a permitted fallback."""
    connections = (
        UserLeagueConnection.objects
        .filter(user=request.user)
        .select_related("league")
    )

    connection_id = request.session.get("active_connection_id")
    if connection_id:
        connection = connections.filter(id=connection_id).first()
        if connection is not None:
            return connection

    league_id = request.session.get("active_league_id")
    if league_id:
        matching_connections = list(
            connections.filter(league_id=league_id)[:2]
        )
        if len(matching_connections) == 1:
            return matching_connections[0]
        if len(matching_connections) > 1:
            return None

    if fallback_to_recent:
        return connections.order_by("-league__updated_at").first()

    return None
