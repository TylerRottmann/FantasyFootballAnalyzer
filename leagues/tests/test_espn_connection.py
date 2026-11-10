"""Database-free regression tests for ESPN connection handling."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory

from leagues.views import connect_league, resync_league


class ESPNConnectionViewTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.token = "test-connection-token"
        self.lookup = {
            "league_id": "123456",
            "season": 2026,
            "swid": None,
            "espn_s2": None,
            "team_ids": ["1"],
        }

    def check_connection(self, complete, unresolved):
        request = self.factory.post(
            "/leagues/connect/",
            {
                "platform": "espn",
                "espn_connection_token": self.token,
                "espn_team_id": "1",
            },
        )
        request.user = SimpleNamespace(
            pk=42,
            is_authenticated=True,
        )
        request.session = {}

        league = SimpleNamespace(id=10)
        roster = SimpleNamespace(id=20)

        result = {
            "league": league,
            "my_roster": roster,
            "my_roster_complete": complete,
            "players_unresolved": unresolved,
        }

        with (
            patch("leagues.views.cache") as cache,
            patch("leagues.views.ESPNLeagueService") as service,
            patch("leagues.views.UserLeagueConnection") as connections,
            patch("leagues.views.render") as render,
            patch("leagues.views.redirect") as redirect,
        ):
            cache.get.return_value = self.lookup
            service.return_value.import_league.return_value = result
            connections.objects.get.return_value.league_id = 10

            response = connect_league(request)

            service.return_value.import_league.assert_called_once_with(
                request.user,
                owned_team_id="1",
            )

            if complete:
                redirect.assert_called_once_with("start_sit")
                cache.delete.assert_called_once_with(
                    f"espn_connect:42:{self.token}"
                )
                self.assertEqual(
                    request.session["active_league_id"],
                    10,
                )
            else:
                redirect.assert_not_called()
                cache.delete.assert_not_called()
                self.assertNotIn(
                    "active_league_id",
                    request.session,
                )
                render.assert_called_once()
                context = render.call_args.args[2]
                self.assertIn("could not be fully imported", context["error"])

            return response

    def test_incomplete_selected_roster_does_not_redirect(self):
        self.check_connection(complete=False, unresolved=1)

    def test_complete_selected_roster_redirects(self):
        self.check_connection(complete=True, unresolved=0)

    def test_other_team_unresolved_does_not_block_connection(self):
        self.check_connection(complete=True, unresolved=1)


class ESPNResyncViewTests(unittest.TestCase):
    """Verify ESPN resync never reports incomplete imports as successful."""

    def setUp(self):
        self.factory = RequestFactory()

    def check_resync(self, complete):
        request = self.factory.post("/leagues/resync/")
        request.user = SimpleNamespace(pk=42, is_authenticated=True)
        request.session = {"active_league_id": 10}

        identity = SimpleNamespace(external_id="123456:2026")
        identities = MagicMock()
        identities.filter.return_value.first.return_value = identity

        league = SimpleNamespace(
            id=10,
            name="Test ESPN League",
            platform_identities=identities,
        )
        connection = SimpleNamespace(
            platform="espn",
            league=league,
            external_user_id="123456:2026:1",
            espn_credentials_encrypted=None,
        )

        with (
            patch("leagues.services.active_connection.get_active_connection") as active_connection,
            patch("leagues.views.ESPNLeagueService") as service,
            patch("leagues.views.messages") as messages,
            patch("leagues.views.redirect") as redirect,
        ):

            active_connection.return_value = connection
            service.return_value.get_league.return_value = {"id": "123456"}
            service.return_value.import_league.return_value = {
                "my_roster": SimpleNamespace(id=20),
                "my_roster_complete": complete,
            }

            resync_league(request)

            service.return_value.import_league.assert_called_once_with(
                request.user,
                owned_team_id="1",
            )
            redirect.assert_called_once_with("start_sit")

            if complete:
                messages.success.assert_called_once()
                messages.error.assert_not_called()
            else:
                messages.success.assert_not_called()
                messages.error.assert_called_once()
                self.assertIn(
                    "could not be fully resynced",
                    messages.error.call_args.args[1],
                )

    def test_complete_resync_reports_success(self):
        self.check_resync(complete=True)

    def test_incomplete_resync_reports_error(self):
        self.check_resync(complete=False)


class ESPNPrivateResyncTests(unittest.TestCase):
    """Verify private ESPN resync uses saved credentials safely."""

    def setUp(self):
        self.factory = RequestFactory()

    def make_request(self):
        request = self.factory.post("/leagues/resync/")
        request.user = SimpleNamespace(pk=42, is_authenticated=True)
        request.session = {"active_league_id": 10}
        return request

    def make_connection(self, encrypted_credentials):
        identity = SimpleNamespace(external_id="123456:2026")
        identities = MagicMock()
        identities.filter.return_value.first.return_value = identity

        league = SimpleNamespace(
            id=10,
            name="Private ESPN League",
            platform_identities=identities,
        )

        return SimpleNamespace(
            platform="espn",
            league=league,
            external_user_id="123456:2026:1",
            espn_credentials_encrypted=encrypted_credentials,
        )

    def test_private_resync_uses_saved_credentials(self):
        request = self.make_request()
        connection = self.make_connection("encrypted-test-value")

        with (
            patch("leagues.services.active_connection.get_active_connection") as active_connection,
            patch("leagues.views.ESPNLeagueService") as service,
            patch(
                "leagues.integrations.espn_credentials.decrypt_espn_credentials",
                return_value=("{TEST-SWID}", "test-session"),
            ) as decrypt,
            patch("leagues.views.messages") as messages,
            patch("leagues.views.redirect"),
        ):

            active_connection.return_value = connection

            service.return_value.get_league.return_value = {"id": "123456"}
            service.return_value.import_league.return_value = {
                "my_roster": SimpleNamespace(id=20),
                "my_roster_complete": True,
            }

            resync_league(request)

            decrypt.assert_called_once_with("encrypted-test-value")
            service.assert_called_once_with(
                "123456",
                "2026",
                swid="{TEST-SWID}",
                espn_s2="test-session",
            )
            service.return_value.import_league.assert_called_once_with(
                request.user,
                owned_team_id="1",
            )
            messages.success.assert_called_once()
            messages.error.assert_not_called()

    def test_invalid_credentials_prevent_resync(self):
        request = self.make_request()
        connection = self.make_connection("invalid-encrypted-value")

        with (
            patch("leagues.services.active_connection.get_active_connection") as active_connection,
            patch("leagues.views.ESPNLeagueService") as service,
            patch(
                "leagues.integrations.espn_credentials.decrypt_espn_credentials",
                side_effect=ValueError(
                    "Saved ESPN credentials cannot be decrypted. "
                    "Reconnect your ESPN league."
                ),
            ),
            patch("leagues.views.messages") as messages,
            patch("leagues.views.redirect"),
        ):

            active_connection.return_value = connection

            resync_league(request)

            service.assert_not_called()
            messages.success.assert_not_called()
            messages.error.assert_called_once()
            self.assertIn(
                "Reconnect your ESPN league",
                messages.error.call_args.args[1],
            )
            self.assertNotIn(
                "invalid-encrypted-value",
                messages.error.call_args.args[1],
            )

    def test_other_users_connection_cannot_be_resynced(self):
        request = self.make_request()

        with (
            patch("leagues.services.active_connection.get_active_connection") as active_connection,
            patch("leagues.views.ESPNLeagueService") as service,
            patch("leagues.views.messages") as messages,
            patch("leagues.views.redirect") as redirect,
        ):
            active_connection.return_value = None

            resync_league(request)

            active_connection.assert_called_once_with(
                request,
                fallback_to_recent=False,
            )
            service.assert_not_called()
            messages.error.assert_called_once()
            self.assertIn(
                "connection could not be found",
                messages.error.call_args.args[1],
            )
            redirect.assert_called_once_with("start_sit")
