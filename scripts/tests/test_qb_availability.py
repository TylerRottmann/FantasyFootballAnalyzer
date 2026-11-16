"""Backup-QB detection and partial-game filtering (ticket: optimize algorithms)."""
import os
from datetime import timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from scripts.algorithm.features.game_participation import (
    drop_partial_games, is_full_role_game, restrict_to_player_weeks,
)
from scripts.algorithm.features.qb_role import infer_backup


class PartialGameTests(TestCase):
    def test_snap_share_threshold_and_unknowns(self):
        self.assertTrue(is_full_role_game(None))        # unknown is kept, never guessed
        self.assertTrue(is_full_role_game(0.5))
        self.assertTrue(is_full_role_game(0.97))
        self.assertFalse(is_full_role_game(0.45))
        self.assertTrue(is_full_role_game(85))          # 0-100 percentages are tolerated
        self.assertFalse(is_full_role_game(40))

    def test_drop_partial_games_removes_the_game_he_left_hurt(self):
        # (week, attempts, snap_share): week 4 is the game Lamar left early
        rows = [(1, 28, 1.0), (2, 31, 0.99), (3, 25, 0.96), (4, 9, 0.31), (5, 30, 0.98)]
        kept = drop_partial_games(rows, share_index=2)
        self.assertEqual([r[0] for r in kept], [1, 2, 3, 5])

    def test_team_context_skips_games_the_qb_missed(self):
        team_rows = [(w, f"game{w}") for w in range(1, 9)]
        # QB played weeks 1-3 and 7-8; his backup started 4-6.
        kept = restrict_to_player_weeks(team_rows, {1, 2, 3, 7, 8})
        self.assertEqual([r[0] for r in kept], [1, 2, 3, 7, 8])

    def test_team_context_falls_back_when_too_little_remains(self):
        team_rows = [(w, f"game{w}") for w in range(1, 6)]
        self.assertEqual(restrict_to_player_weeks(team_rows, {5}), team_rows)
        self.assertEqual(restrict_to_player_weeks(team_rows, set()), team_rows)


def usage(*pairs):
    return {pid: dict(weeks) for pid, weeks in pairs}


class InferBackupTests(TestCase):
    STARTER_WEEKS = {1: 30, 2: 33, 3: 28, 4: 35}

    def test_backup_behind_clear_starter(self):
        data = usage((1, self.STARTER_WEEKS), (2, {2: 2, 4: 3}))
        is_backup, detail = infer_backup(data, player_id=2, week=5)
        self.assertTrue(is_backup, detail)
        self.assertEqual(detail["reason"], "backup_by_usage")

    def test_starter_is_not_flagged(self):
        data = usage((1, self.STARTER_WEEKS), (2, {2: 2}))
        self.assertEqual(infer_backup(data, 1, 5), (False, infer_backup(data, 1, 5)[1]))
        self.assertEqual(infer_backup(data, 1, 5)[1]["reason"], "is_starter")

    def test_qb_with_no_attempts_behind_a_clear_starter_is_a_backup(self):
        data = usage((1, self.STARTER_WEEKS), (2, {}))
        self.assertTrue(infer_backup(data, 2, 5)[0])

    def test_starter_returning_from_injury_is_not_zeroed(self):
        """Lamar case: out weeks 7-9, backup took every recent snap, but he is the real starter."""
        lamar = {1: 28, 2: 31, 3: 25, 4: 30, 5: 27, 6: 29}
        backup = {7: 30, 8: 33, 9: 28}
        is_backup, detail = infer_backup(usage((1, lamar), (2, backup)), player_id=1, week=10)
        self.assertFalse(is_backup, detail)
        self.assertEqual(detail["reason"], "meaningful_role")

    def test_backup_is_not_flagged_when_the_starter_is_out(self):
        data = usage((1, self.STARTER_WEEKS), (2, {2: 2, 4: 3}))
        is_backup, detail = infer_backup(data, 2, 5, blocked_ids={1})
        self.assertFalse(is_backup)
        self.assertEqual(detail["reason"], "starter_unavailable")

    def test_no_clear_starter_means_no_flag(self):
        data = usage((1, {1: 18, 2: 16, 3: 20}), (2, {1: 14, 2: 17, 3: 12}))
        self.assertFalse(infer_backup(data, 2, 4)[0])

    def test_too_little_history_means_no_flag(self):
        data = usage((1, {1: 30}), (2, {}))
        is_backup, detail = infer_backup(data, 2, 2)
        self.assertFalse(is_backup)
        self.assertEqual(detail["reason"], "not_enough_team_games")

    def test_only_games_before_the_target_week_are_used(self):
        # Week 5 data must not influence a prediction for week 5.
        data = usage((1, {1: 30, 2: 30, 3: 30}), (2, {5: 40}))
        self.assertTrue(infer_backup(data, 2, 5)[0])


class QuarterbackRoleTests(TestCase):
    """quarterback_role: depth chart first, usage fallback for future weeks/missing reports."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FantasyFootballAnalyzer.settings')
        django.setup()
        from django.utils import timezone
        from leagues.services import player_availability
        cls.pa, cls.timezone = player_availability, timezone

    def player(self):
        return SimpleNamespace(pk=2, position='QB', team_id=7)

    def report(self, depth, pk=2, injury='', hours_ago=1):
        return SimpleNamespace(player_id=pk, team_id=7, position='QB', depth_order=depth,
                               injury_status=injury, roster_status='Active',
                               observed_at=self.timezone.now() - timedelta(hours=hours_ago))

    def role(self, reports, week, *, active_week=7, is_live=None, backup_by_usage=False):
        with patch.object(self.pa, 'active_week_for_season', return_value=active_week), \
             patch.object(self.pa, 'live_week', side_effect=lambda s, w: w == active_week), \
             patch('scripts.algorithm.features.qb_role.usage_based_qb_backup',
                   return_value=backup_by_usage) as usage_check:
            result = self.pa.quarterback_role(self.player(), 2026, week, reports=reports, is_live=is_live)
        return result, usage_check

    def test_fresh_depth_chart_starter_never_reaches_the_fallback(self):
        result, usage_check = self.role({2: self.report(1)}, week=7, backup_by_usage=True)
        self.assertIsNone(result)
        usage_check.assert_not_called()

    def test_fresh_depth_chart_backup_stays_backup(self):
        reports = {2: self.report(2), 1: self.report(1, pk=1)}
        self.assertEqual(self.role(reports, week=7)[0], 'qb_backup')

    def test_future_week_backup_is_caught_by_usage(self):
        result, usage_check = self.role({}, week=9, backup_by_usage=True)
        self.assertEqual(result, 'qb_backup')
        usage_check.assert_called_once()

    def test_stale_depth_chart_falls_back_to_usage(self):
        result, _ = self.role({2: self.report(1, hours_ago=24 * 10)}, week=7, backup_by_usage=True)
        self.assertEqual(result, 'qb_backup')

    def test_future_week_starter_is_untouched(self):
        self.assertIsNone(self.role({}, week=9, backup_by_usage=False)[0])

    def test_past_weeks_are_never_rewritten(self):
        result, usage_check = self.role({}, week=5, backup_by_usage=True)
        self.assertIsNone(result)
        usage_check.assert_not_called()

    def test_non_qb_is_ignored(self):
        non_qb = SimpleNamespace(pk=3, position='WR', team_id=7)
        self.assertIsNone(self.pa.quarterback_role(non_qb, 2026, 9, reports={}))
