"""Regression tests for platform-aware fantasy roster resolution."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from leagues.models import UserLeagueConnection
from leagues.services.roster_identity import resolve_connection_roster


class RosterIdentityTests(TestCase):

    @patch("leagues.services.roster_identity.FantasyRoster.objects.filter")
    def test_sleeper_resolves_owner(self, mock_filter):
        roster = SimpleNamespace(id=10)
        mock_filter.return_value.first.return_value = roster

        connection = SimpleNamespace(
            league_id=1,
            platform=UserLeagueConnection.PLATFORM_SLEEPER,
            external_user_id="sleeper-user-123",
        )

        self.assertIs(resolve_connection_roster(connection), roster)
        mock_filter.assert_called_once_with(
            league_id=1,
            owner_sleeper_id="sleeper-user-123",
        )

    @patch("leagues.services.roster_identity.RosterPlatformIdentity.objects.filter")
    def test_espn_resolves_platform_identity(self, mock_filter):
        roster = SimpleNamespace(id=20)
        mock_filter.return_value.select_related.return_value.first.return_value = (
            SimpleNamespace(roster=roster)
        )

        connection = SimpleNamespace(
            league_id=1,
            platform=UserLeagueConnection.PLATFORM_ESPN,
            external_user_id="12345:2026:7",
        )

        self.assertIs(resolve_connection_roster(connection), roster)
        mock_filter.assert_called_once_with(
            roster__league_id=1,
            platform=UserLeagueConnection.PLATFORM_ESPN,
            external_id="12345:2026:7",
        )

    @patch("leagues.services.roster_identity.RosterPlatformIdentity.objects.filter")
    def test_two_espn_teams_resolve_separately(self, mock_filter):
        rosters = {
            "12345:2026:7": SimpleNamespace(id=20),
            "12345:2026:8": SimpleNamespace(id=21),
        }

        def lookup(**kwargs):
            result = MagicMock()
            result.select_related.return_value.first.return_value = (
                SimpleNamespace(roster=rosters[kwargs["external_id"]])
            )
            return result

        mock_filter.side_effect = lookup

        def connection(team_id):
            return SimpleNamespace(
                league_id=1,
                platform=UserLeagueConnection.PLATFORM_ESPN,
                external_user_id=team_id,
            )

        first = resolve_connection_roster(connection("12345:2026:7"))
        second = resolve_connection_roster(connection("12345:2026:8"))

        self.assertEqual(first.id, 20)
        self.assertEqual(second.id, 21)

    @patch("leagues.services.roster_identity.RosterPlatformIdentity.objects.filter")
    def test_missing_espn_identity_returns_none(self, mock_filter):
        mock_filter.return_value.select_related.return_value.first.return_value = None

        connection = SimpleNamespace(
            league_id=1,
            platform=UserLeagueConnection.PLATFORM_ESPN,
            external_user_id="missing-team",
        )

        self.assertIsNone(resolve_connection_roster(connection))

    def test_missing_external_user_id_returns_none(self):
        connection = SimpleNamespace(
            league_id=1,
            platform=UserLeagueConnection.PLATFORM_ESPN,
            external_user_id="",
        )
        self.assertIsNone(resolve_connection_roster(connection))
        self.assertIsNone(resolve_connection_roster(None))
