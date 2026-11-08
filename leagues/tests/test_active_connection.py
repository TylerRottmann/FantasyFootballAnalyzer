"""Database-free tests for active fantasy connection selection."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from leagues.services.active_connection import get_active_connection


class ActiveConnectionTests(unittest.TestCase):

    def setUp(self):
        self.first = SimpleNamespace(id=10, league_id=5)
        self.second = SimpleNamespace(id=20, league_id=5)
        self.other = SimpleNamespace(id=30, league_id=6)
        self.connections = [self.first, self.second, self.other]

    def resolve(self, session, fallback_to_recent=True):
        request = SimpleNamespace(
            user=SimpleNamespace(id=1),
            session=session,
        )

        def filter_connections(**kwargs):
            matches = [
                connection for connection in self.connections
                if all(
                    getattr(connection, key) == value
                    for key, value in kwargs.items()
                )
            ]
            result = MagicMock()
            result.first.return_value = matches[0] if matches else None
            result.select_related.return_value = result
            result.filter.side_effect = filter_connections
            result.order_by.return_value = result
            result.__getitem__.side_effect = lambda key: matches[key]
            return result

        queryset = filter_connections()

        with patch(
            "leagues.services.active_connection.UserLeagueConnection.objects.filter",
            return_value=queryset,
        ):
            return get_active_connection(
                request, fallback_to_recent=fallback_to_recent
            )

    def test_selected_connection_wins_over_league_id(self):
        result = self.resolve({
            "active_connection_id": 20,
            "active_league_id": 5,
        })
        self.assertIs(result, self.second)

    def test_legacy_league_only_session_with_one_connection(self):
        self.connections = [self.first, self.other]
        result = self.resolve(
            {"active_league_id": 5},
            fallback_to_recent=False,
        )
        self.assertIs(result, self.first)

    def test_ambiguous_legacy_league_session_does_not_select_a_team(self):
        result = self.resolve({"active_league_id": 5})
        self.assertIsNone(result)

    def test_invalid_connection_with_ambiguous_league_returns_none(self):
        result = self.resolve({
            "active_connection_id": 999,
            "active_league_id": 5,
        })
        self.assertIsNone(result)

    def test_recent_connection_fallback(self):
        result = self.resolve({})
        self.assertIs(result, self.first)

    def test_fallback_can_be_disabled(self):
        result = self.resolve({}, fallback_to_recent=False)
        self.assertIsNone(result)

    def test_no_connections(self):
        self.connections = []
        result = self.resolve({})
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
