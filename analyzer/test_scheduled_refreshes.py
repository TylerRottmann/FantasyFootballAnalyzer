from datetime import datetime, timezone
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from analyzer.management.commands.run_scheduled_refreshes import Command
from analyzer.models import ScheduledRefresh


class ScheduledRefreshTests(TestCase):
    def setUp(self):
        self.command = Command(stdout=StringIO())
        self.slot = datetime(2026, 11, 3, 16, tzinfo=timezone.utc)
        self.job = ScheduledRefresh.objects.get(pk="weekly")

    def test_seeded_jobs(self):
        self.assertEqual(
            set(ScheduledRefresh.objects.values_list("name", flat=True)),
            {"external-cache", "player-metadata", "injuries", "adp", "market", "weekly"},
        )
        output = StringIO()
        call_command("run_scheduled_refreshes", "--list", "--lane", "cache", stdout=output)
        self.assertIn("external-cache", output.getvalue())
        self.assertNotIn("weekly", output.getvalue())

    def test_failure_releases_lease_and_manual_rerun_completes_period(self):
        with patch.object(self.command, "run_pipeline", side_effect=RuntimeError("feed unavailable")):
            with self.assertRaisesMessage(CommandError, "feed unavailable"):
                self.command.run_job("weekly", self.slot, manual=False)
        self.job.refresh_from_db()
        self.assertIsNone(self.job.lease_until)
        self.assertEqual(self.job.completed_period, "")

        with patch.object(self.command, "run_pipeline", return_value="2026-9") as run:
            self.command.run_job("weekly", self.slot, manual=False)
            run.assert_not_called()
            self.command.run_job("weekly", self.slot, manual=True)
            run.assert_called_once()
        self.job.refresh_from_db()
        self.assertEqual(self.job.completed_period, "2026-9")

    def test_weekly_pipeline_runs_boom_bust_last(self):
        with (
            patch.object(self.command, "require_artifact_directory"),
            patch.object(self.command, "step") as step,
        ):
            period = self.command.weekly(self.job, self.slot, 2026, 9, "regular", True, manual=False)

        names = [
            call.kwargs["module"].rsplit(".", 1)[-1] if "module" in call.kwargs else call.args[0]
            for call in step.call_args_list
        ]
        self.assertEqual(period, "2026-9")
        self.assertEqual(names, [
            "load_player_data", "import_nfl_schedule", "refresh_player_context", "load_team_data",
            "load_dst_stats", "load_opportunity_stats", "load_advanced_team_data", "prepare_kicker_data",
            "build_injury_duration_profiles", "build_team_features", "build_matchup_features",
            "import_sleeper_market_projections", "generate_projections", "refresh_market_ranks",
            "generate_boom_bust_weekly",
        ])

    def test_prerequisite_failure_stops_downstream_work(self):
        with (
            patch.object(self.command, "require_artifact_directory"),
            patch.object(self.command, "step", side_effect=[None, None, RuntimeError("source missing")]) as step,
            self.assertRaisesMessage(RuntimeError, "source missing"),
        ):
            self.command.weekly(self.job, self.slot, 2026, 9, "regular", True, manual=False)
        self.assertEqual(step.call_count, 3)

    def test_week_one_skips_builders_that_need_prior_games(self):
        with (
            patch.object(self.command, "require_artifact_directory"),
            patch.object(self.command, "step") as step,
        ):
            period = self.command.weekly(self.job, self.slot, 2026, 1, "regular", True, manual=False)
        modules = [call.kwargs.get("module", "") for call in step.call_args_list]
        self.assertEqual(period, "2026-1")
        self.assertNotIn("scripts.imports.build_team_features", modules)
        self.assertNotIn("scripts.imports.build_matchup_features", modules)
        self.assertIn("scripts.generate_boom_bust_weekly", modules)

    def test_closeout_refreshes_week_18_without_postseason_projections(self):
        with (
            patch.object(self.command, "require_artifact_directory"),
            patch.object(self.command, "step") as step,
        ):
            period = self.command.weekly(self.job, self.slot, 2026, 1, "post", False, manual=False)
        self.assertEqual(period, "2026-final")
        step.assert_any_call("refresh_player_context", "--season", 2026, "--through-week", 18, "--stats-only")
        self.assertFalse(any(call.args[:1] == ("generate_projections",) for call in step.call_args_list))
