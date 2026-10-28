from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test import SimpleTestCase
from types import SimpleNamespace
from django.test.utils import ContextList
from django.urls import reverse
from django.utils import timezone

from analyzer.models import Players, Teams
from analyzer.waiver_predictions import WaiverPrediction, predict_waiver_player
from analyzer.waiver_moves import suggested_moves
from analyzer.waiver_value import PlayerValue
from leagues.models import FantasyProjection, FantasyLeague, FantasyRoster, FantasyRosterPlayer, UserLeagueConnection


class WaiverWireTests(TestCase):
    # These tables are externally managed in production. Create only test tables,
    # without changing managed flags or introducing shared-schema migrations.
    external_models = (Teams, Players, FantasyLeague, FantasyRoster, FantasyRosterPlayer)

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

    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.user = get_user_model().objects.create_user(username='waiver-tester')
        cls.team = Teams.objects.create(external_id='GB', name='Green Bay Packers',
            abbreviation='GB', conference='NFC', division='North', is_active=True,
            created_at=now, updated_at=now)
        cls.other_team = Teams.objects.create(external_id='KC', name='Kansas City Chiefs',
            abbreviation='KC', conference='AFC', division='West', is_active=True,
            created_at=now, updated_at=now)
        cls.league_a = FantasyLeague.objects.create(sleeper_league_id='A', name='League A',
            season=2026, created_at=now, updated_at=now)
        cls.league_b = FantasyLeague.objects.create(sleeper_league_id='B', name='League B',
            season=2026, created_at=now, updated_at=now + timezone.timedelta(seconds=1))
        for league in (cls.league_a, cls.league_b):
            UserLeagueConnection.objects.create(user=cls.user, league=league, platform='sleeper')
        cls.roster_a = FantasyRoster.objects.create(league=cls.league_a, sleeper_roster_id=1,
            created_at=now, updated_at=now)
        cls.roster_b = FantasyRoster.objects.create(league=cls.league_b, sleeper_roster_id=1,
            created_at=now, updated_at=now)
        cls.owned_a = cls.make_player('Owned A', 'WR', 24)
        cls.owned_b = cls.make_player('Owned B', 'RB', 25)
        cls.available = cls.make_player('Available Receiver', 'WR', 26)
        cls.young = cls.make_player('Young Receiver', 'WR', 21)
        cls.unknown = cls.make_player('Unknown Age', 'WR', None)
        cls.other = cls.make_player('Other Team', 'WR', 26, cls.other_team)
        cls.make_player('Lineman', 'OL', 26)
        cls.make_player('', 'WR', 26)
        FantasyRosterPlayer.objects.create(roster=cls.roster_a, player_id=cls.owned_a.pk, created_at=now)
        FantasyRosterPlayer.objects.create(roster=cls.roster_b, player_id=cls.owned_b.pk, created_at=now)

    @classmethod
    def make_player(cls, name, position, age, team=None):
        return Players.objects.create(sleeper_id=f'player-{Players.objects.count()}',
            full_name=name, position=position, age=age, team=team or cls.team)

    def setUp(self):
        cache.clear()
        week = patch('analyzer.waivers.get_current_nfl_week', return_value=7)
        week.start()
        self.addCleanup(week.stop)
        injury_week = patch('leagues.services.player_availability.get_current_nfl_week', return_value=7)
        injury_week.start()
        self.addCleanup(injury_week.stop)
        # Django 5.1 context copying is incompatible with Python 3.14.
        def capture(store, signal, sender, template, context, **kwargs):
            store.setdefault('templates', []).append(template)
            store.setdefault('context', ContextList()).append(context.flatten())
        capture_patch = patch('django.test.client.store_rendered_templates', side_effect=capture)
        capture_patch.start()
        self.addCleanup(capture_patch.stop)
        self.client.force_login(self.user)
        self.select(self.league_a.pk)

    def select(self, league_id):
        session = self.client.session
        session['active_league_id'] = league_id
        session.save()

    def browse(self, **params):
        return self.client.get(reverse('waiver_wire'), params)

    def names(self, response):
        return [row['player'].full_name for row in response.context['page_obj']]

    def test_requires_login(self):
        self.client.logout()
        self.assertRedirects(self.browse(), '/accounts/login/?next=/waivers/', fetch_redirect_response=False)

    def test_availability_changes_with_active_league(self):
        response = self.browse()
        self.assertNotIn('Owned A', self.names(response))
        self.assertIn('Owned B', self.names(response))
        self.assertNotIn('Lineman', self.names(response))
        self.assertNotIn('', self.names(response))
        self.assertContains(response, 'Find a quick fill-in')
        self.assertNotContains(response, 'demo pts')
        self.assertContains(response, 'GB')
        self.client.get(reverse('select_league', args=[self.league_b.pk]), HTTP_REFERER='/waivers/')
        response = self.browse()
        self.assertIn('Owned A', self.names(response))
        self.assertNotIn('Owned B', self.names(response))
        self.assertEqual(response.context['active_league'], self.league_b)

    def test_excludes_players_on_other_owners_rosters(self):
        now = timezone.now()
        roster = FantasyRoster.objects.create(league=self.league_a, sleeper_roster_id=2,
            owner_sleeper_id='someone-else', created_at=now, updated_at=now)
        FantasyRosterPlayer.objects.create(roster=roster, player_id=self.available.pk, created_at=now)
        self.assertNotIn(self.available.full_name, self.names(self.browse()))

    def test_invalid_or_unconnected_league_falls_back_to_selector(self):
        now = timezone.now()
        private = FantasyLeague.objects.create(sleeper_league_id='private', name='Private league',
            created_at=now, updated_at=now)
        for league_id in (private.pk, 99999, None):
            with self.subTest(league_id=league_id):
                self.select(league_id)
                response = self.browse()
                self.assertEqual(response.context['active_league'], self.league_b)
                self.assertNotContains(response, 'Private league')
                self.assertNotIn('Owned B', self.names(response))

    def test_combined_filters_and_inclusive_age_bounds(self):
        response = self.browse(position='WR', team=self.team.pk, age_min=26, age_max=26, search='receiver')
        self.assertEqual(self.names(response), ['Available Receiver'])
        self.assertContains(response, 'value="26"')

    def test_unknown_age_is_available_without_age_filter(self):
        self.assertIn('Unknown Age', self.names(self.browse()))
        self.assertNotIn('Unknown Age', self.names(self.browse(age_min=20)))
        self.assertNotIn('Unknown Age', self.names(self.browse(age_max=30)))

    def test_invalid_filters_show_errors_without_results(self):
        for params in ({'age_min': 'oops'}, {'age_min': -1}, {'age_min': 30, 'age_max': 20},
                       {'team': 'oops'}, {'team': 99999}, {'position': 'invalid'}, {'sort': 'invalid'}):
            with self.subTest(params=params):
                response = self.browse(**params)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['filter_form'].errors)
                self.assertEqual(self.names(response), [])
                self.assertContains(response, 'Please correct the filters')

    def test_no_league_and_no_rosters_states(self):
        UserLeagueConnection.objects.filter(user=self.user).delete()
        self.assertContains(self.browse(), 'Connect a league to get started')
        FantasyRosterPlayer.objects.filter(roster=self.roster_a).delete()
        self.roster_a.delete()
        UserLeagueConnection.objects.create(user=self.user, league=self.league_a, platform='sleeper')
        response = self.browse()
        self.assertContains(response, 'No imported rosters yet')
        self.assertEqual(self.names(response), [])

    def test_empty_results(self):
        self.assertContains(self.browse(search='no matching name'), 'No available players match')

    @patch('analyzer.waivers.predict_waiver_player')
    def test_both_sort_orders_and_stable_ties(self, predict):
        values = {
            self.available.pk: WaiverPrediction(30, 10),
            self.young.pk: WaiverPrediction(10, 300),
        }
        predict.side_effect = lambda player, league, week, forecasts: values.get(player.pk, WaiverPrediction(1, 1))
        weekly = self.browse()
        season = self.browse(sort='season')
        self.assertEqual(self.names(weekly)[0], self.available.full_name)
        self.assertEqual(self.names(season)[0], self.young.full_name)
        self.assertEqual(self.names(weekly)[2:], sorted(self.names(weekly)[2:], key=str.casefold))

    def save_projection(self, player, week, points, **kwargs):
        return FantasyProjection.objects.create(player_id=player.pk, season=2026,
            week=week, projected_fantasy_points=points, **kwargs)

    def test_saved_forecast_and_complete_remaining_season(self):
        self.save_projection(self.available, 6, 999, status='ml_model')
        for week in range(7, 19):
            self.save_projection(self.available, week, 12, status='ml_model')
        response = self.browse()
        row = next(r for r in response.context['page_obj'] if r['player'].pk == self.available.pk)
        self.assertEqual(row['prediction'], WaiverPrediction(12, 144))
        self.assertEqual(self.names(response)[0], self.available.full_name)
        self.assertContains(response, 'Week 7')

    def test_missing_forecast_is_not_zero_and_sorts_after_negative(self):
        self.save_projection(self.available, 7, -2, status='ml_model')
        response = self.browse()
        self.assertEqual(self.names(response)[0], self.available.full_name)
        row = next(r for r in response.context['page_obj'] if r['player'].pk == self.available.pk)
        self.assertIsNone(row['prediction'].rest_of_season)
        self.assertContains(response, 'Prediction unavailable')

    def test_saved_zero_bye_and_wrong_season_version_or_status(self):
        self.save_projection(self.available, 7, 0, status='bye')
        self.save_projection(self.young, 7, 99, status='insufficient_history')
        self.save_projection(self.other, 7, 99, model_version='old')
        FantasyProjection.objects.create(player_id=self.unknown.pk, season=2025,
            week=7, projected_fantasy_points=99)
        rows = {r['player'].pk: r['prediction'] for r in self.browse().context['page_obj']}
        self.assertEqual(rows[self.available.pk].this_week, 0)
        for player in (self.young, self.other, self.unknown):
            self.assertIsNone(rows[player.pk].this_week)

    def test_week_selection_and_missing_current_week(self):
        self.save_projection(self.available, 8, 15, status='ml_model')
        response = self.browse(week=8)
        self.assertEqual(response.context['projection_week'], 8)
        self.assertEqual(self.names(response)[0], self.available.full_name)
        for week in ('bad', 0, 19):
            self.assertTrue(self.browse(week=week).context['filter_form'].errors)
        with patch('analyzer.waivers.get_current_nfl_week', side_effect=ValueError):
            self.assertContains(self.browse(), 'Choose a week below')

    def test_pagination_preserves_combined_filters(self):
        for number in range(55):
            self.make_player(f'Extra {number}', 'TE', 24)
        response = self.browse(position='TE', age_min=24, sort='season')
        self.assertEqual(len(self.names(response)), 50)
        self.assertContains(response, 'position=TE&amp;age_min=24&amp;sort=season&amp;week=7&amp;page=2')
        second = self.browse(position='TE', age_min=24, sort='season', page=2)
        self.assertEqual(len(self.names(second)), 5)
        self.assertTrue(set(self.names(response)).isdisjoint(self.names(second)))
        self.assertEqual(self.browse(page='bad').status_code, 200)
        self.assertEqual(self.browse(page=99999).status_code, 200)

    def test_combined_skill_position_filter(self):
        self.make_player('Available Quarterback', 'QB', 25)
        self.make_player('Available Tight End', 'TE', 25)
        response = self.browse(position='FLEX')
        positions = {row['player'].position for row in response.context['page_obj']}
        self.assertEqual(positions, {'WR', 'RB', 'TE'})
        self.assertNotIn('Available Quarterback', self.names(response))
        self.assertContains(response, 'WR/RB/TE')

    @patch('analyzer.waivers.load_player_values')
    def test_suggestions_use_own_roster_and_ignore_browse_filters(self, values):
        UserLeagueConnection.objects.filter(user=self.user, league=self.league_a).update(external_user_id='owner-a')
        self.roster_a.owner_sleeper_id = 'owner-a'
        self.roster_a.save()
        self.league_a.roster_positions = ['WR']
        self.league_a.save()
        values.return_value = {self.available.pk: PlayerValue(horizon='short')}
        self.save_projection(self.owned_a, 7, 8, status='ml_model')
        FantasyRosterPlayer.objects.filter(roster=self.roster_a, player_id=self.owned_a.pk).update(roster_slot='BN')
        for week in range(8, 19):
            self.save_projection(self.owned_a, week, 8, status='ml_model')
        self.save_projection(self.available, 7, 15, status='ml_model')
        response = self.browse(search='no matching name')
        self.assertEqual(self.names(response), [])
        move = response.context['suggested_moves'][1]
        self.assertEqual(move['pickup']['player'].pk, self.available.pk)
        self.assertEqual(move['gain'], 7)
        self.assertContains(response, 'Suggested Moves')
        self.assertEqual(move['drop']['player'].pk, self.owned_a.pk)
        self.assertEqual(move['drop']['player'].team.abbreviation, 'GB')
        self.assertContains(response, 'WR · GB')
        self.assertContains(response, 'class="waiver-move-points"', count=2)
        self.assertContains(response, '96.0')
        self.assertContains(response, 'aria-label="Rest-of-season prediction unavailable"')
        self.assertContains(response, 'waiver-add-label">Add')
        self.assertContains(response, 'waiver-move-action">Drop')

    @patch('analyzer.waivers.load_player_values')
    def test_missing_unrelated_forecast_does_not_block_live_suggestion(self, values):
        UserLeagueConnection.objects.filter(user=self.user, league=self.league_a).update(external_user_id='owner-a')
        self.roster_a.owner_sleeper_id = 'owner-a'
        self.roster_a.save()
        self.league_a.roster_positions = ['WR', 'TE']
        self.league_a.save()
        missing = self.make_player('Missing Tight End', 'TE', 25)
        FantasyRosterPlayer.objects.create(roster=self.roster_a, player_id=missing.pk,
            roster_slot='TE', created_at=timezone.now())
        FantasyRosterPlayer.objects.filter(roster=self.roster_a, player_id=self.owned_a.pk).update(roster_slot='BN')
        for week in range(7, 19):
            self.save_projection(self.owned_a, week, 8, status='ml_model')
        self.save_projection(self.available, 7, 15, status='ml_model')
        values.return_value = {self.available.pk: PlayerValue(horizon='short')}
        move = self.browse(position='FLEX').context['suggested_moves'][1]
        self.assertEqual(move['pickup']['player'].pk, self.available.pk)
        self.assertEqual(move['drop']['player'].pk, self.owned_a.pk)
        self.assertEqual(move['gain'], 7)


