"""Database-free regression test for ESPN trade suggestion cache isolation."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory

from leagues.trades.views import trade_suggestions


class TradeSuggestionsCacheTests(unittest.TestCase):
    def test_espn_team_switching_separates_suggestions(self):
        factory = RequestFactory()
        user = SimpleNamespace(id=42, is_authenticated=True)
        league = SimpleNamespace(id=9, season=2026, name="ESPN League")
        connections = [
            SimpleNamespace(id=14, league_id=9, league=league, platform="espn"),
            SimpleNamespace(id=20, league_id=9, league=league, platform="espn"),
        ]
        stored = {}
        generated = []

        def build_universe(league, user, week, *, connection):
            generated.append(connection.id)
            return {"connection_id": connection.id}

        def suggestions(universe, *, filters):
            return [{"connection_id": universe["connection_id"]}]

        with (
            patch("leagues.trades.views._active_connection") as active,
            patch("leagues.trades.views._current_week", return_value=10),
            patch("leagues.trades.views._suggestion_filters", return_value={}),
            patch("leagues.trades.views.build_trade_universe", side_effect=build_universe),
            patch("leagues.trades.views.generate_best_trades", side_effect=suggestions),
            patch("leagues.trades.views.cache.get", side_effect=lambda key: stored.get(key)),
            patch("leagues.trades.views.cache.set", side_effect=lambda key, value, timeout=None: stored.__setitem__(key, value)),
        ):
            responses = []
            for connection in (connections[0], connections[1], connections[0]):
                active.return_value = connection
                request = factory.get("/leagues/trades/suggestions/")
                request.user = user
                responses.append(trade_suggestions(request))

        import json
        results = [json.loads(response.content) for response in responses]

        self.assertEqual([r["suggestions"][0]["connection_id"] for r in results], [14, 20, 14])
        self.assertEqual(generated, [14, 20])
        self.assertEqual(len(stored), 2)


if __name__ == "__main__":
    unittest.main()
