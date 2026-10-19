from django.core.management.base import BaseCommand, CommandError

from leagues.models import UserLeagueConnection
from leagues.services.matchup_sync import sync_connection_matchups
from scripts.commands.nflweek import get_current_nfl_week


class Command(BaseCommand):
    help = "Sync league schedules and completed matchup results."

    def add_arguments(self, parser):
        parser.add_argument("--league-id", type=int, required=True)
        parser.add_argument("--start-week", type=int, default=1)
        parser.add_argument("--end-week", type=int, default=18)

    def handle(self, *args, **options):
        connection = (
            UserLeagueConnection.objects
            .select_related("league", "user")
            .filter(league_id=options["league_id"])
            .first()
        )
        if connection is None:
            raise CommandError("No connected platform account was found for that league.")

        current_week = get_current_nfl_week()
        try:
            imported = sync_connection_matchups(
                connection,
                current_week,
                start_week=options["start_week"],
                end_week=options["end_week"],
            )
        except Exception as exc:
            raise CommandError(f"Unable to sync matchup schedule: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(
            f"Synced {imported} team-week matchup rows for {connection.league.name}."
        ))
