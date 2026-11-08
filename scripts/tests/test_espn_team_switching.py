"""Database-backed regression test for switching ESPN teams."""

from django.test import TestCase
from django.urls import reverse

from leagues.models import UserLeagueConnection
from leagues.services.active_connection import get_active_connection
from scripts.tests.test_rb_start_sit import RBStartSitTests


class ESPNTeamSwitchingTests(RBStartSitTests):
    def test_two_espn_teams_can_switch(self):
        UserLeagueConnection.objects.filter(
            user=self.user, league=self.league
        ).delete()

        team_a = UserLeagueConnection.objects.create(
            user=self.user,
            league=self.league,
            platform="espn",
            external_user_id="123:2026:1",
        )
        team_b = UserLeagueConnection.objects.create(
            user=self.user,
            league=self.league,
            platform="espn",
            external_user_id="123:2026:2",
        )

        self.assertEqual(
            UserLeagueConnection.objects.filter(
                user=self.user, league=self.league, platform="espn"
            ).count(),
            2,
        )

        for selected in (team_a, team_b, team_a):
            response = self.client.get(
                reverse("select_league_connection", args=[selected.id])
            )
            self.assertEqual(response.status_code, 302)

            session = self.client.session
            self.assertEqual(session["active_connection_id"], selected.id)

            request = response.wsgi_request
            request.session = session
            resolved = get_active_connection(
                request, fallback_to_recent=False
            )
            self.assertEqual(resolved.id, selected.id)
