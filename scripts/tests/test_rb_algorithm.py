import os
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import django
import numpy as np

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "FantasyFootballAnalyzer.settings")
django.setup()

from scripts.algorithm.features.rb_features import RBSeasonData, build_rb_features, paired_rate
from scripts.algorithm.rb.feature_names import RB_FEATURE_NAMES
from scripts.algorithm.rb.rb_model import load_model, train_model
from scripts.algorithm.rb.rb_predictor import build_model_row, predict_rb
from scripts.algorithm.rb.train_rb_model import build_dataset, compare_baseline


def player_game(week, points=12, **changes):
    return {
        "player_id": 1, "week": week, "opponent_team": "LA",
        "carries": 10, "rushing_yards": 50, "rushing_tds": 0,
        "targets": 4, "receptions": 3, "receiving_yards": 20,
        "receiving_tds": 0, "fumbles_lost": 0, "fantasy_points_ppr": points,
        "team_carries": 20, "team_targets": 30, **changes,
    }


def team_game(week, team_id=10, opponent_id=20, **changes):
    return {
        "week": week, "team_id": team_id, "opponent_team_id": opponent_id,
        "is_home": True, "points_for": 24, "passing_yards": 200,
        "rushing_yards": 100, "total_yards": 300,
        "rb_fantasy_points_allowed": 15, "rushing_yards_against": 90,
        "passing_yards_against": 210, "points_against": 21,
        "total_yards_against": 300, **changes,
    }


def snapshot(player_games=None, team_games=None, schedules=None, season=2025):
    return RBSeasonData(
        season,
        player_games if player_games is not None else [player_game(1), player_game(2)],
        team_games if team_games is not None else [
            team_game(1), team_game(2), team_game(1, 20, 10), team_game(2, 20, 10),
        ],
        [{"id": 10, "abbreviation": "KC"}, {"id": 20, "abbreviation": "LAR"}],
        schedules or [],
    )


