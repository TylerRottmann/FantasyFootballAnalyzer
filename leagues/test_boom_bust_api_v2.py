import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory

from leagues.boom_bust_api_v2 import _generate_authorized_boom_bust_v2


class BoomBustAPIv2Tests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(id=1)

    def request(self, week="10", league_id=9, connection_id=14):
        request = self.factory.get("/boom-bust/123/", {"week": week})
        request.user = self.user
        request.session = {
            "active_league_id": league_id,
            "active_connection_id": connection_id,
        }
        return request

    @staticmethod
    def payload(response):
        return json.loads(response.content)

    @patch("leagues.boom_bust_api_v2.UserLeagueConnection.objects.filter")
    def test_missing_connection_is_rejected(self, filter_connections):
        filter_connections.return_value.select_related.return_value.filter.return_value.first.return_value = None

        response = _generate_authorized_boom_bust_v2(self.request(), 123)

        self.assertEqual(response.status_code, 404)
        self.assertIn("connected league", self.payload(response)["error"])
        filter_connections.assert_called_once_with(
            user=self.user, league_id=9
        )

    @patch("leagues.boom_bust_api_v2.UserLeagueConnection.objects.filter")
    def test_invalid_week_is_rejected(self, filter_connections):
        filter_connections.return_value.select_related.return_value.filter.return_value.first.return_value = (
            SimpleNamespace(league=SimpleNamespace(season=2026))
        )

        for week in ("abc", "0", "19"):
            with self.subTest(week=week):
                response = _generate_authorized_boom_bust_v2(
                    self.request(week=week), 123
                )
                self.assertEqual(response.status_code, 400)

    @patch("leagues.boom_bust_api_v2.BoomBustWeeklyPrediction.objects.filter")
    @patch("leagues.boom_bust_api_v2.Players.objects.filter")
    @patch("leagues.boom_bust_api_v2.UserLeagueConnection.objects.filter")
    def test_connected_user_can_read_saved_prediction_for_any_player(
        self, filter_connections, filter_players, filter_predictions
    ):
        filter_connections.return_value.select_related.return_value.filter.return_value.first.return_value = (
            SimpleNamespace(league=SimpleNamespace(season=2026))
        )
        filter_players.return_value.first.return_value = (
            SimpleNamespace(position="WR")
        )
        expected = {
            "week": 10,
            "probabilities": {"boom": 0.3, "normal": 0.5, "bust": 0.2},
        }
        filter_predictions.return_value.order_by.return_value.first.return_value = (
            SimpleNamespace(prediction_data=expected)
        )

        response = _generate_authorized_boom_bust_v2(self.request(), 123)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payload(response), expected)
        filter_predictions.assert_called_once_with(
            player_id=123, season=2026, week=10
        )

    @patch("leagues.boom_bust_api_v2.BoomBustWeeklyPrediction.objects.filter")
    @patch("leagues.boom_bust_api_v2.Players.objects.filter")
    @patch("leagues.boom_bust_api_v2.UserLeagueConnection.objects.filter")
    def test_missing_saved_prediction_returns_404(
        self, filter_connections, filter_players, filter_predictions
    ):
        filter_connections.return_value.select_related.return_value.filter.return_value.first.return_value = (
            SimpleNamespace(league=SimpleNamespace(season=2026))
        )
        filter_players.return_value.first.return_value = (
            SimpleNamespace(position="QB")
        )
        filter_predictions.return_value.order_by.return_value.first.return_value = None

        response = _generate_authorized_boom_bust_v2(self.request(), 123)

        self.assertEqual(response.status_code, 404)
        self.assertIn("not yet available", self.payload(response)["error"])


if __name__ == "__main__":
    unittest.main()
