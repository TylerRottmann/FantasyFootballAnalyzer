from leagues.models import UserLeagueConnection, RosterPlatformIdentity


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

    active_connection_id = request.session.get("active_connection_id")
    active_league_id = request.session.get("active_league_id")

    active_connection = None

    if  active_connection_id:
            active_connection = next(
            (
                connection
                for connection in connections
                if connection.id == active_connection_id
            ),
            None,
    )

    if active_connection is None and active_league_id:
        active_connection = next(
            (
                connection
                for connection in connections
                if connection.league_id == active_league_id
            ),
            None,
    )

    # If no valid league is selected, use the first connected league.
    if active_connection is None:
        active_connection = connections[0]

    espn_connections = [
        connection for connection in connections
        if connection.platform == "espn"
    ]

    espn_ids = [
        connection.external_user_id
        for connection in espn_connections
    ]

    identities = RosterPlatformIdentity.objects.filter(
        platform="espn",
        external_id__in=espn_ids,
        roster__league__in=[
            connection.league for connection in espn_connections
        ],
    ).select_related("roster")

    team_names = {
        (identity.roster.league_id, identity.external_id):
        identity.roster.owner_name
        for identity in identities
    }

    for connection in connections:
        connection.display_team_name = team_names.get(
            (connection.league_id, connection.external_user_id),
            connection.league.name,
        )

    active_team_name = active_connection.display_team_name

    return {
        "active_team_name": active_team_name,
        "connected_leagues": connections,
        "active_league": active_connection.league,
        "active_connection": active_connection,
    }
