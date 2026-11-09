"""Regression tests for platform-aware fantasy league display names."""

from unittest.mock import Mock

from django.test import SimpleTestCase

from leagues.models import FantasyLeague


class LeagueDisplayNameTests(SimpleTestCase):
    def make_league(self, identities):
        league = FantasyLeague(id=999, name="Original League Name")
        league._prefetched_objects_cache = {
            "platform_identities": identities
        }
        return league

    def test_modern_espn_id(self):
        league = self.make_league([
            Mock(platform="espn", external_id="2075821650:2026")
        ])
        self.assertEqual(
            league.display_name,
            "ESPN League #2075821650",
        )

    def test_legacy_espn_id(self):
        league = self.make_league([
            Mock(platform="espn", external_id="2127")
        ])
        self.assertEqual(
            league.display_name,
            "ESPN League #2127",
        )

    def test_sleeper_preserves_original_name(self):
        league = self.make_league([
            Mock(platform="sleeper", external_id="123456")
        ])
        self.assertEqual(
            league.display_name,
            "Original League Name",
        )

    def test_no_identity_preserves_original_name(self):
        league = self.make_league([])
        self.assertEqual(
            league.display_name,
            "Original League Name",
        )

    def test_empty_espn_id_preserves_original_name(self):
        league = self.make_league([
            Mock(platform="espn", external_id="")
        ])
        self.assertEqual(
            league.display_name,
            "Original League Name",
        )
