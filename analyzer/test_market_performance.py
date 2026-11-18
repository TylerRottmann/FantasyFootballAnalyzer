from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from analyzer.market import _filtered_rows
from analyzer.models import Players, Teams, PlayerMarketProjection
from leagues.models import FantasyLeague, FantasyProjection


class MarketRetrievalTests(TestCase):
    external_models = (Teams, Players, FantasyLeague)

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
        cls.team = Teams.objects.create(external_id='GB', name='Packers', abbreviation='GB',
            conference='NFC', division='North', is_active=True, created_at=now, updated_at=now)
        cls.league = FantasyLeague.objects.create(name='Test league', season=2026, ppr=1,
            te_premium=0, scoring_settings={'schema_version': 1, 'source': 'reference',
                'rules': {'rec': 1, 'rec_yd': 0.1}}, created_at=now, updated_at=now)
        for index, position in enumerate(('WR', 'TE')):
            player = Players.objects.create(sleeper_id=f'test-{index}', full_name=f'Player {index}',
                position=position, team=cls.team, created_at=now, updated_at=now)
            for week in range(11, 19):
                FantasyProjection.objects.create(player_id=player.pk, season=2026, week=week,
                    model_version='v2_stat', status='projected', projected_fantasy_points=8,
                    projected_stats={'receptions': 3, 'receiving_yards': 50})
                PlayerMarketProjection.objects.create(entity_key=f'player:{player.pk}',
                    external_id=player.sleeper_id, player_id=player.pk, position=position,
                    season=2026, week=week, projection_available=True,
                    projected_stats={'rec': 4, 'rec_yd': 60})

    def browse(self, route='market_short_term', **params):
        request = RequestFactory().get('/market/short-term/', {'week': 11, **params})
        request.resolver_match = SimpleNamespace(url_name=route)
        with patch('analyzer.market.league_selector', return_value={'active_league': self.league}):
            with CaptureQueriesContext(connection) as queries:
                context = _filtered_rows(request)
        return context, [query['sql'] for query in queries]

    def test_weekly_page_loads_only_weekly_data_and_reuses_players(self):
        context, queries = self.browse()
        self.assertEqual(len(queries), 5)
        self.assertFalse(any('analyzer_playeradp' in sql for sql in queries))
        self.assertFalse(any('>= 11' in sql for sql in queries))
        for sql in queries:
            if 'FROM "fantasy_projections"' in sql:
                self.assertNotIn('JOIN "players"', sql)
                self.assertNotIn('"created_at"', sql)
        rows = [row for row in context['market_rows'] if row['player'] is not None]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row['weekly_our'], 8)
            self.assertEqual(row['weekly_sleeper'], 10)
            self.assertIsNone(row['our_ros'])

    def test_long_term_keeps_complete_totals_and_ranks(self):
        context, queries = self.browse('market_long_term')
        self.assertTrue(any('>= 11' in sql for sql in queries))
        self.assertTrue(context['has_ros_data'])
        rows = [row for row in context['market_rows'] if row['player'] is not None]
        for rank, row in enumerate(rows, 1):
            self.assertEqual(row['our_ros'], 64)
            self.assertEqual(row['sleeper_ros'], 80)
            self.assertEqual(row['our_ros_rank'], rank)

    def test_legacy_season_sort_on_weekly_page_still_works(self):
        context, _ = self.browse(sort='our_ros')
        self.assertEqual(context['sort'], 'our_ros')
        self.assertTrue(context['has_ros_data'])

    def test_missing_week_does_not_invent_a_season_total(self):
        PlayerMarketProjection.objects.filter(week=18).delete()
        FantasyProjection.objects.filter(week=18).delete()
        context, _ = self.browse('market_long_term')
        self.assertFalse(context['has_ros_data'])
        for row in context['market_rows']:
            self.assertIsNone(row['our_ros'])
            self.assertIsNone(row['sleeper_ros'])
