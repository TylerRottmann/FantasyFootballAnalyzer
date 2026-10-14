import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ESPNLeagueService:
    BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
    REQUEST_TIMEOUT = 15

    def __init__(self, league_id, season):
        self.league_id = str(league_id or "").strip()

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

        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "FantasyFootballAnalyzer/1.0",
            },
        )

        try:
            with urlopen(request, timeout=self.REQUEST_TIMEOUT) as response:
                return json.load(response)

        except HTTPError as error:
            if error.code in (401, 403):
                raise ValueError(
                    "This ESPN league is private or could not be accessed. "
                    "Public ESPN leagues are currently supported."
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
            "name": league.get("settings", {}).get("name", "Unnamed ESPN League"),
            "season": self.season,
            "league_id": self.league_id,
        }