import os
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import django
import numpy as np
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FantasyFootballAnalyzer.settings')
django.setup()
from scripts.algorithm.features.k_features import KSeasonData, build_k_features
from scripts.algorithm.k.feature_names import K_FEATURE_NAMES, TARGETS, PLAYER_STATS
from scripts.algorithm.k.k_predictor import build_model_row, predict_k
from scripts.algorithm.k.k_model import train_model, load_model, predict
from scripts.algorithm.k.scoring import REFERENCE_SCORING, score_kicking
from scripts.algorithm.k.train_k_model import build_dataset, metrics
from scripts.imports.prepare_kicker_data import normalize_stats
from leagues.services.kicker_scoring import league_projection

def game(week, **changes):
    return {**dict.fromkeys(PLAYER_STATS, 0), 'player_id': 1, 'week': week,
            'season': 2025, 'source_team': 'KC', 'opponent_team': 'LA',
            'fg_att': 2, 'fg_made': 2, 'fg_made_40_49': 2, 'fg_made_distance': 84,
            'pat_att': 3, 'pat_made': 3, 'fg_made_yards_over_30': 24, **changes}

def team(week, tid=10, oid=20, **changes):
    return {'week': week, 'team_id': tid, 'opponent_team_id': oid, 'is_home': True,
            'points_for': 24, 'total_yards': 350, 'kicking_points_for': 9,
            'points_against': 20, 'total_yards_against': 300, 'kicking_points_against': 6, **changes}

def snapshot(games=None, teams=None, schedules=None, season=2025):
    return KSeasonData(season, games if games is not None else [game(1),game(2)],
                       teams if teams is not None else [team(1),team(2),team(1,20,10),team(2,20,10)],
                       [{'id':10,'abbreviation':'KC'},{'id':20,'abbreviation':'LAR'}], schedules or [])

class KFeaturesTests(TestCase):
    def setUp(self): self.player=SimpleNamespace(id=1,team_id=99,position='K')

    def test_no_target_week_or_future_performance_leakage(self):
        a=build_k_features(self.player,2025,2,snapshot())
        b=build_k_features(self.player,2025,2,snapshot(
            [game(1),game(2,fg_att=900,fg_made=800),game(3,fg_att=999)],
            [team(1),team(2,points_for=999),team(1,20,10),team(2,20,10,kicking_points_against=999)]))
        for name in K_FEATURE_NAMES: self.assertEqual(a[name],b[name],name)
        self.assertEqual(a['team_id'],10)
        self.assertEqual(a['opponent_team'],'LAR')
        self.assertEqual(a['fg_rate_l3'],1)
        self.assertEqual(a['games_played'],1)

    def test_source_team_recovers_incomplete_historical_schedule(self):
        f=build_k_features(self.player,2025,2,snapshot(teams=[]))
        self.assertEqual(f['game_status'],'GAME')
        self.assertEqual(f['team_id'],10)
        self.assertIsNone(f['is_home'])

    def test_missing_stats_stay_missing(self):
        f=build_k_features(self.player,2025,2,snapshot([game(1,fg_att=None),game(2)]))
        self.assertIsNone(f['fg_rate_l3'])
        self.assertTrue(np.isnan(build_model_row(f)[0,K_FEATURE_NAMES.index('fg_att_l3')]))

    def test_week_and_snapshot_validation(self):
        for week in (0,19):
            with self.assertRaises(ValueError): build_k_features(self.player,2025,week,snapshot())
        with self.assertRaises(ValueError): build_k_features(self.player,2024,2,snapshot())

    def test_bye_requires_complete_current_schedule(self):
        self.player.team_id=10
        schedules=[{'week':w,'home_team_id':10,'away_team_id':20} for w in range(1,19) if w!=5]
        d=snapshot(games=[],teams=[],schedules=schedules,season=date.today().year)
        self.assertEqual(d.game_context(self.player,5)['game_status'],'BYE')
        d=snapshot(games=[],teams=[],schedules=schedules[:2],season=date.today().year)
        self.assertEqual(d.game_context(self.player,5)['game_status'],'UNKNOWN')

    def test_zero_target_retained_and_first_game_excluded(self):
        d=snapshot([game(1),game(2,**dict.fromkeys(PLAYER_STATS,0))])
        X,y,baseline,rows,counts=build_dataset(2025,{1:self.player},d)
        self.assertEqual(len(y),1)
        self.assertTrue((y[0]==0).all())
        self.assertEqual(counts['no_history'],1)
        self.assertEqual(rows,[{'player_id':1,'week':2}])
        self.assertEqual(len(K_FEATURE_NAMES),len(set(K_FEATURE_NAMES)))

