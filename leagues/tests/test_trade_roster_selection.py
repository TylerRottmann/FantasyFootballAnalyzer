"""Database-free tests for trade roster selection across platforms."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from leagues.models import UserLeagueConnection
from leagues.trades.trade_generator import build_trade_universe


class TradeRosterSelectionTests(unittest.TestCase):

    def run_trade(self, platform, resolved_roster_id, username="testuser"):
        league = SimpleNamespace(
            id=1, season=2026, roster_positions=["QB"]
        )
        user = SimpleNamespace(
            get_username=lambda: username
        )
        connection = SimpleNamespace(
            league_id=1,
            platform=platform,
            external_user_id="external-team-id",
        )

        rosters = [
            SimpleNamespace(
                id=10, owner_name="Other Team",
                roster_players=SimpleNamespace(all=lambda: []),
            ),
            SimpleNamespace(
                id=20, owner_name="testuser",
                roster_players=SimpleNamespace(all=lambda: []),
            ),
        ]

        roster_query = MagicMock()
        roster_query.prefetch_related.return_value.order_by.return_value = rosters

        projection = SimpleNamespace(
            week=1, player_id=999, updated_at=None
        )
        projection_query = MagicMock()
        projection_query.select_related.return_value = [projection]

        with (
            patch("leagues.trades.trade_generator.UserLeagueConnection.objects.filter") as connections,
            patch("leagues.trades.trade_generator.FantasyRoster.objects.filter") as fantasy_rosters,
            patch("leagues.trades.trade_generator.FantasyProjection.objects.filter") as projections,
            patch("leagues.trades.trade_generator.DefenseProjection.objects.filter") as defenses,
            patch("leagues.trades.trade_generator.Teams.objects.in_bulk", return_value={}),
            patch("leagues.trades.trade_generator._build_bye_map", return_value={}),
            patch("leagues.trades.trade_generator.league_projection", return_value=0.0),
            patch("leagues.trades.trade_generator._optimized_roster_lineup", return_value=(0.0, [])),
            patch("leagues.trades.trade_generator.resolve_connection_roster") as resolver,
        ):
            connections.return_value.only.return_value.first.return_value = connection
            fantasy_rosters.return_value = roster_query
            projections.return_value = projection_query
            defenses.return_value.select_related.return_value = []
            resolver.return_value = (
                SimpleNamespace(id=resolved_roster_id)
                if resolved_roster_id is not None else None
            )

            return build_trade_universe(league, user, current_week=1)

    def test_espn_selects_connected_roster(self):
        result = self.run_trade(
            UserLeagueConnection.PLATFORM_ESPN, 10
        )
        self.assertEqual(result["user_roster"]["roster"].id, 10)

    def test_espn_missing_identity_does_not_use_username_fallback(self):
        with self.assertRaisesRegex(ValueError, "could not be matched"):
            self.run_trade(
                UserLeagueConnection.PLATFORM_ESPN, None
            )

    def test_sleeper_retains_legacy_username_fallback(self):
        result = self.run_trade(
            UserLeagueConnection.PLATFORM_SLEEPER, None
        )
        self.assertEqual(result["user_roster"]["roster"].id, 20)


    def test_explicit_espn_connection_overrides_first_connection(self):
        league = SimpleNamespace(
            id=1, season=2026, roster_positions=["QB"]
        )
        user = SimpleNamespace(get_username=lambda: "testuser")
        first_connection = SimpleNamespace(
            id=14, league_id=1, platform=UserLeagueConnection.PLATFORM_ESPN,
            external_user_id="2026:1",
        )
        selected_connection = SimpleNamespace(
            id=20, league_id=1, platform=UserLeagueConnection.PLATFORM_ESPN,
            external_user_id="2026:2",
        )
        rosters = [
            SimpleNamespace(
                id=10, owner_name="Team One",
                roster_players=SimpleNamespace(all=lambda: []),
            ),
            SimpleNamespace(
                id=20, owner_name="Team Two",
                roster_players=SimpleNamespace(all=lambda: []),
            ),
        ]
        roster_query = MagicMock()
        roster_query.prefetch_related.return_value.order_by.return_value = rosters

        with (
            patch("leagues.trades.trade_generator.UserLeagueConnection.objects.filter") as connections,
            patch("leagues.trades.trade_generator.FantasyRoster.objects.filter") as fantasy_rosters,
            patch("leagues.trades.trade_generator.FantasyProjection.objects.filter") as projections,
            patch("leagues.trades.trade_generator.DefenseProjection.objects.filter") as defenses,
            patch("leagues.trades.trade_generator.Teams.objects.in_bulk", return_value={}),
            patch("leagues.trades.trade_generator._build_bye_map", return_value={}),
            patch("leagues.trades.trade_generator.league_projection", return_value=0.0),
            patch("leagues.trades.trade_generator._optimized_roster_lineup", return_value=(0.0, [])),
            patch("leagues.trades.trade_generator.resolve_connection_roster") as resolver,
        ):
            connections.return_value.only.return_value.first.return_value = first_connection
            fantasy_rosters.return_value = roster_query
            projections.return_value.select_related.return_value = [
                SimpleNamespace(week=1, player_id=999, updated_at=None)
            ]
            defenses.return_value.select_related.return_value = []
            resolver.return_value = SimpleNamespace(id=20)

            result = build_trade_universe(
                league, user, current_week=1, connection=selected_connection
            )

        self.assertEqual(result["user_roster"]["roster"].id, 20)
        resolver.assert_called_once_with(selected_connection)
        connections.assert_not_called()


if __name__ == "__main__":
    unittest.main()
