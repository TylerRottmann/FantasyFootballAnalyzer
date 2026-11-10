from leagues.models import RosterPlatformIdentity
from leagues.services.active_connection import get_active_connection


def league_selector(request):
    if not request.user.is_authenticated:
        return {
            "connected_leagues": [],
            "active_league": None,
            "active_connection": None,
            "active_team_name": None,
        }

    connections = list(
        request.user.league_connections
        .select_related("league")
        .prefetch_related("league__platform_identities")
        .order_by("-league__updated_at", "-id")
    )

    if not connections:
        return {
            "connected_leagues": [],
            "active_league": None,
            "active_connection": None,
            "active_team_name": None,
        }

    active_connection = get_active_connection(request)

    # Keep the session synchronized with the resolved connection.
    if active_connection is not None:
        request.session["active_connection_id"] = active_connection.id
        request.session["active_league_id"] = active_connection.league_id

    espn_connections = [
        connection for connection in connections
        if connection.platform == "espn"
    ]

    identities = RosterPlatformIdentity.objects.filter(
        platform="espn",
        external_id__in=[
            connection.external_user_id
            for connection in espn_connections
            if connection.external_user_id
        ],
        roster__league_id__in=[
            connection.league_id for connection in espn_connections
        ],
    ).select_related("roster")

    team_names = {
        (identity.roster.league_id, identity.external_id):
        identity.roster.owner_name
        for identity in identities
    }

    for connection in connections:
        connection.display_team_name = (
            team_names.get(
                (connection.league_id, connection.external_user_id)
            )
            if connection.platform == "espn"
            else None
        ) or connection.league.name

    active_team_name = next(
        (
            connection.display_team_name
            for connection in connections
            if active_connection is not None
            and connection.id == active_connection.id
        ),
        None,
    )

    return {
        "active_team_name": active_team_name,
        "connected_leagues": connections,
        "active_league": (
            active_connection.league
            if active_connection is not None else None
        ),
        "active_connection": active_connection,
    }
