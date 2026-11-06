"""Regression tests for Trades D/ST projection eligibility."""
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from leagues.models import DefenseProjection, FantasyRosterPlayer
from scripts.tests.test_rb_start_sit import RBStartSitTests


class TradeScoringTests(RBStartSitTests):
    def setUp(self):
        super().setUp()
        FantasyRosterPlayer.objects.create(
            roster=self.roster,
            team=self.home,
            player=None,
            roster_slot="DEF",
            created_at=timezone.now(),
        )

    def test_trade_search_respects_partial_dst_scoring(self):
        DefenseProjection.objects.create(
            team=self.home,
            season=2026,
            week=2,
            model_version="v2_stat",
            projected_fantasy_points=12.0,
            projected_stats={
                "sacks": 2,
                "interceptions": 2,
                "defensive_tds": 1,
            },
            status="ml_model",
        )

        url = reverse("trade_player_search")

        def search_with(status, usable, points):
            from types import SimpleNamespace

            scored = SimpleNamespace(
                status=status,
                usable_partial_scoring=usable,
                projected_fantasy_points=points,
            )

            with (
                patch("leagues.trades.views._current_week", return_value=2),
                patch(
                    "leagues.trades.views.league_defense_projection",
                    return_value=scored,
                ),
            ):
                response = self.client.get(url, {"q": "Kansas"})

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            defenses = [r for r in results if r["position"] == "DEF"]
            self.assertEqual(len(defenses), 1)
            return defenses[0]["rest_of_season_points"]

        self.assertEqual(search_with("ml_model", False, 12.0), 12.0)
        self.assertEqual(search_with("partial_scoring", False, 12.0), 0.0)
        self.assertEqual(search_with("partial_scoring", True, 12.0), 12.0)

    def test_trade_search_uses_league_offensive_scoring(self):
        from types import SimpleNamespace
        from leagues.models import FantasyProjection

        player = self.high

        FantasyProjection.objects.create(
            player=player,
            season=2026,
            week=2,
            model_version="v2_stat",
            projected_fantasy_points=10.0,
        )

        scored = SimpleNamespace(
            status="ml_model",
            projected_fantasy_points=18.5,
        )

        with (
            patch("leagues.trades.views._current_week", return_value=2),
            patch(
                "leagues.trades.views.league_projection",
                return_value=scored,
            ),
        ):
            response = self.client.get(
                reverse("trade_player_search"),
                {"q": player.full_name},
            )

        self.assertEqual(response.status_code, 200)
        results = [
            item for item in response.json()["results"]
            if item["player_id"] == player.id
        ]
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0]["rest_of_season_points"],
            18.5,
        )
