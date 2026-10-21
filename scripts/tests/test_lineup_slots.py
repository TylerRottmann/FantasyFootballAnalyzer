from types import SimpleNamespace
from unittest import TestCase
from scripts.commands.lineup import build_optimized_lineup


def player(position, points, player_id=1):
    return {'player':SimpleNamespace(position=position,id=player_id),
            'prediction':{'projected_fantasy_points':points},
            'roster_player':SimpleNamespace(id=player_id)}


class RequiredLineupSlotsTests(TestCase):
    def test_zero_point_player_still_fills_eligible_slot(self):
        item=player('QB',0)
        lineup,total=build_optimized_lineup([item],['QB'])
        self.assertIs(lineup[0]['item'],item)
        self.assertEqual(total,0)

    def test_negative_kicker_score_does_not_make_slot_empty(self):
        item=player('K',-1)
        lineup,total=build_optimized_lineup([item],['K'])
        self.assertIs(lineup[0]['item'],item)
        self.assertEqual(total,-1)

    def test_best_complete_lineup_is_chosen_without_reusing_player(self):
        rb=player('RB',5,1)
        wr=player('WR',10,2)
        lineup,total=build_optimized_lineup([rb,wr],['RB','FLEX'])
        self.assertIs(lineup[0]['item'],rb)
        self.assertIs(lineup[1]['item'],wr)
        self.assertEqual(total,15)

    def test_missing_position_remains_empty(self):
        lineup,total=build_optimized_lineup([player('K',8)],['QB','K'])
        self.assertIsNone(lineup[0]['item'])
        self.assertEqual(total,8)