class KScoringTests(TestCase):
    def setUp(self): self.stats={n:game(1)[n] for n in TARGETS}

    def test_reference_and_custom_league(self):
        self.assertEqual(score_kicking(self.stats,REFERENCE_SCORING),11)
        self.assertEqual(score_kicking(self.stats,{'fgm':3,'xpm':2}),12)
        self.assertAlmostEqual(score_kicking(self.stats,{'fgm_yds':0.1,'xpm':0}),8.4)
        self.assertAlmostEqual(score_kicking(self.stats,{'fgm_yds_over_30':0.1}),2.4)

    def test_generic_and_distance_bonuses_stack(self):
        self.stats.update(fg_made_50_59=1,fg_made_60_=1)
        self.assertEqual(score_kicking(self.stats,{'fgm':1,'fgm_50p':2,'fgm_60p':3}),11)

    def test_blocked_attempts_normalized_once_including_distance(self):
        row=game(1,fg_missed=1,fg_missed_40_49=1,fg_blocked=1,fg_blocked_list='45',fg_made_list='42;42',pat_blocked=1)
        stats=normalize_stats(row)
        self.assertEqual(stats['fg_missed_40_49'],2)
        self.assertEqual(stats['fg_missed'],2)
        self.assertEqual(stats['pat_missed'],1)
        self.assertEqual(score_kicking(stats,{'fgmiss':-1,'fgmiss_40_49':-2,'xpmiss':-1}),-7)

    def test_unsupported_rules_do_not_fall_back(self):
        for settings in ({},{'yahoo':{}},{'fgm_unknown_bonus':1},{'xpm':float('nan')}):
            with self.assertRaises(ValueError): score_kicking(self.stats,settings)

    def test_two_leagues_do_not_mutate_saved_projection(self):
        row=SimpleNamespace(season=2025,week=2,player=SimpleNamespace(position='K'),status='ml_model',
                            projected_stats=self.stats,projected_fantasy_points=11)
        first=league_projection(row,SimpleNamespace(scoring_settings={'fgm':3}))
        second=league_projection(row,SimpleNamespace(scoring_settings={'fgm':5}))
        self.assertEqual(first.projected_fantasy_points,6)
        self.assertEqual(second.projected_fantasy_points,10)
        self.assertEqual(row.projected_fantasy_points,11)

    def test_missing_stats_and_unsupported_league_report_unavailable(self):
        row=SimpleNamespace(season=2025,week=2,player=SimpleNamespace(position='K'),status='ml_model',projected_stats={})
        result=league_projection(row,SimpleNamespace(scoring_settings={}))
        self.assertIsNone(result.projected_fantasy_points)
        row.projected_stats=self.stats
        self.assertEqual(league_projection(row,SimpleNamespace(scoring_settings={})).status,'unsupported_scoring')

class KPredictorTests(TestCase):
    def setUp(self):
        self.player=SimpleNamespace(id=1,team_id=10,position='K')
        self.features=build_k_features(self.player,2025,2,snapshot())

    def result(self, features=None, model=object(), settings=None):
        with patch('scripts.algorithm.k.k_predictor.build_k_features',return_value=features or self.features),              patch('scripts.algorithm.k.k_predictor.load_model',return_value=model),              patch('scripts.algorithm.k.k_predictor.predict',return_value=np.array([[game(1)[n] for n in TARGETS]])):
            return predict_k(self.player,2025,2,settings)

    def test_model_and_unavailable_statuses(self):
        self.assertEqual(self.result()['projected_fantasy_points'],11)
        self.assertEqual(self.result(model=None)['status'],'model_not_found')
        self.assertEqual(self.result(settings={'fgm':3})['projected_fantasy_points'],6)
        self.assertEqual(self.result(settings={})['status'],'unsupported_scoring')
        for feature,value,status in [('games_played',0,'insufficient_history'),('game_status','UNKNOWN','matchup_not_found'),('game_status','BYE','bye')]:
            self.assertEqual(self.result({**self.features,feature:value})['status'],status)

    def test_router_passes_league_settings(self):
        from scripts.algorithm import predictor
        with patch.object(predictor.Player.objects,'filter') as query,patch.dict(predictor.PREDICTORS,{'K':lambda p,s,w,scoring_settings:{'status':'ml_model','projected_fantasy_points':11,'scoring_settings':scoring_settings}}):
            query.return_value.first.return_value=self.player
            self.assertEqual(predictor.predict_player(1,2025,2,{'xpm':2})['scoring_settings'],{'xpm':2})

    def test_model_round_trip_feature_guard_and_nonnegative_stats(self):
        X=np.zeros((25,len(K_FEATURE_NAMES)))
        y=np.ones((25,len(TARGETS)))
        with tempfile.TemporaryDirectory() as temp,patch('scripts.algorithm.k.k_model.MODEL_PATH',Path(temp)/'k.pkl'):
            train_model(X,y,[2023,2024])
            model=load_model()
            self.assertTrue((predict(model,X)>=0).all())
            self.assertEqual(model.k_training_seasons_,[2023,2024])
            with patch('scripts.algorithm.k.k_model.K_FEATURE_NAMES',['changed']):
                with self.assertRaises(ValueError): load_model()

    def test_backtest_refuses_training_seasons(self):
        from scripts.algorithm.k.backtest_k_model import main
        with patch('scripts.algorithm.k.backtest_k_model.load_model',return_value=SimpleNamespace(k_training_seasons_=[2025])):
            with self.assertRaises(ValueError): main(2025)
        with self.assertRaises(ValueError): metrics([],[])
