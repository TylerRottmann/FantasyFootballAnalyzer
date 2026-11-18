"""Exercise timing middleware without connecting to the shared database."""
import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FantasyFootballAnalyzer.test_settings')
django.setup()

from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from analyzer.middleware import RequestPerformanceMiddleware
from analyzer.performance import checkpoint, current_profile, timed_call


class ServerTimingTests(TestCase):
    def setUp(self):
        self.enterContext(override_settings(
            SERVER_TIMING_ENABLED=True, DEBUG=True, SLOW_REQUEST_LOG_THRESHOLD_MS=999999,
        ))

    def request(self, route='market_short_term', staff=False):
        request = RequestFactory().get('/market/short-term/?search=private-search')
        request.resolver_match = SimpleNamespace(url_name=route)
        request.user = SimpleNamespace(is_authenticated=True, is_staff=staff)
        return request

    def run_request(self, request, response=None, fail=False):
        def view(request):
            with connection.cursor() as cursor:
                timed_call('load_data', cursor.execute, 'SELECT 1')
            checkpoint('setup')
            if fail:
                raise ValueError('test failure')
            return response if response is not None else HttpResponse('ok')

        def get_response(request):
            middleware.process_view(request, view, (), {})
            return view(request)

        middleware = RequestPerformanceMiddleware(get_response)
        return middleware(request)

    def test_timings_query_count_and_request_isolation(self):
        for route in ('market_short_term', 'market_long_term', 'waiver_wire'):
            with self.subTest(route=route):
                response = self.run_request(self.request(route))
                header = response['Server-Timing']
                for metric in ('total;dur=', 'db;dur=', 'load_data;dur=', 'setup;dur='):
                    self.assertIn(metric, header)
                self.assertIn('db_queries;desc="1 queries"', header)
                self.assertNotIn('SELECT', header)
                self.assertNotIn('private-search', header)
                self.assertIn('private', response['Cache-Control'])
                self.assertIn('no-store', response['Cache-Control'])
                self.assertIsNone(current_profile.get())

    @override_settings(SERVER_TIMING_ENABLED=False)
    def test_can_disable_in_development(self):
        response = self.run_request(self.request())
        self.assertNotIn('Server-Timing', response)
        self.assertIsNone(current_profile.get())

    def test_unrelated_route_not_profiled(self):
        self.assertNotIn('Server-Timing', self.run_request(self.request('profile')))

    @override_settings(DEBUG=False)
    def test_production_requires_staff(self):
        self.assertNotIn('Server-Timing', self.run_request(self.request()))
        self.assertIn('Server-Timing', self.run_request(self.request(staff=True)))

    def test_preserves_existing_server_timing(self):
        response = HttpResponse('ok', headers={'Server-Timing': 'upstream;dur=1'})
        self.assertTrue(self.run_request(self.request(), response)['Server-Timing'].startswith('upstream;dur=1,'))

    def test_context_is_reset_on_exception(self):
        with self.assertRaises(ValueError):
            self.run_request(self.request(), fail=True)
        self.assertIsNone(current_profile.get())

    def test_real_page_views_include_render_timing(self):
        from analyzer.market import market_short_term, market_long_term
        from analyzer.waivers import waiver_wire

        cases = [('market_short_term', market_short_term, 'analyzer.market.league_selector'),
                 ('market_long_term', market_long_term, 'analyzer.market.league_selector'),
                 ('waiver_wire', waiver_wire, 'analyzer.waivers.league_selector')]
        for route, view, selector in cases:
            with self.subTest(route=route):
                request = self.request(route)
                request.GET = request.GET.copy()
                request.GET['week'] = '11'

                def get_response(request):
                    middleware.process_view(request, view, (), {})
                    return view(request)

                middleware = RequestPerformanceMiddleware(get_response)
                with patch(selector, return_value={'active_league': None}), patch(
                    'analyzer.performance.django_render', return_value=HttpResponse('ok'),
                ):
                    response = middleware(request)
                self.assertEqual(response.status_code, 200)
                self.assertIn('render;dur=', response['Server-Timing'])
                self.assertIsNone(current_profile.get())

    @override_settings(SLOW_REQUEST_LOG_THRESHOLD_MS=0)
    def test_slow_request_logs_stages_without_search_or_sql(self):
        with self.assertLogs('performance.requests', level='WARNING') as logs:
            self.run_request(self.request())
        message = logs.output[0]
        self.assertIn('db_queries=1', message)
        self.assertIn('load_data', message)
        self.assertNotIn('private-search', message)
        self.assertNotIn('SELECT', message)
