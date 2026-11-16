"""WR/TE injury-shortened game filtering (ticket: optimize algorithms)."""
from unittest import TestCase

from scripts.algorithm.features.game_participation import (
    MIN_BASELINE_GAMES, MIN_BASELINE_SHARE, RELATIVE_SNAP_FRACTION,
    drop_injury_shortened_games, skill_games_sql,
)


def rows(*shares):
    """(week, ..., snap_share) rows; snap share sits at index 2 here."""
    return [(week, 5, share) for week, share in enumerate(shares, start=1)]


class InjuryShortenedGameTests(TestCase):
    def weeks(self, data, **kwargs):
        return [r[0] for r in drop_injury_shortened_games(data, share_index=2, **kwargs)]

    def test_normal_wr3_games_are_kept(self):
        # A WR3 at ~45% snaps is not hurt; a flat 50% cutoff would have erased these.
        self.assertEqual(self.weeks(rows(0.45, 0.50, 0.42, 0.48, 0.44)), [1, 2, 3, 4, 5])

    def test_wr1_game_he_left_early_is_dropped(self):
        # usual share ~0.90; week 3 he played 22% -> shortened
        self.assertEqual(self.weeks(rows(0.92, 0.88, 0.22, 0.90, 0.95)), [1, 2, 4, 5])

    def test_cutoff_is_relative_to_his_own_median(self):
        # 0.30 is shortened for a 0.90 player (cutoff 0.36) but normal for a 0.50 player (cutoff 0.20)
        self.assertEqual(self.weeks(rows(0.90, 0.92, 0.30, 0.88)), [1, 2, 4])
        self.assertEqual(self.weeks(rows(0.50, 0.52, 0.30, 0.48)), [1, 2, 3, 4])

    def test_fringe_players_are_left_alone(self):
        self.assertEqual(self.weeks(rows(0.10, 0.25, 0.02, 0.15)), [1, 2, 3, 4])

    def test_too_little_history_keeps_everything(self):
        self.assertEqual(self.weeks(rows(0.9, 0.1)), [1, 2])

    def test_unknown_snap_share_is_kept(self):
        data = [(1, 5, 0.9), (2, 5, None), (3, 5, 0.92), (4, 5, 0.88)]
        self.assertEqual(self.weeks(data), [1, 2, 3, 4])

    def test_percent_scale_is_tolerated(self):
        self.assertEqual(self.weeks(rows(92, 88, 22, 90)), [1, 2, 4])

    def test_even_number_of_games_uses_the_true_median(self):
        # median of [0.2, 0.9, 0.9, 0.95] = 0.9 -> cutoff 0.36 drops only the 0.2 game
        self.assertEqual(self.weeks(rows(0.9, 0.2, 0.95, 0.9)), [1, 3, 4])


class TrainingQueryTests(TestCase):
    def test_returns_the_columns_the_training_scripts_unpack(self):
        sql, params = skill_games_sql(2025, [1, 2, 3])
        # player_id, week + 14 COALESCE stat columns = the 16 the WR/TE scripts expect
        self.assertEqual(sql.count("COALESCE(b."), 14)
        self.assertIn("b.player_id,", sql)
        self.assertIn("b.week,", sql)

    def test_parameters_line_up_with_placeholders(self):
        sql, params = skill_games_sql(2025, [1, 2, 3])
        self.assertEqual(sql.count("%s"), len(params))
        self.assertEqual(params, (2025, [1, 2, 3], MIN_BASELINE_GAMES,
                                  MIN_BASELINE_SHARE, RELATIVE_SNAP_FRACTION))

    def test_skips_only_games_well_below_the_players_own_baseline(self):
        sql, _ = skill_games_sql(2025, [1])
        self.assertIn("b.snap >= m.median_snap * %s", sql)
        self.assertIn("b.snap IS NULL", sql)  # unknown share is kept
