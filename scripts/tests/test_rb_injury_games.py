"""RB injury-shortened game filtering (ticket: optimize algorithms)."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.algorithm.features.rb_features import RBSeasonData, build_rb_features

SEASON = 2025


def game(week, carries, share):
    return {
        "player_id": 44, "week": week, "game_id": f"2025_{week:02d}_BBB_AAA",
        "opponent_team": "BBB", "fantasy_points_ppr": 12.0,
        "passing_yards": 0, "passing_tds": 0, "passing_interceptions": 0,
        "passing_2pt_conversions": 0,
        "carries": carries, "rushing_yards": carries * 4, "rushing_tds": 0,
        "rushing_2pt_conversions": 0,
        "targets": 3, "receptions": 2, "receiving_yards": 15, "receiving_tds": 0,
        "receiving_2pt_conversions": 0, "fumbles_lost": 0,
        "team_carries": 25, "team_targets": 30,
        "offense_snap_share": share,
        "red_zone_targets": 1, "red_zone_rushes": 1, "goal_line_carries": 0,
        "team_offensive_plays": 65, "team_offensive_dropbacks": 35,
    }


def season_data(player_games, weeks):
    team_games = [{
        "team_id": team, "week": w, "opponent_team_id": opp, "is_home": team == 1,
        "points_for": 24, "passing_yards": 240, "rushing_yards": 120, "total_yards": 360,
        "rb_fantasy_points_allowed": 18, "rushing_yards_against": 110,
        "passing_yards_against": 220, "points_against": 20, "total_yards_against": 330,
        "offensive_plays": 65, "offensive_dropbacks": 35, "red_zone_trips": 4, "sacks": 2,
        "interceptions": 1, "turnovers_forced": 2,
        "opponent_offensive_plays": 60, "opponent_offensive_dropbacks": 32,
    } for w in weeks for team, opp in ((1, 2), (2, 1))]
    return RBSeasonData(
        SEASON, player_games, team_games,
        [{"id": 1, "abbreviation": "AAA"}, {"id": 2, "abbreviation": "BBB"}],
        [{"week": w, "home_team_id": 1, "away_team_id": 2} for w in weeks],
    )


def features_for(player_games, week):
    weeks = sorted({g["week"] for g in player_games} | {week})
    player = SimpleNamespace(id=44, team_id=1, position="RB")
    with patch("scripts.algorithm.features.player_priors.build_player_prior_features",
               return_value={"prior_season_games": 8}):
        return build_rb_features(player, SEASON, week, data=season_data(player_games, weeks))


class RBInjuryShortenedHistoryTests(unittest.TestCase):
    def test_game_he_left_hurt_is_not_counted(self):
        # usual workload ~16 carries at ~70% snaps; week 4 he got 2 carries on 20% snaps
        games = [game(1, 16, 0.70), game(2, 17, 0.68), game(3, 15, 0.72), game(4, 2, 0.20),
                 game(5, 16, 0.70), game(6, 18, 0.69), game(7, 16, 0.71)]
        features = features_for(games, week=8)
        self.assertEqual(features["games_played"], 6)
        self.assertAlmostEqual(features["carries_season"], (16 + 17 + 15 + 16 + 18 + 16) / 6)

    def test_committee_back_keeps_every_game(self):
        # ~40% snap share is his normal role; none of these games are shortened
        games = [game(1, 9, 0.42), game(2, 7, 0.38), game(3, 10, 0.45), game(4, 6, 0.33),
                 game(5, 8, 0.40), game(6, 9, 0.41)]
        features = features_for(games, week=7)
        self.assertEqual(features["games_played"], 6)

    def test_unknown_snap_share_keeps_the_game(self):
        games = [game(1, 16, 0.70), game(2, 17, 0.68), game(3, 15, None), game(4, 16, 0.70)]
        self.assertEqual(features_for(games, week=5)["games_played"], 4)

    def test_target_week_never_influences_the_filter(self):
        games = [game(1, 16, 0.70), game(2, 17, 0.68), game(3, 15, 0.72), game(4, 16, 0.70)]
        normal_target = features_for(games + [game(5, 16, 0.70)], week=5)
        # Same history, but the target-week game itself is a shortened one.
        shortened_target = features_for(games + [game(5, 1, 0.05)], week=5)
        self.assertEqual(normal_target, shortened_target)


if __name__ == "__main__":
    unittest.main()
