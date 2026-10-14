import base64
import json
import logging
import re
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from datetime import timedelta

from django.conf import settings
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
    YahooAccount,
)

logger = logging.getLogger(__name__)


class YahooLeagueService:
    AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
    TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
    API_URL = "https://fantasysports.yahooapis.com/fantasy/v2"
    PLATFORM = UserLeagueConnection.PLATFORM_YAHOO
    REQUEST_TIMEOUT = 10

    def __init__(self, yahoo_account=None):
        self.yahoo_account = yahoo_account

    # ---------------------------------------------------------
    # OAuth
    # ---------------------------------------------------------

    @staticmethod
    def build_authorization_url(state):
        params = {
            "client_id": settings.YAHOO_CLIENT_ID,
            "redirect_uri": settings.YAHOO_REDIRECT_URI,
            "response_type": "code",
            "state": state,
        }

        return (
            f"{YahooLeagueService.AUTH_URL}?"
            f"{urlencode(params)}"
        )

    @staticmethod
    def _build_basic_auth_header():
        credentials = (
            f"{settings.YAHOO_CLIENT_ID}:"
            f"{settings.YAHOO_CLIENT_SECRET}"
        )

        encoded_credentials = base64.b64encode(
            credentials.encode("utf-8")
        ).decode("utf-8")

        return f"Basic {encoded_credentials}"

    @staticmethod
    def exchange_code(code):
        data = urlencode({
            "grant_type": "authorization_code",
            "redirect_uri": settings.YAHOO_REDIRECT_URI,
            "code": code,
        }).encode("utf-8")

        request = Request(
            YahooLeagueService.TOKEN_URL,
            data=data,
            method="POST",
            headers={
                "Authorization": (
                    YahooLeagueService._build_basic_auth_header()
                ),
                "Content-Type": (
                    "application/x-www-form-urlencoded"
                ),
            },
        )

        with urlopen(request, timeout=YahooLeagueService.REQUEST_TIMEOUT) as response:
            return json.load(response)

    # ---------------------------------------------------------
    # Token Refresh
    # ---------------------------------------------------------

    @staticmethod
    def refresh_account(yahoo_account):
        data = urlencode({
            "grant_type": "refresh_token",
            "redirect_uri": settings.YAHOO_REDIRECT_URI,
            "refresh_token": yahoo_account.refresh_token,
        }).encode("utf-8")

        request = Request(
            YahooLeagueService.TOKEN_URL,
            data=data,
            method="POST",
            headers={
                "Authorization": (
                    YahooLeagueService._build_basic_auth_header()
                ),
                "Content-Type": (
                    "application/x-www-form-urlencoded"
                ),
            },
        )

        try:
            with urlopen(request, timeout=YahooLeagueService.REQUEST_TIMEOUT) as response:
                token_data = json.load(response)

        except HTTPError as error:
            if error.code in (400, 401):
                raise ValueError(
                    "Yahoo authorization has expired or "
                    "has been revoked. Please reconnect your Yahoo account."
                ) from error

            raise

        access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in")

        if not access_token or not expires_in:
            raise ValueError(
                "Yahoo returned an invalid token refresh response."
            )

        yahoo_account.access_token = access_token
        yahoo_account.expires_at = (
                timezone.now()
                + timedelta(seconds=int(expires_in))
        )

        # Yahoo may issue a new refresh token.
        # If it does, the old one must be replaced.
        new_refresh_token = token_data.get("refresh_token")

        if new_refresh_token:
            yahoo_account.refresh_token = new_refresh_token

        yahoo_account.save(
            update_fields=[
                "access_token",
                "refresh_token",
                "expires_at",
                "updated_at",
            ]
        )

        return yahoo_account

    def get_valid_access_token(self):
        if self.yahoo_account is None:
            raise ValueError(
                "A Yahoo account is required."
            )

        # Refresh slightly early so we don't start an API request
        # with a token that is about to expire.
        refresh_buffer = timedelta(minutes=5)

        if (
            not self.yahoo_account.expires_at
            or timezone.now()
            >= self.yahoo_account.expires_at - refresh_buffer
        ):
            self.yahoo_account = self.refresh_account(
                self.yahoo_account
            )

        return self.yahoo_account.access_token

    # ---------------------------------------------------------
    # Yahoo API Requests
    # ---------------------------------------------------------

    def _get(self, endpoint):
        access_token = self.get_valid_access_token()

        if endpoint.startswith("/"):
            endpoint = f"{self.API_URL}{endpoint}"
        separator = "&" if "?" in endpoint else "?"
        endpoint = f"{endpoint}{separator}format=json"

        request = Request(
            endpoint,
            method="GET",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=self.REQUEST_TIMEOUT) as response:
                return json.load(response)

        except HTTPError as error:
            if error.code == 401:
                # The token may have expired between our
                # validity check and the actual API request.
                self.yahoo_account = self.refresh_account(
                    self.yahoo_account
                )

                access_token = self.yahoo_account.access_token

                retry_request = Request(
                    endpoint,
                    method="GET",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                )

                with urlopen(retry_request, timeout=self.REQUEST_TIMEOUT) as response:
                    return json.load(response)

            raise

    @staticmethod
    def _walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from YahooLeagueService._walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from YahooLeagueService._walk(child)

    @staticmethod
    def _values_named(payload, name):
        values = []
        for node in YahooLeagueService._walk(payload):
            if name in node:
                values.append(node[name])
        return values

    @staticmethod
    def _metadata(payload, required_key):
        return next(
            (node for node in YahooLeagueService._walk(payload) if required_key in node),
            {},
        )

    @staticmethod
    def _is_true(value):
        return str(value).strip().lower() in {"1", "true", "yes", "y"}

    @staticmethod
    def _resource_records(payload, resource, id_key):
        records = {}
        for value in YahooLeagueService._values_named(payload, resource):
            if not isinstance(value, list):
                continue
            metadata = next(
                (node for node in YahooLeagueService._walk(value) if id_key in node),
                None,
            )
            if metadata:
                records[str(metadata[id_key])] = (metadata, value)
        return list(records.values())

    def get_user_teams(self):
        return self._get("/users;use_login=1/games;game_codes=nfl/teams")

    def get_user_team_keys(self):
        records = self._resource_records(self.get_user_teams(), "team", "team_key")
        return {str(metadata["team_key"]) for metadata, _ in records}

    @staticmethod
    def _league_key(value):
        value = (value or "").strip()
        match = re.search(r"(?:/|^)(\d+\.l\.\d+)(?:/|$|\?)", value)
        if match:
            return match.group(1)
        url_id = re.search(r"/f\d+/(\d+)(?:/|$|\?)", value)
        if url_id:
            return url_id.group(1)
        if value.isdigit():
            return value
        raise ValueError("Enter a Yahoo NFL league ID or league key.")

    @staticmethod
    def _normalize_slot(position):
        position = (position or "").strip().upper()
        aliases = {
            "W/R/T": "FLEX", "W/R": "FLEX", "R/W/T": "FLEX",
            "Q/W/R/T": "SUPER_FLEX", "Q/R/W/T": "SUPER_FLEX",
            "D/ST": "DEF", "DEF": "DEF", "BN": "BN",
            "IR+": "IR", "NA": "TAXI",
        }
        return aliases.get(position, position)

    @staticmethod
    def _name_parts(player_data):
        name = player_data.get("name") or {}
        if isinstance(name, str):
            full_name = name
        else:
            full_name = name.get("full") or " ".join(
                part for part in (name.get("first"), name.get("last")) if part
            )
        return full_name.strip()

    @staticmethod
    def player_identity(player_data):
        """Use Yahoo's player ID, excluding the season-specific game key."""
        player_id = player_data.get("player_id")
        if player_id not in (None, ""):
            return str(player_id)
        player_key = str(player_data.get("player_key") or "")
        return player_key.rsplit(".p.", 1)[-1] if ".p." in player_key else player_key

    def _resolve_player(
        self, player_data, player_cache, team_map, identity_cache=None,
        identities_preloaded=False,
    ):
        yahoo_id = self.player_identity(player_data)
        if not yahoo_id:
            return None
        identity_cache = identity_cache if identity_cache is not None else {}
        if yahoo_id in identity_cache:
            return identity_cache[yahoo_id]
        identity = None if identities_preloaded else PlayerPlatformIdentity.objects.filter(
            platform=self.PLATFORM, external_id=yahoo_id,
        ).select_related("player").first()
        if identity:
            identity_cache[yahoo_id] = identity.player
            return identity.player

        full_name = self._name_parts(player_data)
        if not full_name:
            return None
        normalized_name = re.sub(r"[^a-z0-9]", "", full_name.lower())
        position = (player_data.get("display_position") or "").split("/")[0].upper()
        team_abbr = (player_data.get("editorial_team_abbr") or "").upper()
        candidates = [
            player for player in player_cache
            if re.sub(r"[^a-z0-9]", "", (player.full_name or "").lower()) == normalized_name
        ]
        if position:
            position_matches = [candidate for candidate in candidates if candidate.position == position]
            if position_matches:
                candidates = position_matches
        if team_abbr and team_abbr in team_map:
            team_matches = [candidate for candidate in candidates if candidate.team_id == team_map[team_abbr].id]
            if team_matches:
                candidates = team_matches
        if len(candidates) != 1:
            logger.warning("Yahoo player %s (%s) did not map to one local player", yahoo_id, full_name)
            identity_cache[yahoo_id] = None
            return None
        player = candidates[0]
        PlayerPlatformIdentity.objects.get_or_create(
            platform=self.PLATFORM,
            external_id=yahoo_id,
            defaults={"player": player},
        )
        identity_cache[yahoo_id] = player
        return player

    @classmethod
    def _roster_positions(cls, settings_data):
        values = cls._values_named(settings_data, "roster_positions")
        raw = values[0] if values else []
        if isinstance(raw, dict):
            raw = list(raw.values())
        positions = []
        for entry in raw if isinstance(raw, list) else []:
            if isinstance(entry, str):
                position, count = entry, 1
            elif isinstance(entry, dict):
                position = entry.get("position") or entry.get("name") or ""
                try:
                    count = int(entry.get("count", 1))
                except (TypeError, ValueError):
                    count = 1
            else:
                continue
            positions.extend([cls._normalize_slot(position)] * max(count, 0))
        return positions

    @staticmethod
    def _scoring_details(settings_data):
        scoring = {}
        for node in YahooLeagueService._walk(settings_data):
            if "stat_id" in node and "value" in node:
                scoring[str(node["stat_id"])] = node["value"]
        names = {}
        for node in YahooLeagueService._walk(settings_data):
            if "stat_id" in node and node.get("name"):
                names[str(node["stat_id"])] = str(node["name"]).lower()
        rec_values = []
        for stat_id, value in scoring.items():
            if "reception" not in names.get(stat_id, ""):
                continue
            try:
                rec_values.append(float(value))
            except (TypeError, ValueError):
                continue
        ppr = rec_values[0] if rec_values else 0.0
        return scoring, ppr

    @transaction.atomic
    def import_league(self, user, league_identifier, owned_team_keys=None):
        """Normalize Yahoo league, settings, teams, rosters, and player IDs."""
        league_key = self._league_key(league_identifier)
        encoded_key = quote(league_key, safe=".")
        league_payload = self._get(f"/league/{encoded_key}")
        settings_payload = self._get(f"/league/{encoded_key}/settings")
        teams_payload = self._get(f"/league/{encoded_key}/teams;out=roster")

        league_data = self._metadata(league_payload, "league_key")
        settings_data = next(iter(self._values_named(settings_payload, "settings")), {})
        teams = self._resource_records(teams_payload, "team", "team_key")
        if not league_data or not teams:
            raise ValueError("Yahoo did not return league metadata and team rosters.")

        league_key = str(league_data.get("league_key") or league_key)
        team_keys = set(owned_team_keys or [])
        owned_team = next((
            meta for meta, _ in teams
            if self._is_true(meta.get("is_owned_by_current_login"))
        ), None)
        if owned_team is None and team_keys:
            owned_team = next((meta for meta, _ in teams if str(meta.get("team_key")) in team_keys), None)

        roster_positions = self._roster_positions(settings_data)
        scoring, ppr = self._scoring_details(settings_data)
        te_premium = 0.0
        season_value = league_data.get("season")
        try:
            season = int(season_value)
        except (TypeError, ValueError):
            season = None
        now = timezone.now()
        internal_league_id = f"yahoo:{league_key}"
        identity = LeaguePlatformIdentity.objects.filter(
            platform=self.PLATFORM, external_id=league_key,
        ).select_related("league").first()
        league = identity.league if identity else None
        if league is None:
            league = FantasyLeague.objects.filter(sleeper_league_id=internal_league_id).first()
        league_defaults = {
            "name": league_data.get("name") or "Yahoo Fantasy League",
            "season": season,
            "ppr": ppr,
            "te_premium": te_premium,
            "scoring_settings": {"yahoo": settings_data, "stat_modifiers": scoring},
            "starter_count": len([slot for slot in roster_positions if slot not in {"BN", "IR", "TAXI", "NA"}]),
            "roster_positions": roster_positions,
            "updated_at": now,
        }
        if league is None:
            league = FantasyLeague.objects.create(
                sleeper_league_id=internal_league_id,
                created_at=now,
                **league_defaults,
            )
        else:
            for field, value in league_defaults.items():
                setattr(league, field, value)
            league.save(update_fields=list(league_defaults))
        LeaguePlatformIdentity.objects.update_or_create(
            platform=self.PLATFORM, external_id=league_key,
            defaults={"league": league},
        )

        team_map = {
            (team.abbreviation or "").upper(): team
            for team in Teams.objects.all()
        }
        for alias, canonical in {
            "JAC": "JAX", "LA": "LAR", "STL": "LAR", "OAK": "LV",
            "SD": "LAC", "WSH": "WAS",
        }.items():
            if canonical in team_map:
                team_map.setdefault(alias, team_map[canonical])
        player_cache = list(Player.objects.all())
        all_player_keys = []
        for _, team_resource in teams:
            roster_blocks = self._values_named(team_resource, "roster")
            if roster_blocks:
                all_player_keys.extend(
                    self.player_identity(player_data)
                    for player_data, _ in self._resource_records(roster_blocks[0], "player", "player_key")
                )
        player_identity_cache = {
            identity.external_id: identity.player
            for identity in PlayerPlatformIdentity.objects.filter(
                platform=self.PLATFORM, external_id__in=set(all_player_keys),
            ).select_related("player")
        }
        own_roster = None
        imported_rosters = imported_players = 0
        for team_data, team_resource in teams:
            team_key = str(team_data["team_key"])
            try:
                team_id = int(team_data.get("team_id"))
            except (TypeError, ValueError):
                logger.warning("Skipping Yahoo team with invalid ID %s", team_key)
                continue
            roster, _ = FantasyRoster.objects.update_or_create(
                league=league, sleeper_roster_id=team_id,
                defaults={
                    "owner_sleeper_id": team_key,
                    "owner_name": team_data.get("name") or f"Yahoo team {team_id}",
                    "updated_at": now,
                },
            )
            RosterPlatformIdentity.objects.update_or_create(
                roster=roster, platform=self.PLATFORM,
                defaults={"external_id": team_key},
            )
            imported_rosters += 1
            if (owned_team and team_key == str(owned_team.get("team_key"))) or team_key in team_keys:
                own_roster = roster

            roster_blocks = self._values_named(team_resource, "roster")
            roster_data = roster_blocks[0] if roster_blocks else {}
            player_records = self._resource_records(roster_data, "player", "player_key")
            normalized_players = []
            for player_data, _ in player_records:
                yahoo_key = str(player_data.get("player_key"))
                selected_values = self._values_named(player_data, "selected_position")
                selected = selected_values[0] if selected_values else "BN"
                if isinstance(selected, list):
                    selected = selected[0] if selected else "BN"
                if isinstance(selected, dict):
                    selected = selected.get("position", "BN")
                slot = self._normalize_slot(selected)
                display_position = (player_data.get("display_position") or "").split("/")[0].upper()
                team_abbr = (player_data.get("editorial_team_abbr") or "").upper()
                if display_position in {"DEF", "D/ST"}:
                    defense_team = team_map.get(team_abbr)
                    if defense_team:
                        normalized_players.append(FantasyRosterPlayer(
                            roster=roster, player=None, team=defense_team,
                            roster_slot=slot or "DEF", created_at=now,
                        ))
                    continue
                player = self._resolve_player(
                    player_data, player_cache, team_map, player_identity_cache,
                    identities_preloaded=True,
                )
                if player:
                    normalized_players.append(FantasyRosterPlayer(
                        roster=roster, player=player, team=None,
                        roster_slot=slot or "BN", created_at=now,
                    ))
            FantasyRosterPlayer.objects.filter(roster=roster).delete()
            if normalized_players:
                FantasyRosterPlayer.objects.bulk_create(normalized_players)
            imported_players += len(normalized_players)

        if own_roster is None:
            raise ValueError("Yahoo could not identify your team in this league.")
        UserLeagueConnection.objects.update_or_create(
            user=user, league=league,
            defaults={
                "platform": self.PLATFORM,
                "external_user_id": own_roster.owner_sleeper_id,
            },
        )
        return {
            "league": league,
            "rosters_imported": imported_rosters,
            "players_imported": imported_players,
            "my_roster": own_roster,
        }

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    @staticmethod
    def get_api_error(error):
        try:
            body = error.read().decode("utf-8")
            return body
        except Exception:
            return str(error)
