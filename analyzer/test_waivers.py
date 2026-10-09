from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from analyzer.models import Players, Teams
from analyzer.waiver_predictions import WaiverPrediction, predict_waiver_player
from leagues.models import FantasyLeague, FantasyRoster, FantasyRosterPlayer, UserLeagueConnection


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
        self.assertContains(response, 'Demo predictions')
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
        predict.side_effect = lambda player, league: values.get(player.pk, WaiverPrediction(1, 1))
        weekly = self.browse()
        season = self.browse(sort='season')
        self.assertEqual(self.names(weekly)[0], self.available.full_name)
        self.assertEqual(self.names(season)[0], self.young.full_name)
        self.assertEqual(self.names(weekly)[2:], sorted(self.names(weekly)[2:], key=str.casefold))

    def test_placeholder_is_repeatable(self):
        value = predict_waiver_player(self.available, self.league_a)
        self.assertEqual(value, predict_waiver_player(self.available, self.league_a))
        self.assertGreater(value.this_week, 0)
        self.assertGreater(value.rest_of_season, 0)

    def test_pagination_preserves_combined_filters(self):
        for number in range(55):
            self.make_player(f'Extra {number}', 'TE', 24)
        response = self.browse(position='TE', age_min=24, sort='season')
        self.assertEqual(len(self.names(response)), 50)
        self.assertContains(response, 'position=TE&amp;age_min=24&amp;sort=season&amp;page=2')
        second = self.browse(position='TE', age_min=24, sort='season', page=2)
        self.assertEqual(len(self.names(second)), 5)
        self.assertTrue(set(self.names(response)).isdisjoint(self.names(second)))
        self.assertEqual(self.browse(page='bad').status_code, 200)
        self.assertEqual(self.browse(page=99999).status_code, 200)
