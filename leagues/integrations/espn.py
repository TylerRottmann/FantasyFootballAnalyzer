import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.db import transaction
from django.utils import timezone

from analyzer.models import Teams
from leagues.models import (
    FantasyLeague,
    FantasyRoster,
    FantasyRosterPlayer,
    LeaguePlatformIdentity,
    Player,
    PlayerPlatformIdentity,
    RosterPlatformIdentity,
    UserLeagueConnection,
)


class ESPNLeagueService:
    PLATFORM = UserLeagueConnection.PLATFORM_ESPN
    BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
    REQUEST_TIMEOUT = 15

    def __init__(self, league_id, season, swid=None, espn_s2=None):
        self.league_id = str(league_id or "").strip()
        self.swid = str(swid or "").strip()
        self.espn_s2 = str(espn_s2 or "").strip()

        if not self.league_id:
            raise ValueError("An ESPN League ID is required.")

        try:
            self.season = int(season)
        except (TypeError, ValueError):
            raise ValueError("A valid ESPN season is required.")

        if self.season < 2000:
            raise ValueError("Please enter a valid ESPN season.")

    def _get(self, view=None):
        url = (
            f"{self.BASE_URL}/seasons/{self.season}"
            f"/segments/0/leagues/{self.league_id}"
        )

        if view:
            url += f"?view={view}"

        headers = {
            "Accept": "application/json",
            "User-Agent": "FantasyFootballAnalyzer/1.0",
        }

        if self.swid and self.espn_s2:
            headers["Cookie"] = (
                f"SWID={self.swid}; espn_s2={self.espn_s2}"
            )

        request = Request(
            url,
            method="GET",
            headers=headers,
        )

        try:
            with urlopen(
                request,
                timeout=self.REQUEST_TIMEOUT,
            ) as response:
                return json.load(response)

        except HTTPError as error:
            if error.code in (401, 403):
                raise ValueError(
                    "This ESPN league is private or could not be accessed. "
                    "Private leagues require valid ESPN authentication."
                ) from error

            if error.code == 404:
                raise ValueError(
                    "ESPN league not found. Check the League ID and season."
                ) from error

            raise ValueError(
                f"ESPN returned an error ({error.code})."
            ) from error

        except (URLError, TimeoutError, OSError) as error:
            raise ValueError(
                "Could not connect to ESPN. Please try again."
            ) from error

    def get_league(self):
        return self._get("mSettings")

    def get_teams(self):
        data = self._get("mTeam")
        return data.get("teams", [])

    def get_rosters(self):
        data = self._get("mRoster")
        return data.get("teams", [])

    def get_league_data(self):
        league = self.get_league()

        return {
            "league": league,
            "teams": self.get_teams(),
            "rosters": self.get_rosters(),
            "name": league.get(
                "settings", {}
            ).get(
                "name",
                "Unnamed ESPN League",
            ),
            "season": self.season,
            "league_id": self.league_id,
        }
    @staticmethod
    def _position_name(position_id):
        positions = {
            1: "QB",
            2: "RB",
            3: "WR",
            4: "TE",
            5: "K",
            16: "DEF",
        }
        return positions.get(position_id)
    @staticmethod
    def _lineup_slot_name(slot_id):
        slots = {
            0: "QB",
            2: "RB",
            4: "WR",
            6: "TE",
            16: "DEF",
            17: "K",
            20: "BN",
            21: "IR",
            23: "FLEX",
        }
        return slots.get(slot_id, "BN")

    def _resolve_player(
        self,
        player_data,
        player_cache,
        identity_cache=None,
        identities_preloaded=False,
    ):
        espn_id = str(player_data.get("id") or "").strip()

        if not espn_id:
            return None

        identity_cache = (
            identity_cache
            if identity_cache is not None
            else {}
        )

        if espn_id in identity_cache:
            return identity_cache[espn_id]

        identity = (
            None
            if identities_preloaded
            else PlayerPlatformIdentity.objects.filter(
                platform=self.PLATFORM,
                external_id=espn_id,
            ).select_related("player").first()
        )

        if identity:
            identity_cache[espn_id] = identity.player
            return identity.player

        full_name = (player_data.get("fullName") or "").strip()

        if not full_name:
            return None

        normalized_name = re.sub(
            r"[^a-z0-9]",
            "",
            full_name.lower(),
        )

        position = self._position_name(
            player_data.get("defaultPositionId")
        )

        candidates = [
            player
            for player in player_cache
            if re.sub(
                r"[^a-z0-9]",
                "",
                (player.full_name or "").lower(),
            ) == normalized_name
        ]

        if position and position != "DEF":
            position_matches = [
                candidate
                for candidate in candidates
                if (candidate.position or "").upper() == position
            ]

            if position_matches:
                candidates = position_matches

        if len(candidates) != 1:
            identity_cache[espn_id] = None
            return None

        player = candidates[0]

        PlayerPlatformIdentity.objects.get_or_create(
            platform=self.PLATFORM,
            external_id=espn_id,
            defaults={
                "player": player,
            },
        )

        identity_cache[espn_id] = player
        return player
    @transaction.atomic
    def import_league(self, user, owned_team_id=None):
        data = self.get_league_data()

        league_data = data["league"]
        teams = data["teams"]
        roster_teams = data["rosters"]
        lineup_slot_counts = (
            league_data.get("settings", {})
            .get("rosterSettings", {})
            .get("lineupSlotCounts", {})
        )

        roster_positions = []
        for slot_id, count in lineup_slot_counts.items():
            slot_name = self._lineup_slot_name(int(slot_id))

            if slot_name not in {"BN", "IR"}:
                roster_positions.extend([slot_name] * int(count))

        starter_count = len(roster_positions)

        if not teams:
            raise ValueError("ESPN did not return any teams for this league.")

        now = timezone.now()

        identity = LeaguePlatformIdentity.objects.filter(
            platform=self.PLATFORM,
            external_id=self.league_id,
        ).select_related("league").first()

        league = identity.league if identity else None

        league_defaults = {
            "name": data["name"],
            "season": self.season,
            "ppr": None,
            "te_premium": 0,
            "scoring_settings": league_data.get("settings", {}),
            "starter_count": starter_count,
            "roster_positions": roster_positions,
            "updated_at": now,
        }

        if league is None:
            league = FantasyLeague.objects.create(
                sleeper_league_id=None,
                created_at=now,
                **league_defaults,
            )
        else:
            for field, value in league_defaults.items():
                setattr(league, field, value)

            league.save(
                update_fields=list(league_defaults)
            )

        LeaguePlatformIdentity.objects.update_or_create(
            platform=self.PLATFORM,
            external_id=self.league_id,
            defaults={
                "league": league,
            },
        )

        player_cache = list(Player.objects.all())

        all_espn_player_ids = []

        for roster_team in roster_teams:
            entries = (
                roster_team.get("roster", {})
                .get("entries", [])
            )

            for entry in entries:
                player_data = (
                    entry.get("playerPoolEntry", {})
                    .get("player", {})
                )

                player_id = str(
                    player_data.get("id") or ""
                ).strip()

                if player_id:
                    all_espn_player_ids.append(player_id)

        player_identity_cache = {
            identity.external_id: identity.player
            for identity in PlayerPlatformIdentity.objects.filter(
                platform=self.PLATFORM,
                external_id__in=set(all_espn_player_ids),
            ).select_related("player")
        }

        roster_data_by_id = {
            str(team.get("id")): team
            for team in roster_teams
        }

        own_roster = None
        imported_rosters = 0
        imported_players = 0

        for team_data in teams:
            team_id = team_data.get("id")

            if team_id is None:
                continue

            team_id_string = str(team_id)

            owner_id = str(
                team_data.get("primaryOwner") or ""
            ).strip()

            roster, _ = FantasyRoster.objects.update_or_create(
                league=league,
                sleeper_roster_id=None,
                owner_sleeper_id=owner_id or None,
                defaults={
                    "owner_name": (
                        team_data.get("name")
                        or f"ESPN team {team_id}"
                    ),
                    "updated_at": now,
                },
            )

            RosterPlatformIdentity.objects.update_or_create(
                roster=roster,
                platform=self.PLATFORM,
                defaults={
                    "external_id": team_id_string,
                },
            )

            imported_rosters += 1

            if (
                owned_team_id is not None
                and str(owned_team_id) == team_id_string
            ):
                own_roster = roster

            roster_team = roster_data_by_id.get(
                team_id_string,
                {},
            )

            entries = (
                roster_team.get("roster", {})
                .get("entries", [])
            )

            normalized_players = []

            for entry in entries:
                player_data = (
                    entry.get("playerPoolEntry", {})
                    .get("player", {})
                )

                if not player_data:
                    continue

                player = self._resolve_player(
                    player_data,
                    player_cache,
                    player_identity_cache,
                    identities_preloaded=True,
                )

                if player:
                    normalized_players.append(
                        FantasyRosterPlayer(
                            roster=roster,
                            player=player,
                            team=None,
                            roster_slot=self._lineup_slot_name(
                                entry.get("lineupSlotId")
                            ),
                            created_at=now,
                        )
                    )

            FantasyRosterPlayer.objects.filter(
                roster=roster
            ).delete()

            if normalized_players:
                FantasyRosterPlayer.objects.bulk_create(
                    normalized_players
                )

            imported_players += len(normalized_players)

        if own_roster is not None:
            UserLeagueConnection.objects.update_or_create(
                user=user,
                league=league,
                defaults={
                    "platform": self.PLATFORM,
                    "external_user_id": str(
                        owned_team_id
                    ),
                },
            )

        return {
            "league": league,
            "rosters_imported": imported_rosters,
            "players_imported": imported_players,
            "my_roster": own_roster,
        }