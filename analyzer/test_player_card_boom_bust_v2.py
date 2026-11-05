"""Database-free authorization tests for saved Boom/Bust v2 player cards."""
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from django.http import HttpResponse
from django.test import RequestFactory

from analyzer.player_cards import player_card


class PlayerCardBoomBustV2Tests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_authenticated=True)
        self.league = SimpleNamespace(pk=1, season=2026)
        self.player = SimpleNamespace(pk=305, position="RB")
        self.saved = SimpleNamespace(
            boom_probability=0.218,
            bust_probability=0.14,
        )

    def run_card(self, *, connected=True, rostered=True, saved=True,
                 active=True, legacy_boom=None, legacy_bust=None):
        request = self.factory.get("/players/305/?week=9&format=json")
        request.user = self.user
        request.session = {"active_league_id": 1 if active else 2}
        profile = {"boom_pct": legacy_boom, "bust_pct": legacy_bust}

        with (
            patch("analyzer.player_cards.league_selector",
                  return_value={"active_league": self.league}),
            patch("analyzer.player_cards.get_object_or_404",
                  return_value=self.player),
            patch("analyzer.player_cards.build_player_profile",
                  return_value=profile),
            patch("analyzer.player_cards.UserLeagueConnection.objects") as connections,
            patch("analyzer.player_cards.FantasyRosterPlayer.objects") as rosters,
            patch("analyzer.player_cards.BoomBustWeeklyPrediction.objects") as predictions,
        ):
            connections.filter.return_value.only.return_value.first.return_value = (
                SimpleNamespace(external_user_id="owner123") if connected else None
            )
            rosters.filter.return_value.exists.return_value = rostered
            predictions.filter.return_value.first.return_value = (
                self.saved if saved else None
            )

            response = player_card(request, 305)

            return response, connections, rosters, predictions

    def test_authorized_saved_prediction(self):
        response, _, _, predictions = self.run_card()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["boom_pct"], 21.8)
        self.assertEqual(json.loads(response.content)["bust_pct"], 14.0)
        predictions.filter.assert_called_once_with(
            player_id=305, season=2026, week=9, model_version="2"
        )

    def test_unconnected_user_cannot_read_v2(self):
        response, _, _, predictions = self.run_card(connected=False)
        self.assertIsNone(json.loads(response.content)["boom_pct"])
        self.assertIsNone(json.loads(response.content)["bust_pct"])
        predictions.filter.assert_not_called()

    def test_other_managers_roster_cannot_read_v2(self):
        response, _, _, predictions = self.run_card(rostered=False)
        self.assertIsNone(json.loads(response.content)["boom_pct"])
        self.assertIsNone(json.loads(response.content)["bust_pct"])
        predictions.filter.assert_not_called()

    def test_wrong_active_league_cannot_read_v2(self):
        response, _, _, predictions = self.run_card(active=False)
        self.assertIsNone(json.loads(response.content)["boom_pct"])
        self.assertIsNone(json.loads(response.content)["bust_pct"])
        predictions.filter.assert_not_called()

    def test_missing_prediction_stays_unavailable(self):
        response, _, _, _ = self.run_card(saved=False)
        self.assertIsNone(json.loads(response.content)["boom_pct"])
        self.assertIsNone(json.loads(response.content)["bust_pct"])

    def test_existing_estimates_take_precedence(self):
        response, _, _, predictions = self.run_card(
            legacy_boom=30, legacy_bust=10
        )
        self.assertEqual(json.loads(response.content)["boom_pct"], 30)
        self.assertEqual(json.loads(response.content)["bust_pct"], 10)
        predictions.filter.assert_not_called()
