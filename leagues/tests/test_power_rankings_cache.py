"""Database-free regression tests for connection-specific Power Rankings caching."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from leagues.views import get_power_rankings_snapshot


class PowerRankingsCacheTests(unittest.TestCase):
    def test_switching_espn_connections_uses_separate_snapshots(self):
        updated_at = datetime(2026, 11, 8, tzinfo=timezone.utc)
        league = SimpleNamespace(id=9, season=2026, updated_at=updated_at)
        user = SimpleNamespace(id=42)
        connection_one = SimpleNamespace(id=14, platform="espn")
        connection_two = SimpleNamespace(id=20, platform="espn")

        stored = {}
        calls = []

        def build_rankings(league, user, **kwargs):
            connection_id = kwargs["connection"].id
            calls.append(connection_id)
            return ([{"selected_connection_id": connection_id}], 0.0, updated_at)

        with (
            patch("leagues.views.FantasyMatchup.objects.filter") as matchups,
            patch("leagues.views.cache.get") as cache_get,
            patch("leagues.views.cache.set") as cache_set,
            patch("leagues.views.get_saved_power_rankings", side_effect=build_rankings),
        ):
            matchups.return_value.aggregate.return_value = {"updated": updated_at}
            cache_get.side_effect = lambda key, default=None: stored.get(key, default)
            cache_set.side_effect = lambda key, value, timeout=None: stored.__setitem__(key, value)

            first, _ = get_power_rankings_snapshot(
                league, user, 10, connection_one
            )
            second, _ = get_power_rankings_snapshot(
                league, user, 10, connection_two
            )
            first_again, _ = get_power_rankings_snapshot(
                league, user, 10, connection_one
            )

        self.assertEqual(first[0][0]["selected_connection_id"], 14)
        self.assertEqual(second[0][0]["selected_connection_id"], 20)
        self.assertEqual(first_again, first)
        self.assertEqual(calls, [14, 20])
        self.assertEqual(len(stored), 2)


if __name__ == "__main__":
    unittest.main()
