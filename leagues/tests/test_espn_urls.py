from django.test import SimpleTestCase

from leagues.integrations.espn import ESPNLeagueService


class ESPNLeagueURLTests(SimpleTestCase):
    def test_numeric_league_id(self):
        self.assertEqual(
            ESPNLeagueService.parse_league_id("123456789"),
            "123456789",
        )

    def test_query_parameter_url(self):
        self.assertEqual(
            ESPNLeagueService.parse_league_id(
                "https://fantasy.espn.com/football/league?leagueId=123456789"
            ),
            "123456789",
        )

    def test_path_based_url(self):
        self.assertEqual(
            ESPNLeagueService.parse_league_id(
                "https://fantasy.espn.com/football/league/123456789"
            ),
            "123456789",
        )

    def test_path_based_url_with_trailing_slash(self):
        self.assertEqual(
            ESPNLeagueService.parse_league_id(
                "https://fantasy.espn.com/football/league/123456789/"
            ),
            "123456789",
        )

    def test_reject_external_domain(self):
        with self.assertRaises(ValueError):
            ESPNLeagueService.parse_league_id(
                "https://example.com/football/league/123456789"
            )

    def test_reject_invalid_input(self):
        with self.assertRaises(ValueError):
            ESPNLeagueService.parse_league_id("invalid")
