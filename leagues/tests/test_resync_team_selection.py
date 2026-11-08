"""Database-free regression test for ESPN Resync team selection."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory

from leagues.views import resync_league


class ESPNResyncTeamSelectionTests(unittest.TestCase):

    def test_resync_uses_selected_team_in_shared_league(self):
        request = RequestFactory().post("/leagues/resync/")
        request.user = SimpleNamespace(pk=42, is_authenticated=True)
        request.session = {
            "active_league_id": 10,
            "active_connection_id": 20,
        }

        identities = MagicMock()
        identities.filter.return_value.first.return_value = (
            SimpleNamespace(external_id="123456:2026")
        )
        league = SimpleNamespace(
            id=10,
            name="Test ESPN League",
            platform_identities=identities,
        )

        first = SimpleNamespace(
            id=10,
            league_id=10,
            league=league,
            platform="espn",
            external_user_id="123456:2026:1",
            espn_credentials_encrypted=None,
        )
        second = SimpleNamespace(
            id=20,
            league_id=10,
            league=league,
            platform="espn",
            external_user_id="123456:2026:2",
            espn_credentials_encrypted=None,
        )

        def lookup(**kwargs):
            matches = [
                connection for connection in (first, second)
                if all(getattr(connection, key) == value
                       for key, value in kwargs.items())
            ]
            queryset = MagicMock()
            queryset.first.return_value = matches[0] if matches else None
            return queryset

        queryset = MagicMock()
        queryset.filter.side_effect = lookup
        queryset.select_related.return_value = queryset

        with (
            patch(
                "leagues.services.active_connection."
                "UserLeagueConnection.objects.filter",
                return_value=queryset,
            ),
            patch("leagues.views.ESPNLeagueService") as service,
            patch("leagues.views.messages") as messages,
            patch("leagues.views.redirect"),
        ):
            service.return_value.get_league.return_value = {
                "id": "123456"
            }
            service.return_value.import_league.return_value = {
                "my_roster": SimpleNamespace(id=22),
                "my_roster_complete": True,
            }

            resync_league(request)

            service.return_value.import_league.assert_called_once_with(
                request.user,
                owned_team_id="2",
            )
            messages.success.assert_called_once()
            messages.error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
