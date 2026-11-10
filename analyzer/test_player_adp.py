from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from analyzer.models import PlayerADP
from analyzer.management.commands.refresh_player_adp import valid_adp
from analyzer.test_waivers import WaiverWireTests


class PlayerADPTests(WaiverWireTests):
    def setUp(self):
        super().setUp()
        PlayerADP.objects.bulk_create([
            PlayerADP(
                player=self.available,
                season=2026,
                scoring_format="ppr",
                adp=Decimal("12.50"),
            ),
            PlayerADP(
                player=self.other,
                season=2026,
                scoring_format="ppr",
                adp=Decimal("4.20"),
            ),
            PlayerADP(
                player=self.available,
                season=2026,
                scoring_format="half_ppr",
                adp=Decimal("15.75"),
            ),
            PlayerADP(
                player=self.available,
                season=2026,
                scoring_format="std",
                adp=Decimal("19.00"),
            ),
        ])

    def test_adp_validation(self):
        for value in (None, True, 0, -1, 999, 1000, "NaN", "Infinity", "bad"):
            with self.subTest(value=value):
                self.assertIsNone(valid_adp(value))

        self.assertEqual(valid_adp(12.345), Decimal("12.35"))
        self.assertEqual(valid_adp("4.2"), Decimal("4.20"))

    def test_rankings_are_sorted_by_adp(self):
        response = self.client.get(reverse("standalone_adp_rankings"), {"view": "full"})
        self.assertEqual(response.status_code, 200)
        names = [p.full_name for p in response.context["players"]]
        self.assertEqual(names, ["Other Team", "Available Receiver"])
        self.assertContains(response, "4.20")
        self.assertContains(response, "12.50")

    def test_scoring_formats(self):
        for scoring, expected in (
            ("ppr", "12.50"),
            ("half_ppr", "15.75"),
            ("std", "19.00"),
        ):
            with self.subTest(scoring=scoring):
                response = self.client.get(
                    reverse("standalone_adp_rankings"),
                    {"view": "full", "scoring": scoring, "search": "Available Receiver"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, expected)

    def test_search_position_and_team_filters(self):
        response = self.client.get(
            reverse("standalone_adp_rankings"),
            {
                "view": "full",
                "scoring": "ppr",
                "position": "WR",
                "team": str(self.team.pk),
                "search": "Available",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Available Receiver")
        self.assertNotContains(response, "Other Team")

    def test_import_dry_run_does_not_write(self):
        response = Mock()
        response.json.return_value = [
            {
                "player_id": self.available.sleeper_id,
                "stats": {
                    "adp_ppr": 9.5,
                    "adp_half_ppr": 11.0,
                    "adp_std": 13.0,
                },
            }
        ]

        with patch(
            "analyzer.management.commands.refresh_player_adp.requests.get",
            return_value=response,
        ):
            call_command(
                "refresh_player_adp",
                season=2026,
                dry_run=True,
                stdout=StringIO(),
            )

        self.assertEqual(
            PlayerADP.objects.get(
                player=self.available,
                season=2026,
                scoring_format="ppr",
            ).adp,
            Decimal("12.50"),
        )

    def test_import_updates_existing_adp(self):
        response = Mock()
        response.json.return_value = [
            {
                "player_id": self.available.sleeper_id,
                "stats": {
                    "adp_ppr": 9.5,
                    "adp_half_ppr": 11.0,
                    "adp_std": 13.0,
                },
            }
        ]

        with patch(
            "analyzer.management.commands.refresh_player_adp.requests.get",
            return_value=response,
        ):
            call_command(
                "refresh_player_adp",
                season=2026,
                stdout=StringIO(),
            )

        ranking = PlayerADP.objects.get(
            player=self.available,
            season=2026,
            scoring_format="ppr",
        )
        self.assertEqual(ranking.adp, Decimal("9.50"))

    def test_api_failure_preserves_existing_rankings(self):
        with patch(
            "analyzer.management.commands.refresh_player_adp.requests.get",
            side_effect=__import__("requests").ConnectionError("API unavailable"),
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "refresh_player_adp",
                    season=2026,
                    stdout=StringIO(),
                )

        self.assertEqual(PlayerADP.objects.count(), 4)

    def test_successful_refresh_removes_stale_rankings(self):
        response = Mock()
        response.json.return_value = [
            {
                "player_id": self.available.sleeper_id,
                "stats": {
                    "adp_ppr": 9.5,
                    "adp_half_ppr": 11.0,
                    "adp_std": 13.0,
                },
            }
        ]

        with patch(
            "analyzer.management.commands.refresh_player_adp.requests.get",
            return_value=response,
        ):
            call_command(
                "refresh_player_adp",
                season=2026,
                stdout=StringIO(),
            )

        self.assertFalse(
            PlayerADP.objects.filter(
                player=self.other,
                season=2026,
                scoring_format="ppr",
            ).exists()
        )
        self.assertEqual(
            PlayerADP.objects.filter(season=2026).count(),
            3,
        )

    def test_incomplete_refresh_preserves_existing_rankings(self):
        response = Mock()
        response.json.return_value = [
            {
                "player_id": self.available.sleeper_id,
                "stats": {"adp_ppr": 9.5},
            }
        ]

        with patch(
            "analyzer.management.commands.refresh_player_adp.requests.get",
            return_value=response,
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "refresh_player_adp",
                    season=2026,
                    stdout=StringIO(),
                )

        self.assertEqual(PlayerADP.objects.count(), 4)
        self.assertEqual(
            PlayerADP.objects.get(
                player=self.available,
                season=2026,
                scoring_format="ppr",
            ).adp,
            Decimal("12.50"),
        )
