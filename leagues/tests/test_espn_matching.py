"""Regression tests for ESPN player and defense resolution."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from leagues.integrations.espn import ESPNLeagueService


class ESPNMatchingTests(unittest.TestCase):
    def setUp(self):
        self.service = ESPNLeagueService(
            "123456",
            2026,
            swid="{TEST-SWID}",
            espn_s2="test-session",
        )

    def test_defense_resolves_to_existing_team(self):
        teams = [
            SimpleNamespace(id=1, name="Buffalo Bills", abbreviation="BUF"),
            SimpleNamespace(id=5, name="Baltimore Ravens", abbreviation="BAL"),
        ]

        result = self.service._resolve_defense(
            {"fullName": "Bills D/ST", "defaultPositionId": 16},
            teams,
        )

        self.assertIs(result, teams[0])

    def test_unknown_defense_is_rejected(self):
        teams = [
            SimpleNamespace(id=1, name="Buffalo Bills", abbreviation="BUF")
        ]

        result = self.service._resolve_defense(
            {"fullName": "Unknown D/ST", "defaultPositionId": 16},
            teams,
        )

        self.assertIsNone(result)

    def test_ambiguous_defense_is_rejected(self):
        teams = [
            SimpleNamespace(name="Buffalo Bills"),
            SimpleNamespace(name="Other Bills"),
        ]

        result = self.service._resolve_defense(
            {"fullName": "Bills D/ST"},
            teams,
        )

        self.assertIsNone(result)

    @patch("leagues.integrations.espn.PlayerPlatformIdentity")
    def test_junior_suffix_matches_existing_player(self, identities):
        player = SimpleNamespace(
            id=100,
            full_name="Brian Robinson",
            position="RB",
        )

        result = self.service._resolve_player(
            {
                "id": 4241474,
                "fullName": "Brian Robinson Jr.",
                "defaultPositionId": 2,
            },
            [player],
            {},
            identities_preloaded=True,
        )

        self.assertIs(result, player)
        identities.objects.get_or_create.assert_called_once()

    @patch("leagues.integrations.espn.PlayerPlatformIdentity")
    def test_exact_name_takes_priority(self, identities):
        exact = SimpleNamespace(
            id=1, full_name="Brian Robinson Jr.", position="RB"
        )
        fallback = SimpleNamespace(
            id=2, full_name="Brian Robinson", position="RB"
        )

        result = self.service._resolve_player(
            {
                "id": 4241474,
                "fullName": "Brian Robinson Jr.",
                "defaultPositionId": 2,
            },
            [fallback, exact],
            {},
            identities_preloaded=True,
        )

        self.assertIs(result, exact)

    @patch("leagues.integrations.espn.PlayerPlatformIdentity")
    def test_ambiguous_suffix_match_is_rejected(self, identities):
        players = [
            SimpleNamespace(full_name="Brian Robinson", position="RB"),
            SimpleNamespace(full_name="Brian Robinson III", position="RB"),
        ]

        result = self.service._resolve_player(
            {
                "id": 4241474,
                "fullName": "Brian Robinson Jr.",
                "defaultPositionId": 2,
            },
            players,
            {},
            identities_preloaded=True,
        )

        self.assertIsNone(result)
        identities.objects.get_or_create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
