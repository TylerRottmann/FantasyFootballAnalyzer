"""Refresh small Sleeper values served by the web app from shared cache."""
from django.utils import timezone
from django.core.management.base import BaseCommand, CommandError

from leagues.services.player_availability import projection_context
from leagues.models import UserLeagueConnection
from leagues.services.external_cache import refresh_sleeper_playoff_info
from scripts.commands.nflweek import refresh_current_nfl_week


class Command(BaseCommand):
    help = "Refresh cached NFL week and Sleeper playoff metadata."

    def handle(self, *args, **options):
        try:
            week = refresh_current_nfl_week()
        except Exception as exc:
            raise CommandError(f"Could not refresh the NFL week from Sleeper: {exc}") from exc
        self.stdout.write(f"Cached NFL week {week}.")

        today = timezone.localdate()
        season = today.year - 1 if today.month <= 2 else today.year
        try:
            projection_context(season, week)
            self.stdout.write(f"Warmed injury and player-role context for {season} week {week}.")
        except Exception as exc:
            self.stderr.write(self.style.WARNING(f"Could not warm player context: {exc}"))

        connections = (
            UserLeagueConnection.objects
            .filter(platform=UserLeagueConnection.PLATFORM_SLEEPER)
            .select_related("league")
            .order_by("league_id", "id")
        )
        seen_leagues = set()
        refreshed = failed = 0
        for connection in connections:
            league = connection.league
            if league.id in seen_leagues:
                continue
            seen_leagues.add(league.id)
            try:
                refresh_sleeper_playoff_info(league)
                refreshed += 1
            except Exception as exc:
                failed += 1
                self.stderr.write(
                    self.style.WARNING(
                        f"Could not refresh playoff metadata for {league.name}: {exc}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Refreshed playoff metadata for {refreshed} leagues; {failed} failed."
            )
        )
