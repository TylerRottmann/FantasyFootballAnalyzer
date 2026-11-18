import os
from itertools import product
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FantasyFootballAnalyzer.test_settings')
django.setup()

from analyzer import waiver_moves
from analyzer.waiver_predictions import WaiverPrediction


class WaiverLineupPerformanceTests(TestCase):
    def rows(self):
        return [{'player': SimpleNamespace(position=position),
                 'prediction': WaiverPrediction(points, points)}
                for position, points in [('QB', 20), ('RB', 12), ('WR', 11), ('TE', -1), ('RB', 9)]]

    def test_known_lineups_match_exhaustive_assignments_with_flex(self):
        rows = self.rows()
        slots = ['QB', 'RB', 'FLEX', 'SUPER_FLEX']
        expected = {}
        choices = [[0] + waiver_moves._slot_bits(row, slots) for row in rows]
        for assignment in product(*choices):
            assigned = [bit for bit in assignment if bit]
            if len(set(assigned)) != len(assigned):
                continue
            mask = sum(assigned)
            score = sum(row['prediction'].this_week for row, bit in zip(rows, assignment) if bit)
            expected[mask] = max(expected.get(mask, float('-inf')), score)
        with patch.object(waiver_moves, '_slot_bits', wraps=waiver_moves._slot_bits) as eligibility:
            actual = waiver_moves._known_scores(rows, slots, 'this_week')
        self.assertEqual(actual, expected)
        self.assertEqual(eligibility.call_count, len(rows))

    def test_unknown_players_keep_all_possible_reservations(self):
        rows = self.rows()
        for row in rows:
            row['prediction'] = WaiverPrediction(None, None)
        slots = ['QB', 'RB', 'FLEX', 'SUPER_FLEX']
        choices = [[0] + waiver_moves._slot_bits(row, slots) for row in rows]
        expected = {sum(bits) for assignment in product(*choices)
                    if len(bits := [bit for bit in assignment if bit]) == len(set(bits))}
        with patch.object(waiver_moves, '_slot_bits', wraps=waiver_moves._slot_bits) as eligibility:
            actual = waiver_moves._unknown_masks(rows, slots, 'this_week')
        self.assertEqual(actual, expected)
        self.assertEqual(eligibility.call_count, len(rows))
