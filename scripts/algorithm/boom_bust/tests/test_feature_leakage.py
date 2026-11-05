"""Regression tests for Boom/Bust feature leakage."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.algorithm.features.rb_features import (
    RBSeasonData,
    build_rb_features,
)


class TestRBFeatureLeakage(unittest.TestCase):

    def test_target_week_performance_does_not_change_features(self):
        """Target-week outcomes must not affect pregame features."""
        player = SimpleNamespace(id=44, team_id=1, position="RB")
        season, week = 2025, 10

        player_games = []
        team_games = []

        for w in (8, 9, 10):
            player_games.append({
                "player_id": 44, "week": w,
                "game_id": f"2025_{w:02d}_BBB_AAA",
                "opponent_team": "BBB",
                "fantasy_points_ppr": 12.0,
                "passing_yards": 0, "passing_tds": 0,
                "passing_interceptions": 0,
                "passing_2pt_conversions": 0,
                "carries": 12, "rushing_yards": 65,
                "rushing_tds": 1, "rushing_2pt_conversions": 0,
                "targets": 4, "receptions": 3,
                "receiving_yards": 25, "receiving_tds": 0,
                "receiving_2pt_conversions": 0,
                "fumbles_lost": 0,
                "team_carries": 25, "team_targets": 30,
                "offense_snap_share": 0.65,
                "red_zone_targets": 1, "red_zone_rushes": 2,
                "goal_line_carries": 1,
                "team_offensive_plays": 65,
                "team_offensive_dropbacks": 35,
            })

            for team_id, opponent_id in ((1, 2), (2, 1)):
                team_games.append({
                    "team_id": team_id, "week": w,
                    "opponent_team_id": opponent_id,
                    "is_home": team_id == 1,
                    "points_for": 24, "passing_yards": 240,
                    "rushing_yards": 120, "total_yards": 360,
                    "rb_fantasy_points_allowed": 18,
                    "rushing_yards_against": 110,
                    "passing_yards_against": 220,
                    "points_against": 20,
                    "total_yards_against": 330,
                    "offensive_plays": 65,
                    "offensive_dropbacks": 35,
                    "red_zone_trips": 4, "sacks": 2,
                    "interceptions": 1, "turnovers_forced": 2,
                    "opponent_offensive_plays": 60,
                    "opponent_offensive_dropbacks": 32,
                })

        data = RBSeasonData(
            season, player_games, team_games,
            [{"id": 1, "abbreviation": "AAA"},
             {"id": 2, "abbreviation": "BBB"}],
            [{"week": w, "home_team_id": 1, "away_team_id": 2}
             for w in (8, 9, 10)],
        )

        with patch(
            "scripts.algorithm.features.player_priors.build_player_prior_features",
            return_value={"prior_season_games": 8},
        ):
            before = build_rb_features(player, season, week, data=data)
            self.assertEqual(before["game_status"], "GAME")

            excluded = {
                "player_id", "week", "game_id", "opponent_team",
                "team_id", "opponent_team_id", "is_home",
            }

            modified = 0

            for game in data.players[player.id]:
                if game["week"] >= week:
                    for key, value in game.items():
                        if (
                            key not in excluded
                            and isinstance(value, (int, float))
                            and not isinstance(value, bool)
                        ):
                            game[key] = 999999
                            modified += 1

            for games in data.team_games.values():
                for game in games:
                    if game["week"] >= week:
                        for key, value in game.items():
                            if (
                                key not in excluded
                                and isinstance(value, (int, float))
                                and not isinstance(value, bool)
                            ):
                                game[key] = 999999
                                modified += 1

            self.assertGreater(modified, 0)
            after = build_rb_features(player, season, week, data=data)
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