class SuggestedMoveTests(SimpleTestCase):
    def row(self, name, position='RB', weekly=10, season=100, horizon='long', slot='BN'):
        return {'player': SimpleNamespace(pk=name, full_name=name, position=position),
            'prediction': WaiverPrediction(weekly, season), 'value': PlayerValue(horizon=horizon), 'roster_slot': slot}

    def test_short_pickup_must_beat_bench_options_and_fill_league_slot(self):
        owned = [self.row('Starter', weekly=8, slot='RB'), self.row('Bench', weekly=18, horizon='fading')]
        moves = suggested_moves([self.row('Temporary', weekly=12, horizon='short')], owned, ['RB'])
        self.assertIsNone(moves[1]['pickup'])
        self.assertIn('Hold for now', moves[1]['message'])
        moves = suggested_moves([self.row('Temporary', weekly=20, horizon='short')], owned, ['RB'])
        self.assertEqual(moves[1]['gain'], 2)
        self.assertEqual(moves[1]['drop']['player'].full_name, 'Bench')
        self.assertIsNone(suggested_moves([self.row('QB', position='QB', weekly=30, horizon='short')], owned, ['RB'])[1]['pickup'])

    def test_long_pickup_uses_season_points_and_flex_slots(self):
        owned = [self.row('Roster', weekly=20, season=90)]
        moves = suggested_moves([self.row('Hold', position='WR', weekly=8, season=130)], owned, ['FLEX'])
        self.assertEqual(moves[0]['pickup']['player'].full_name, 'Hold')
        self.assertEqual(moves[0]['gain'], 40)

    def test_missing_forecasts_do_not_become_zero_for_recommendations(self):
        moves = suggested_moves([self.row('Hold', season=130)], [self.row('Unknown', season=None)], ['RB'])
        self.assertIsNone(moves[0]['pickup'])
        self.assertIn('missing', moves[0]['message'])
        moves = suggested_moves([self.row('Unknown', season=None, weekly=0, horizon='short')], [], ['RB'])
        self.assertTrue(all(move['pickup'] is None for move in moves))

    def test_no_eligible_pickups_explains_both_empty_cards(self):
        moves = suggested_moves([], [], ['RB'])
        self.assertEqual([move['horizon'] for move in moves], ['long', 'short'])
        self.assertTrue(all(move['message'] and move['pickup'] is None for move in moves))

    def test_short_pickup_does_not_drop_starter_injury_stash_or_long_term_hold(self):
        pickup = self.row('Fill-in', weekly=30, horizon='short')
        for slot, horizon, injury in [('RB', 'fading', ''), ('IR', 'fading', ''),
                ('TAXI', 'fading', ''), ('BN', 'long', ''), ('BN', 'fading', 'Questionable'),
                ('BN', 'fading', 'Out')]:
            with self.subTest(slot=slot, horizon=horizon, injury=injury):
                held = self.row('Hold', weekly=0, horizon=horizon, slot=slot)
                held['player'].injury_status = injury
                move = suggested_moves([pickup], [held], ['RB'])[1]
                self.assertIsNone(move['pickup'])
                self.assertIn('no clear bench player to drop', move['message'])

    def test_drops_need_known_season_value_and_preserve_filled_lineup_slots(self):
        pickup = self.row('Fill-in', weekly=30, horizon='short')
        missing = self.row('Unknown', weekly=8, season=None, horizon='unknown')
        self.assertIsNone(suggested_moves([pickup], [missing], ['RB'])[1]['pickup'])
        # A WR pickup must not cut the only RB to inflate the total with an empty RB slot.
        held = self.row('Only RB', weekly=8, horizon='fading')
        pickup['player'].position = 'WR'
        self.assertIsNone(suggested_moves([pickup], [held], ['RB', 'WR'])[1]['pickup'])

    def test_long_term_depth_swap_with_missing_running_back_forecasts(self):
        owned = [self.row('Starter QB', position='QB', season=260, slot='QB'),
            self.row('Backup QB', position='QB', season=220),
            self.row('Unknown RB one', weekly=None, season=None, slot='RB'),
            self.row('Unknown RB two', weekly=None, season=None)]
        pickup = self.row('RB prospect', weekly=8, season=130)
        move = suggested_moves([pickup], owned, ['QB', 'RB', 'FLEX'])[0]
        self.assertEqual(move['pickup']['player'].full_name, 'RB prospect')
        self.assertEqual(move['drop']['player'].full_name, 'Backup QB')
        self.assertEqual(move['gain'], 0)
        self.assertIn('Adds RB depth', move['message'])

    def test_depth_swap_keeps_only_quarterback_and_superflex_cover(self):
        backup = self.row('Backup QB', position='QB', season=220)
        starter = self.row('Starter QB', position='QB', season=260, slot='QB')
        pickup = self.row('RB prospect', season=130)
        unknown = self.row('Unknown RB', season=None, slot='RB')
        self.assertIsNone(suggested_moves([pickup], [backup, unknown], ['QB', 'RB'])[0]['pickup'])
        self.assertIsNone(suggested_moves([pickup], [starter, backup, unknown], ['QB', 'SUPER_FLEX', 'RB'])[0]['pickup'])

    def test_weekly_upgrade_cancels_unrelated_missing_forecast(self):
        owned = [self.row('Starter RB', weekly=8, slot='RB'),
            self.row('Fading bench', weekly=5, horizon='fading'),
            self.row('Unknown TE', position='TE', weekly=None, season=None, slot='TE')]
        move = suggested_moves([self.row('Fill-in', weekly=20, horizon='short')], owned, ['RB', 'TE'])[1]
        self.assertEqual(move['gain'], 12)
        self.assertEqual(move['drop']['player'].full_name, 'Fading bench')

    def test_weekly_upgrade_does_not_assume_unknown_competitor_scores_zero(self):
        owned = [self.row('Bench', weekly=8, horizon='fading'),
            self.row('Unknown RB', weekly=None, season=None, slot='RB')]
        move = suggested_moves([self.row('Fill-in', weekly=20, horizon='short')], owned, ['RB'])[1]
        self.assertIsNone(move['pickup'])
        self.assertIn('missing', move['message'])

    def test_long_term_requires_stable_role_and_complete_season_projection(self):
        owned = [self.row('Bench', season=90)]
        for horizon, season in [('short', 200), ('unknown', 200), ('fading', 200), ('long', None)]:
            with self.subTest(horizon=horizon, season=season):
                pickup = self.row('Weekly spike', weekly=35, season=season, horizon=horizon)
                self.assertIsNone(suggested_moves([pickup], owned, ['RB'])[0]['pickup'])

    def test_depth_swap_does_not_overfill_already_deep_position(self):
        owned = [self.row('Starter QB', position='QB', season=260, slot='QB'),
            self.row('Backup QB', position='QB', season=220),
            self.row('Better RB', season=250, slot='RB'),
            self.row('Reserve RB', season=None)]
        self.assertIsNone(suggested_moves([self.row('Another RB', season=130)], owned, ['QB', 'RB'])[0]['pickup'])

    def test_depth_swap_needs_known_stronger_cover(self):
        owned = [self.row('Unknown QB', position='QB', season=None, slot='QB'),
            self.row('Backup QB', position='QB', season=220),
            self.row('Unknown RB', season=None, slot='RB')]
        self.assertIsNone(suggested_moves([self.row('RB prospect', season=130)], owned, ['QB', 'RB'])[0]['pickup'])
