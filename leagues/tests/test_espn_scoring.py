"""Regression tests for ESPN league-specific projection scoring."""
from django.test import SimpleTestCase

from leagues.services.scoring import score_stat_line
from leagues.services.scoring_settings import normalize_scoring_settings


class ESPNScoringNormalizationTests(SimpleTestCase):
    def test_espn_payload_is_not_misidentified_as_sleeper(self):
        settings = {
            "scoringSettings": {
                "scoringItems": [
                    {"statId": 24, "points": 0.1},
                    {"statId": 25, "points": 6},
                    {"statId": 53, "points": 1},
                ]
            }
        }

        normalized = normalize_scoring_settings(settings)

        self.assertEqual(normalized["source"], "espn")
        self.assertEqual(normalized["rules"]["rush_yd"], 0.1)
        self.assertEqual(normalized["rules"]["rush_td"], 6)
        self.assertEqual(normalized["rules"]["rec"], 1)

    def test_espn_running_back_projection(self):
        settings = {
            "scoringSettings": {
                "scoringItems": [
                    {"statId": 24, "points": 0.1},
                    {"statId": 25, "points": 6},
                    {"statId": 53, "points": 1},
                ]
            }
        }
        stats = {
            "rushing_yards": 80,
            "rushing_tds": 1,
            "receptions": 2,
        }

        self.assertAlmostEqual(
            score_stat_line(stats, settings, "RB"),
            16.0,
        )

class ESPNTwoPointConversionTests(SimpleTestCase):
    def test_all_three_two_point_conversions(self):
        from leagues.services.scoring_settings import normalize_scoring_settings
        from leagues.services.scoring import score_stat_line

        raw = {
            "scoringSettings": {
                "scoringItems": [
                    {"statId": 19, "points": 2},
                    {"statId": 26, "points": 2},
                    {"statId": 44, "points": 2},
                ]
            }
        }

        settings = normalize_scoring_settings(raw)

        self.assertEqual(settings["source"], "espn")
        self.assertEqual(settings["unsupported_rules"], [])
        self.assertEqual(settings["rules"]["pass_2pt"], 2)
        self.assertEqual(settings["rules"]["rush_2pt"], 2)
        self.assertEqual(settings["rules"]["rec_2pt"], 2)

        stats = {
            "passing_2pt_conversions": 1,
            "rushing_2pt_conversions": 1,
            "receiving_2pt_conversions": 1,
        }

        self.assertEqual(score_stat_line(stats, settings, "QB"), 6.0)

class ESPNPositionOverrideTests(SimpleTestCase):
    def test_defensive_override_does_not_change_offensive_rule(self):
        from leagues.services.scoring_settings import normalize_scoring_settings
        from leagues.services.scoring import _rules

        raw = {
            "scoringSettings": {
                "scoringItems": [
                    {
                        "statId": 24,
                        "points": 0.1,
                        "pointsOverrides": {"16": 0.25},
                    }
                ]
            }
        }

        settings = normalize_scoring_settings(raw)

        self.assertEqual(_rules(settings, "RB")["rush_yd"], 0.1)
        self.assertEqual(_rules(settings, "DEF")["rush_yd"], 0.25)

class ESPNUnsupportedScoringTests(SimpleTestCase):
    def test_unmapped_nonzero_rule_does_not_silently_score(self):
        from leagues.services.scoring_settings import normalize_scoring_settings
        from leagues.services.scoring import score_stat_line

        raw = {
            "scoringSettings": {
                "scoringItems": [
                    {"statId": 24, "points": 0.1},
                    {"statId": 999999, "points": 10},
                ]
            }
        }

        settings = normalize_scoring_settings(raw)

        self.assertIn("statId:999999", settings["unsupported_rules"])

        with self.assertRaises(ValueError):
            score_stat_line(
                {"rushing_yards": 80},
                settings,
                "RB",
            )

class ESPNPositionAwareUnsupportedTests(SimpleTestCase):
    def test_defense_only_unknown_rule_does_not_block_running_back(self):
        from leagues.services.scoring_settings import normalize_scoring_settings
        from leagues.services.scoring import score_stat_line

        settings = normalize_scoring_settings({
            "scoringSettings": {
                "scoringItems": [
                    {"statId": 24, "points": 0.1},
                    {
                        "statId": 999999,
                        "points": 0,
                        "pointsOverrides": {"16": 10},
                    },
                ]
            }
        })

        self.assertEqual(
            score_stat_line({"rushing_yards": 80}, settings, "RB"),
            8.0,
        )

        with self.assertRaises(ValueError):
            score_stat_line({"sacks": 2}, settings, "DEF")
