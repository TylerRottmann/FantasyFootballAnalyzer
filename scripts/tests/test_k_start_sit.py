"""Kicker stat persistence, league scoring, lineup, and details integration."""
from io import StringIO
from unittest.mock import patch
from unittest import skipUnless
from django.core.management import call_command
from django.db import connection
from django.urls import reverse
from leagues.models import FantasyProjection, FantasyRosterPlayer
from scripts.algorithm.features.k_features import KSeasonData
from scripts.algorithm.predictor import predict_player
from scripts.tests import test_rb_start_sit as rb_fixture
from scripts.tests.test_k_algorithm import snapshot, game
from django.test import TestCase

@skipUnless(connection.vendor == "sqlite", "Use isolated scripts.tests.rb_test_settings.")
class KStartSitTests(TestCase):
    external_models = rb_fixture.RBStartSitTests.external_models
    @classmethod
    def setUpClass(cls):
        cls.created_models=[]
        existing=set(connection.introspection.table_names())
        with connection.schema_editor() as editor:
            for model in cls.external_models:
                if model._meta.db_table not in existing:
                    editor.create_model(model)
                    cls.created_models.append(model)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with connection.schema_editor() as editor:
            for model in reversed(cls.created_models):
                editor.delete_model(model)
    make_player = rb_fixture.RBStartSitTests.make_player
    page = rb_fixture.RBStartSitTests.page

    def setUp(self):
        rb_fixture.RBStartSitTests.setUp(self)
        self.league.roster_positions=['K','BN']
        self.league.scoring_settings={'fgm':3,'xpm':2,'fgmiss':-1}
        self.league.save()
        self.low.position='K'
        self.low.save()
        self.high.position='K'
        self.high.save()
        FantasyRosterPlayer.objects.filter(player=self.low).update(roster_slot='K')
        self.data=snapshot(season=2026,games=[
            game(1,player_id=self.low.id),game(2,player_id=self.low.id),
            game(1,player_id=self.high.id,pat_made=5),game(2,player_id=self.high.id),
        ])

    def generate(self):
        output=StringIO()
        with patch.object(KSeasonData,'load',return_value=self.data):
            expected={p.id:predict_player(p.id,2026,2,self.league.scoring_settings) for p in (self.low,self.high)}
            call_command('generate_projections',season=2026,week=2,stdout=output,stderr=StringIO())
        self.assertIn('Failed: 0',output.getvalue())
        for player in (self.low,self.high):
            stored=FantasyProjection.objects.get(player=player,season=2026,week=2)
            self.assertTrue(stored.projected_stats)
            self.assertEqual(stored.status,'ml_model')
        return expected

    def test_saved_model_stats_persist_and_page_uses_league_rules(self):
        expected=self.generate()
        response=self.page()
        self.assertEqual(response.status_code,200)
        for item in response.context['players']:
            self.assertEqual(item['prediction'].projected_fantasy_points,
                             expected[item['player'].id]['projected_fantasy_points'])
        stored=FantasyProjection.objects.get(player=self.low)
        reference=stored.projected_fantasy_points
        self.league.scoring_settings={'fgm':8,'xpm':4}
        self.league.save()
        changed=self.page()
        low=next(item for item in changed.context['players'] if item['player'].id==self.low.id)
        self.assertNotEqual(low['prediction'].projected_fantasy_points,expected[self.low.id]['projected_fantasy_points'])
        stored.refresh_from_db()
        self.assertEqual(stored.projected_fantasy_points,reference)
        self.assertEqual(changed.context['optimized_lineup'][0]['slot'],'K')

    def test_generation_idempotent_and_missing_scoring_does_not_use_reference(self):
        self.generate()
        self.generate()
        self.assertEqual(FantasyProjection.objects.count(),2)
        self.league.scoring_settings={}
        self.league.save()
        response=self.page()
        self.assertEqual(response.status_code,200)
        for item in response.context['players']:
            self.assertIsNone(item['prediction'].projected_fantasy_points)
            self.assertEqual(item['prediction'].status,'unsupported_scoring')

    def test_kicker_details_use_kicking_history(self):
        with patch.object(KSeasonData,'load',return_value=self.data):
            response=self.client.get(reverse('projection_details',args=[self.low.id]),{'week':2})
        self.assertEqual(response.status_code,200)
        details=response.json()
        self.assertEqual(details['position'],'K')
        stats={row['label']:row for row in details['player_stats']}
        self.assertEqual(stats['FG attempts']['last3'],2)
        self.assertEqual(stats['PAT made']['last3'],3)

    def test_rankings_and_team_breakdown_use_league_kicker_scores(self):
        from leagues.services.power_rankings import get_saved_power_rankings
        from leagues.services.team_breakdown import build_team_breakdown
        expected=self.generate()
        rows, average, generated=get_saved_power_rankings(self.league,self.user,2)
        best=max(r['projected_fantasy_points'] for r in expected.values())
        self.assertAlmostEqual(rows[0]['weeks'][0]['projected_points'],best)
        self.assertIn('K',rows[0]['position_averages'])
        details=build_team_breakdown(self.league,self.roster,2,rows,self.user)
        self.assertIn('K',details['position_codes'])
        player_rows={p['name']:p for p in details['players']}
        for player in (self.low,self.high):
            self.assertEqual(player_rows[player.full_name]['projected_points'],
                             round(expected[player.id]['projected_fantasy_points'],1))