class RBFeaturesTests(TestCase):
    def setUp(self):
        # Current team differs from the recorded team to exercise historical context.
        self.player = SimpleNamespace(id=1, position="RB", team_id=99)

    def test_target_week_and_later_outcomes_do_not_change_features(self):
        before = build_rb_features(self.player, 2025, 2, snapshot())
        changed = snapshot(
            [player_game(1), player_game(2, 900, carries=500), player_game(3, 1000)],
            [team_game(1), team_game(2, points_for=900), team_game(3, points_for=1000),
             team_game(1, 20, 10), team_game(2, 20, 10, rb_fantasy_points_allowed=900)],
        )
        after = build_rb_features(self.player, 2025, 2, changed)
        for name in RB_FEATURE_NAMES:
            self.assertEqual(before[name], after[name], name)
        self.assertEqual(before["team_id"], 10)
        self.assertEqual(before["opponent_team"], "LAR")
        self.assertEqual(before["fantasy_points_l1"], 12)

    def test_workload_and_efficiency(self):
        features = build_rb_features(self.player, 2025, 2, snapshot())
        self.assertEqual(len(RB_FEATURE_NAMES), len(set(RB_FEATURE_NAMES)))
        self.assertTrue(all(name in features for name in RB_FEATURE_NAMES))
        self.assertEqual(features["touches_l1"], 13)
        self.assertEqual(features["opportunities_l1"], 14)
        self.assertEqual(features["rushing_yards_per_carry_l1"], 5)
        self.assertEqual(features["carry_share_l1"], 0.5)
        self.assertAlmostEqual(features["target_share_l1"], 4 / 30)
        self.assertEqual(features["catch_rate_l1"], 0.75)
        self.assertIsNone(features["fantasy_points_stddev_l3"])

    def test_rates_keep_missing_values_paired(self):
        games = [{"a": 2, "b": 4}, {"a": None, "b": 100}, {"a": 100, "b": None}]
        self.assertEqual(paired_rate(games, "a", "b"), 0.5)
        self.assertIsNone(paired_rate([{"a": 0, "b": 0}], "a", "b"))

    def test_missing_historical_context_is_not_a_bye(self):
        features = build_rb_features(self.player, 2025, 2, snapshot(team_games=[]))
        self.assertEqual(features["game_status"], "UNKNOWN")
        self.assertIsNone(features["team_id"])

    def test_schedule_recovers_recorded_matchup_without_current_team(self):
        data = snapshot(team_games=[], schedules=[{"week": 2, "home_team_id": 10, "away_team_id": 20}])
        features = build_rb_features(self.player, 2025, 2, data)
        self.assertEqual(features["game_status"], "GAME")
        self.assertEqual(features["team_id"], 10)
        self.assertIsNone(features["opponent_rb_fantasy_allowed_l3"])

    def test_schedule_and_bye_for_current_season(self):
        self.player.team_id = 10
        data = snapshot(player_games=[], season=date.today().year,
                        schedules=[{"week": week, "home_team_id": 10, "away_team_id": 20}
                                   for week in range(1, 19) if week != 3])
        self.assertEqual(build_rb_features(self.player, data.season, 2, data)["game_status"], "GAME")
        self.assertEqual(build_rb_features(self.player, data.season, 3, data)["game_status"], "BYE")
        data.schedules = []
        self.assertEqual(build_rb_features(self.player, data.season, 3, data)["game_status"], "UNKNOWN")

    def test_incomplete_schedule_does_not_create_false_bye(self):
        self.player.team_id = 10
        data = snapshot(player_games=[], season=date.today().year,
                        schedules=[{"week": 2, "home_team_id": 10, "away_team_id": 20}])
        self.assertEqual(build_rb_features(self.player, data.season, 3, data)["game_status"], "UNKNOWN")

    def test_game_id_recovers_missing_imported_matchup(self):
        data = snapshot(player_games=[player_game(1), player_game(2, game_id="2025_02_KC_LA")], team_games=[])
        features = build_rb_features(self.player, 2025, 2, data)
        self.assertEqual(features["game_status"], "GAME")
        self.assertEqual(features["team_id"], 10)
        self.assertFalse(features["is_home"])
        for invalid in ("2024_02_KC_LA", "2025_03_KC_LA", "2025_02_GB_LA", "2025_02_KC_GB", "invalid"):
            data.players[1][-1]["game_id"] = invalid
            self.assertEqual(build_rb_features(self.player, 2025, 2, data)["game_status"], "UNKNOWN")

    def test_no_current_roster_fallback_for_earlier_season(self):
        self.player.team_id = 10
        data = snapshot(player_games=[], season=date.today().year - 1,
                        schedules=[{"week": 2, "home_team_id": 10, "away_team_id": 20}])
        self.assertEqual(build_rb_features(self.player, data.season, 2, data)["game_status"], "UNKNOWN")

    def test_dataset_retains_zero_targets_and_skips_no_history(self):
        data = snapshot(player_games=[player_game(1), player_game(2, 0)])
        X, y, rows, counts = build_dataset(2025, {1: self.player}, data)
        self.assertEqual(X.shape, (1, len(RB_FEATURE_NAMES)))
        self.assertEqual(y.tolist(), [0.0])
        self.assertEqual(rows[0]["week"], 2)
        self.assertEqual(counts["no_history"], 1)

    def test_empty_dataset_has_consistent_shape(self):
        X, y, _, _ = build_dataset(2025, {}, snapshot())
        self.assertEqual(X.shape, (0, len(RB_FEATURE_NAMES)))
        self.assertEqual(y.shape, (0,))

    def test_model_row_order_and_nan(self):
        features = {name: index for index, name in enumerate(reversed(RB_FEATURE_NAMES))}
        features[RB_FEATURE_NAMES[0]] = None
        row = build_model_row(features)
        self.assertTrue(np.isnan(row[0, 0]))
        self.assertEqual(row[0, 1], features[RB_FEATURE_NAMES[1]])
        del features[RB_FEATURE_NAMES[1]]
        with self.assertRaises(KeyError):
            build_model_row(features)


