from io import StringIO
from unittest.mock import patch, Mock
from datetime import timedelta
from django.core.cache import cache
from django.core.management import call_command, CommandError
from django.utils import timezone
from django.urls import reverse
from analyzer.test_waivers import WaiverWireTests
from analyzer.models import PlayerWeeklyStats, PlayerInjuryReport, PlayerSnapCount
from analyzer.waiver_value import classify_value, load_player_values
from leagues.models import FantasyProjection, Player
from leagues.services.kicker_scoring import league_projection
from leagues.services.player_availability import availability
from scripts.algorithm.predictor import predict_player
from scripts.algorithm.features.injury_history import filter_injury_history


class PlayerContextTests(WaiverWireTests):
    external_models = (*WaiverWireTests.external_models, PlayerWeeklyStats)

    def setUp(self):
        super().setUp()
        clock = patch('leagues.services.player_availability.live_week', side_effect=lambda s,w: s == 2026 and w == 7)
        clock.start()
        self.addCleanup(clock.stop)

    def report(self, player=None, week=7, injury='', order=2, **kwargs):
        player = player or self.available
        return PlayerInjuryReport.objects.update_or_create(player_id=player.pk, season=2026, week=week,
            defaults={'injury_status': injury, 'roster_status': 'Active', 'depth_order': order,
                'team_id': player.team_id, 'position': player.position, 'observed_at': timezone.now(), **kwargs})[0]

    def test_out_doubtful_ir_zero_and_questionable_discount(self):
        player = Player.objects.get(pk=self.available.pk)
        for status in ['Out', 'Doubtful', 'IR', 'Injured Reserve']:
            self.report(injury=status)
            cache.clear()
            self.assertEqual(availability(player,2026,7)[1],0)
        self.report(injury='Questionable')
        cache.clear()
        self.assertEqual(availability(player,2026,7)[1],0.8)
        self.assertEqual(availability(player,2026,8)[1],1)
        self.assertEqual(availability(player,2025,7)[1],1)

    def test_stale_and_future_reports_do_not_adjust_points(self):
        player = Player.objects.get(pk=self.available.pk)
        for timestamp in [timezone.now()-timedelta(days=8), timezone.now()+timedelta(days=1)]:
            self.report(injury='Out', observed_at=timestamp)
            cache.clear()
            self.assertEqual(availability(player,2026,7)[1],1)

    def test_generation_and_display_do_not_double_discount(self):
        self.report(injury='Questionable')
        with patch.dict('scripts.algorithm.predictor.PREDICTORS', {'WR': Mock(return_value={'status':'ml_model','projected_fantasy_points':20})}):
            result = predict_player(self.available.pk,2026,7)
        self.assertEqual(result['projected_fantasy_points'],16)
        saved = FantasyProjection.objects.create(player_id=self.available.pk,season=2026,week=7,
            projected_fantasy_points=16,status=result['status'],projected_stats=result['projected_stats'])
        self.assertEqual(league_projection(saved,self.league_a).projected_fantasy_points,16)
        self.report(injury='')
        cache.clear()
        self.assertEqual(league_projection(saved,self.league_a).projected_fantasy_points,20)

    def test_out_overrides_missing_model_and_saved_forecast(self):
        self.report(injury='Out')
        model = Mock(side_effect=AssertionError('Out player should not need a model'))
        with patch.dict('scripts.algorithm.predictor.PREDICTORS',{'WR': model}):
            self.assertEqual(predict_player(self.available.pk,2026,7)['projected_fantasy_points'],0)
        response = self.browse(search=self.available.full_name)
        self.assertEqual(response.context['page_obj'][0]['prediction'].this_week,0)
        ranking = self.client.get(reverse('weekly_rankings'), {'week':7, 'position':'WR'})
        row = next(r for r in ranking.context['page_obj'] if r['player'].pk == self.available.pk)
        self.assertEqual(row['points'],0)
        self.assertContains(ranking,'Out')

    def test_old_high_projection_is_zero_on_waiver_and_rankings(self):
        self.save_projection(self.available,7,30,status='ml_model')
        self.report(injury='Out')
        response = self.browse(search=self.available.full_name)
        self.assertEqual(response.context['page_obj'][0]['prediction'].this_week,0)
        self.assertContains(response,'Out')

    def test_injury_missed_games_are_not_zero_performance_games(self):
        self.report(week=5,injury='Out')
        self.report(week=6,injury='Out')
        PlayerWeeklyStats.objects.create(player_id=self.available.pk,season=2026,week=5,season_type='REG',carries=0,targets=0)
        PlayerWeeklyStats.objects.create(player_id=self.available.pk,season=2026,week=6,season_type='REG',carries=1,targets=0)
        rows=[(4,10),(5,0),(6,1)]
        self.assertEqual(filter_injury_history(rows,self.available.pk,2026),[(4,10),(6,1)])

    def games(self):
        return [{'week':w, 'share':share, 'opportunities':opps} for w,share,opps in [(3,.2,2),(4,.3,3),(5,.4,6),(6,.5,8)]]

    def test_role_classification_requires_both_trends_and_context(self):
        games=self.games()
        self.assertEqual(classify_value(games,healthy_context=True).category,'long')
        self.assertEqual(classify_value(games,injured_ahead=True,healthy_context=True).category,'short')
        self.assertEqual(classify_value(games).category,'long')
        self.assertEqual(classify_value(games[:3],healthy_context=True).category,'unknown')
        declining=[dict(g,share=.8-g['share'],opportunities=12-g['opportunities']) for g in games]
        self.assertEqual(classify_value(declining,competitor_growing=True).category,'declining')
        self.assertEqual(classify_value(declining).category,'declining')
        games[-1]['opportunities']=0
        self.assertNotEqual(classify_value(games,healthy_context=True).category,'long')

    def test_real_usage_join_value_filter_and_projection_effect(self):
        for game in self.games():
            PlayerSnapCount.objects.create(player_id=self.available.pk,season=2026,week=game['week'],team_id=self.team.pk,offense_snaps=20,offense_share=game['share'])
            PlayerWeeklyStats.objects.create(player_id=self.available.pk,season=2026,week=game['week'],season_type='REG',carries=0,targets=game['opportunities'])
        for week in [5,6,7]:
            self.report(week=week)
            self.report(self.other,week=week,order=1,team_id=self.team.pk)
        self.save_projection(self.available,7,10,status='ml_model')
        values=load_player_values(2026,7)
        self.assertEqual(values[self.available.pk].category,'long')
        response=self.browse(value='long')
        self.assertEqual(self.names(response),[self.available.full_name])
        self.assertEqual(response.context['page_obj'][0]['prediction'].this_week,11)
        self.report(self.other,injury='Out',order=1,team_id=self.team.pk)
        cache.clear()
        self.assertEqual(load_player_values(2026,7)[self.available.pk].category,'short')
        self.assertIn(self.available.full_name,self.names(self.browse(sort='short')))

    def test_refresh_clears_recovered_injury_and_dry_run_does_not_write(self):
        self.available.injury_status='Out';self.available.save()
        state=Mock();state.json.return_value={'season':'2026','week':7,'season_type':'regular'}
        feed=Mock();feed.json.return_value={self.available.sleeper_id:{'injury_status':None,'status':'Active','team':'GB','position':'WR','depth_chart_order':2}}
        with patch('analyzer.management.commands.refresh_player_context.requests.get',side_effect=[state,feed]):
            call_command('refresh_player_context',injuries_only=True,dry_run=True,stdout=StringIO())
        self.assertFalse(PlayerInjuryReport.objects.exists())
        with patch('analyzer.management.commands.refresh_player_context.requests.get',side_effect=[state,feed]):
            call_command('refresh_player_context',injuries_only=True,stdout=StringIO())
        self.available.refresh_from_db()
        self.assertIsNone(self.available.injury_status)
        self.assertEqual(PlayerInjuryReport.objects.get().depth_order,2)
        with patch('analyzer.management.commands.refresh_player_context.requests.get',side_effect=ValueError('bad source')):
            with self.assertRaises(CommandError):
                call_command('refresh_player_context',injuries_only=True,stdout=StringIO())
        self.assertEqual(PlayerInjuryReport.objects.count(),1)

    def test_full_refresh_maps_ids_and_excludes_target_week(self):
        state=Mock();state.json.return_value={'season':'2026','week':7,'season_type':'regular'}
        feed=Mock();feed.json.return_value={self.available.sleeper_id:{'injury_status':'Questionable','status':'Active','team':'GB','position':'WR','depth_chart_order':2}}
        identity={'pfr_id':'Test00','gsis_id':'00-test','sleeper_id':self.available.sleeper_id}
        ids=Mock();ids.columns=list(identity);ids.select.return_value.to_dicts.return_value=[identity]
        snap={'season':2026,'week':6,'game_type':'REG','pfr_player_id':'Test00','team':'GB','offense_snaps':30,'offense_pct':0.5}
        snaps=Mock();snaps.columns=list(snap);snaps.to_dicts.return_value=[snap,dict(snap,week=7),dict(snap,pfr_player_id='Unknown')]
        fields=['completions','attempts','passing_yards','passing_tds','passing_interceptions','carries','rushing_yards','rushing_tds','targets','receptions','receiving_yards','receiving_tds','fantasy_points','fantasy_points_ppr']
        stat={field:0 for field in fields}
        stat.update(player_id='00-test',season=2026,week=6,season_type='REG',opponent_team='KC',targets=5,receptions=4,receiving_yards=50,fantasy_points_ppr=9)
        stats=Mock();stats.columns=list(stat);stats.to_dicts.return_value=[stat,dict(stat,week=7)]
        with patch('analyzer.management.commands.refresh_player_context.requests.get',side_effect=[state,feed]), patch('nflreadpy.load_snap_counts',return_value=snaps), patch('nflreadpy.load_ff_playerids',return_value=ids), patch('nflreadpy.load_player_stats',return_value=stats):
            call_command('refresh_player_context',stdout=StringIO())
        self.assertEqual(PlayerSnapCount.objects.count(),1)
        self.assertEqual(PlayerSnapCount.objects.get().player_id,self.available.pk)
        self.assertEqual(PlayerWeeklyStats.objects.get().targets,5)
        self.assertEqual(PlayerWeeklyStats.objects.get().week,6)

    def test_out_player_season_total_does_not_assume_recovery(self):
        for week in range(7,19):
            self.save_projection(self.available,week,20,status='ml_model')
        self.report(injury='Out')
        row=self.browse(search=self.available.full_name).context['page_obj'][0]
        self.assertEqual(row['prediction'].this_week,0)
        self.assertIsNone(row['prediction'].rest_of_season)

    def test_historical_saved_injury_prediction_remains_zero(self):
        saved=FantasyProjection.objects.create(player_id=self.available.pk,season=2026,week=6,
            projected_fantasy_points=0,status='injury_out',projected_stats={'_context':{'base_points':None,'base_status':'insufficient_history'}})
        self.assertEqual(league_projection(saved,self.league_a).projected_fantasy_points,0)

    def test_waiver_explanations_are_collapsed_and_plain(self):
        response=self.browse(search=self.available.full_name)
        self.assertContains(response,'Still evaluating')
        self.assertNotContains(response,'<summary>Why?</summary>')
        self.assertNotContains(response,'Snap share')
        self.assertNotContains(response,'calibrated probabilities')

    def test_rising_role_survives_a_lower_target_game(self):
        games=[{'week':w,'share':share,'opportunities':opps} for w,share,opps in
            [(2,.79,8),(3,.27,1),(4,.4,2),(5,.92,10),(6,.94,12),(7,.91,5)]]
        self.assertEqual(classify_value(games).category,'long')
        games=[{'week':w,'share':share,'opportunities':opps} for w,share,opps in
            [(2,.66,7),(3,.86,9),(4,.92,8),(5,.16,1),(6,.81,8),(7,.79,13)]]
        self.assertEqual(classify_value(games).category,'long')
        self.assertEqual(classify_value(games,injured_ahead=True).category,'short')

    def test_longer_baseline_recognizes_loss_without_named_replacement(self):
        games=[{'week':w,'share':share,'opportunities':opps} for w,share,opps in
            [(1,.35,3),(2,.54,8),(3,.37,1),(4,.62,2),(5,.51,3),(6,.21,2)]]
        self.assertEqual(classify_value(games).category,'declining')

    def test_one_big_game_is_not_a_sustained_gain(self):
        games=[{'week':w,'share':share,'opportunities':opps} for w,share,opps in
            [(1,.3,5),(2,.3,5),(3,.3,5),(4,.3,5),(5,.3,1),(6,.9,20)]]
        self.assertNotEqual(classify_value(games).category,'long')

    def test_picture_hides_initials_until_image_fails(self):
        self.available.headshot_url='https://example.com/player.png'
        self.available.save()
        response=self.browse(search=self.available.full_name)
        self.assertContains(response,'<span hidden>')
        self.assertContains(response,'this.previousElementSibling.hidden=false')
        self.available.headshot_url=None
        self.available.save()
        response=self.browse(search=self.available.full_name)
        self.assertNotContains(response,'<span hidden>')

    def test_usage_rebound_is_not_treated_as_losing_a_job(self):
        games=[{'week':w,'share':share,'opportunities':opps} for w,share,opps in
            [(2,.57,7),(3,.61,12),(4,.56,7),(5,.77,10),(6,.39,8),(7,.61,5)]]
        result=classify_value(games)
        self.assertEqual(result.category,'uneven')
        self.assertEqual(result.multiplier,1)

    def test_stable_usage_is_not_called_uneven(self):
        games=[{'week':w,'share':.6,'opportunities':6} for w in range(1,7)]
        self.assertEqual(classify_value(games).category,'neutral')

    def qb_depth(self, starter_injury=''):
        self.available.position='QB';self.available.save()
        self.young.position='QB';self.young.save()
        self.report(self.available,order=2)
        self.report(self.young,order=1,injury=starter_injury)
        cache.clear()
        return Player.objects.get(pk=self.available.pk)

    def test_confirmed_backup_qb_does_not_keep_old_starter_projection(self):
        player=self.qb_depth()
        saved=self.save_projection(player,7,18,status='ml_model')
        result=league_projection(saved,self.league_a)
        self.assertEqual(result.projected_fantasy_points,0)
        self.assertEqual(result.status,'qb_backup')
        response=self.browse(search=player.full_name)
        self.assertEqual(response.context['page_obj'][0]['prediction'].this_week,0)
        self.assertIsNone(response.context['page_obj'][0]['prediction'].rest_of_season)
        model=Mock(side_effect=AssertionError('Backup should not get starter model forecast'))
        with patch.dict('scripts.algorithm.predictor.PREDICTORS',{'QB':model}):
            self.assertEqual(predict_player(player.pk,2026,7)['projected_fantasy_points'],0)

    def test_backup_can_start_when_quarterback_ahead_is_out(self):
        player=self.qb_depth('Out')
        saved=self.save_projection(player,7,18,status='ml_model')
        self.assertEqual(league_projection(saved,self.league_a).projected_fantasy_points,18)
        self.report(self.young,order=1,injury='Questionable')
        cache.clear()
        self.assertEqual(league_projection(saved,self.league_a).projected_fantasy_points,0)

    def test_depth_guard_does_not_rewrite_other_weeks(self):
        player=self.qb_depth()
        for week in (6,8):
            saved=self.save_projection(player,week,18,status='ml_model')
            self.assertEqual(league_projection(saved,self.league_a).projected_fantasy_points,18)
        self.report(self.young,order=1,observed_at=timezone.now()-timedelta(days=8))
        cache.clear()
        saved=self.save_projection(player,7,18,status='ml_model')
        self.assertIsNone(league_projection(saved,self.league_a).projected_fantasy_points)

    def test_value_duration_is_separate_from_growing_workload(self):
        games=self.games()
        rising=classify_value(games,healthy_context=True)
        self.assertEqual(rising.horizon,'long')
        self.assertEqual(rising.value_label,'Long-term')
        temporary=classify_value(games,injured_ahead=True,healthy_context=True)
        self.assertEqual(temporary.horizon,'short')
        self.assertEqual(temporary.value_label,'Short-term')
        self.assertEqual(temporary.short_label,'Growing role')
        self.assertEqual(classify_value(games).horizon,'unknown')

    def test_steady_injury_replacement_is_still_short_term(self):
        games=[{'week':w,'share':.8,'opportunities':18} for w in range(1,7)]
        result=classify_value(games,injured_ahead=True,position='RB')
        self.assertEqual(result.category,'neutral')
        self.assertEqual(result.horizon,'short')
        self.assertEqual(classify_value(games,healthy_context=True,position='RB').horizon,'long')

    def test_returning_questionable_regular_limits_duration_and_filters(self):
        self.available.position='RB';self.available.save()
        self.young.position='RB';self.young.save()
        self.report(self.available,order=2)
        self.report(self.young,order=1,injury='Questionable')
        usage={self.available.pk:[(1,.40,11),(2,.31,6),(3,.52,7),(4,.94,16),(5,.86,28),(6,.87,19)],
               self.young.pk:[(1,.58,24),(2,.65,21),(3,.48,16)]}
        for player_id, games in usage.items():
            for week,share,opportunities in games:
                PlayerSnapCount.objects.create(player_id=player_id,season=2026,week=week,team_id=self.team.pk,offense_snaps=30,offense_share=share)
                PlayerWeeklyStats.objects.create(player_id=player_id,season=2026,week=week,season_type='REG',carries=opportunities,targets=0)
        for week in range(7,19):
            self.save_projection(self.available,week,15,status='ml_model')
        result=load_player_values(2026,7)[self.available.pk]
        self.assertEqual(result.horizon,'short')
        response=self.browse(value='short',position='RB')
        self.assertIn(self.available.full_name,self.names(response))
        self.assertNotIn(self.available.full_name,self.names(self.browse(value='long')))
        self.assertIsNone(next(r for r in response.context['page_obj'] if r['player'].pk==self.available.pk)['prediction'].rest_of_season)
        self.assertContains(response,'Short-term')
        self.assertNotContains(response,'<summary>Why?</summary>')
        self.report(self.young,order=1,injury='')
        cache.clear()
        self.assertEqual(load_player_values(2026,7)[self.available.pk].horizon,'short')

    def test_questionable_teammate_who_keeps_playing_is_not_an_absence(self):
        from analyzer.waiver_value import injury_dependent_role
        own=self.report(self.available,order=2)
        other=self.report(self.young,order=1,injury='Questionable')
        history={own.player_id:[dict(g,team_id=self.team.pk) for g in self.games()],
                 other.player_id:[dict(g,team_id=self.team.pk,opportunities=15) for g in self.games()]}
        self.assertFalse(injury_dependent_role(own,[other],history))

    def test_season_ending_regular_creates_rest_of_season_value(self):
        from analyzer.injury_outlooks import season_ending_player_ids
        self.available.position='RB';self.available.save()
        self.young.position='RB';self.young.save()
        self.report(self.available,order=1)
        self.report(self.young,order=5,injury='IR')
        for player,games in [(self.available,[(1,.3,5),(2,.3,5),(3,.4,6),(4,.8,15),(5,.8,18),(6,.8,18)]),
                             (self.young,[(1,.7,20),(2,.7,20),(3,.7,18)])]:
            for week,share,opportunities in games:
                PlayerSnapCount.objects.create(player_id=player.pk,season=2026,week=week,team_id=self.team.pk,offense_snaps=30,offense_share=share)
                PlayerWeeklyStats.objects.create(player_id=player.pk,season=2026,week=week,season_type='REG',carries=opportunities,targets=0)
        self.assertEqual(load_player_values(2026,7)[self.available.pk].horizon,'short')
        cache.clear()
        timeline=[{'sleeper_id':self.young.sleeper_id,'season':2026,'effective_week':7,
            'status':'out_for_season','verified_on':timezone.localdate().isoformat(),'source_url':'https://example.com/confirmed-report'}]
        with patch('analyzer.injury_outlooks._load_timelines',return_value=timeline):
            self.assertEqual(load_player_values(2026,7)[self.available.pk].horizon,'long')
            self.assertIn(self.young.pk,season_ending_player_ids(2026,18))
            self.assertNotIn(self.young.pk,season_ending_player_ids(2027,7))
            self.assertNotIn(self.young.pk,season_ending_player_ids(2026,6))
            saved=self.save_projection(self.young,8,20,status='ml_model')
            self.assertEqual(league_projection(saved,self.league_a).projected_fantasy_points,0)

    def test_generic_ir_does_not_imply_season_ending(self):
        from analyzer.injury_outlooks import season_ending_player_ids
        self.report(injury='IR')
        with patch('analyzer.injury_outlooks._load_timelines',return_value=[]):
            self.assertNotIn(self.available.pk,season_ending_player_ids(2026,7))
            self.assertEqual(availability(Player.objects.get(pk=self.available.pk),2026,8)[1],1)

    def test_confirmed_qb_starter_has_long_term_value_without_touch_history(self):
        self.available.position='QB';self.available.save()
        self.report(self.available,order=1)
        result=load_player_values(2026,7)[self.available.pk]
        self.assertEqual(result.horizon,'long')
        response=self.browse(value='long',position='QB')
        self.assertIn(self.available.full_name,self.names(response))

    def test_qb_backup_and_injury_fill_in_have_different_duration(self):
        self.qb_depth()
        self.assertEqual(load_player_values(2026,7)[self.available.pk].horizon,'unknown')
        self.report(self.young,order=1,injury='Out')
        cache.clear()
        self.assertEqual(load_player_values(2026,7)[self.available.pk].horizon,'short')
        self.assertIn(self.available.full_name,self.names(self.browse(value='short',position='QB')))
        self.report(self.young,order=1,injury='Questionable')
        cache.clear()
        self.assertEqual(load_player_values(2026,7)[self.available.pk].horizon,'unknown')

    def test_qb_replacing_confirmed_season_ending_starter_has_season_value(self):
        self.qb_depth('IR')
        with patch('analyzer.waiver_value.season_ending_player_ids',return_value={self.young.pk}):
            self.assertEqual(load_player_values(2026,7)[self.available.pk].horizon,'long')

    def test_stale_qb_depth_does_not_establish_long_term_value(self):
        self.available.position='QB';self.available.save()
        self.report(self.available,order=1,observed_at=timezone.now()-timedelta(days=8))
        self.assertNotIn(self.available.pk,load_player_values(2026,7))

    def test_qb1_is_not_temporary_because_questionable_backup_started_earlier(self):
        self.available.position='QB';self.available.save()
        self.young.position='QB';self.young.save()
        self.report(self.available,order=1)
        self.report(self.young,order=2,injury='Questionable')
        for player,games in [(self.available,[(1,.1,2),(3,.9,45),(4,.9,22),(5,.9,29),(6,.9,51)]),
                             (self.young,[(1,.9,22),(2,.9,26)])]:
            for week,share,attempts in games:
                PlayerSnapCount.objects.create(player_id=player.pk,season=2026,week=week,team_id=self.team.pk,offense_snaps=30,offense_share=share)
                PlayerWeeklyStats.objects.create(player_id=player.pk,season=2026,week=week,season_type='REG',attempts=attempts,carries=0,targets=0)
        self.assertEqual(load_player_values(2026,7)[self.available.pk].horizon,'long')
