"""Database-free regression tests for Power Rankings team identification."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from leagues.services.power_rankings import get_saved_power_rankings


class PowerRankingsRosterSelectionTests(unittest.TestCase):

    def run_rankings(self, selected_roster_id):
        league = SimpleNamespace(
            id=1, season=2026, roster_positions=["QB"]
        )
        user = SimpleNamespace(id=42)

        rosters = []
        for roster_id in (10, 20):
            player = SimpleNamespace(
                id=roster_id + 100,
                position="QB",
                team_id=1,
            )
            entry = SimpleNamespace(
                id=roster_id + 200,
                player_id=player.id,
                team_id=None,
                player=player,
                team=None,
            )
            rosters.append(SimpleNamespace(
                id=roster_id,
                owner_name=f"Team {roster_id}",
                sleeper_roster_id=roster_id,
                roster_players=SimpleNamespace(all=lambda e=entry: [e]),
            ))

        roster_query = MagicMock()
        roster_query.prefetch_related.return_value.order_by.return_value = rosters

        updated_at = datetime(2026, 11, 1, tzinfo=timezone.utc)
        projections = [
            SimpleNamespace(
                player_id=roster.id + 100,
                week=1,
                updated_at=updated_at,
            )
            for roster in rosters
        ]

        with (
            patch("leagues.services.power_rankings.FantasyRoster.objects.filter") as roster_filter,
            patch("leagues.services.power_rankings.FantasyProjection.objects.filter") as projection_filter,
            patch("leagues.services.power_rankings.DefenseProjection.objects.filter") as defense_filter,
            patch("leagues.services.power_rankings.FantasyMatchup.objects.filter") as matchup_filter,
            patch("leagues.services.power_rankings.UserLeagueConnection.objects.filter") as connection_filter,
            patch("leagues.services.power_rankings.resolve_connection_roster") as resolver,
            patch("leagues.services.power_rankings.projection_context", return_value={}),
            patch("leagues.services.power_rankings.league_projection", return_value=10.0),
            patch("leagues.services.power_rankings.build_optimized_lineup") as optimizer,
            patch("leagues.services.power_rankings.get_projection", return_value=10.0),
        ):
            roster_filter.return_value = roster_query
            projection_filter.return_value.select_related.return_value = projections
            defense_filter.return_value.select_related.return_value = []
            matchup_filter.return_value.select_related.return_value = []

            connection = SimpleNamespace(platform="espn")
            connection_filter.return_value.first.return_value = connection
            resolver.return_value = (
                SimpleNamespace(id=selected_roster_id)
                if selected_roster_id is not None else None
            )

            def optimize(items, slots):
                return ([{"slot": "QB", "item": items[0]}], 10.0)

            optimizer.side_effect = optimize

            rows, _, _ = get_saved_power_rankings(
                league, user, current_week=1
            )
            return {row["roster_id"]: row["is_user_team"] for row in rows}

    def test_explicit_connection_controls_matchup_platform(self):
        """Standings must use the selected platform, not the first connection."""
        league = SimpleNamespace(
            id=1, season=2026, roster_positions=["QB"]
        )
        user = SimpleNamespace(id=42)
        player = SimpleNamespace(id=110, position="QB", team_id=1)
        entry = SimpleNamespace(
            id=210, player_id=110, team_id=None,
            player=player, team=None,
        )
        roster = SimpleNamespace(
            id=10, owner_name="ESPN Team",
            sleeper_roster_id=10,
            roster_players=SimpleNamespace(all=lambda: [entry]),
        )
        projection = SimpleNamespace(
            player_id=110, week=1,
            updated_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        )
        selected = SimpleNamespace(platform="espn")

        with (
            patch("leagues.services.power_rankings.FantasyRoster.objects.filter") as rosters,
            patch("leagues.services.power_rankings.FantasyProjection.objects.filter") as projections,
            patch("leagues.services.power_rankings.DefenseProjection.objects.filter") as defenses,
            patch("leagues.services.power_rankings.FantasyMatchup.objects.filter") as matchups,
            patch("leagues.services.power_rankings.UserLeagueConnection.objects.filter") as connections,
            patch("leagues.services.power_rankings.resolve_connection_roster", return_value=roster),
            patch("leagues.services.power_rankings.projection_context", return_value={}),
            patch("leagues.services.power_rankings.league_projection", return_value=10.0),
            patch("leagues.services.power_rankings.build_optimized_lineup",
                  return_value=([{"slot": "QB", "item": {"roster_player": entry,
                      "player": player, "prediction": 10.0}}], 10.0)),
            patch("leagues.services.power_rankings.get_projection", return_value=10.0),
        ):
            rosters.return_value.prefetch_related.return_value.order_by.return_value = [roster]
            projections.return_value.select_related.return_value = [projection]
            defenses.return_value.select_related.return_value = []
            matchups.return_value.select_related.return_value = []
            connections.return_value.first.return_value = SimpleNamespace(platform="sleeper")

            get_saved_power_rankings(
                league, user, current_week=1, connection=selected
            )

            self.assertEqual(matchups.call_args.kwargs["platform"], "espn")
            connections.assert_not_called()

    def test_espn_marks_selected_team_only(self):
        result = self.run_rankings(20)
        self.assertEqual(result, {10: False, 20: True})

    def test_other_espn_team_can_be_selected(self):
        result = self.run_rankings(10)
        self.assertEqual(result, {10: True, 20: False})

    def test_missing_identity_marks_no_team(self):
        result = self.run_rankings(None)
        self.assertEqual(result, {10: False, 20: False})


if __name__ == "__main__":
    unittest.main()
