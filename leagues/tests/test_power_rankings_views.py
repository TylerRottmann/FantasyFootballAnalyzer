"""Regression tests for Power Rankings with multiple ESPN connections."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import Http404
from django.db import connection
from django.utils import timezone
from django.test import RequestFactory, TestCase
from django.urls import reverse

from leagues.models import FantasyLeague, UserLeagueConnection
from leagues.views import get_user_league_or_404, sync_matchups


class PowerRankingsMultipleConnectionsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        with connection.schema_editor() as editor:
            editor.create_model(FantasyLeague)
        try:
            super().setUpClass()
        except Exception:
            with connection.schema_editor() as editor:
                editor.delete_model(FantasyLeague)
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(FantasyLeague)

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="rankings_owner", password="test-password"
        )
        cls.other_user = get_user_model().objects.create_user(
            username="rankings_other", password="test-password"
        )
        cls.league = FantasyLeague.objects.create(
            sleeper_league_id="espn-rankings-test",
            name="ESPN Test League",
            season=2026,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        cls.first = UserLeagueConnection.objects.create(
            user=cls.user,
            league=cls.league,
            platform="espn",
            external_user_id="12345:2026:7",
        )
        cls.second = UserLeagueConnection.objects.create(
            user=cls.user,
            league=cls.league,
            platform="espn",
            external_user_id="12345:2026:8",
        )

    def test_multiple_connections_can_access_same_league(self):
        result = get_user_league_or_404(self.user, self.league.pk)
        self.assertEqual(result.pk, self.league.pk)

    def test_unconnected_user_cannot_access_league(self):
        with self.assertRaises(Http404):
            get_user_league_or_404(self.other_user, self.league.pk)

    def test_sync_uses_selected_connection(self):
        request = RequestFactory().post(
            reverse("sync_matchups", args=[self.league.pk]),
            HTTP_ACCEPT="application/json",
        )
        request.user = self.user
        request.session = {
            "active_connection_id": self.second.pk,
            "active_league_id": self.league.pk,
        }

        with (
            patch("leagues.views.cache.get", return_value=None),
            patch("leagues.views.cache.add", return_value=True),
            patch("leagues.views.cache.set"),
            patch("leagues.views.cache.delete"),
            patch("leagues.views.get_current_nfl_week", return_value=10),
            patch("leagues.views.sync_connection_matchups", return_value=3) as sync,
        ):
            response = sync_matchups(request, self.league.pk)

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content, {"status": "synced", "synced": 3}
        )
        self.assertEqual(sync.call_args.args[0].pk, self.second.pk)

    def test_sync_rejects_ambiguous_connection(self):
        request = RequestFactory().post(
            reverse("sync_matchups", args=[self.league.pk]),
            HTTP_ACCEPT="application/json",
        )
        request.user = self.user
        request.session = {"active_league_id": self.league.pk}

        with patch("leagues.views.sync_connection_matchups") as sync:
            response = sync_matchups(request, self.league.pk)

        self.assertEqual(response.status_code, 400)
        self.assertIn("Select a team", json.loads(response.content)["error"])
        sync.assert_not_called()
