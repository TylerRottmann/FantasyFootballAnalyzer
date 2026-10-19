# Database-free tests for the D/ST algorithm.
#   python -m unittest scripts.tests.test_dst_algorithm

import unittest

import numpy as np

from scripts.algorithm.dst.dst_model import create_model
from scripts.algorithm.dst.feature_names import DST_FEATURE_NAMES
from scripts.algorithm.dst.scoring import dst_fantasy_points, points_allowed_score
from scripts.algorithm.features.dst_features import compute_dst_features

CONTEXT = {"game_status": "GAME", "opponent_team_id": 2, "is_home": True}


def make_rows(n):
    dst = [(w, float(w), 2, 1, 1, 0, 20, 300) for w in range(1, n + 1)]
    off = [(w, 20, 300, 200, 2, 1) for w in range(1, n + 1)]
    return dst, off


class ScoringTests(unittest.TestCase):
    def test_points_allowed_tiers(self):
        expected = {0: 10, 3: 7, 10: 4, 17: 1, 24: 0, 31: -1, 45: -4}
        for points, score in expected.items():
            self.assertEqual(points_allowed_score(points), score)

    def test_full_line(self):
        # 3 sacks, 1 INT, 1 fumble rec, 1 TD, 13 allowed
        self.assertEqual(
            dst_fantasy_points(3, 1, 1, 0, 1, 13), 3 + 2 + 2 + 6 + 4
        )


class FeatureTests(unittest.TestCase):
    def test_every_named_feature_is_produced(self):
        dst, off = make_rows(10)
        f = compute_dst_features(dst, off, off, CONTEXT)
        missing = [n for n in DST_FEATURE_NAMES if n not in f]
        self.assertEqual(missing, [])

    def test_no_duplicate_feature_names(self):
        self.assertEqual(len(DST_FEATURE_NAMES), len(set(DST_FEATURE_NAMES)))

    def test_windows_use_only_given_history(self):
        dst, off = make_rows(10)  # points 1..10
        f = compute_dst_features(dst, off, off, CONTEXT)
        self.assertEqual(f["dst_fantasy_points_l1"], 10)
        self.assertEqual(f["dst_fantasy_points_l3"], 9)
        self.assertEqual(f["dst_fantasy_points_season"], 5.5)
        self.assertEqual(f["games_played"], 10)
        self.assertEqual(f["games_played_l8"], 8)

    def test_early_season_does_not_crash(self):
        dst, off = make_rows(1)
        f = compute_dst_features(dst, off, off, CONTEXT)
        self.assertIsNone(f["dst_fantasy_points_stddev_l3"])

    def test_missing_values_become_none(self):
        dst = [(1, None, None, None, None, 0, None, None)]
        f = compute_dst_features(dst, [], [], CONTEXT)
        self.assertIsNone(f["sacks_l3"])
        self.assertIsNone(f["opponent_points_for_l3"])


class ModelSmokeTest(unittest.TestCase):
    def test_model_fits_with_nans(self):
        rng = np.random.default_rng(0)
        X = rng.normal(size=(300, len(DST_FEATURE_NAMES)))
        X[::7, 0] = np.nan
        y = X[:, 1] * 2 + rng.normal(size=300)
        pred = create_model().fit(X, y).predict(X[:5])
        self.assertEqual(pred.shape, (5,))


if __name__ == "__main__":
    unittest.main()
