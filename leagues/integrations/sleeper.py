import json
from urllib.request import urlopen

from django.db import transaction
from django.utils import timezone

from leagues.models import (
    FantasyLeague,
    FantasyRoster,
    FantasyRosterPlayer,
    Player,
    UserLeagueConnection,
)


class SleeperLeagueService:
    BASE_URL = "https://api.sleeper.app/v1"

    def __init__(self, league_id):
        self.league_id = str(league_id).strip()

    def _get(self, endpoint):
        url = f"{self.BASE_URL}{endpoint}"

        with urlopen(url) as response:
            return json.load(response)

    def get_league(self):
        return self._get(
            f"/league/{self.league_id}"
        )

    def get_rosters(self):
        return self._get(
            f"/league/{self.league_id}/rosters"
        )

    def get_users(self):
        return self._get(
            f"/league/{self.league_id}/users"
        )

    def get_league_data(self):
        return {
            "league": self.get_league(),
            "rosters": self.get_rosters(),
            "users": self.get_users(),
        }

    @staticmethod
    def find_user(users, username):
        if not username:
            return None

        username = username.strip().lower()

        for sleeper_user in users:
            sleeper_username = (
                sleeper_user.get("username") or ""
            ).strip().lower()

            display_name = (
                sleeper_user.get("display_name") or ""
            ).strip().lower()

            if (
                username == sleeper_username
                or username == display_name
            ):
                return sleeper_user

        return None

    @transaction.atomic
    def import_league(
        self,
        user,
        platform_username=None,
    ):
        league_data = self.get_league()
        rosters = self.get_rosters()
        users = self.get_users()

        now = timezone.now()

        # ---------------------------------------------------------
        # League scoring settings
        # ---------------------------------------------------------

        scoring_settings = (
            league_data.get("scoring_settings") or {}
        )

        roster_positions = (
            league_data.get("roster_positions") or []
        )

        ppr = scoring_settings.get(
            "rec",
            0,
        )

        te_premium = scoring_settings.get(
            "bonus_rec_te",
            0,
        )

        non_starting_positions = {
            "BN",
            "IR",
            "TAXI",
        }

        starter_count = sum(
            1
            for position in roster_positions
            if position not in non_starting_positions
        )

        # ---------------------------------------------------------
        # Find the user's Sleeper account
        # ---------------------------------------------------------

        username = (
            platform_username
            or user.sleeper_username
        )

        sleeper_user = self.find_user(
            users,
            username,
        )

        if sleeper_user is None:
            raise ValueError(
                f"Sleeper user '{username}' was not found "
                f"in this league."
            )

        # ---------------------------------------------------------
        # Import / update league
        # ---------------------------------------------------------

        league, _ = (
            FantasyLeague.objects.update_or_create(
                sleeper_league_id=self.league_id,
                defaults={
                    "name": league_data.get(
                        "name",
                        "Unnamed League",
                    ),
                    "season": (
                        int(league_data["season"])
                        if league_data.get("season")
                        else None
                    ),
                    "ppr": ppr,
                    "te_premium": te_premium,
                    "starter_count": starter_count,
                    "updated_at": now,
                },
            )
        )

        imported_rosters = 0
        imported_players = 0

        # ---------------------------------------------------------
        # Import rosters
        # ---------------------------------------------------------

        for roster_data in rosters:

            roster_id = roster_data.get(
                "roster_id"
            )

            if roster_id is None:
                continue

            owner_sleeper_id = (
                roster_data.get("owner_id")
            )

            owner_name = None

            # Find the owner of this roster.
            for sleeper_user_data in users:

                if (
                    sleeper_user_data.get("user_id")
                    == owner_sleeper_id
                ):
                    owner_name = (
                        sleeper_user_data.get(
                            "display_name"
                        )
                        or sleeper_user_data.get(
                            "username"
                        )
                    )

                    break

            # Create or update roster.
            roster, _ = (
                FantasyRoster.objects.update_or_create(
                    league=league,
                    sleeper_roster_id=roster_id,
                    defaults={
                        "owner_sleeper_id": (
                            owner_sleeper_id
                        ),
                        "owner_name": owner_name,
                        "updated_at": now,
                    },
                )
            )

            imported_rosters += 1

            # -----------------------------------------------------
            # Rebuild players belonging to this roster
            # -----------------------------------------------------

            FantasyRosterPlayer.objects.filter(
                roster=roster
            ).delete()

            roster_player_entries = []

            for sleeper_player_id in (
                roster_data.get("players") or []
            ):

                try:
                    player = Player.objects.get(
                        sleeper_id=str(
                            sleeper_player_id
                        )
                    )

                except (
                    Player.DoesNotExist,
                    ValueError,
                    TypeError,
                ):
                    continue

                roster_player_entries.append(
                    FantasyRosterPlayer(
                        roster=roster,
                        player=player,
                        created_at=now,
                    )
                )

            if roster_player_entries:

                FantasyRosterPlayer.objects.bulk_create(
                    roster_player_entries
                )

                imported_players += len(
                    roster_player_entries
                )

        # ---------------------------------------------------------
        # Associate league with logged-in user
        # ---------------------------------------------------------

        UserLeagueConnection.objects.update_or_create(
            user=user,
            league=league,
            defaults={
                "platform": (
                    UserLeagueConnection.PLATFORM_SLEEPER
                ),
                "external_user_id": (
                    sleeper_user.get("user_id")
                    if sleeper_user
                    else None
                ),
            },
        )

        # ---------------------------------------------------------
        # Return import results
        # ---------------------------------------------------------

        return {
            "league": league,
            "sleeper_user": sleeper_user,
            "rosters_imported": imported_rosters,
            "players_imported": imported_players,
        }