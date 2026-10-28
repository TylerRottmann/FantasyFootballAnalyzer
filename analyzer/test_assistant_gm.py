from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from analyzer import assistant_gm as gm


class DetectPositionTests(SimpleTestCase):
    def test_plural_and_phrase_forms(self):
        self.assertEqual(gm._detect_position("best waiver WRs?"), "WR")
        self.assertEqual(gm._detect_position("top tight ends this week"), "TE")
        self.assertEqual(gm._detect_position("best defense to stream"), "DST")

    def test_no_position(self):
        self.assertIsNone(gm._detect_position("how is my team doing"))


class ScoringNoteTests(SimpleTestCase):
    def test_note_only_for_non_ppr_league(self):
        self.assertEqual(gm._scoring_note(gm.ChatContext(league=SimpleNamespace(ppr=1))), "")
        self.assertIn("0.5", gm._scoring_note(gm.ChatContext(league=SimpleNamespace(ppr=0.5))))


class RoutingTests(SimpleTestCase):
    def test_which_is_not_a_greeting(self):
        ctx = gm.ChatContext(week=8, season=2026)
        with mock.patch.object(gm, "_build_context", return_value=ctx), \
             mock.patch.object(gm, "_find_players_in_question", return_value=[]), \
             mock.patch.object(gm, "_answer_my_lineup", return_value="LINEUP") as lineup:
            self.assertEqual(gm.answer_question("Which of my lineup should I change?"), "LINEUP")
            lineup.assert_called_once()
