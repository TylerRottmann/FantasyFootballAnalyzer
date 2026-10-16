"""Exercise saved RB model predictions through generation and the start/sit page."""

from io import StringIO
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import ContextList
from django.urls import reverse
from django.utils import timezone

from analyzer.models import NFLGame, PlayerWeeklyStats, Teams, TeamWeeklyStats
from leagues.models import (
    FantasyLeague, FantasyProjection, FantasyRoster, FantasyRosterPlayer,
    Player, UserLeagueConnection,
)
from scripts.algorithm.features.rb_features import RBSeasonData, build_rb_features
from scripts.algorithm.predictor import predict_player
from scripts.tests.test_rb_algorithm import player_game, snapshot, team_game


@skipUnless(connection.vendor == "sqlite", "Run with scripts.tests.rb_test_settings for an isolated database.")
class RBStartSitTests(TestCase):
    external_models = (
        Teams, Player, FantasyLeague, FantasyRoster, FantasyRosterPlayer,
        PlayerWeeklyStats, TeamWeeklyStats, NFLGame,
    )

    @classmethod
    def setUpClass(cls):
        cls.created_models = []
        existing = set(connection.introspection.table_names())
        with connection.schema_editor() as editor:
            for model in cls.external_models:
                if model._meta.db_table not in existing:
                    editor.create_model(model)
                    cls.created_models.append(model)
                    existing.add(model._meta.db_table)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with connection.schema_editor() as editor:
            for model in reversed(cls.created_models):
                editor.delete_model(model)

    def setUp(self):
        cache.clear()
        now = timezone.now()
        self.user = get_user_model().objects.create_user(username="rb-page-review")
        self.home = Teams.objects.create(
            id=10, external_id="KC", abbreviation="KC", name="Kansas City",
            conference="AFC", division="West", is_active=True,
            created_at=now, updated_at=now,
        )
        self.away = Teams.objects.create(
            id=20, external_id="LAR", abbreviation="LAR", name="Los Angeles",
            conference="NFC", division="West", is_active=True,
            created_at=now, updated_at=now,
        )
        self.league = FantasyLeague.objects.create(
            sleeper_league_id="rb-page-fixture", name="RB Integration League", season=2026,
            ppr=1, scoring_settings={"rec": 1}, starter_count=1,
            roster_positions=["RB", "BN"], created_at=now, updated_at=now,
        )
        self.roster = FantasyRoster.objects.create(
            league=self.league, sleeper_roster_id=1, owner_sleeper_id="rb-test-owner",
            owner_name="RB Test Roster", created_at=now, updated_at=now,
        )
        UserLeagueConnection.objects.create(
            user=self.user, league=self.league, platform="sleeper", external_user_id="rb-test-owner",
        )
        self.low = self.make_player(1, "Fixture Reserve RB", "rb-fixture-low")
        self.high = self.make_player(2, "Fixture Starter RB", "rb-fixture-high")
        for player, slot in ((self.low, "RB"), (self.high, "BN")):
            FantasyRosterPlayer.objects.create(
                roster=self.roster, player=player, roster_slot=slot, created_at=now,
            )
        NFLGame.objects.create(
            season=2026, week=2, game_type="REG", game_date=now.date(),
            home_team=self.home, away_team=self.away,
        )
        for tid, opponent in ((10, 20), (20, 10)):
            TeamWeeklyStats.objects.create(
                team_id=tid, opponent_team_id=opponent, season=2026, week=1, season_type=1,
                is_home=tid == 10, points_for=24, points_against=21,
                passing_yards=200, rushing_yards=100, total_yards=300,
                rb_fantasy_points_allowed=15, te_fantasy_points_allowed=10,
                created_at=now, updated_at=now,
            )
        self.data = snapshot(season=2026, player_games=[
            player_game(1, 2, player_id=1, carries=1, rushing_yards=5,
                        targets=1, receptions=1, receiving_yards=2),
            player_game(2, 5, player_id=1),
            player_game(1, 25, player_id=2, carries=20, rushing_yards=100,
                        rushing_tds=1, targets=6, receptions=5, receiving_yards=45),
            player_game(2, 20, player_id=2),
        ], schedules=[{"week": 2, "home_team_id": 10, "away_team_id": 20}])
        self.client.force_login(self.user)
        session = self.client.session
        session["active_league_id"] = self.league.id
        session.save()

    def make_player(self, player_id, name, sleeper_id, position="RB"):
        now = timezone.now()
        return Player.objects.create(
            id=player_id, sleeper_id=sleeper_id, full_name=name, position=position,
            team_id=10, created_at=now, updated_at=now,
        )

    def generate(self):
        output = StringIO()
        # The saved model, feature calculations, router, and persistence are real.
        # Only the historical source snapshot is supplied by isolated fixtures.
        with patch.object(RBSeasonData, "load", return_value=self.data):
            expected = {p.id: predict_player(p.id, 2026, 2) for p in (self.low, self.high)}
            call_command("generate_projections", season=2026, week=2, stdout=output)
        self.assertIn("Failed: 0", output.getvalue())
        self.assertEqual(FantasyProjection.objects.count(), 2)
        for player_id, prediction in expected.items():
            self.assertEqual(prediction["status"], "ml_model")
            stored = FantasyProjection.objects.get(player_id=player_id, season=2026, week=2)
            self.assertEqual(stored.model_version, "v1")
            self.assertEqual(stored.status, "ml_model")
            self.assertEqual(stored.projected_fantasy_points, prediction["projected_fantasy_points"])
        return expected

    def page(self, current_week=2):
        def capture_context(store, signal, sender, template, context, **kwargs):
            # Django 5.1 Context copying fails on Python 3.14 during test capture.
            # Capture a flattened snapshot while leaving template rendering intact.
            store.setdefault("templates", []).append(template)
            store.setdefault("context", ContextList()).append(context.flatten())

        with patch("leagues.views.get_current_nfl_week", return_value=current_week), \
             patch("django.test.client.store_rendered_templates", side_effect=capture_context):
            return self.client.get(reverse("start_sit"), {"week": 2})

    def test_generation_saved_model_to_page_and_optimizer(self):
        expected = self.generate()
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "start_sit/start-sit.html")
        self.assertTrue(response.context["projections_available"])
        self.assertFalse(response.context["projections_required"])
        self.assertEqual(response.context["current_lineup"][0]["item"]["player"].id, self.low.id)
        self.assertGreater(expected[self.high.id]["projected_fantasy_points"],
                           expected[self.low.id]["projected_fantasy_points"])
        self.assertEqual(response.context["optimized_lineup"][0]["item"]["player"].id, self.high.id)
        self.assertEqual(response.context["optimized_total"], expected[self.high.id]["projected_fantasy_points"])
        for prediction in expected.values():
            formatted = f'{prediction["projected_fantasy_points"]:.1f}'
            self.assertContains(response, f'data-projection-points="{formatted}"')
        self.assertContains(response, 'data-projection-status="ml_model"')
        self.assertContains(response, 'data-model-version="v1"')

    def test_generation_updates_same_version_without_duplicates(self):
        first = self.generate()
        second = self.generate()
        self.assertEqual(first, second)

    def test_missing_saved_projections_are_reported(self):
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["projections_required"])
        self.assertFalse(response.context["projections_available"])
        self.assertContains(response, "Projections Not Available")

    def test_historical_roster_uses_saved_rb_model_projections(self):
        expected = self.generate()
        matchups = [{
            "roster_id": 1, "players": [self.low.sleeper_id, self.high.sleeper_id],
            "starters": [self.low.sleeper_id],
            "players_points": {self.low.sleeper_id: 5, self.high.sleeper_id: 20},
        }]
        with patch("leagues.views.SleeperLeagueService.get_matchups", return_value=matchups):
            response = self.page(current_week=3)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["historical_mode"])
        self.assertFalse(response.context["algorithm_projection_gaps"])
        self.assertEqual(response.context["current_projected_total"], expected[self.low.id]["projected_fantasy_points"])
        self.assertEqual(response.context["optimized_lineup"][0]["item"]["player"].id, self.high.id)
        self.assertEqual(response.context["optimized_actual_total"], 20)

    def test_rb_details_use_same_model_features_and_matchup(self):
        expected = build_rb_features(self.high, 2026, 2, self.data)
        with patch.object(RBSeasonData, "load", return_value=self.data):
            response = self.client.get(reverse("projection_details", args=[self.high.id]), {"week": 2})
        self.assertEqual(response.status_code, 200)
        details = response.json()
        self.assertEqual(details["position"], "RB")
        self.assertEqual(details["game_status"], expected["game_status"])
        self.assertEqual(details["opponent"], expected["opponent_team"])
        self.assertEqual(details["home"], expected["is_home"])
        stats = {row["label"]: row for row in details["player_stats"]}
        self.assertEqual(stats["Rush attempts"]["last3"], expected["carries_l3"])
        self.assertEqual(stats["Touches"]["last3"], expected["touches_l3"])
        self.assertEqual(stats["Carry share"]["last3"], expected["carry_share_l3"])
        self.assertTrue(stats["Carry share"]["percent"])
        self.assertEqual(details["defense"]["position_allowed"], expected["opponent_rb_fantasy_allowed_l3"])

    def test_projection_details_enforce_roster_access(self):
        other = self.make_player(3, "Unrostered Fixture RB", "unrostered-rb")
        response = self.client.get(reverse("projection_details", args=[other.id]), {"week": 2})
        self.assertEqual(response.status_code, 404)

    def test_te_details_keep_existing_stats_path(self):
        now = timezone.now()
        te = self.make_player(3, "Fixture TE", "fixture-te", position="TE")
        FantasyRosterPlayer.objects.create(roster=self.roster, player=te, roster_slot="BN", created_at=now)
        PlayerWeeklyStats.objects.create(
            player_id=te.id, season=2026, week=1, season_type="REG", opponent_team="LA",
            targets=4, receptions=3, receiving_yards=30, receiving_tds=0, fantasy_points_ppr=6,
        )
        with patch.object(RBSeasonData, "load", side_effect=AssertionError("TE must not use RB features")):
            response = self.client.get(reverse("projection_details", args=[te.id]), {"week": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["position"], "TE")
        stats = {row["label"]: row for row in response.json()["player_stats"]}
        self.assertEqual(stats["Targets"]["last3"], 4)
        self.assertEqual(stats["Receptions"]["last3"], 3)
