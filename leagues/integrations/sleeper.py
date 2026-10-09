import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.utils import timezone

from analyzer.models import Teams
from leagues.models import (
    FantasyLeague,
    FantasyRoster,
    FantasyRosterPlayer,
    Player,
    UserLeagueConnection,
)

logger = logging.getLogger(__name__)


class SleeperLeagueService:
    BASE_URL = "https://api.sleeper.app/v1"
    REQUEST_TIMEOUT = 10
    PLAYER_LOOKUP_WORKERS = 8

    def __init__(self, league_id):
        self.league_id = str(league_id).strip()
        self._team_by_abbreviation = None

    def _get(self, endpoint):
        """Fetch JSON from Sleeper, logging request duration and failures."""
        url = f"{self.BASE_URL}{endpoint}"
        started = time.perf_counter()

        request = Request(
            url,
            headers={"User-Agent": "FantasyFootballAnalyzer/1.0"},
        )

        try:
            with urlopen(request, timeout=self.REQUEST_TIMEOUT) as response:
                result = json.load(response)

            elapsed = time.perf_counter() - started
            logger.info(
                "Sleeper API %s completed in %.2fs",
                endpoint,
                elapsed,
            )
            if elapsed >= 3:
                logger.warning(
                    "Slow Sleeper API request: %s took %.2fs",
                    endpoint,
                    elapsed,
                )
            return result

        except (HTTPError, URLError, TimeoutError, OSError):
            elapsed = time.perf_counter() - started
            logger.exception(
                "Sleeper API request failed after %.2fs: %s",
                elapsed,
                endpoint,
            )
            raise

    def get_league(self):
        return self._get(f"/league/{self.league_id}")

    def get_rosters(self):
        return self._get(f"/league/{self.league_id}/rosters")

    def get_matchups(self, week):
        """Fetch historical starters and roster players for a league week."""
        return self._get(f"/league/{self.league_id}/matchups/{int(week)}")

    def get_users(self):
        return self._get(f"/league/{self.league_id}/users")

    def get_player(self, sleeper_player_id):
        return self._get(f"/players/nfl/{sleeper_player_id}")

    def get_league_data(self):
        """Retrieve the three league-level API resources and report total time."""
        started = time.perf_counter()
        league = self.get_league()
        rosters = self.get_rosters()
        users = self.get_users()
        logger.info(
            "Sleeper league metadata loaded in %.2fs",
            time.perf_counter() - started,
        )
        return {"league": league, "rosters": rosters, "users": users}

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

            if username in {sleeper_username, display_name}:
                return sleeper_user

        return None

    def _get_team_map(self):
        """Load the local NFL team table once per service instance."""
        if self._team_by_abbreviation is None:
            self._team_by_abbreviation = {
                (team.abbreviation or "").upper(): team
                for team in Teams.objects.all()
            }
        return self._team_by_abbreviation

    @staticmethod
    def _to_int(value):
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _player_defaults_from_sleeper(self, sleeper_player, player_id, now):
        first_name = sleeper_player.get("first_name")
        last_name = sleeper_player.get("last_name")
        full_name = (
            f"{first_name or ''} {last_name or ''}".strip()
            or sleeper_player.get("search_full_name")
            or sleeper_player.get("full_name")
            or player_id
        )

        team_id = None
        team_abbr = (sleeper_player.get("team") or "").upper()
        if team_abbr:
            team = self._get_team_map().get(team_abbr)
            if team:
                team_id = team.id

        return {
            "first_name": first_name,
            "last_name": last_name,
            "full_name": full_name,
            "position": sleeper_player.get("position"),
            "age": sleeper_player.get("age"),
            "team_id": team_id,
            "status": sleeper_player.get("status"),
            "injury_status": sleeper_player.get("injury_status"),
            "years_exp": sleeper_player.get("years_exp"),
            "jersey_number": self._to_int(sleeper_player.get("number")),
            "height": sleeper_player.get("height"),
            "weight": self._to_int(sleeper_player.get("weight")),
            "college": sleeper_player.get("college"),
            "updated_at": now,
        }

    def get_or_create_player(self, sleeper_player_id, now=None):
        """Get a local player or fetch details for one missing player."""
        player_id = str(sleeper_player_id)
        try:
            return Player.objects.get(sleeper_id=player_id)
        except Player.DoesNotExist:
            pass

        sleeper_player = self.get_player(player_id)
        if not sleeper_player:
            return None

        defaults = self._player_defaults_from_sleeper(
            sleeper_player,
            player_id,
            now or timezone.now(),
        )
        player, _ = Player.objects.get_or_create(
            sleeper_id=player_id,
            defaults={**defaults, "created_at": now or timezone.now()},
        )
        return player

    def _fetch_missing_player_data(self, player_ids):
        """
        Fetch missing players concurrently rather than serially.
        This avoids waiting for each individual HTTP request in sequence.
        """
        unique_ids = list(dict.fromkeys(str(pid) for pid in player_ids))
        if not unique_ids:
            return {}

        started = time.perf_counter()
        results = {}

        def fetch_one(player_id):
            return player_id, self.get_player(player_id)

        workers = min(self.PLAYER_LOOKUP_WORKERS, len(unique_ids))
        logger.info(
            "Fetching %d missing Sleeper player records using %d workers",
            len(unique_ids),
            workers,
        )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(fetch_one, player_id): player_id
                for player_id in unique_ids
            }
            for future in as_completed(futures):
                player_id = futures[future]
                try:
                    _, player_data = future.result()
                    if player_data:
                        results[player_id] = player_data
                except Exception:
                    # Keep processing other players; log the failing player.
                    logger.exception(
                        "Could not fetch Sleeper player %s",
                        player_id,
                    )

        logger.info(
            "Fetched %d/%d missing player records in %.2fs",
            len(results),
            len(unique_ids),
            time.perf_counter() - started,
        )
        return results

    def import_league(self, user, platform_username=None):
        import_started = time.perf_counter()
        logger.info("Starting Sleeper league import for league %s", self.league_id)

        # Time each top-level API request separately.
        stage_started = time.perf_counter()
        league_data = self.get_league()
        logger.info("Import stage: league details %.2fs", time.perf_counter() - stage_started)

        stage_started = time.perf_counter()
        rosters = self.get_rosters()
        logger.info("Import stage: rosters %.2fs", time.perf_counter() - stage_started)

        stage_started = time.perf_counter()
        users = self.get_users()
        logger.info("Import stage: users %.2fs", time.perf_counter() - stage_started)

        now = timezone.now()
        scoring_settings = league_data.get("scoring_settings") or {}
        roster_positions = league_data.get("roster_positions") or []
        ppr = scoring_settings.get("rec", 0)
        te_premium = scoring_settings.get("bonus_rec_te", 0)

        non_starting_positions = {"BN", "IR", "TAXI"}
        starting_positions = [
            position
            for position in roster_positions
            if position not in non_starting_positions
        ]
        starter_count = len(starting_positions)

        username = platform_username or user.sleeper_username
        sleeper_user = self.find_user(users, username)
        if sleeper_user is None:
            raise ValueError(
                f"Sleeper user '{username}' was not found in this league."
            )

        # Collect all player IDs first, then resolve existing players in one query.
        all_player_ids = set()
        for roster_data in rosters:
            for sleeper_player_id in roster_data.get("players") or []:
                player_id = str(sleeper_player_id)
                # Sleeper represents D/ST with a three-letter team abbreviation.
                if not (len(player_id) == 3 and player_id.isalpha()):
                    all_player_ids.add(player_id)

        stage_started = time.perf_counter()
        existing_players = {
            player.sleeper_id: player
            for player in Player.objects.filter(sleeper_id__in=all_player_ids)
        }
        missing_player_ids = all_player_ids - set(existing_players)
        logger.info(
            "Import stage: found %d existing players, %d missing (%.2fs)",
            len(existing_players),
            len(missing_player_ids),
            time.perf_counter() - stage_started,
        )

        # Fetch only missing records, in parallel. Existing local player records
        # never trigger individual Sleeper requests.
        missing_player_data = self._fetch_missing_player_data(missing_player_ids)

        # Cache team abbreviations so every roster entry does not query Teams.
        team_by_abbreviation = self._get_team_map()

        stage_started = time.perf_counter()
        league, _ = FantasyLeague.objects.update_or_create(
            sleeper_league_id=self.league_id,
            defaults={
                "name": league_data.get("name", "Unnamed League"),
                "season": (
                    int(league_data["season"])
                    if league_data.get("season")
                    else None
                ),
                "ppr": ppr,
                "te_premium": te_premium,
                "scoring_settings": scoring_settings,
                "starter_count": starter_count,
                "roster_positions": roster_positions,
                "updated_at": now,
            },
        )

        # Create any missing player records in bulk. This substantially reduces
        # database round trips compared with get_or_create for every player.
        new_player_objects = []
        for player_id, sleeper_player in missing_player_data.items():
            defaults = self._player_defaults_from_sleeper(
                sleeper_player,
                player_id,
                now,
            )
            new_player_objects.append(
                Player(
                    sleeper_id=player_id,
                    created_at=now,
                    **defaults,
                )
            )

        if new_player_objects:
            Player.objects.bulk_create(
                new_player_objects,
                ignore_conflicts=True,
            )

        # Re-query IDs after bulk insert, including records that another request
        # may have inserted concurrently.
        if missing_player_ids:
            existing_players.update({
                player.sleeper_id: player
                for player in Player.objects.filter(
                    sleeper_id__in=missing_player_ids
                )
            })

        imported_rosters = 0
        imported_players = 0
        users_by_id = {
            str(sleeper_user_data.get("user_id")): sleeper_user_data
            for sleeper_user_data in users
        }

        for roster_data in rosters:
            roster_id = roster_data.get("roster_id")
            if roster_id is None:
                continue

            owner_sleeper_id = roster_data.get("owner_id")
            owner_data = users_by_id.get(str(owner_sleeper_id), {})
            owner_name = (
                owner_data.get("display_name")
                or owner_data.get("username")
            )

            roster, _ = FantasyRoster.objects.update_or_create(
                league=league,
                sleeper_roster_id=roster_id,
                defaults={
                    "owner_sleeper_id": owner_sleeper_id,
                    "owner_name": owner_name,
                    "updated_at": now,
                },
            )
            imported_rosters += 1

            FantasyRosterPlayer.objects.filter(roster=roster).delete()

            starters = roster_data.get("starters") or []
            starter_slots = {}
            for index, sleeper_player_id in enumerate(starters):
                if index >= len(starting_positions):
                    break
                if sleeper_player_id is None or str(sleeper_player_id) == "0":
                    continue

                roster_slot = starting_positions[index]
                starter_slots[str(sleeper_player_id)] = roster_slot

            roster_player_entries = []
            for sleeper_player_id in roster_data.get("players") or []:
                player_id = str(sleeper_player_id)

                # Defense/special teams entries use team abbreviations.
                if len(player_id) == 3 and player_id.isalpha():
                    team = team_by_abbreviation.get(player_id.upper())
                    if team is None:
                        logger.warning(
                            "Skipping unknown Sleeper defense/team abbreviation %s",
                            player_id,
                        )
                        continue

                    roster_player_entries.append(
                        FantasyRosterPlayer(
                            roster=roster,
                            player=None,
                            team=team,
                            roster_slot="DEF",
                            created_at=now,
                        )
                    )
                    continue

                player = existing_players.get(player_id)
                if player is None:
                    logger.warning(
                        "Skipping player %s because Sleeper did not return player data",
                        player_id,
                    )
                    continue

                roster_player_entries.append(
                    FantasyRosterPlayer(
                        roster=roster,
                        player=player,
                        team=None,
                        roster_slot=starter_slots.get(player_id, "BN"),
                        created_at=now,
                    )
                )

            if roster_player_entries:
                FantasyRosterPlayer.objects.bulk_create(roster_player_entries)
                imported_players += len(roster_player_entries)

        UserLeagueConnection.objects.update_or_create(
            user=user,
            league=league,
            defaults={
                "platform": UserLeagueConnection.PLATFORM_SLEEPER,
                "external_user_id": sleeper_user.get("user_id"),
            },
        )

        logger.info(
            "Finished Sleeper league import %s: %d rosters, %d roster entries, "
            "total %.2fs (league/player/roster DB stage %.2fs)",
            self.league_id,
            imported_rosters,
            imported_players,
            time.perf_counter() - import_started,
            time.perf_counter() - stage_started,
        )

        return {
            "league": league,
            "sleeper_user": sleeper_user,
            "rosters_imported": imported_rosters,
            "players_imported": imported_players,
        }
