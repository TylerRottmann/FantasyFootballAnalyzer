"""Build empirical injury-duration profiles from nflverse history and local stats."""
from django.core.management.base import BaseCommand, CommandError
from pathlib import Path

from analyzer.injury_prediction import (
    build_duration_profiles,
    build_injury_episodes,
    save_duration_profiles,
)
from analyzer.models import PlayerWeeklyStats


class Command(BaseCommand):
    help = "Build injury return-duration profiles from historical injury reports."

    def add_arguments(self, parser):
        parser.add_argument(
            "--seasons",
            nargs="+",
            type=int,
            default=[2023, 2024, 2025, 2026],
            help="Seasons to include (default: 2023 through 2026).",
        )
        parser.add_argument("--output", help="Optional JSON output path.")

    def handle(self, *args, **options):
        import nflreadpy as nfl

        seasons = sorted(set(options["seasons"]))
        try:
            reports = nfl.load_injuries(seasons=seasons)
        except Exception as exc:
            raise CommandError(f"Could not load nflverse injury reports: {exc}") from exc

        required = {
            "season", "season_type", "week", "gsis_id", "position",
            "report_status", "report_primary_injury",
        }
        missing = required.difference(reports.columns)
        if missing:
            raise CommandError(
                "nflverse injury report schema is missing: " + ", ".join(sorted(missing))
            )

        reports = reports.filter(reports["season_type"] == "REG")
        rows = []
        for report in reports.iter_rows(named=True):
            if not report.get("gsis_id"):
                continue
            rows.append({
                "player_id": str(report["gsis_id"]),
                "season": report["season"],
                "week": report["week"],
                "position": report["position"],
                "status": report["report_status"],
                "injury_type": report["report_primary_injury"],
            })

        weekly_rows = PlayerWeeklyStats.objects.filter(
            season__in=seasons,
            season_type="REG",
        ).exclude(nflverse_player_id__isnull=True).values_list(
            "nflverse_player_id", "season", "week"
        )
        appearances = {}
        for player_id, season, week in weekly_rows.iterator():
            appearances.setdefault((str(player_id), int(season)), set()).add(int(week))

        episodes = build_injury_episodes(rows, appearances)
        profiles = build_duration_profiles(episodes)
        if not episodes or profiles["global"] is None:
            raise CommandError(
                "No resolved injury/return episodes matched local weekly stats; "
                "no profile file was written. Check player IDs and imported seasons."
            )

        output = Path(options["output"]) if options["output"] else None
        if output:
            save_duration_profiles(profiles, output)
        else:
            save_duration_profiles(profiles)

        self.stdout.write(f"Loaded {len(rows)} regular-season injury reports.")
        self.stdout.write(f"Matched {len(episodes)} resolved absence episodes.")
        self.stdout.write(
            f"Global 75th-percentile absence: {profiles['global']['weeks']} weeks "
            f"({profiles['global']['samples']} episodes)."
        )
        self.stdout.write(
            f"Saved injury duration profiles to "
            f"{output or 'analyzer/data/injury_duration_profiles.json'}."
        )
