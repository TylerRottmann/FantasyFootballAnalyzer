from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from analyzer import assistant_gm
from analyzer.models import PlayerWeeklyStats, PlayerSnapCount, PlayerInjuryReport, PlayerADP, NFLGame, TeamWeeklyStats
from analyzer.player_profiles import build_player_profile, profile_overview_text, _saved_probability
from analyzer import test_waivers as waiver_fixtures
from leagues.models import UserLeagueConnection


class PlayerCardTests(TestCase):
    external_models = waiver_fixtures.WaiverWireTests.external_models + (PlayerWeeklyStats, TeamWeeklyStats)
    setUpTestData = classmethod(waiver_fixtures.WaiverWireTests.setUpTestData.__func__)
    make_player = classmethod(waiver_fixtures.WaiverWireTests.make_player.__func__)
    select = waiver_fixtures.WaiverWireTests.select
    def save_projection(self, player, week, points, **kwargs):
        from leagues.models import FantasyProjection
        version = kwargs.pop("model_version", None)
        if version is not None:
            return FantasyProjection.objects.create(
                player_id=player.pk, season=2026, week=week,
                projected_fantasy_points=points, model_version=version, **kwargs
            )
        for model_version in ("v1", "v2_stat"):
            result = FantasyProjection.objects.create(
                player_id=player.pk, season=2026, week=week,
                projected_fantasy_points=points, model_version=model_version, **kwargs
            )
        return result

    @classmethod
    def setUpClass(cls):
        with connection.schema_editor() as editor:
            for model in cls.external_models:
                editor.create_model(model)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with connection.schema_editor() as editor:
            for model in reversed(cls.external_models):
                editor.delete_model(model)

    def setUp(self):
        waiver_fixtures.WaiverWireTests.setUp(self)
        current_week = patch('analyzer.player_cards.get_current_nfl_week', return_value=7)
        current_week.start()
        self.addCleanup(current_week.stop)
        self.player = self.available
        self.player.first_name = 'Available'
        self.player.last_name = 'Receiver'
        self.player.years_exp = 0
        self.player.save()
        for week in range(7, 19):
            self.save_projection(self.player, week, 12, status='ml_model')
        for week, points in [(2, 10), (3, 11), (4, 12), (5, 13), (6, 14)]:
            PlayerWeeklyStats.objects.create(player=self.player, season=2026, week=week,
                season_type='REG', targets=6, receptions=4, receiving_yards=60,
                fantasy_points_ppr=points, fumbles=0)
            PlayerSnapCount.objects.create(player=self.player, season=2026, week=week,
                team_id=self.team.pk, offense_snaps=45, offense_share=.75)

    def card(self, **params):
        return self.client.get(reverse('player_card', args=[self.player.pk]), params)

    def test_card_is_available_for_unrostered_players_and_uses_saved_points(self):
        data = self.card(format='json', week=7).json()
        self.assertEqual(data['player']['team'], 'GB')
        self.assertEqual(data['weekly_points'], 12)
        self.assertEqual(data['rest_of_season'], 144)
        self.assertIsNone(data['boom_pct'])
        self.assertIsNone(data['bust_pct'])
        self.assertEqual(data['consistency']['average'], 12)
        self.assertEqual(data['consistency']['label'], 'Steady scoring')
        self.assertEqual(data['game_log'][0]['week'], 6)
        self.assertEqual(data['game_log'][0]['snap_share'], 75)
        self.assertEqual(next(f['value'] for f in data['facts'] if f['label'] == 'Experience'), 0)

    def test_modal_fragment_and_standalone_page(self):
        fragment = self.card(fragment=1)
        self.assertContains(fragment, 'data-player-profile')
        self.assertNotContains(fragment, '<!DOCTYPE html>')
        self.assertContains(self.card(), '<!DOCTYPE html>')
        self.assertContains(fragment, 'All weeks')
        self.assertNotContains(fragment, 'data-player-tab="projections"')
        self.assertContains(fragment, 'Estimate unavailable')
        self.assertNotContains(fragment, 'data-player-history-season')

    def test_weekly_stats_are_aligned_columns_without_dropdowns(self):
        from leagues.models import FantasyProjection
        FantasyProjection.objects.filter(player_id=self.player.pk, week=7).update(projected_stats={'receptions': 5})
        data = self.card(format='json', week=7).json()
        columns = data['season_stat_columns']
        self.assertEqual(data['season_weeks'][2]['stat_cells'][columns.index('Catches')], 4)
        self.assertEqual(data['season_weeks'][2]['stat_cells'][columns.index('Fumbles')], 0)
        self.assertIsNone(data['season_weeks'][6]['stat_cells'][columns.index('Catches')])
        self.assertEqual(data['season_weeks'][6]['stat_cells'][columns.index('Projected Receptions')], 5)
        self.assertTrue(all(len(row['stat_cells']) == len(columns) for row in data['season_weeks']))
        fragment = self.card(fragment=1, week=7)
        self.assertContains(fragment, '<th>Catches</th>')
        self.assertContains(fragment, 'pc-weeks-table')
        self.assertNotContains(fragment, '<details>')

    def test_authentication_invalid_inputs_and_unknown_player(self):
        for params in ({'week': 'bad'}, {'week': 0}, {'week': 19}):
            self.assertEqual(self.card(**params).status_code, 400)
        self.assertEqual(self.client.get(reverse('player_card', args=[999999])).status_code, 404)
        self.client.logout()
        self.assertEqual(self.card().status_code, 302)

    def test_future_actual_results_are_not_used_in_historical_card(self):
        PlayerWeeklyStats.objects.create(player=self.player, season=2026, week=8, season_type='REG', fantasy_points_ppr=999)
        data = self.card(format='json', week=7).json()
        self.assertEqual(data['consistency']['average'], 12)
        self.assertNotIn(8, [g['week'] for g in data['game_log']])
        self.assertEqual([row['week'] for row in data['season_weeks']], list(range(1, 19)))
        self.assertEqual(data['season_weeks'][5]['actual_points'], 14)
        self.assertIsNone(data['season_weeks'][7]['actual_points'])
        self.assertEqual(data['season_weeks'][7]['projected_points'], 12)

    def test_zero_and_missing_forecasts_remain_distinct(self):
        from leagues.models import FantasyProjection
        FantasyProjection.objects.filter(player_id=self.player.pk, week=7).update(projected_fantasy_points=0, status='bye')
        FantasyProjection.objects.filter(player_id=self.player.pk, week=8).delete()
        data = self.card(format='json', week=7).json()
        self.assertEqual(data['weekly_points'], 0)
        self.assertIsNone(data['rest_of_season'])
        self.assertIsNone(next(p['points'] for p in data['projections'] if p['week'] == 8))

    def test_saved_past_forecasts_and_byes_appear_in_all_weeks(self):
        self.save_projection(self.player, 3, 17, status='ml_model')
        self.save_projection(self.player, 4, 0, status='bye')
        PlayerWeeklyStats.objects.filter(player=self.player, week=4).delete()
        data = self.card(format='json', week=7).json()
        self.assertEqual(data['season_weeks'][2]['projected_points'], 17)
        self.assertEqual(data['season_weeks'][2]['actual_points'], 11)
        self.assertEqual(data['season_weeks'][3]['opponent'], 'BYE')
        self.assertEqual(data['season_weeks'][3]['projected_points'], 0)
        self.assertIsNone(data['season_weeks'][0]['projected_points'])
        self.assertEqual(data['rest_of_season'], 144)

    def test_rams_matchup_overrides_stale_bye_forecasts(self):
        from datetime import date
        from leagues.models import FantasyProjection
        self.other_team.abbreviation = 'LAR'
        self.other_team.save()
        for week in (3, 7):
            NFLGame.objects.create(season=2026, week=week, game_type='REG',
                game_date=date(2026, 10, 1), home_team_id=self.team.pk, away_team_id=self.other_team.pk)
            FantasyProjection.objects.filter(player_id=self.player.pk, week=week).delete()
            self.save_projection(self.player, week, 0, status='bye')
        PlayerWeeklyStats.objects.filter(player=self.player, week=3).update(opponent_team='LA')
        FantasyProjection.objects.filter(player_id=self.player.pk, week=8).update(projected_fantasy_points=0, status='bye')
        data = self.card(format='json', week=7).json()
        self.assertEqual(data['season_weeks'][2]['opponent'], 'LAR')
        self.assertIsNone(data['season_weeks'][2]['projected_points'])
        self.assertEqual(data['season_weeks'][6]['opponent'], 'vs LAR')
        self.assertIsNone(data['season_weeks'][6]['projected_points'])
        self.assertEqual(data['season_weeks'][7]['opponent'], 'BYE')
        self.assertIsNone(data['weekly_points'])
        self.assertIsNone(data['rest_of_season'])

    def test_qb_historical_rams_alias_finds_actual_matchup(self):
        from scripts.algorithm.features.qb_features import get_player_game_context
        self.other_team.abbreviation = 'LAR'
        self.other_team.save()
        PlayerWeeklyStats.objects.filter(player=self.player, week=3).update(opponent_team='LA')
        TeamWeeklyStats.objects.create(team_id=self.team.pk, opponent_team_id=self.other_team.pk,
            season=2026, week=3, season_type=1, is_home=True,
            created_at=timezone.now(), updated_at=timezone.now())
        with patch('scripts.algorithm.features.qb_features.get_connection', return_value=connection):
            context = get_player_game_context(self.player.pk, 2026, 3)
        self.assertEqual(context['game_status'], 'GAME')
        self.assertEqual(context['opponent_team'], 'LAR')
        self.assertEqual(context['opponent_team_id'], self.other_team.pk)

    def test_injuries_and_saved_risk_estimates(self):
        from leagues.models import FantasyProjection
        FantasyProjection.objects.filter(player_id=self.player.pk, week=7).update(projected_stats={
            'boom_probability': .25, 'bust_pct': 10, 'receptions': 5, 'receiving_yards': 70, 'receiving_tds': 0, 'passing_yards': 0, 'passing_tds': 0, 'passing_interceptions': 0, 'rushing_yards': 0, 'rushing_tds': 0, 'fumbles_lost': 0, '_context_private': 'not for display'})
        PlayerInjuryReport.objects.create(player=self.player, season=2026, week=7, injury_status='Questionable',
            roster_status='Active', depth_order=1, team_id=self.team.pk, position='WR', observed_at=timezone.now())
        data = self.card(format='json', week=7).json()
        self.assertAlmostEqual(data['weekly_points'], 9.6)
        self.assertEqual(data['player']['injury'], 'Questionable')
        self.assertEqual((data['boom_pct'], data['bust_pct']), (25, 10))
        self.assertNotContains(self.card(fragment=1, week=7), '_context_private')

    def test_older_season_query_keeps_current_season_and_adp_details(self):
        PlayerWeeklyStats.objects.create(player=self.player, season=2025, week=10, season_type='REG', fantasy_points_ppr=8)
        PlayerADP.objects.create(player=self.player, season=2026, scoring_format='ppr', adp=25)
        data = self.card(format='json', week=7, history_season=2025).json()
        self.assertEqual(data['season'], 2026)
        self.assertEqual(data['history_season'], 2026)
        self.assertEqual([g['week'] for g in data['game_log']], [6, 5, 4, 3, 2])
        self.assertIsNone(data['season_weeks'][9]['actual_points'])
        self.assertEqual(data['season_weeks'][9]['projected_points'], 12)
        self.assertEqual(data['adp'][0]['value'], 25)

    def test_active_league_scope_cannot_be_overridden_by_query(self):
        data = self.card(format='json', week=7, league_id=self.league_b.pk, season=2025).json()
        self.assertEqual(data['season'], self.league_a.season)

    def test_no_league_and_no_history_are_explicit(self):
        UserLeagueConnection.objects.filter(user=self.user).delete()
        PlayerWeeklyStats.objects.filter(player=self.player).delete()
        data = self.card(format='json', week=7).json()
        self.assertIsNone(data['weekly_points'])
        self.assertIn('Connect a league', data['summary'])
        self.assertEqual(data['consistency']['label'], 'Still evaluating')

    def test_chatbot_uses_the_card_overview(self):
        ctx = assistant_gm.ChatContext(user=self.user, league=self.league_a, season=2026, week=7)
        with patch.object(assistant_gm, '_build_context', return_value=ctx):
            answer = assistant_gm.answer_question('Give an overview of Available Receiver', self.user, self.league_a)
        profile = build_player_profile(self.player, self.league_a, 7)
        self.assertEqual(answer, profile_overview_text(profile))

    def test_html_player_name_is_escaped(self):
        self.player.full_name = '<script>alert(1)</script>'
        self.player.save()
        response = self.card(fragment=1)
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')

    def test_kicker_game_log_uses_league_scoring_and_distance_data(self):
        from scripts.algorithm.k.feature_names import TARGETS
        from scripts.algorithm.k.scoring import REFERENCE_SCORING
        self.player.position = 'K'
        self.player.save()
        self.league_a.scoring_settings = REFERENCE_SCORING
        self.league_a.save()
        game = {key: 0 for key in TARGETS}
        game.update(player_id=self.player.pk, season=2026, week=6, fg_made_0_19=1, pat_made=2,
            fg_att=1, fg_made=1, opponent_team='KC')
        with patch('analyzer.player_profiles._kicker_games', return_value=[game]):
            data = self.card(format='json', week=7).json()
        self.assertEqual(data['game_log'][0]['cells'][0], 5)
        self.assertIn('FG made', data['game_columns'])

    def test_chat_player_links_keep_the_question_week(self):
        with patch('analyzer.assistant_gm._build_context', return_value=assistant_gm.ChatContext(
                user=self.user, league=self.league_a, season=2026, week=7)):
            response = self.client.post(reverse('assistant_gm_chat'), {'message': 'Give an overview of Available Receiver week 7'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['week'], 7)
        self.assertIn({'id': self.player.pk, 'name': self.player.full_name}, response.json()['players'])

    def test_confirmed_injury_absence_is_not_counted_as_bad_scoring_game(self):
        PlayerWeeklyStats.objects.filter(player=self.player, week=6).update(targets=0, receptions=0, receiving_yards=0, fantasy_points_ppr=0)
        PlayerSnapCount.objects.filter(player=self.player, week=6).update(offense_snaps=0, offense_share=0)
        PlayerInjuryReport.objects.create(player=self.player, season=2026, week=6, injury_status='Out', observed_at=timezone.now())
        self.assertEqual(self.card(format='json', week=7).json()['consistency']['games'], 4)
        # Actual snaps are evidence of participation, even without any touches.
        PlayerSnapCount.objects.filter(player=self.player, week=6).update(offense_snaps=20)
        self.assertEqual(self.card(format='json', week=7).json()['consistency']['games'], 5)


class SavedEstimateTests(SimpleTestCase):
    def test_missing_invalid_or_ambiguous_probabilities_are_unavailable(self):
        for stats in ({}, {'boom': 80}, {'boom_probability': 80}, {'boom_pct': -1}, {'boom_probability': float('nan')}):
            self.assertIsNone(_saved_probability(stats, 'boom'))
        self.assertEqual(_saved_probability({'boom_probability': 0}, 'boom'), 0)
        self.assertEqual(_saved_probability({'boom_probability': .75}, 'boom'), 75)
