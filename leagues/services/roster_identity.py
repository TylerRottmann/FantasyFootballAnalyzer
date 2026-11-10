"""Resolve the roster owned by a connected fantasy-platform user."""

from leagues.models import (
    FantasyRoster,
    RosterPlatformIdentity,
    UserLeagueConnection,
)


def resolve_connection_roster(connection):
    """Return the roster belonging to a connection, or None."""
    if connection is None or not connection.external_user_id:
        return None

    if connection.platform == UserLeagueConnection.PLATFORM_SLEEPER:
        return FantasyRoster.objects.filter(
            league_id=connection.league_id,
            owner_sleeper_id=connection.external_user_id,
        ).first()

    identity = (
        RosterPlatformIdentity.objects
        .filter(
            roster__league_id=connection.league_id,
            platform=connection.platform,
            external_id=connection.external_user_id,
        )
        .select_related("roster")
        .first()
    )
    return identity.roster if identity else None