class RBPredictorTests(TestCase):
    def setUp(self):
        self.player = SimpleNamespace(id=1, position="RB", team_id=10)
        self.features = build_rb_features(self.player, 2025, 2, snapshot())

    def result(self, features, model=None):
        with patch("scripts.algorithm.rb.rb_predictor.build_rb_features", return_value=features), \
             patch("scripts.algorithm.rb.rb_predictor.load_model", return_value=model), \
             patch("scripts.algorithm.rb.rb_predictor.predict", return_value=[14.567]):
            return predict_rb(self.player, 2025, 2)

    def test_statuses(self):
        self.assertEqual(self.result(self.features)["status"], "model_not_found")
        self.assertEqual(self.result({**self.features, "game_status": "UNKNOWN"})["status"], "matchup_not_found")
        self.assertEqual(self.result({**self.features, "games_played": 0}, object())["status"], "insufficient_history")
        bye = self.result({**self.features, "game_status": "BYE"})
        self.assertEqual((bye["status"], bye["projected_fantasy_points"]), ("bye", 0))
        result = self.result(self.features, object())
        self.assertEqual((result["status"], result["projected_fantasy_points"]), ("ml_model", 14.57))

    def test_shared_router_and_other_positions(self):
        from scripts.algorithm import predictor
        self.assertIs(predictor.PREDICTORS["RB"], predict_rb)
        for position in ("QB", "RB", "WR", "TE"):
            self.player.position = position
            with patch.object(predictor.Player.objects, "filter") as query, \
                 patch.dict(predictor.PREDICTORS, {position: lambda p, s, w: {"status": position}}):
                query.return_value.first.return_value = self.player
                self.assertEqual(predictor.predict_player(1, 2025, 2)["status"], position)
        self.player.position = "UNKNOWN"
        with patch.object(predictor.Player.objects, "filter") as query:
            query.return_value.first.return_value = self.player
            self.assertEqual(predictor.predict_player(1, 2025, 2)["status"], "placeholder")
            query.return_value.first.return_value = None
            self.assertIsNone(predictor.predict_player(1, 2025, 2))

    def test_model_round_trip_and_feature_order_guard(self):
        rng = np.random.default_rng(42)
        X = rng.normal(size=(60, len(RB_FEATURE_NAMES)))
        X[0, 0] = np.nan
        y = rng.normal(size=60)
        with tempfile.TemporaryDirectory() as directory, \
             patch("scripts.algorithm.rb.rb_model.MODEL_PATH", str(Path(directory) / "model.pkl")):
            self.assertIsNone(load_model())
            model = train_model(X, y, [2023, 2024, 2025])
            restored = load_model()
            np.testing.assert_allclose(model.predict(X), restored.predict(X))
            self.assertEqual(restored.rb_training_seasons_, [2023, 2024, 2025])
            with patch("scripts.algorithm.rb.rb_model.RB_FEATURE_NAMES", list(reversed(RB_FEATURE_NAMES))):
                with self.assertRaises(ValueError):
                    load_model()

    def test_baseline_uses_identical_rows(self):
        X = np.zeros((2, len(RB_FEATURE_NAMES)))
        X[:, RB_FEATURE_NAMES.index("fantasy_points_l3")] = [np.nan, 10]
        with patch("scripts.algorithm.rb.train_rb_model.predict", return_value=np.array([50, 12])):
            result = compare_baseline(object(), X, np.array([5, 11]))
        self.assertEqual(result["model_all_rows"]["predictions"], 2)
        self.assertEqual(result["model_baseline_rows"]["predictions"], 1)
        self.assertEqual(result["model_baseline_rows"]["mae"], 1)
        self.assertEqual(result["last_three_average"]["mae"], 1)

    def test_backtest_rejects_training_seasons(self):
        from scripts.algorithm.rb import backtest_rb_model
        with patch.object(backtest_rb_model, "load_model", return_value=SimpleNamespace(rb_training_seasons_=[2023, 2024, 2025])):
            with self.assertRaises(ValueError):
                backtest_rb_model.main(2025)
