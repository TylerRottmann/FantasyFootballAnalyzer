"""Regression tests for Boom/Bust feature leakage."""

import unittest

from leagues.models import Player
from scripts.algorithm.features.rb_features import (
    RBSeasonData,
    build_rb_features,
)


class TestRBFeatureLeakage(unittest.TestCase):

    def test_target_week_performance_does_not_change_features(self):
        """Target-week outcomes must not affect pregame features."""
        player = Player.objects.get(id=44)
        season = 2025
        week = 10

        data = RBSeasonData.load(season)
        before = build_rb_features(player, season, week, data=data)

        self.assertEqual(before["game_status"], "GAME")

        excluded = {
            "player_id",
            "week",
            "game_id",
            "opponent_team",
            "team_id",
            "opponent_team_id",
            "is_home",
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
