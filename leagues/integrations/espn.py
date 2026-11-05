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

    @staticmethod
    def parse_league_id(value):
        from urllib.parse import parse_qs, urlparse

        raw = str(value or "").strip()
        if raw.isdecimal():
            return raw

        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Enter a valid ESPN League ID or URL.")

        if parsed.hostname not in {
            "fantasy.espn.com",
            "fantasy.espn.com",
            "lm-api-reads.fantasy.espn.com",
        }:
            raise ValueError("Enter an ESPN fantasy football URL.")

        ids = parse_qs(parsed.query).get("leagueId", [])
        if len(ids) != 1 or not ids[0].isdecimal():
            raise ValueError("Could not find a valid leagueId in the ESPN URL.")

        return ids[0]

    def __init__(self, league_id, season, swid=None, espn_s2=None):
        self.league_id = self.parse_league_id(league_id)
        self.swid = str(swid or "").strip()
        self.espn_s2 = str(espn_s2 or "").strip()

        if bool(self.swid) != bool(self.espn_s2):
            raise ValueError(
                "Private ESPN leagues require both SWID and espn_s2 cookies."
            )

        if self.swid:
            self.swid = self.swid.strip("{}")
            self.swid = "{" + self.swid + "}"

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

    def get_team_choices(self):
        """Retrieve selectable ESPN teams without importing the league."""
        teams = self.get_teams()
        choices = []

        for team in teams:
            team_id = team.get("id")
            if team_id is None:
                continue

            name = str(team.get("name") or "").strip()
            if not name:
                location = str(team.get("location") or "").strip()
                nickname = str(team.get("nickname") or "").strip()
                name = f"{location} {nickname}".strip()

            choices.append({
                "id": str(team_id),
                "name": name or f"ESPN Team {team_id}",
            })

        if not choices:
            raise ValueError(
                "ESPN returned no teams. Check the league ID, season, "
                "and authentication credentials."
            )

        return sorted(
            choices,
            key=lambda team: (team["name"].casefold(), team["id"]),
        )

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
    @staticmethod
    def _scoring_details(settings):
        """Extract ESPN reception scoring without assuming a PPR format."""
        scoring_settings = (
            settings.get("scoringSettings") or {}
        )
        scoring_items = scoring_settings.get("scoringItems") or []

        reception_values = []

        for item in scoring_items:
            if not isinstance(item, dict):
                continue

            try:
                stat_id = int(item.get("statId"))
            except (TypeError, ValueError):
                continue

            if stat_id != 53:
                continue

            try:
                value = float(item["points"])
            except (KeyError, TypeError, ValueError):
                continue

            reception_values.append(value)

        if not reception_values:
            return None, 0.0

        # Multiple reception values may represent position-specific
        # scoring rules. Do not silently choose an arbitrary value.
        if len(set(reception_values)) > 1:
            return None, 0.0

        return reception_values[0], 0.0

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

        league_identity_key = f"{self.league_id}:{self.season}"

        identity = LeaguePlatformIdentity.objects.filter(
            platform=self.PLATFORM,
            external_id=league_identity_key,
        ).select_related("league").first()

        league = identity.league if identity else None

        # Compatibility with ESPN leagues imported before season-scoped IDs.
        # Only reuse a legacy identity when its season matches.
        if league is None:
            legacy_identity = (
                LeaguePlatformIdentity.objects.filter(
                    platform=self.PLATFORM,
                    external_id=self.league_id,
                    league__season=self.season,
                )
                .select_related("league")
                .first()
            )

            if legacy_identity is not None:
                league = legacy_identity.league
                legacy_identity.external_id = league_identity_key
                legacy_identity.save(update_fields=["external_id"])

        espn_settings = league_data.get("settings") or {}
        ppr, te_premium = self._scoring_details(espn_settings)

        league_defaults = {
            "name": data["name"],
            "season": self.season,
            "ppr": ppr,
            "te_premium": te_premium,
            "scoring_settings": espn_settings,
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
            external_id=league_identity_key,
            defaults={
                "league": league,
            },
        )

        player_cache = list(Player.objects.all())

        all_espn_player_ids = []

        for roster_team in roster_teams:
            if not isinstance(roster_team, dict):
                continue

            roster_payload = roster_team.get("roster")
            if not isinstance(roster_payload, dict):
                continue

            entries = roster_payload.get("entries")
            if not isinstance(entries, list):
                continue

            for entry in entries:
                if not isinstance(entry, dict):
                    continue

                player_pool_entry = entry.get("playerPoolEntry")
                if not isinstance(player_pool_entry, dict):
                    continue

                player_data = player_pool_entry.get("player")
                if not isinstance(player_data, dict):
                    continue

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
        my_roster_complete = False
        imported_rosters = 0
        imported_players = 0
        unresolved_players = 0

        for team_data in teams:
            team_id = team_data.get("id")

            if team_id is None:
                continue

            team_id_string = str(team_id)

            owner_id = str(
                team_data.get("primaryOwner") or ""
            ).strip()

            roster_identity_key = (
                f"{self.league_id}:{self.season}:{team_id_string}"
            )

            roster_identity = (
                RosterPlatformIdentity.objects.filter(
                    platform=self.PLATFORM,
                    external_id=roster_identity_key,
                ).select_related("roster").first()
            )

            roster = roster_identity.roster if roster_identity else None

            # Reuse a legacy ESPN roster only when it belongs to this
            # exact league. Never match a raw ESPN team ID globally.
            if roster is None:
                legacy_roster_identity = (
                    RosterPlatformIdentity.objects.filter(
                        platform=self.PLATFORM,
                        external_id=team_id_string,
                        roster__league=league,
                    )
                    .select_related("roster")
                    .first()
                )

                if legacy_roster_identity is not None:
                    roster = legacy_roster_identity.roster
                    legacy_roster_identity.external_id = (
                        roster_identity_key
                    )
                    legacy_roster_identity.save(
                        update_fields=["external_id"]
                    )

            if roster is None:
                roster = FantasyRoster.objects.create(
                    league=league,
                    sleeper_roster_id=None,
                    owner_sleeper_id=None,
                    owner_name=(
                        team_data.get("name")
                        or f"ESPN team {team_id}"
                    ),
                    created_at=now,
                    updated_at=now,
                )
            else:
                roster.owner_name = (
                    team_data.get("name")
                    or f"ESPN team {team_id}"
                )
                roster.updated_at = now
                roster.save(update_fields=["owner_name", "updated_at"])

            RosterPlatformIdentity.objects.update_or_create(
                roster=roster,
                platform=self.PLATFORM,
                defaults={
                    "external_id": roster_identity_key,
                },
            )

            imported_rosters += 1

            if (
                owned_team_id is not None
                and str(owned_team_id) == team_id_string
            ):
                own_roster = roster

            roster_team = roster_data_by_id.get(team_id_string)

            # Missing roster data is not an empty roster.
            # Preserve existing players if ESPN omitted this team's
            # roster or did not supply its entries.
            if not isinstance(roster_team, dict):
                continue

            roster_payload = roster_team.get("roster")
            if not isinstance(roster_payload, dict):
                continue

            entries = roster_payload.get("entries")
            if not isinstance(entries, list):
                continue

            normalized_players = []
            team_unresolved_players = 0

            for entry in entries:
                # Every roster entry must contain a valid player payload.
                # Missing or malformed entries make the roster incomplete.
                if not isinstance(entry, dict):
                    unresolved_players += 1
                    team_unresolved_players += 1
                    continue

                player_pool_entry = entry.get("playerPoolEntry")

                if not isinstance(player_pool_entry, dict):
                    unresolved_players += 1
                    team_unresolved_players += 1
                    continue

                player_data = player_pool_entry.get("player")

                if not isinstance(player_data, dict) or not player_data:
                    unresolved_players += 1
                    team_unresolved_players += 1
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
                else:
                    unresolved_players += 1
                    team_unresolved_players += 1

            # Preserve previously imported players when ESPN entries
            # cannot all be resolved. A partial roster must never
            # overwrite a previously complete roster.
            if team_unresolved_players:
                continue

            FantasyRosterPlayer.objects.filter(
                roster=roster
            ).delete()

            if normalized_players:
                FantasyRosterPlayer.objects.bulk_create(
                    normalized_players
                )

            imported_players += len(normalized_players)

            if (
                owned_team_id is not None
                and str(owned_team_id) == team_id_string
            ):
                my_roster_complete = True

        if own_roster is not None and my_roster_complete:
            UserLeagueConnection.objects.update_or_create(
                user=user,
                league=league,
                defaults={
                    "platform": self.PLATFORM,
                    "external_user_id": (
                        f"{self.league_id}:{self.season}:{owned_team_id}"
                    ),
                },
            )

        return {
            "league": league,
            "rosters_imported": imported_rosters,
            "players_imported": imported_players,
            "players_unresolved": unresolved_players,
            "my_roster": own_roster,
            "my_roster_complete": my_roster_complete,
        }