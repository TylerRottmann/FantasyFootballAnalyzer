"""Database-free regression tests for SCRUM-39 Boom/Bust v2."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts.algorithm.boom_bust import (
    boom_bust_availability_v2 as availability,
    boom_bust_history_v2 as history,
    boom_bust_predict_v2 as predictor,
)


class BoomBustV2RegressionTests(unittest.TestCase):

    def test_scoring_history_excludes_target_week(self):
        player = SimpleNamespace(id=326, position="QB")
        cursor = MagicMock()
        cursor.fetchall.return_value = [(6, 18.5), (7, 21.0)]
        manager = MagicMock()
        manager.__enter__.return_value = cursor

        with patch.object(history.connection, "cursor", return_value=manager):
            result = history.load_previous_points(player, 2026, 9)

        self.assertEqual(result, [18.5, 21.0])
        sql, params = cursor.execute.call_args.args
        self.assertIn("week < %s", sql)
        self.assertEqual(params, [326, 2026, 9])

    def test_availability_cutoffs(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = [(8, 0.8), (7, 0.6)]
        manager = MagicMock()
        manager.__enter__.return_value = cursor

        cutoff = datetime(2026, 11, 4, tzinfo=timezone.utc)

        with patch.object(
            availability.connection, "cursor", return_value=manager
        ):
            result = availability.load_availability_context_v2(
                326, 2026, 9, cutoff
            )

        calls = cursor.execute.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertIn("observed_at < %s", calls[0].args[0])
        self.assertIn("week < %s", calls[1].args[0])
        self.assertIn("imported_at < %s", calls[1].args[0])
        self.assertEqual(result["snap_history_count"], 2)

    def test_unavailable_player_rejected(self):
        for injury, roster in [
            ("Out", "Inactive"),
            ("IR", "Inactive"),
            ("Suspended", "Active"),
        ]:
            with self.subTest(injury=injury, roster=roster):
                with self.assertRaises(
                    predictor.PlayerUnavailableForPrediction
                ):
                    predictor.validate_player_availability_v2({
                        "injury_status": injury,
                        "roster_status": roster,
                    })

    def test_questionable_player_allowed(self):
        predictor.validate_player_availability_v2({
            "injury_status": "Questionable",
            "roster_status": "Active",
        })

    def test_feature_schema_validation(self):
        features = {"a": 1.0, "b": 2.0}
        frame = predictor.prepare_prediction_frame(
            features, ["b", "a"]
        )
        self.assertEqual(list(frame.columns), ["b", "a"])
        self.assertEqual(frame.iloc[0].tolist(), [2.0, 1.0])

        with self.assertRaises(ValueError):
            predictor.prepare_prediction_frame(
                features, ["a", "missing"]
            )

        with self.assertRaises(ValueError):
            predictor.prepare_prediction_frame(
                features, ["a", "a"]
            )

    def test_invalid_prediction_inputs(self):
        player = SimpleNamespace(id=326, position="QB")

        for season, week in [(1999, 9), (2026, 0), (2026, 19)]:
            with self.subTest(season=season, week=week):
                with self.assertRaises(ValueError):
                    predictor.predict_boom_bust_v2(
                        player, season, week
                    )


if __name__ == "__main__":
    unittest.main()
